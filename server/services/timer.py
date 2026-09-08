"""计时区间服务（SSOT §15/D-39~D-42——03-04 服务端权威区间）。

双形态（difficulty.py 先例）：
- 纯函数区（不持 conn）：_ts / merge_spans / overlap_seconds——Python merge 重叠区间
  （实验 5 实证 SQL SUM 跨行双计 8 vs 6——Anti-pattern 3 禁 SQL SUM 求和，仅 Python merge）；
- 接 conn 区（不 commit——D-06 契约：事务边界由调用者持有，本模块零 commit）：
  close_open_interval / open_interval / advance_interval / paused_overlap_seconds /
  session_active_seconds / seal_if_question_timed_out / maybe_abandon_session / touch_last_activity。

interval_type ∈ {active, paused}（N11 代码校验，无 DB CHECK）；reason 敏感不进评分 prompt（D-40）。
6h ABANDONED 惰性判定（无后台线程 D-005——A3：判定挂 answer 路径 load_owned_session 相邻）。
"""
import sqlite3
from datetime import datetime

from .. import config
from .pipeline import new_id, now_iso
from .state_events import append_event

_VALID_INTERVAL_TYPES = ("active", "paused")


# ---------- 纯函数区（不持 conn） ----------

def _ts(iso: str) -> datetime:
    """ISO 字符串 → datetime（fromisoformat——now_iso 产物带微秒+时区全兼容实验 8）。"""
    return datetime.fromisoformat(iso)


def merge_spans(spans: list[tuple]) -> list[list]:
    """排序合并重叠区间（实验 5 骨架）：[(0,3),(2,5),(8,10)] → [[0,5],[8,10]]。

    SQL SUM 跨行双计反例（实验 5）：两重叠段直接 SUM 会双计 8+8=16，merge 后只算一次。
    纯函数不类型假设——数值区间（测试直测）与秒浮点区间（生产）均适用。
    """
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: s[0])
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def overlap_seconds(spans_merged: list[list], since, now) -> float:
    """merge 后区间与 [since, now] 窗口的正重叠秒数和（min(e,now)-max(s,since) 正则和）。

    纯函数不类型假设：数值区间（测试直测）与 datetime 区间（生产经 .timestamp() 折秒后传入）
    均适用——重叠差即秒数。调用方把 datetime 折成秒浮点后再传（见 _spans_for）。
    """
    total = 0.0
    for start, end in spans_merged:
        s = max(start, since)
        e = min(end, now)
        if e > s:
            total += (e - s)
    return total


# ---------- 接 conn 区（不 commit——D-06 契约：调用者主事务统一 commit） ----------

def close_open_interval(conn, session_id: str, ended_at: str | None = None) -> None:
    """闭合该 session 所有 open 区间（UPDATE ended_at WHERE ended_at IS NULL）；无 open no-op 幂等。"""
    conn.execute(
        "UPDATE session_time_intervals SET ended_at=? WHERE session_id=? AND ended_at IS NULL",
        (ended_at or now_iso(), session_id),
    )


def open_interval(conn, session_id: str, interval_type: str, reason: str | None = None) -> None:
    """开新区间；IntegrityError（部分唯一索引 uq_sti_open 拦双 open）→ 闭旧后重试一次（实验 6 乐观环）。"""
    if interval_type not in _VALID_INTERVAL_TYPES:
        raise ValueError(f"非法 interval_type: {interval_type}（允许 {', '.join(_VALID_INTERVAL_TYPES)}）")
    try:
        conn.execute(
            "INSERT INTO session_time_intervals(interval_id, session_id, interval_type, reason, started_at)"
            " VALUES(?,?,?,?,?)",
            (new_id("sti"), session_id, interval_type, reason, now_iso()),
        )
    except sqlite3.IntegrityError:
        # 双 open 被 uq_sti_open 拦截（实验 6 乐观环）：闭旧后重试一次——FK 违反等非索引源
        # 在重试后自然再次抛出（不吞）
        close_open_interval(conn, session_id)
        conn.execute(
            "INSERT INTO session_time_intervals(interval_id, session_id, interval_type, reason, started_at)"
            " VALUES(?,?,?,?,?)",
            (new_id("sti"), session_id, interval_type, reason, now_iso()),
        )


def advance_interval(conn, session_id: str, interval_type: str, reason: str | None = None) -> None:
    """answer 正常路径单次调用形态：闭旧 → 开新（主事务内，D-39 两动作）。"""
    close_open_interval(conn, session_id)
    open_interval(conn, session_id, interval_type, reason)


def _spans_for(conn, session_id: str, interval_type: str, now_dt: datetime) -> list[tuple[float, float]]:
    """读某类型区间并折成秒浮点 span（open 区间截到 now）。"""
    rows = conn.execute(
        "SELECT started_at, ended_at FROM session_time_intervals WHERE session_id=? AND interval_type=?",
        (session_id, interval_type),
    ).fetchall()
    now_ts = now_dt.timestamp()
    spans = []
    for r in rows:
        s = _ts(r["started_at"]).timestamp()
        e = _ts(r["ended_at"]).timestamp() if r["ended_at"] else now_ts
        spans.append((s, e))
    return spans


