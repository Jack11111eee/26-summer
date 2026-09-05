"""trace_link 统一审计链写点（SSOT §13.3/D-56）：弱关联 + link_role 枚举代码校验。

业务表不逐一加 trace 外键（D-020）；审计链 report→session→model/version→question→
message→score→trace 通过本表闭合。本模块不 commit——事务边界由调用者持有（照 append_event）。
"""
from .pipeline import new_id, now_iso

# link_role 枚举六值（N11：代码校验，无 DB CHECK）
LINK_ROLES = ("input", "output", "caused_by", "scored", "reported", "source")


def link_entity(conn, *, trace_id, entity_type, entity_id, link_role, created_at=None) -> None:
    """在调用者持有的同一事务内写一条 trace_link（不 commit）。

    link_role 非法 → raise ValueError（阻断非法值落库，T-05-01）。
    """
    if link_role not in LINK_ROLES:
        raise ValueError(f"非法 link_role: {link_role}（允许 {', '.join(LINK_ROLES)}）")
    conn.execute(
        "INSERT INTO trace_link(id, trace_id, entity_type, entity_id, link_role, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (new_id("tl"), trace_id, entity_type, entity_id, link_role, created_at or now_iso()),
    )
