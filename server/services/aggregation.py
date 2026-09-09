"""会话级分数聚合（07 文档 §10.2 阶段② + SSOT §12.4/§19/§20 分母规则，代码执行可审计）。

item 最终等级由 item_measurement 统一裁决（adjudicate，§19）：普通题先转统一测量
记录，adjudicate 产出 item_final_level（不按来源加权、不按题数重复乘 item.weight），
替换按题数均分。缺失普通 item 标 UNMEASURED（§20.1 2026-09-09 修订：作废比例补算
IMPUTED——无证据能力不生成个人等级）；required 缺失 → PROVISIONAL +
HUMAN_REVIEW_REQUIRED（§20.2）；O=∅ → NO_VALID_OBSERVATION。总分 =
Σ(item.weight × normalized_item_score) × 100，normalized_item_score =
(actual_level−1)/4（§20.3）——仅已测项加权和（物理解释：已测项权重和 < 1，
总分即部分测量结果）；gate 项代码二值判定（达标拿满 / 不达标 0），不进 1~5 级评分。

测评范围（§20.1.A）：in_scope=0 条目为岗位背景资料（reference），不进总分、不进
覆盖率分母；NULL 视为 1（存量全部默认正式范围）。

未测量比例门控（§20.3 完整性门控）：正式范围计分项中未测量占比 >
UNMEASURED_RATIO_THRESHOLD（0.2）→ total_score=None（无综合分，不以 0 冒充）+
provisional + HUMAN_REVIEW_REQUIRED + review_reason_code=UNMEASURED_RATIO_HIGH
（复核原因单列，不与冲突/required 混同）。

score_state 分母规则（02-05，Pitfall 7）：
- SCORED → 进正常观察（能力等级分母）；
- REFUSED → 不进能力分母，只进行为/完整度聚合（refusals 单列列表）；
- INVALIDATED/INCOMPLETE/INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED → 排除 +
  missing_warnings 警告列表（不隐式转 0，不静默）。
"""
import json
import re

from ..db import get_conn
from .question_selection import exception_granted_items


# §19 重大冲突取低：观测等级极差 ≥ 此阈值视为重大冲突。已转正进 config
# （2026-09-06 第十轮收口，SSOT §14——全项目唯一影响裁决行为的阈值不再留模块级）。
from .. import config as _config
ADJUDICATE_CONFLICT_THRESHOLD = _config.ADJUDICATE_CONFLICT_THRESHOLD
# §20.1.A 未测量比例阈值（2026-09-09 §20.1 作废补算，§31-3 更名承接裁决值 0.2）
UNMEASURED_RATIO_THRESHOLD = _config.UNMEASURED_RATIO_THRESHOLD
# 归一化 source 标签（§20.1 s_i=(score−1)/4 与 §20.3 normalized_item_score 同尺度）
NORMALIZE_OBSERVED = "observed"


def _normalize_score(score: float, source: str) -> float:
    """归一化 1–5 级 → [0,1]（§20.1 s_i=(score−1)/4）。

    关口 A 已裁决：统一 (score−1)/4——归一化张力隔离进本函数。
    """
    return (score - 1) / 4.0


def adjudicate(measurements: list[dict]) -> tuple[float | None, bool]:
    """返回 (item_final_level, human_review)。

    §19：不按来源加权、不按题数重复乘 item.weight；重大冲突取低留人工标记。
    冲突量化阈值 ADJUDICATE_CONFLICT_THRESHOLD 一处定义；一致场景取 round(mean, 2)。
    measurements 元素为 item_measurement 记录，键 observed_level 承载观测等级。
    """
    levels = [m["observed_level"] for m in measurements if m.get("observed_level") is not None]
    if not levels:
        return None, False
    if max(levels) - min(levels) >= ADJUDICATE_CONFLICT_THRESHOLD:
        return float(min(levels)), True
    return round(sum(levels) / len(levels), 2), False