def paused_overlap_seconds(conn, session_id: str, since: datetime, now: datetime) -> float:
    """paused 区间与 [since, now] 窗口的重叠秒数（单题超时扣除暂停——merge 后正则和）。"""
    spans = merge_spans(_spans_for(conn, session_id, "paused", now))
    return overlap_seconds(spans, since.timestamp(), now.timestamp())


def session_active_seconds(conn, session_id: str) -> float:
    """active 区间合并后的总秒数（open 区间截到 now——全场超时判定）。"""
    now_dt = _ts(now_iso())
    spans = merge_spans(_spans_for(conn, session_id, "active", now_dt))
    return overlap_seconds(spans, 0.0, now_dt.timestamp())


def question_elapsed_seconds(conn, session_id: str, question_id: str) -> float | None:
    """当前题已耗秒（只读展示，§15 客户端只展示）——seal_if_question_timed_out 同口径。

    now - activated_at - Σpaused 重叠（followup 共用；暂停窗口不计入单题计时）。
    legacy（activated_at NULL）或题不存在返回 None（前端显示为 --:--）。
    """
    row = conn.execute(
        "SELECT activated_at FROM assessment_question WHERE question_id=?",
        (question_id,),
    ).fetchone()
    if row is None or row["activated_at"] is None:
        return None
    now_dt = _ts(now_iso())
    activated = _ts(row["activated_at"])
    paused = paused_overlap_seconds(conn, session_id, activated, now_dt)
    return (now_dt - activated).total_seconds() - paused


def seal_if_question_timed_out(conn, session_id: str, question_id: str, user_id: str) -> bool:
    """单题超时点检（Pitfall 10：activated_at NULL 返 False 不 TypeError）。

    now - activated_at - Σpaused重叠 > QUESTION_TIMEOUT_MINUTES*60 → 封存
    （closed_at+seal_reason='timeout'，answered_at 保持 NULL——照 02-04 refused 路径）+
    QUESTION_SEALED 事件（payload seal_reason='timeout'）+ QUESTION_TIMEOUT 事件（§13.2
    独立枚举）同事务；EVIDENCE_EVALUATED 不写（未作答无证据）。返回 True 由调用方走下一题派发。
    """
    row = conn.execute(
        "SELECT activated_at, closed_at FROM assessment_question WHERE question_id=?",
        (question_id,),
    ).fetchone()
    if row is None or row["activated_at"] is None:
        return False  # legacy（activated_at NULL）跳过判定——Pitfall 10
    if row["closed_at"] is not None:
        return False  # 已封存/已答
    now_dt = _ts(now_iso())
    activated = _ts(row["activated_at"])
    paused = paused_overlap_seconds(conn, session_id, activated, now_dt)
    elapsed = (now_dt - activated).total_seconds() - paused
    if elapsed <= config.QUESTION_TIMEOUT_MINUTES * 60:
        return False
    conn.execute(
        "UPDATE assessment_question SET closed_at=?, seal_reason='timeout' WHERE question_id=?",
        (now_iso(), question_id),
    )
    append_event(conn, session_id=session_id, event_type="QUESTION_SEALED",
                 from_state="active", to_state="sealed", actor_type="candidate", actor_id=user_id,
                 assessment_question_id=question_id, payload={"seal_reason": "timeout"})
    append_event(conn, session_id=session_id, event_type="QUESTION_TIMEOUT",
                 from_state="active", to_state="sealed", actor_type="system",
                 assessment_question_id=question_id)
    return True


def maybe_abandon_session(conn, s: dict) -> None:
    """6h 惰性 ABANDONED 判定（D-42——无后台线程 A3 惰性唯一）。

    last_activity_at（NULL 用 created_at 兜底）距今 > ABANDON_HOURS*3600 且 status in_progress
    → status='abandoned' + phase='ABANDONED' + abandoned_at + SESSION_ABANDONED 事件
    （from in_progress to abandoned）。调用方在 load_owned_session 后、判 status 前（409 护栏前）
    调用；本函数 MUTATE s["status"] 使调用方现有 409 SESSION_NOT_IN_PROGRESS 护栏自然接住。
    不删任何证据（消息/实例行保留——T-03-21/§15）。
    """
    if s.get("status") != "in_progress":
        return
    anchor = s.get("last_activity_at") or s.get("created_at")
    if anchor is None:
        return
    if (_ts(now_iso()) - _ts(anchor)).total_seconds() <= config.ABANDON_HOURS * 3600:
        return
    conn.execute(
        "UPDATE assessment_session SET status='abandoned', phase='ABANDONED', abandoned_at=? WHERE session_id=?",
        (now_iso(), s["session_id"]),
    )
    append_event(conn, session_id=s["session_id"], event_type="SESSION_ABANDONED",
                 from_state="in_progress", to_state="abandoned", actor_type="system")
    s["status"] = "abandoned"
    s["phase"] = "ABANDONED"


def touch_last_activity(conn, session_id: str) -> None:
    """每次写操作尾段刷新 last_activity_at（6h 判定基准——D-42）。"""
    conn.execute(
        "UPDATE assessment_session SET last_activity_at=? WHERE session_id=?",
        (now_iso(), session_id),
    )
