"""能力词典管理（P6）：CRUD / 合并 / 停用。编辑即确认（llm_pending→human）。"""
import json

from fastapi import APIRouter, Depends, HTTPException, status

from ...core.security import require_admin
from ...db import get_conn
from ...services.pipeline import now_iso

router = APIRouter(prefix="/api/admin/dict", tags=["admin-dict"], dependencies=[Depends(require_admin)])


def _row_to_dict(r) -> dict:
    d = dict(r)
    d["aliases"] = json.loads(d.get("aliases_json") or "[]")
    d["exclusions"] = json.loads(d.get("exclusions_json") or "[]")
    d.pop("aliases_json", None)
    d.pop("exclusions_json", None)
    return d


@router.get("")
def list_dict(category: str | None = None, created_by: str | None = None,
              status: str | None = None, q: str | None = None) -> list[dict]:
    """词典列表，支持类目/来源/状态/关键字筛选。"""
    sql = "SELECT * FROM competency_dict WHERE 1=1"
    params: list = []
    if category:
        sql += " AND category=?"
        params.append(category)
    if created_by:
        sql += " AND created_by=?"
        params.append(created_by)
    if status:
        sql += " AND status=?"
        params.append(status)
    if q:
        sql += " AND (std_name LIKE ? OR aliases_json LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY created_by='llm_pending' DESC, updated_at DESC"
    conn = get_conn()
    return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def _alias_conflict(conn, aliases: list[str], self_key: tuple[str, str]) -> str | None:
    """校验别名不与任何标准名/别名冲突。返回冲突的别名，无则 None。"""
    for a in aliases:
        if conn.execute("SELECT 1 FROM competency_dict WHERE std_name=?", (a,)).fetchone():
            return a
        row = conn.execute(
            "SELECT std_name, category FROM competency_dict WHERE aliases_json LIKE ?",
            (f'%"{a}"%',),
        ).fetchone()
        if row and (row["std_name"], row["category"]) != self_key:
            return a
    return None


@router.post("")
def create_entry(body: dict) -> dict:
    """新增标准名（created_by=human）。"""
    std_name = (body.get("std_name") or "").strip()
    category = body.get("category")
    if not std_name or category not in ("hard_skill", "soft_skill", "experience", "qualification"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "std_name 必填，category 须为四类之一")
    conn = get_conn()
    if conn.execute("SELECT 1 FROM competency_dict WHERE std_name=? AND category=?",
                    (std_name, category)).fetchone():
        raise HTTPException(status.HTTP_409_CONFLICT, "该标准名+类目已存在")
    aliases = body.get("aliases") or []
    conflict = _alias_conflict(conn, aliases, (std_name, category))
    if conflict:
        raise HTTPException(status.HTTP_409_CONFLICT, f"别名「{conflict}」与现有标准名/别名冲突")
    conn.execute(
        "INSERT INTO competency_dict(std_name, category, definition, exclusions_json,"
        " aliases_json, created_by, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (std_name, category, body.get("definition"), json.dumps(body.get("exclusions") or [], ensure_ascii=False),
         json.dumps(aliases, ensure_ascii=False), "human", "active", now_iso(), now_iso()),
    )
    conn.commit()
    return {"std_name": std_name, "category": category, "created_by": "human"}


@router.put("/{std_name}/{category}")
def update_entry(std_name: str, category: str, body: dict) -> dict:
    """编辑定义/排除项/别名；保存即 created_by=human（编辑即确认）。"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM competency_dict WHERE std_name=? AND category=?",
                       (std_name, category)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "词典条目不存在")
    aliases = body.get("aliases")
    if aliases is None:
        aliases = json.loads(row["aliases_json"] or "[]")
    conflict = _alias_conflict(conn, aliases, (std_name, category))
    if conflict:
        raise HTTPException(status.HTTP_409_CONFLICT, f"别名「{conflict}」与现有标准名/别名冲突")
    conn.execute(
        "UPDATE competency_dict SET definition=?, exclusions_json=?, aliases_json=?,"
        " created_by='human', updated_at=? WHERE std_name=? AND category=?",
        (body.get("definition", row["definition"]),
         json.dumps(body.get("exclusions", json.loads(row["exclusions_json"] or "[]")), ensure_ascii=False),
         json.dumps(aliases, ensure_ascii=False), now_iso(), std_name, category),
    )
    conn.commit()
    return {"std_name": std_name, "category": category, "created_by": "human", "saved": True}


@router.post("/merge")
def merge_entries(body: dict) -> dict:
    """合并：from 的标准名并入 to 的别名；from 条目删除，to 保存即 human。"""
    frm, to = body.get("from"), body.get("to")
    if not frm or not to:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "需提供 from 与 to")
    conn = get_conn()
    from_row = conn.execute("SELECT * FROM competency_dict WHERE std_name=? AND category=?",
                            (frm["std_name"], frm["category"])).fetchone()
    to_row = conn.execute("SELECT * FROM competency_dict WHERE std_name=? AND category=?",
                          (to["std_name"], to["category"])).fetchone()
    if from_row is None or to_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "from 或 to 条目不存在")

    to_aliases = json.loads(to_row["aliases_json"] or "[]")
    if frm["std_name"] not in to_aliases:
        to_aliases.append(frm["std_name"])
    # from 的别名也并入
    to_aliases += [a for a in json.loads(from_row["aliases_json"] or "[]") if a not in to_aliases]
    conn.execute(
        "UPDATE competency_dict SET aliases_json=?, created_by='human', updated_at=?"
        " WHERE std_name=? AND category=?",
        (json.dumps(to_aliases, ensure_ascii=False), now_iso(), to["std_name"], to["category"]),
    )
    conn.execute("DELETE FROM competency_dict WHERE std_name=? AND category=?",
                 (frm["std_name"], frm["category"]))
    conn.commit()
    return {"merged": frm["std_name"], "into": to["std_name"], "aliases": to_aliases}


@router.delete("/{std_name}/{category}")
def delete_entry(std_name: str, category: str) -> dict:
    """被 competency_item 引用 → 仅停用；无引用 → 真删。"""
    conn = get_conn()
    row = conn.execute("SELECT std_name FROM competency_dict WHERE std_name=? AND category=?",
                       (std_name, category)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "词典条目不存在")
    referenced = conn.execute(
        "SELECT 1 FROM competency_item WHERE std_name=? AND category=? LIMIT 1",
        (std_name, category),
    ).fetchone()
    if referenced:
        conn.execute("UPDATE competency_dict SET status='disabled', updated_at=?"
                     " WHERE std_name=? AND category=?", (now_iso(), std_name, category))
        conn.commit()
        return {"std_name": std_name, "category": category, "status": "disabled",
                "note": "已被模型引用，仅停用未删除"}
    conn.execute("DELETE FROM competency_dict WHERE std_name=? AND category=?", (std_name, category))
    conn.commit()
    return {"std_name": std_name, "category": category, "status": "deleted"}
