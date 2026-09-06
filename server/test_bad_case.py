"""bad case 候选测试（REF-5.11/D-031）：双分背离 ≥ 阈值建候选，永不自动改分。

阈值已裁决 2（2026-09-06 第十轮收口，SSOT §14）；测试 monkeypatch 显式值
验证检测逻辑，并加生产默认回归（锁裁决值）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server.config as C
from server.db import get_conn
from server.services.pipeline import new_id, now_iso
from server.services.report import _detect_bad_case_divergence


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """只读查询：开连接→读→关，避免持锁（SQLite 单写者）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def test_bad_case_divergence_creates_candidate_and_never_rescores(monkeypatch):
    monkeypatch.setattr(C, "BAD_CASE_DIVERGENCE_THRESHOLD", 2.0)

    conn = get_conn()
    uid = new_id("u")
    pid = new_id("p")
    mid = new_id("m")
    item_id = new_id("ci")
    sid = new_id("as")
    try:
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (uid, "bc_user", "x", "candidate", now_iso()),
        )
        conn.execute(
            "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
            (pid, "bc岗位", "active", now_iso()),
        )
        conn.execute(
            "INSERT INTO competency_model(model_id, position_id, version, status, model_json,"
            " created_at) VALUES(?,?,?,?,?,?)",
            (mid, pid, 1, "confirmed", "{}", now_iso()),
        )
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, importance,"
            " weight, gate) VALUES(?,?,?,?,?,?,?)",
            (item_id, mid, "数据库", "hard_skill", "required", 1.0, 0),
        )
        conn.execute(
            "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
            " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (sid, uid, pid, mid, 1, "in_progress", now_iso(), now_iso()),
        )
        # 两对 question_score：发散 4.0（应建候选）与发散 0.5（不应建候选）
        conn.execute(
            "INSERT INTO question_score(score_id, session_id, item_id, score_live, score_final,"
            " created_at) VALUES(?,?,?,?,?,?)",
            (new_id("qs"), sid, item_id, 5.0, 1.0, now_iso()),
        )
        conn.execute(
            "INSERT INTO question_score(score_id, session_id, item_id, score_live, score_final,"
            " created_at) VALUES(?,?,?,?,?,?)",
            (new_id("qs"), sid, item_id, 3.0, 2.5, now_iso()),
        )
        conn.commit()

        created = _detect_bad_case_divergence(conn, sid)
        assert created == 1  # 仅发散 4.0 那行建候选
        conn.commit()
    finally:
        conn.close()

    # 建候选：status='pending'，记录双分与背离
    cand = _q(
        "SELECT status, score_live, score_final, divergence FROM bad_case_candidate"
        " WHERE session_id=?",
        (sid,),
    )
    assert len(cand) == 1
    assert cand[0]["status"] == "pending"
    assert cand[0]["score_live"] == 5.0
    assert cand[0]["score_final"] == 1.0
    assert cand[0]["divergence"] == 4.0

    # D-031：question_score 的 score_live/score_final 未被检测修改
    qs = _q(
        "SELECT score_live, score_final FROM question_score WHERE session_id=?"
        " ORDER BY score_live DESC",
        (sid,),
    )
    assert (qs[0]["score_live"], qs[0]["score_final"]) == (5.0, 1.0)
    assert (qs[1]["score_live"], qs[1]["score_final"]) == (3.0, 2.5)


def test_bad_case_threshold_unset_skips(monkeypatch):
    monkeypatch.setattr(C, "BAD_CASE_DIVERGENCE_THRESHOLD", None)
    conn = get_conn()
    try:
        # 阈值显式置 None（部署方关闭检测）时直接跳过，不误建候选
        assert _detect_bad_case_divergence(conn, "no-such-session") == 0
    finally:
        conn.close()


def test_bad_case_threshold_production_default():
    """已裁决生产默认 2（2026-09-06，SSOT §14）：极差 2 触发、1 不触发。"""
    assert C.BAD_CASE_DIVERGENCE_THRESHOLD == 2
    assert abs(5.0 - 1.0) >= C.BAD_CASE_DIVERGENCE_THRESHOLD
    assert abs(5.0 - 4.0) < C.BAD_CASE_DIVERGENCE_THRESHOLD
