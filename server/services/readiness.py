"""开考前可测量性检查（SSOT §10.4 全链骨架，D-11）。

check_session_readiness 在 create_session 的 INSERT 会话前预检：不通过返回
{"error_code": ..., "detail": ...}，API 层转 409（拒绝创建 0 题会话，REF-3.5）。

三态检查失败名（QUESTION_BANK_GENERATING / QUESTION_BANK_INCOMPLETE /
MODEL_NOT_MEASURABLE）只在本函数统一返回（D-11）。
配额口径用 question_selection.plan_quotas（SSOT §10.1-10.3：岗位级 N + 7:3 最大
余数 + tier 0.8/0.6/1.7 公式，与运行时选题同源——防两处公式漂移，WR-15 教训）。
"""
from ..db import get_conn
from .. import config
from .question_bank import strict_fields_sql
from .question_selection import ORDINARY_CATEGORIES, largest_remainder_73


def _question_count_by_category(conn, position_id: str, model_id: str,
                                model_version: int) -> dict[str, int]:
    """按 category 计数实际可选 active 题（照抄 question_selection 的 WHERE 口径）。

    scope='general' 跨岗位可见；scope='position' 仅本岗位可见；两者同绑 model/version。
    QBANK_STRICT_FIELDS=True 时叠加五字段齐全谓词（§9.4 契约第 1 条——「待审核」题
    不计入可选题量；默认 False 现状行为不回归）。
    """
    rows = conn.execute(
        "SELECT category, COUNT(*) c FROM question_bank WHERE status='active'"
        " AND model_id=? AND model_version=?"
        " AND (scope='general' OR (scope='position' AND position_id=?))"
        f" AND {strict_fields_sql()}"
        " GROUP BY category",
        (model_id, model_version, position_id),
    ).fetchall()
    return {r["category"]: r["c"] for r in rows}


def _covered_std_names(conn, position_id: str, model_id: str,
                       model_version: int) -> set[str]:
    """题库中已覆盖的 std_name 集合（与配额计数同一 WHERE 口径——含 strict 谓词）。"""
    rows = conn.execute(
        "SELECT DISTINCT std_name FROM question_bank WHERE status='active'"
        " AND model_id=? AND model_version=?"
        " AND (scope='general' OR (scope='position' AND position_id=?))"
        f" AND {strict_fields_sql()}",
        (model_id, model_version, position_id),
    ).fetchall()
    return {r["std_name"] for r in rows}


def check_session_readiness(position_id: str, model=None) -> dict | None:
    """开考前可测量性检查（§10.4）。通过返回 None；不通过返回失败三态 dict。

    WR-06：model 可选传入（调用方已取的 confirmed 模型行——单源化「最新
    confirmed 版」取用，create_session 复用同一行避免两次独立查询的口径漂移）；
    缺省时内部自取（readiness 独立调用口径不变）。

    §10.4 全链骨架（Phase 1 实现 1-5 项）：
    1) position active（status != 'active' → MODEL_NOT_MEASURABLE，W-2 写死，
       复用为"岗位不可开测"语义载体，不新增第 4 个状态名）
    2) 模型 confirmed + items 非空（items 空 → MODEL_NOT_MEASURABLE，REF-8.5）
    3) 题库 readiness（question_bank_task 驱动 → GENERATING / INCOMPLETE）
    4) required item 至少一题覆盖（普通类目 hard/soft；exp/qual 不生成题不参与——
       SSOT §9.1 2026-09-07；缺 → INCOMPLETE）
    5) 配额可行（§10.1-10.3 N + 7:3 + tier 目标比对题库实际量；不足 → INCOMPLETE）
    6) 综合题槽位：本期综合题不排期（I=0）→ 恒过（by-design，SSOT §10.4 2026-09-06 注记）
    7) qualification 表单 schema：由会话模型 gate=1 items 动态展开生成
       （form_instance.schema_snapshot），存在性已被第 2 项 items 检查隐式覆盖
       → 恒过（by-design，SSOT §10.4 2026-09-06 注记）
    """
    conn = get_conn()
    try:
        return _check_session_readiness_locked(conn, position_id, model)
    finally:
        # WR-11：与同模块调用方（API/测试）的 try/finally close 纪律一致——
        # 不依赖 CPython 引用计数释放连接
        conn.close()