def _observed_items(measurements: list[dict], model_items: dict) -> list[dict]:
    """question-level item_measurement 归约为 per-item {item_id, weight, score}。

    weight 来源 = model_items[item_id].weight；score = adjudicate 后 item_final_level；
    仅含已裁决（level 非 None）item。§20.1.A：非正式范围（in_scope=0）条目不进
    观察集合（reference 不占覆盖率分子）。
    """
    grouped: dict[str, list[dict]] = {}
    for m in measurements:
        grouped.setdefault(m["item_id"], []).append(m)
    out: list[dict] = []
    for item_id, ms in grouped.items():
        item = model_items.get(item_id) or {}
        if item.get("in_scope") == 0:
            continue  # reference-only 条目不计观察（§20.1.A）
        level, _ = adjudicate(ms)
        if level is not None:
            out.append({
                "item_id": item_id,
                "weight": item.get("weight") or 0.0,
                "score": level,
            })
    return out


def _load_model_items(session_id: str) -> dict[str, dict]:
    """item_id → {std_name, category, required_level, importance, weight, gate, years,
    facet_key, in_scope, occurrence}（facet_key 供报告 gate 段折叠分组——SSOT §16.1，
    读预打标不重跑；in_scope 供 §20.1.A 范围分流——NULL 视为 1 正式计分；occurrence
    供 §16.2 层 3 条件性质判定——req 解析失败按空 dict 保守处理）"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT ci.item_id, ci.std_name, ci.category, ci.required_level, ci.importance,"
        " ci.weight, ci.gate, ci.years, ci.facet_key, ci.in_scope, ci.occurrence_json"
        " FROM competency_item ci"
        " JOIN assessment_session s ON s.model_id=ci.model_id"
        " WHERE s.session_id=?",
        (session_id,),
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        it = dict(r)
        try:
            it["occurrence"] = json.loads(it.pop("occurrence_json") or "{}") or {}
        except json.JSONDecodeError:
            it["occurrence"] = {}
        out[it["item_id"]] = it
    return out


def _load_form_payload(session_id: str) -> dict:
    """合并该会话全部 form_submission 的 payload（后提交覆盖先提交同名字段）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT payload_json FROM form_submission WHERE session_id=? ORDER BY created_at, rowid",
        (session_id,),
    ).fetchall()
    merged: dict = {}
    for r in rows:
        try:
            merged.update(json.loads(r["payload_json"] or "{}"))
        except json.JSONDecodeError:
            continue
    return merged


def _gate_row(conn, session_id: str, item_id: str) -> tuple | None:
    """新链 gate 行（表单链 submit-v2 写 question_score gate 结构化结果）。

    返回 (effective_result, gate_reason) 或 None（无 gate 行——旧链 form_submission 兜底）。
    人工覆盖（human_override，admin gate-override 写入）优先于自动化 gate_result，
    否则覆盖无下游消费者（WR-05）。
    """
    row = conn.execute(
        "SELECT gate_result, gate_reason, human_override FROM question_score"
        " WHERE session_id=? AND item_id=? AND gate_result IS NOT NULL LIMIT 1",
        (session_id, item_id),
    ).fetchone()
    if row is None:
        return None
    effective = row["human_override"] if row["human_override"] is not None else row["gate_result"]
    return (effective, row["gate_reason"])


