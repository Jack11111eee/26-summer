"""会话级分数聚合（07 文档 §10.2 阶段②，代码执行可审计）。

item 得分 = 该项各题 final_score 均分；gap = required − actual；
总分 = Σ(item.weight × actual/5) × 100（U3 复用 item.weight，不二次乘）；
gate 项代码二值判定（达标拿满 / 不达标 0），不进 1~5 级评分。
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
    """聚合 question_score → item_scores + total_score + gate_items + strengths/weaknesses。"""
    conn = get_conn()
    model_items = _load_model_items(session_id)
    form_payload = _load_form_payload(session_id)

    # 按 item 分组收 final_score
    rows = conn.execute(
        "SELECT item_id, final_score FROM question_score WHERE session_id=?",
        (session_id,),
    ).fetchall()
    item_scores_map: dict[str, list[int]] = {}
    for r in rows:
        item_scores_map.setdefault(r["item_id"], []).append(r["final_score"])

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