def _check_session_readiness_locked(conn, position_id: str, model=None) -> dict | None:
    # 1) position active（W-2：inactive 分支写死，勿留占位或放行；
    #    岗位存在性/无 confirmed 模型仍走 create_session 既有 404 路径）
    pos = conn.execute(
        "SELECT status FROM position WHERE position_id=?", (position_id,)
    ).fetchone()
    if pos is None or pos["status"] != "active":
        return {"error_code": "MODEL_NOT_MEASURABLE",
                "detail": "该岗位当前未上架，不可开考"}

    # 2) 最新 confirmed 模型 + items 非空（传参单源——WR-06；缺省自取同款口径）
    if model is None:
        model = conn.execute(
            "SELECT model_id, version, model_json FROM competency_model"
            " WHERE position_id=? AND status='confirmed' ORDER BY version DESC LIMIT 1",
            (position_id,),
        ).fetchone()
    if model is None:
        return None  # 无 confirmed 模型：create_session 既有 404 语义，不在此重复检查
    item_count = conn.execute(
        "SELECT json_array_length(json_extract(model_json,'$.items')) c"
        " FROM competency_model WHERE model_id=?",
        (model["model_id"],),
    ).fetchone()["c"]
    if not item_count:
        return {"error_code": "MODEL_NOT_MEASURABLE",
                "detail": "该岗位模型无可测能力项，无法开考"}

    # 3) 题库 readiness：按 (position_id, model_id, model_version) 取最新 task 行
    task = conn.execute(
        "SELECT status, error_msg FROM question_bank_task"
        " WHERE position_id=? AND model_id=? AND model_version=?"
        " ORDER BY created_at DESC LIMIT 1",
        (position_id, model["model_id"], model["version"]),
    ).fetchone()
    if task is not None and task["status"] in ("QUEUED", "RUNNING"):
        return {"error_code": "QUESTION_BANK_GENERATING",
                "detail": "该岗位题库正在生成中，请稍后开考"}
    if task is not None and task["status"] == "FAILED":
        # WR-03：面向考生仅固定文案，不拼内部 error_msg（ASVS V7.4.1）；
        # 内部细节保留在管理员侧 todos.question_bank_failed 明细
        return {"error_code": "QUESTION_BANK_INCOMPLETE",
                "detail": "该岗位题库生成失败，不可开考"}
    # SUCCEEDED 或无 task 行 → 看实际可选题量（兼容 m5/m6 直插题库种子，Pitfall 3）

    # 4)+5) required 覆盖 + 配额可行（按实际题量判定）
    counts = _question_count_by_category(conn, position_id, model["model_id"], model["version"])
    covered = _covered_std_names(conn, position_id, model["model_id"], model["version"])
    # SSOT §9.1（2026-09-07）：exp/qual 不生成题、不参与题库覆盖检查——带 required
    # 的无年限 experience（gate=0）若不豁免，停生成后会被误判缺题阻断开考
    required_items = conn.execute(
        "SELECT std_name FROM competency_item WHERE model_id=? AND importance='required'"
        " AND gate=0 AND category IN ('hard_skill','soft_skill')",
        (model["model_id"],),
    ).fetchall()
    missing_required = [r["std_name"] for r in required_items if r["std_name"] not in covered]
    # CR-04：配额只在模型实际含该类目时才要求——SSOT §8「若某大类无有效能力项，
    # 现有大类归一到 1.00」——纯软技能/纯硬技能岗位是合法形态（纯单类时大类配额
    # 归一并入该类，见 plan_quotas 退化处理）
    needed_categories = {
        r["category"] for r in conn.execute(
            "SELECT DISTINCT category FROM competency_item WHERE model_id=? AND gate=0",
            (model["model_id"],),
        ).fetchall()
    }
    # tier 可用量：只统计模型实际含类目的普通题（题库行 tier 近似——item 归属按
    # std_name+category 匹配 competency_item importance）
    available: dict[str, dict[str, int]] = {}
    for category in needed_categories:
        if category not in ORDINARY_CATEGORIES:
            continue  # experience/qualification 走表单，不占普通配额
        tiers: dict[str, int] = {"required": 0, "preferred": 0, "plus": 0}
        rows = conn.execute(
            "SELECT COALESCE(ci.importance, 'plus') AS tier, COUNT(*) c"
            " FROM question_bank qb"
            " LEFT JOIN competency_item ci ON ci.model_id=?"
            " AND ci.std_name=qb.std_name AND ci.category=qb.category"
            " WHERE qb.status='active' AND qb.category=?"
            " AND qb.model_id=? AND qb.model_version=?"
            " AND (qb.scope='general' OR (qb.scope='position' AND qb.position_id=?))"
            f" AND {strict_fields_sql('qb')}"
            " GROUP BY COALESCE(ci.importance, 'plus')",
            (model["model_id"], category, model["model_id"], model["version"], position_id),
        ).fetchall()
        for r in rows:
            tiers[r["tier"]] = r["c"]
        available[category] = tiers

    n = config.ORDINARY_PLAN_N
    # WR-01：用未 clamp 的原始大类配额对比实际题量。旧实现 `have < min(target_total,
    # sum(available))` 中 target_total 来自 plan_quotas（tier_targets 已按可用量 clamp），
    # 故 target_total ≤ sum(available) = have，缺口判定恒为 False——题量不足仍放行开考。
    hard_n, soft_n = largest_remainder_73(n)
    cat_quota = {"hard_skill": hard_n, "soft_skill": soft_n}
    present = [c for c in ORDINARY_CATEGORIES if c in available]
    raw_target = {c: cat_quota[c] for c in present}
    if len(present) == 1:
        raw_target[present[0]] = n  # 大类退化：单类目岗位另一类名额并入本类（对齐 plan_quotas）
    gaps: list[str] = []
    for category, target in raw_target.items():
        have = counts.get(category, 0)
        if have < target:
            gaps.append(f"{category} {have}/{target}")
    if missing_required or gaps:
        detail = "该岗位题库不完整，不可开考"
        if missing_required:
            detail += f"（必备能力项缺题：{'、'.join(missing_required[:10])}）"
        if gaps:
            detail += f"（配额不足：{'、'.join(gaps)}）"
        return {"error_code": "QUESTION_BANK_INCOMPLETE", "detail": detail}

    # 6) 综合题槽位：本期不排期（I=0）→ 恒过 by-design（SSOT §10.4 注记，2026-09-06）
    # 7) qualification 表单 schema：由 items 动态展开生成，已被第 2 项隐式覆盖 → 恒过
    #    by-design（SSOT §10.4 注记，2026-09-06；无独立"schema 缺失"失败模式）
    return None