# ---- 经验分类词表（SSOT §16.2「通用年限不证明专项年限」，2026-09-09）----
# 通用经验措辞：years_of_experience（通用工作年限）可证明——维持现状（用表单
# years_of_experience 比对）。词表保守：只收显然通用的措辞。
_GENERAL_EXPERIENCE_WORDS = (
    "工作经验", "工作年限", "相关工作经验", "开发经验", "项目经验", "工作经验年限",
    "行业经验",
)
# 专项经验技术词（命中即专项——表单只提供通用年限，无专项事实 → PENDING_CONFIRMATION，
# 不自动判通过）。词表约 20 词 + 兜底：std_name 含英文/大写字母组合视为专项（宁可
# 误判专项进待确认，也不放过通用年限误通过）。
_SPECIALIZED_EXPERIENCE_WORDS = (
    "NLP", "CV", "CAD", "Java", "Python", "C++", "Go", "SQL", "Linux",
    "算法", "模型", "部署", "前端", "后端", "测试", "运维", "数据", "机器学习",
    "深度学习", "强化学习", "3D", "工业", "图形", "视觉", "语音", "推荐", "风控",
)
# PENDING_CONFIRMATION（§16.2 四状态之一）：必要事实未提供 / 条件方向未解析 →
# 不自动判定。gate_items.passed 映射 False，reason 前缀「待确认：」。
GATE_PENDING = "PENDING_CONFIRMATION"
# §16.2 资格结论四状态全集（SATISFIED 已满足 / UNSATISFIED 明确未满足 /
# PENDING_CONFIRMATION 待确认 / NOT_APPLICABLE 不适用——preferred/背景/非本测评
# 范围条件）。NOT_APPLICABLE：当前数据模型无 preferred gate 条目，本期只入枚举
# 不生产（落值须等 condition nature 三层分离落地）。
GATE_STATUSES = ("SATISFIED", "UNSATISFIED", GATE_PENDING, "NOT_APPLICABLE")

# §16.2 层 3 逐条展示 severity（2026-09-09 专业列举 OR + 条件性质分层）：
# ok=必需已满足 / fail=必需未满足 / pending=待确认 / optional=优先项（未满足不算失败）/
# covered=major_group 组内任一满足但本条未勾（不单独判定）
GATE_SEVERITIES = ("ok", "fail", "pending", "optional", "covered")


def _gate_nature(item: dict) -> str:
    """gate 条目条件性质（SSOT §16.2 层 3，2026-09-09）：required / preferred。

    判据：occurrence.req（标 required 的 JD 数 ÷ 出现 JD 数——§8.1 条件口径）≥
    REQ_THRESHOLD → required；否则 preferred。occurrence 缺失/解析失败（存量模型
    无 occurrence_json 列值）→ 保守 required（性质不明按必需，宁严不松——与
    _gate_check 保守方向一致）。
    """
    req = (item.get("occurrence") or {}).get("req")
    if req is None:
        return "required"
    return "required" if float(req) >= _config.REQ_THRESHOLD else "preferred"


def _annotate_gate_items(gate_items: list[dict], model_items: dict[str, dict]) -> None:
    """结论层标注（SSOT §16.2 层 2 专业列举 OR + 层 3 性质分层，2026-09-09）：
    就地写 g['nature']/g['severity']——逐条原始事实 passed/status/reason 是表单审计
    事实，一律不动（reason 文案由报告端按 severity 组装）。

    - nature：_gate_nature（required=必需 / preferred=优先）；
    - major_group 组内 OR：facet_key='major_group' 的条目视为同一「专业背景维度」
      ——组内任一 passed → 组满足。未勾成员标 covered（组满足）/ fail（组未满足
      且必需）/ optional（组未满足且优先）；勾选成员 passed=True → ok；
    - 其余条目：PENDING→pending；preferred→optional；required 按 passed → ok/fail。
    """
    major_satisfied = any(g["passed"] for g in gate_items
                         if g.get("facet_key") == "major_group")
    for g in gate_items:
        g["nature"] = _gate_nature(model_items.get(g["item_id"]) or {})
        if g.get("facet_key") == "major_group":
            if g["passed"]:
                g["severity"] = "ok"
            elif major_satisfied:
                g["severity"] = "covered"
            elif g["nature"] == "preferred":
                g["severity"] = "optional"
            else:
                g["severity"] = "fail"
        elif g.get("status") == GATE_PENDING:
            g["severity"] = "pending"
        elif g["nature"] == "preferred":
            g["severity"] = "optional"
        else:
            g["severity"] = "ok" if g["passed"] else "fail"


