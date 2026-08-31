"""选题算法（07 文档 §6.2/§6.3，代码执行可审计）。

每会话 10~12 题 ≈ 硬技能 6~7 / 软技能 2~3 / 经验 2 / 门槛走表单不占题；
required 项必考，其余按权重大小优先；硬技能沿 easy→medium→hard 递进（chain_key 链条）。
"""
from ..db import get_conn

# 各类目选题配额（07 §6.2 题量分配）
CATEGORY_QUOTA = {"hard_skill": 6, "soft_skill": 2, "experience": 2}


def _load_item_meta(model: dict) -> dict[tuple[str, str], dict]:
    """(std_name, category) → {importance, weight}，用于 required 优先与权重排序。"""
    return {
        (it["std_name"], it["category"]): it
        for it in model.get("items", [])
    }


def _pick_category(conn, position_id: str, category: str, quota: int,
                   item_meta: dict, used: set[str]) -> list[dict]:
    """单类目选题：required 优先 → 权重大优先；沿 chain_key 取满难度链（easy→medium→hard）。"""
    rows = conn.execute(
        "SELECT * FROM question_bank WHERE status='active' AND category=?"
        " AND (scope='general' OR (scope='position' AND position_id=?))"
        " ORDER BY CASE difficulty WHEN 'easy' THEN 0 WHEN 'medium' THEN 1 WHEN 'hard' THEN 2 ELSE 3 END",
        (category, position_id),
    ).fetchall()

    def sort_key(r):
        meta = item_meta.get((r["std_name"], r["category"]), {})
        required = 0 if meta.get("importance") == "required" else 1
        return (required, -(meta.get("weight") or 0), r["question_id"])

    picked: list[dict] = []
    seen_items: set[str] = set()
    for r in sorted(rows, key=sort_key):
        if r["question_id"] in used or r["std_name"] in seen_items:
            continue
        # 有链条则整链按 chain_seq 入选（难度递进 N1）；无链取单题
        if r["chain_key"]:
            chain = [c for c in rows
                     if c["chain_key"] == r["chain_key"] and c["question_id"] not in used]
            chain.sort(key=lambda c: c["chain_seq"] or 0)
        else:
            chain = [r]
        for c in chain:
            if len(picked) >= quota:
                break
            picked.append(dict(c))
            used.add(c["question_id"])
        seen_items.add(r["std_name"])
        if len(picked) >= quota:
            break
    return picked


def select_questions_for_session(position_id: str, model: dict) -> list[dict]:
    """为新测评会话选 10~12 道题（门槛项走表单不占题）。返回 question_bank 行列表。"""
    conn = get_conn()
    item_meta = _load_item_meta(model)
    used: set[str] = set()
    selected: list[dict] = []
    for category, quota in CATEGORY_QUOTA.items():
        selected.extend(_pick_category(conn, position_id, category, quota, item_meta, used))
    return selected
