"""会话级分数聚合（07 文档 §10.2 阶段② + SSOT §12.4/§19/§20 分母规则，代码执行可审计）。

item 最终等级由 item_measurement 统一裁决（adjudicate，§19）：普通题先转统一测量
记录，adjudicate 产出 item_final_level（不按来源加权、不按题数重复乘 item.weight，
重大冲突取低留人工标记），替换按题数均分。缺失普通 item 走 r 比例补算 IMPUTED
（§20.1）；required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED（§20.2）；
O=∅ → NO_VALID_OBSERVATION。总分 = Σ(item.weight × normalized_item_score) × 100，
normalized_item_score = (actual_level−1)/4（§20.3，统一 observed/imputed 同尺度）；
gate 项代码二值判定（达标拿满 / 不达标 0），不进 1~5 级评分。

score_state 分母规则（02-05，Pitfall 7）：
- SCORED → 进正常观察（能力等级分母）；
- REFUSED → 不进能力分母，只进行为/完整度聚合（refusals 单列列表）；
- INVALIDATED/INCOMPLETE/INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED → 排除 +
  missing_warnings 警告列表（不隐式转 0，不静默）。
"""
import json

from ..db import get_conn


# §19 重大冲突取低：观测等级极差 ≥ 此阈值视为重大冲突（实施期可调）
ADJUDICATE_CONFLICT_THRESHOLD = 2
# 归一化 source 标签（§20.1 s_i=(score−1)/4 与 §20.3 normalized_item_score 同尺度）
NORMALIZE_IMPUTED = "imputed"
NORMALIZE_OBSERVED = "observed"
# §31-3 补算复核阈值：IMPUTED 覆盖率超过此值 → 人工复核（关口 A 已裁决 0.2）
IMPUTE_RATIO_THRESHOLD = 0.2


def _normalize_score(score: float, source: str) -> float:
    """归一化 1–5 级 → [0,1]（§20.1 s_i=(score−1)/4）。

    关口 A 已裁决：observed/imputed 两分支统一 (score−1)/4，作废旧实现 score/5
    两尺度混用——归一化张力隔离进本函数。
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


def _impute_r(observed: list[dict]) -> float | None:
    """观察集合 O 的加权归一化均值 r（§20.1）。

    observed: [{weight, score}]；r = Σ w_i·s_i / Σ w_i（s_i=_normalize_score）。
    O=∅ 或 den=0 → None（不能补算，调用方标 NO_VALID_OBSERVATION）。
    """
    if not observed:
        return None
    num = sum(o["weight"] * _normalize_score(o["score"], NORMALIZE_IMPUTED) for o in observed)
    den = sum(o["weight"] for o in observed)
    if den == 0:
        return None
    return num / den


def _observed_items(measurements: list[dict], model_items: dict) -> list[dict]:
    """question-level item_measurement 归约为 per-item {item_id, weight, score}。

    weight 来源 = model_items[item_id].weight（D-59 r 公式 w_i）；score = adjudicate 后
    item_final_level；仅含已裁决（level 非 None）item。
    """
    grouped: dict[str, list[dict]] = {}
    for m in measurements:
        grouped.setdefault(m["item_id"], []).append(m)
    out: list[dict] = []
    for item_id, ms in grouped.items():
        level, _ = adjudicate(ms)
        if level is not None:
            out.append({
                "item_id": item_id,
                "weight": (model_items.get(item_id) or {}).get("weight") or 0.0,
                "score": level,
            })
    return out


def _load_model_items(session_id: str) -> dict[str, dict]:
    """item_id → {std_name, category, required_level, importance, weight, gate, years}"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT ci.item_id, ci.std_name, ci.category, ci.required_level, ci.importance,"
        " ci.weight, ci.gate, ci.years"
        " FROM competency_item ci"
        " JOIN assessment_session s ON s.model_id=ci.model_id"
        " WHERE s.session_id=?",
        (session_id,),
    ).fetchall()
    return {r["item_id"]: dict(r) for r in rows}


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


def _gate_check(item: dict, form_payload: dict) -> tuple[bool, str]:
    """门槛项二值判定。规则：按 category/std_name 在表单 payload 中查对应字段。

    - qualification（如 本科学历）：payload 含 std_name 字段且真值 → 通过
    - experience 年限项（如 后端开发经验 years=3）：payload.years_of_experience >= 要求 → 通过
    无对应字段视为不达标（保守）。
    """
    std_name = item["std_name"]
    if item["category"] == "experience" and item.get("years"):
        actual_years = form_payload.get("years_of_experience") or form_payload.get(std_name)
        try:
            actual = float(actual_years)
        except (TypeError, ValueError):
            return False, f"未提供工作年限（要求 {item['years']} 年）"
        if actual >= item["years"]:
            return True, f"工作年限 {actual} 年 ≥ 要求 {item['years']} 年"
        return False, f"工作年限 {actual} 年 < 要求 {item['years']} 年"
    # qualification：查找 std_name 字段，常见值 '本科'/'硕士'/True/'yes' 视为通过
    val = form_payload.get(std_name)
    if val in (True, "true", "yes", "是", "达标", "本科", "硕士", "博士"):
        return True, f"{std_name}: 达标"
    return False, f"{std_name}: 未提供或不达标"