def gate_conclusion(gate_items: list[dict]) -> dict:
    """报告级资格结论（SSOT §16.2 层 3「只有必需条件影响资格结论」，2026-09-09：
    取代 report.py 的 all(passed) 逐条 AND。

    - major_group 全组按**一个**维度条件计（组内任一 passed → 维度满足）；
    - 必需条目 PENDING_CONFIRMATION → 计分母不计满足（passed 自然为 False），
      不用单列阻断逻辑；preferred 条目 PENDING 不阻断（不进结论分母）；
    - preferred 条目未满足仅计 optional_fail 提示；空列表 → passed=True
      （沿用 all([]) 语义）。
    """
    major_rows = [g for g in gate_items if g.get("facet_key") == "major_group"]
    major_satisfied = any(g["passed"] for g in major_rows)
    total = satisfied = pending_count = optional_fail = 0
    counted_major = False
    for g in gate_items:
        if g.get("facet_key") == "major_group":
            if not counted_major:
                counted_major = True
                total += 1
                satisfied += 1 if major_satisfied else 0
            continue
        nature = g.get("nature") or "required"
        pending = g.get("status") == GATE_PENDING
        if pending:
            pending_count += 1
        if nature == "preferred":
            if pending or not g["passed"]:
                optional_fail += 1
            continue
        total += 1  # 必需条件（PENDING 未决也进分母，不计满足）
        satisfied += 1 if (g["passed"] and not pending) else 0
    return {
        "passed": bool(satisfied == total),
        "required_total": total,
        "required_satisfied": satisfied,
        "pending_count": pending_count,
        "optional_fail": optional_fail,
    }


def _is_specialized_experience(std_name: str) -> bool:
    """经验 std_name 是否专项（SSOT §16.2 通用年限不证明专项年限，2026-09-09）。

    判序：技术词命中 → 专项；英文/大写字母组合兜底（「ROS开发经验」「Gmapping/
    Cartographer...」）→ 专项；通用词表命中 → 通用。全不命中 → 专项（保守——
    宁可误判专项进待确认，也不让通用年限误通过专项断言）。
    """
    if any(w in std_name for w in _SPECIALIZED_EXPERIENCE_WORDS):
        return True
    if re.search(r"[A-Za-z]", std_name):
        return True  # 含英文/字母组合 → 专项（NLP/CV/ROS/CET 类）
    if any(w in std_name for w in _GENERAL_EXPERIENCE_WORDS):
        return False
    return True  # 兜底保守：不明措辞按专项处理（待确认优于误通过）


def _gate_check(item: dict, form_payload: dict) -> tuple[bool, str, str | None]:
    """门槛项判定（§16.2 四状态，2026-09-09）。返回 (passed, reason, status)。

    - experience 通用项（如 工作经验 years=3）：payload.years_of_experience >= 要求 →
      通过（维持现状）；
    - experience 专项项（如 NLP相关经验）：表单只提供通用年限、无专项事实 →
      不自动判通过——status=PENDING_CONFIRMATION（reason 写明「专项经验需要专项
      事实，通用年限不适用」——验收 13：总年限 10 年不再使 NLP/CAD 项自动通过）；
    - qualification：payload 含 std_name 字段且真值 → 通过；值为 PENDING_CONFIRMATION
      （facet 派生端方向未解析/学历其他，facet.py §16.2）→ status=PENDING_CONFIRMATION。
    - 无对应字段视为不达标（保守）。status=None → 调用方按 passed 推导
      （SATISFIED/UNSATISFIED）。
    """
    std_name = item["std_name"]
    if item["category"] == "experience" and item.get("years"):
        if _is_specialized_experience(std_name):
            return (False, f"待确认：专项经验[{std_name}]需要专项事实，通用年限不适用",
                    GATE_PENDING)
        actual_years = form_payload.get("years_of_experience") or form_payload.get(std_name)
        try:
            actual = float(actual_years)
        except (TypeError, ValueError):
            return False, f"未提供工作年限（要求 {item['years']} 年）", None
        if actual >= item["years"]:
            return True, f"工作年限 {actual} 年 ≥ 要求 {item['years']} 年", None
        return False, f"工作年限 {actual} 年 < 要求 {item['years']} 年", None
    # qualification：查找 std_name 字段，常见值 '本科'/'硕士'/True/'yes' 视为通过
    val = form_payload.get(std_name)
    if val == GATE_PENDING:
        # facet 派生端待确认（facet.py §16.2：条件方向未解析 / 学历其他出口）
        if item.get("facet_key") == "number_range":
            return False, "待确认：条件方向未能解析，需人工确认", GATE_PENDING
        return False, f"待确认：{std_name}学历为其他情况，需人工确认", GATE_PENDING
    if val in (True, "true", "yes", "是", "达标", "本科", "硕士", "博士"):
        return True, f"{std_name}: 达标", None
    return False, f"{std_name}: 未提供或不达标", None


