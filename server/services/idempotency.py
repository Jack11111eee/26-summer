"""幂等与并发防护（SSOT §13.4 / D-36~D-38——REF-4.9 三键作用域 + 两阶段）。

三键作用域 = session_id + endpoint + idempotency_key，落 idempotency_record 表
（UNIQUE 三键拦并发双发——IntegrityError 即并发中或已完成）。两阶段 = INSERT PENDING
占位 → 业务链完成后 UPDATE COMMITTED + response_snapshot（决策结果 dict JSON，白名单键
不含候选人输入原文——A1）。

事务边界（D-06/T-02-13）：
- check_idempotency 接调用方主 conn、不 commit——PENDING 占位随主链首笔 commit 落库；
- finalize_idempotency 自取新连接 + 自身 commit（主链已 commit，新事务干净——answer
  返回 StreamingResponse 前的最后写点，避免 generator 启动前残留写锁）。

W1 修订（修订轮 1）：COMMITTED 命中先比 request_hash——同 key 异 payload 不得回放旧快照。
"""
import hashlib
import json
import sqlite3

from fastapi import HTTPException, status

from ..db import get_conn
from .pipeline import new_id, now_iso


def request_hash_of(payload: dict, extra: dict | None = None) -> str:
    """sha256 规范化 JSON（Claude 裁量：sort_keys=True 保证字段序无关）。

    答题付三键（question_instance_id/expected_question_revision/client_attempt_id）
    并入 extra（D-36——request_hash 计入幂等维度）。refine.py:30 hashlib 用法照抄。
    """
    blob = json.dumps({"payload": payload, "extra": extra or {}},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def check_idempotency(conn, *, session_id: str, endpoint: str, key: str,
                      request_hash: str) -> dict | None:
    """幂等三键检查（两阶段入口）。

    - 无行 → INSERT PENDING 占位（并发双发时 UNIQUE 拦截 IntegrityError → 重查按状态分支）→ None；
    - 命中 PENDING → 409 REQUEST_IN_PROGRESS（并发进行中快速失败）；
    - 命中 COMMITTED → 先比 request_hash（W1）：一致返回快照 dict（API 层直接 200 JSON）；
      不一致 raise 409 IDEMPOTENCY_KEY_REUSED（同 key 异 payload 不回放旧快照）。
    """
    row = conn.execute(
        "SELECT status, request_hash, response_snapshot FROM idempotency_record"
        " WHERE session_id=? AND endpoint=? AND idempotency_key=?",
        (session_id, endpoint, key),
    ).fetchone()
    if row is None:
        try:
            conn.execute(
                "INSERT INTO idempotency_record(id, session_id, endpoint, idempotency_key,"
                " request_hash, status, created_at) VALUES(?,?,?,?,?, 'PENDING', ?)",
                (new_id("idem"), session_id, endpoint, key, request_hash, now_iso()),
            )
        except sqlite3.IntegrityError:
            # 并发双发：对方已插入（UNIQUE 拦截）——重查一次，按状态分支处理
            row = conn.execute(
                "SELECT status, request_hash, response_snapshot FROM idempotency_record"
                " WHERE session_id=? AND endpoint=? AND idempotency_key=?",
                (session_id, endpoint, key),
            ).fetchone()
        else:
            return None  # 首次——PENDING 占位成功，业务链继续

    # row 存在（首查命中或 IntegrityError 重查所得）
    if row["status"] == "COMMITTED":
        if row["request_hash"] != request_hash:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                detail={"error_code": "IDEMPOTENCY_KEY_REUSED",
                                        "message": "同幂等键已被不同请求体使用"})
        try:
            return json.loads(row["response_snapshot"])
        except (json.JSONDecodeError, TypeError):
            # 快照损坏视为不可回放脏数据 → 409 进行中（防回放损坏快照）
            raise HTTPException(status.HTTP_409_CONFLICT,
                                detail={"error_code": "REQUEST_IN_PROGRESS",
                                        "message": "幂等快照损坏，请求视为处理中"})
    raise HTTPException(status.HTTP_409_CONFLICT,
                        detail={"error_code": "REQUEST_IN_PROGRESS",
                                "message": "同幂等键请求处理中"})


def finalize_idempotency(*, session_id: str, endpoint: str, key: str,
                         snapshot: dict) -> None:
    """两阶段收尾：PENDING → COMMITTED + response_snapshot（三键 WHERE）。

    自取新连接 + 自身 commit（主链已 commit，新事务干净——answer 返回
    StreamingResponse 前的最后写点，避免 generator 启动前残留写锁）。
    """
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE idempotency_record SET status='COMMITTED', response_snapshot=?"
            " WHERE session_id=? AND endpoint=? AND idempotency_key=?",
            (json.dumps(snapshot, ensure_ascii=False), session_id, endpoint, key),
        )
        conn.commit()
    finally:
        conn.close()
