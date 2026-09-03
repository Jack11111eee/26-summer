"""assessment_state_event 唯一写入入口（SSOT §13.1：append-only 状态事件表）。

事件行与快照列更新必须在调用者已持有的同一事务内完成——本模块不 commit，
事务边界由调用者持有。纠错不 UPDATE/DELETE（触发器已禁止），走补偿事件。
"""
import json

from .pipeline import new_id, now_iso

# actor_type 枚举三值（N11：代码校验，无 DB CHECK；D-07）
_VALID_ACTOR_TYPES = ("candidate", "system", "admin")


def append_event(
    conn,
    *,
    session_id: str,
    event_type: str,
    from_state: str | None = None,
    to_state: str | None = None,
    actor_type: str = "system",
    actor_id: str | None = None,
    assessment_question_id: str | None = None,
    assessment_message_id: str | None = None,
    payload: dict | None = None,
) -> None:
    """在调用者已持有的同一事务内追加一条状态事件（不 commit）。

    sequence_no 取号：同事务 SELECT COALESCE(MAX(sequence_no),0)+1——
    SQLite 单写者下安全，UNIQUE(session_id, sequence_no) 为并发兜底。
    未使用的 SSOT §13.1 列（request_id/idempotency_key/policy_version/
    correlation_id 等）不写即默认 NULL。
    """
    if actor_type not in _VALID_ACTOR_TYPES:
        raise ValueError(f"非法 actor_type: {actor_type}（允许 {', '.join(_VALID_ACTOR_TYPES)}）")
    seq = conn.execute(
        "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM assessment_state_event WHERE session_id=?",
        (session_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO assessment_state_event(id, session_id, sequence_no, assessment_question_id,"
        " assessment_message_id, event_type, from_state, to_state, actor_type, actor_id,"
        " payload_json, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("asev"), session_id, seq, assessment_question_id, assessment_message_id,
         event_type, from_state, to_state, actor_type, actor_id,
         json.dumps(payload, ensure_ascii=False) if payload else None, now_iso()),
    )