def aggregate_session_scores(session_id: str) -> dict:
    """聚合 question_score → item_scores + total_score + gate_items + strengths/weaknesses。

    score_state 三路分流（§12.4）：SCORED 收成 item_measurement 统一测量记录后由
    adjudicate 裁决 item_final_level（§19，废弃按题数均分）；REFUSED 进 refusals 列表；
    排除态（INVALIDATED/INCOMPLETE/INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED）进
    missing_warnings 警告列表。

    缺失项（§20，2026-09-09 修订）：普通（preferred/plus）缺失 → UNMEASURED（无
    个人等级、不进总分——作废 IMPUTED r 比例补算）；required 缺失 → PROVISIONAL +
    HUMAN_REVIEW_REQUIRED；qualification 缺失不补算仅记警告；O=∅ →
    NO_VALID_OBSERVATION + HUMAN_REVIEW_REQUIRED。总分 = Σ(item.weight ×
    (actual_level−1)/4) × 100——仅已测项加权和；未测量比例 > 0.2（§20.3 完整性
    门控）→ total_score=None（无综合分，不以 0 冒充）。
    """
    conn = get_conn()
    model_items = _load_model_items(session_id)
    form_payload = _load_form_payload(session_id)

    # 三路分流收成 item_measurement 内存记录（SCORED → ordinary 测量）
    rows = conn.execute(
        "SELECT qs.item_id, qs.score_final, qs.score_state, qs.question_id"
        " FROM question_score qs WHERE qs.session_id=?",
        (session_id,),
    ).fetchall()
    measurements: list[dict] = []
    refusals: list[dict] = []
    missing_warnings: list[dict] = []
    _EXCLUDED_STATES = ("INVALIDATED", "INCOMPLETE", "INSUFFICIENT_EVIDENCE", "NOT_ADMINISTERED")
    for r in rows:
        std_name = (model_items.get(r["item_id"]) or {}).get("std_name")
        if r["score_state"] == "SCORED":
            measurements.append({
                "question_id": r["question_id"],
                "item_id": r["item_id"],
                "observed_level": r["score_final"],
                "evidence_refs": [],
                "measurement_source": "ordinary",
            })
        elif r["score_state"] == "REFUSED":
            # 不进能力分母，只进行为/完整度聚合（refusals 单列——§18/§12.4）
            refusals.append({
                "item_id": r["item_id"], "std_name": std_name,
                "question_id": r["question_id"],
            })
        elif r["score_state"] in _EXCLUDED_STATES:
            # 排除 + 缺失警告（不隐式转 0，不静默——D-28）
            missing_warnings.append({
                "item_id": r["item_id"], "std_name": std_name,
                "reason": r["score_state"],
            })

    # question-level → per-item 已裁决 observed 列表（in_scope=0 不进观察，§20.1.A）
    observed_items = _observed_items(measurements, model_items)
    observed_item_ids = {o["item_id"] for o in observed_items}

    # 测评范围（§20.1.A）：正式范围计分项 = 非 gate 且 in_scope≠0（NULL 视为 1——
    # 作废旧口径排除 required/qualification 的分母收缩，§20.4「必备项不从分母排除」）。
    # in_scope=0 为 reference（岗位背景资料项）：不进总分、不进覆盖率，报告可区分。
    scope_items = [
        (iid, it) for iid, it in model_items.items()
        if not it.get("gate") and it.get("in_scope") != 0
    ]
    scope_item_ids = {iid for iid, _ in scope_items}
    scope_total = len(scope_items)
    scope_weight = sum((it.get("weight") or 0.0) for _, it in scope_items)
    required_scope = [it for _, it in scope_items if it.get("importance") == "required"]

    # 作答完成情况（§20.4 指标 1）：已答题数（answered_at 非空）与计划题量
    # （N + 已发生例外数 E，与 get_session total_count 同口径——WR-02 分母不漂移）
    answered_questions = conn.execute(
        "SELECT COUNT(*) c FROM assessment_question WHERE session_id=? AND answered_at IS NOT NULL",
        (session_id,),
    ).fetchone()["c"]
    planned_questions = _config.ORDINARY_PLAN_N + len(exception_granted_items(conn, session_id))

    measurements_by_item: dict[str, list[dict]] = {}
    for m in measurements:
        measurements_by_item.setdefault(m["item_id"], []).append(m)

    item_scores: list[dict] = []
    gate_items: list[dict] = []
    total_score = 0.0
    provisional = False
    review_status = None
    observation_status = None
    review_reason_code = None

    for item_id, item in model_items.items():
        weight = item.get("weight") or 0.0
        if item.get("in_scope") == 0:
            # 岗位背景资料项（§20.1.A reference-only）：不进总分、不进覆盖率分母、
            # 不出雷达（actual_level 保持 None）；报告可凭 role="reference" 区分。
            # weight 字段保留模型原值（检查② weight 总和一致性仍含全部条目；
            # 贡献恒 0 因 actual_level=None——不进总分链）。
            item_scores.append({
                "item_id": item_id, "std_name": item["std_name"],
                "category": item["category"],
                "required_level": item.get("required_level"),
                "actual_level": None, "gap": None,
                "weight": weight, "score": None,
                "gate": bool(item.get("gate")), "role": "reference",
            })
            continue
        if item.get("gate"):
            # 双源（D-31）：先查 gate 行（新链表单链 submit-v2），无行回退
            # _gate_check(item, form_payload)（旧链 form_submission——m6 脚本路径不变）
            row = _gate_row(conn, session_id, item_id)
            if row is not None:
                passed, reason = (row[0] == "true", row[1])
                # gate 行的待确认识别：result=false + reason 前缀「待确认：」（_gate_check
                # 落行时写入——§16.2 四状态经 reason 前缀传输，gate_status 列维持
                # EVALUATED 生命周期语义）
                status = (GATE_PENDING if not passed and str(reason).startswith("待确认：")
                          else None)
            else:
                passed, reason, status = _gate_check(item, form_payload)
            # §16.2 四状态（2026-09-09）：status 缺省按 passed 推导
            # （SATISFIED/UNSATISFIED）；PENDING_CONFIRMATION 由 _gate_check/
            # gate 行前缀识别产生；NOT_APPLICABLE 当前数据模型无 preferred gate
            # 条目，本期只入枚举不生产。
            if status is None:
                status = "SATISFIED" if passed else "UNSATISFIED"
            else:
                # PENDING_CONFIRMATION 语义：passed=False（不动贡献分母——权重恒 0 行为
                # 不变）+ reason 前缀已由 _gate_check 写入；此处保证 status 与 passed 一致
                passed = False
            contribution = weight * 100.0 if passed else 0.0
            gate_items.append({
                "item_id": item_id, "std_name": item["std_name"],
                "passed": passed, "reason": reason,
                "status": status,
                # 展示元数据透传（讨论稿 §四 2026-09-09）：gate_details 带 category，
                # 供报告页资格折叠分组（旧报告缺列时前端用 item_details 兜底）。仅透传。
                "category": item["category"],
                "facet_key": item.get("facet_key"),
            })
            item_scores.append({
                "item_id": item_id, "std_name": item["std_name"],
                "category": item["category"],
                "required_level": item.get("required_level"),
                "actual_level": None, "gap": None,
                "weight": weight, "score": contribution,
                "gate": True, "gate_passed": passed, "gate_reason": reason,
                "gate_status": status,
            })
            total_score += contribution
            continue

        item_measurements = measurements_by_item.get(item_id, [])
        required = item.get("required_level")

        if item_measurements:
            # 有测量 → adjudicate 裁决（冲突取低留人工标记）
            item_final_level, human_review = adjudicate(item_measurements)
            if human_review:
                # 重大冲突 → 顶层 PROVISIONAL + HUMAN_REVIEW_REQUIRED（§19 留人工标记）
                provisional = True
                review_status = "HUMAN_REVIEW_REQUIRED"
            gap = (required - item_final_level) if required is not None else None
            contribution = weight * _normalize_score(item_final_level, NORMALIZE_OBSERVED) * 100.0
            item_scores.append({
                "item_id": item_id, "std_name": item["std_name"],
                "category": item["category"],
                "required_level": required,
                "actual_level": round(item_final_level, 2),
                "gap": round(gap, 2) if gap is not None else None,
                "weight": weight, "score": contribution,
                "gate": False,
                "no_data": False, "imputed": False, "human_review": human_review,
            })
            total_score += contribution
            continue

        # 无 SCORED 测量：按 importance/category 分流
        if item.get("importance") == "required":
            # required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED（不触发补测）
            provisional = True
            review_status = "HUMAN_REVIEW_REQUIRED"
            item_scores.append({
                "item_id": item_id, "std_name": item["std_name"],
                "category": item["category"],
                "required_level": required,
                "actual_level": None, "gap": None,
                "weight": weight, "score": 0.0,
                "gate": False, "no_data": True, "imputed": False,
                "provisional": True,
            })
            continue

        if item.get("category") == "qualification":
            # qualification 不补算、不标 PROVISIONAL，仅记缺失警告（§20.1）
            missing_warnings.append({
                "item_id": item_id, "std_name": item["std_name"],
                "reason": "qualification 缺失（不补算）",
            })
            item_scores.append({
                "item_id": item_id, "std_name": item["std_name"],
                "category": item["category"],
                "required_level": required,
                "actual_level": None, "gap": None,
                "weight": weight, "score": 0.0,
                "gate": False, "no_data": True, "imputed": False,
            })
            continue

        # 普通（preferred/plus）缺失 → UNMEASURED（§20.1 2026-09-09 作废比例补算：
        # 无个人等级、不进总分、不用 0 分代替缺失——Python 作答不能证明其他能力等级）
        item_scores.append({
            "item_id": item_id, "std_name": item["std_name"],
            "category": item["category"],
            "required_level": required,
            "actual_level": None, "gap": None,
            "weight": weight, "score": None,
            "gate": False, "no_data": True, "imputed": False,
            "status": "UNMEASURED",
        })

    # 未测量项数（§20.4/门控口径）：scope_total − 直接观测数——按集合补集计算，
    # 覆盖全部缺失路径（普通 UNMEASURED、required 缺失、qualification 缺失），
    # 与 coverage 的 observed_items/scope_items 同一对分子分母自洽。
    measured_item_ids = observed_item_ids & scope_item_ids
    unmeasured_count = scope_total - len(measured_item_ids)

    # §16.2 层 2/3 结论层标注（2026-09-09）：nature/severity 只写 gate_items 展示
    # 元数据，逐条 passed/status（表单审计事实）不动；结论见 gate_summary。
    _annotate_gate_items(gate_items, model_items)
    gate_summary = gate_conclusion(gate_items)

    # O=∅（正式范围内无任何已裁决观测）→ NO_VALID_OBSERVATION + HUMAN_REVIEW_REQUIRED
    # （§20.1 不变；session 级判定——不是逐 item 打标）
    if scope_total and not observed_items:
        observation_status = "NO_VALID_OBSERVATION"
        review_status = "HUMAN_REVIEW_REQUIRED"

    # 优势 = gap≤0 中权重最大前 3；短板 = gap>0 中 gap×weight 最大前 3
    # （§20.1 未测量项无 gap → 自然不进优势/短板；§20.1.A reference 无 gap 同）
    non_gate = [it for it in item_scores if not it.get("gate") and it.get("gap") is not None]
    strengths = sorted(
        (it for it in non_gate if it["gap"] <= 0),
        key=lambda x: (-x["weight"], x["item_id"]),
    )[:3]
    weaknesses = sorted(
        (it for it in non_gate if it["gap"] > 0),
        key=lambda x: (-(x["gap"] * x["weight"]), x["item_id"]),
    )[:3]

    # 未测量比例门控（§20.3 完整性门控）：正式范围计分项中未测量占比 >
    # UNMEASURED_RATIO_THRESHOLD → total_score=None（无综合分）+ PROVISIONAL +
    # HUMAN_REVIEW_REQUIRED + review_reason_code=UNMEASURED_RATIO_HIGH（复核原因
    # 单列，不与冲突/required 混同）。比例 ≤ 阈值时总分照常——仅已测项加权和，
    # 已测项权重和 < 1（物理解释：总分即部分测量结果，报告须展示测量完整性）。
    unmeasured_ratio = (unmeasured_count / scope_total) if scope_total else 0.0
    if unmeasured_ratio > UNMEASURED_RATIO_THRESHOLD:
        total_score = None
        provisional = True
        review_status = "HUMAN_REVIEW_REQUIRED"
        review_reason_code = "UNMEASURED_RATIO_HIGH"

    # 覆盖率五指标（§20.4）：分母 = 正式范围内全部非 gate 条目（含 required——
    # 作废把必备项排除分母的旧 coverage_ratio 口径）。分母为 0 → 比率字段 null
    # （前端显「不适用」，不显 0%/100%）。
    # - observed_items：有有效直接观测（SCORED）的不同能力项数；
    # - measured_items：满足最低证据要求的能力项（本期 = observed——证据要求
    #   检验留 U5b，§20.4「区分存在记录与充分测量」的分层占位）；
    # - weight_coverage：已测权重 / 范围权重（分母 0 → null）。
    measured_weight = sum(
        (model_items[iid].get("weight") or 0.0) for iid in measured_item_ids
    )
    required_covered = sum(
        1 for it in required_scope if it["item_id"] in measured_item_ids
    )
    coverage = {
        "answered_questions": answered_questions,
        "planned_questions": planned_questions,
        "observed_items": len(measured_item_ids),
        "scope_items": scope_total,
        "measured_items": len(measured_item_ids),
        "weight_coverage": round(measured_weight / scope_weight, 4) if scope_weight else None,
        "required_covered": required_covered,
        "required_total": len(required_scope),
        "unmeasured_count": unmeasured_count,
        "missing_reasons": missing_warnings,
    }

    return {
        "session_id": session_id,
        "total_score": round(total_score, 2) if total_score is not None else None,
        "unmeasured_ratio": round(unmeasured_ratio, 4) if scope_total else None,
        "item_scores": item_scores,
        "gate_items": gate_items,
        "gate_summary": gate_summary,
        "refusals": refusals,
        "missing_warnings": missing_warnings,
        "coverage": coverage,
        "review_status": review_status,
        "review_reason_code": review_reason_code,
        "observation_status": observation_status,
        "provisional": provisional,
        "strengths": [
            {"item_id": s["item_id"], "std_name": s["std_name"],
             "weight": s["weight"], "gap": s["gap"]}
            for s in strengths
        ],
        "weaknesses": [
            {"item_id": w["item_id"], "std_name": w["std_name"],
             "weight": w["weight"], "gap": w["gap"]}
            for w in weaknesses
        ],
    }
