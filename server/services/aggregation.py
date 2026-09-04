"""会话级分数聚合（07 文档 §10.2 阶段② + SSOT §12.4 分母规则，代码执行可审计）。

item 得分 = 该项各题 score_final 均分（仅 SCORED 行进能力分母）；gap = required − actual；
总分 = Σ(item.weight × actual/5) × 100（U3 复用 item.weight，不二次乘）；
gate 项代码二值判定（达标拿满 / 不达标 0），不进 1~5 级评分。

score_state 分母规则（02-05，Pitfall 7）：
- SCORED → 进正常观察（能力等级分母）；
- REFUSED → 不进能力分母，只进行为/完整度聚合（refusals 单列列表）；
- INVALIDATED/INCOMPLETE/INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED → 排除 +
  missing_warnings 警告列表（不隐式转 0，不静默——前向兼容 Phase 5 生产态）。
"""
import json

from ..db import get_conn


def _load_model_items(session_id: str) -> dict[str, dict]:
    """item_id → {std_name, category, required_level, weight, gate, years}"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT ci.item_id, ci.std_name, ci.category, ci.required_level, ci.weight,"
        " ci.gate, ci.years"
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

    score_state 三路分流（§12.4）：SCORED 进分母；REFUSED 进 refusals 列表；
    排除态（INVALIDATED/INCOMPLETE/INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED）进
    missing_warnings 警告列表。
    """
    conn = get_conn()
    model_items = _load_model_items(session_id)
    form_payload = _load_form_payload(session_id)

    # 按 item 分组收 score_final（score_state 过滤在循环内分流——三路）
    rows = conn.execute(
        "SELECT qs.item_id, qs.score_final, qs.score_state, qs.question_id"
        " FROM question_score qs WHERE qs.session_id=?",
        (session_id,),
    ).fetchall()
    item_scores_map: dict[str, list[int]] = {}
    refusals: list[dict] = []
    missing_warnings: list[dict] = []
    _EXCLUDED_STATES = ("INVALIDATED", "INCOMPLETE", "INSUFFICIENT_EVIDENCE", "NOT_ADMINISTERED")
    for r in rows:
        std_name = (model_items.get(r["item_id"]) or {}).get("std_name")
        if r["score_state"] == "SCORED":
            item_scores_map.setdefault(r["item_id"], []).append(r["score_final"])
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
        # 其余枚举值（Phase 5 生产态 IMPUTED 等）不在 Phase 2 过滤名单——
        # 过度过滤会与 Phase 5 冲突（plan <interfaces> 注记）

    item_scores: list[dict] = []
    gate_items: list[dict] = []
    total_score = 0.0

    for item_id, item in model_items.items():
        weight = item.get("weight") or 0.0
        if item.get("gate"):
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

        finals = item_scores_map.get(item_id, [])
        if not finals:
            # 未出题/未作答项：不计分，不贡献总分
            item_scores.append({
                "item_id": item_id, "std_name": item["std_name"],
                "category": item["category"],
                "required_level": item.get("required_level"),
                "actual_level": None, "gap": None,
                "weight": weight, "score": 0.0,
                "gate": False, "no_data": True,
            })
            continue

        actual = sum(finals) / len(finals)
        required = item.get("required_level")
        gap = (required - actual) if required is not None else None
        contribution = weight * (actual / 5.0) * 100.0
        item_scores.append({
            "item_id": item_id, "std_name": item["std_name"],
            "category": item["category"],
            "required_level": required,
            "actual_level": round(actual, 2),
            "gap": round(gap, 2) if gap is not None else None,
            "weight": weight, "score": round(contribution, 2),
            "gate": False,
        })
        total_score += contribution

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

    return {
        "session_id": session_id,
        "total_score": round(total_score, 2),
        "item_scores": item_scores,
        "gate_items": gate_items,
        "refusals": refusals,
        "missing_warnings": missing_warnings,
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