def aggregate_session_scores(session_id: str) -> dict:
    """聚合 question_score → item_scores + total_score + gate_items + strengths/weaknesses。

    score_state 三路分流（§12.4）：SCORED 收成 item_measurement 统一测量记录后由
    adjudicate 裁决 item_final_level（§19，废弃按题数均分）；REFUSED 进 refusals 列表；
    排除态（INVALIDATED/INCOMPLETE/INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED）进
    missing_warnings 警告列表。

    缺失项（§20）：required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED；qualification
    缺失不补算仅记警告；普通（preferred/plus）缺失 → IMPUTED r 比例补算；O=∅ →
    NO_VALID_OBSERVATION + HUMAN_REVIEW_REQUIRED。总分 = Σ(item.weight × (actual_level−1)/4) × 100。
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

    # question-level → per-item 已裁决 observed 列表（r 公式输入，D-59）
    observed_items = _observed_items(measurements, model_items)

    # 覆盖率（§20.1 展示）：可测量普通 item = 非 gate、非 required、非 qualification
    measurable_item_ids = [
        iid for iid, it in model_items.items()
        if not it.get("gate")
        and it.get("importance") != "required"
        and it.get("category") != "qualification"
    ]
    total_measureable = len(measurable_item_ids)
    observed_count = len(observed_items)
    coverage_ratio = observed_count / total_measureable if total_measureable else 0.0

    measurements_by_item: dict[str, list[dict]] = {}
    for m in measurements:
        measurements_by_item.setdefault(m["item_id"], []).append(m)

    item_scores: list[dict] = []
    gate_items: list[dict] = []
    total_score = 0.0
    imputed_count = 0
    provisional = False
    review_status = None
    observation_status = None

    for item_id, item in model_items.items():
        weight = item.get("weight") or 0.0
        if item.get("gate"):
            # 双源（D-31）：先查 gate 行（新链表单链 submit-v2），无行回退
            # _gate_check(item, form_payload)（旧链 form_submission——m6 脚本路径不变）
            row = _gate_row(conn, session_id, item_id)
            if row is not None:
                passed, reason = (row[0] == "true", row[1])
            else:
                passed, reason = _gate_check(item, form_payload)
            contribution = weight * 100.0 if passed else 0.0
            gate_items.append({
                "item_id": item_id, "std_name": item["std_name"],
                "passed": passed, "reason": reason,
            })
            item_scores.append({
                "item_id": item_id, "std_name": item["std_name"],
                "category": item["category"],
                "required_level": item.get("required_level"),
                "actual_level": None, "gap": None,
                "weight": weight, "score": contribution,
                "gate": True, "gate_passed": passed, "gate_reason": reason,
            })
            total_score += contribution
            continue

        item_measurements = measurements_by_item.get(item_id, [])
        required = item.get("required_level")

        if item_measurements:
            # 有测量 → adjudicate 裁决（冲突取低留人工标记）
            item_final_level, human_review = adjudicate(item_measurements)
            gap = (required - item_final_level) if required is not None else None
            contribution = weight * _normalize_score(item_final_level, NORMALIZE_OBSERVED) * 100.0
            item_scores.append({
                "item_id": item_id, "std_name": item["std_name"],
                "category": item["category"],
                "required_level": required,
                "actual_level": round(item_final_level, 2),
                "gap": round(gap, 2) if gap is not None else None,
                "weight": weight, "score": round(contribution, 2),
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

        # 普通（preferred/plus）缺失 → IMPUTED r 比例补算
        r = _impute_r(observed_items)
        if r is not None:
            actual_level = round(r * 4 + 1, 2)
            gap = (required - actual_level) if required is not None else None
            contribution = weight * _normalize_score(actual_level, NORMALIZE_OBSERVED) * 100.0
            imputed_count += 1
            item_scores.append({
                "item_id": item_id, "std_name": item["std_name"],
                "category": item["category"],
                "required_level": required,
                "actual_level": actual_level,
                "gap": round(gap, 2) if gap is not None else None,
                "weight": weight, "score": round(contribution, 2),
                "gate": False,
                "no_data": False, "imputed": True,
                "human_review": coverage_ratio > IMPUTE_RATIO_THRESHOLD,
            })
            total_score += contribution
            continue

        # O=∅ → 不能补算 → NO_VALID_OBSERVATION + HUMAN_REVIEW_REQUIRED
        observation_status = "NO_VALID_OBSERVATION"
        review_status = "HUMAN_REVIEW_REQUIRED"
        item_scores.append({
            "item_id": item_id, "std_name": item["std_name"],
            "category": item["category"],
            "required_level": required,
            "actual_level": None, "gap": None,
            "weight": weight, "score": 0.0,
            "gate": False, "no_data": True, "imputed": False,
            "observation_status": "NO_VALID_OBSERVATION",
        })

    # 优势 = gap≥0 中权重最大前 3；短板 = gap<0 中 |gap|×weight 最大前 3
    non_gate = [it for it in item_scores if not it.get("gate") and it.get("gap") is not None]
    strengths = sorted(
        (it for it in non_gate if it["gap"] >= 0),
        key=lambda x: (-x["weight"], x["item_id"]),
    )[:3]
    weaknesses = sorted(
        (it for it in non_gate if it["gap"] < 0),
        key=lambda x: (-abs(x["gap"] * x["weight"]), x["item_id"]),
    )[:3]

    coverage = {
        "observed_count": observed_count,
        "imputed_count": imputed_count,
        "total_measureable": total_measureable,
        "coverage_ratio": round(coverage_ratio, 4),
        "missing_reasons": missing_warnings,
    }

    return {
        "session_id": session_id,
        "total_score": round(total_score, 2),
        "item_scores": item_scores,
        "gate_items": gate_items,
        "refusals": refusals,
        "missing_warnings": missing_warnings,
        "coverage": coverage,
        "review_status": review_status,
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
