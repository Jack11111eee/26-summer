"""Phase 5 报告契约测试：adjudicate 裁决 / IMPUTED 补算 / required 缺失 PROVISIONAL / O=∅ NO_VALID_OBSERVATION。

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db。
运行：cd server && python -m pytest test_phase5_report.py -v

纯函数（adjudicate/_impute_r/_normalize_score）懒导入：Task 2 先落地 adjudicate/
_normalize_score，Task 3 落地 _impute_r——懒导入让 Task 2 子集先可收集（同 05-01
_locate_span 先例）。
"""
import json
import os
import sys
import tempfile

import pytest

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase5_report.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.aggregation import aggregate_session_scores  # noqa: E402
# 05-03 报告状态机 / 七项校验符号（Task 2 落地；RED 阶段收集失败）
from server.services.report import (  # noqa: E402
    REPORT_STATUSES,
    REVIEW_STATUSES,
    _assert_report_status,
    _assert_report_transition,
    _run_consistency_checks,
)
from server.services.report_checks import HIRING_REDLINE_WORDS  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _seed_session(items: list[dict]) -> tuple[str, list[str]]:
    """造 position + model + competency_item（含 importance）+ session，返回 (session_id, item_ids)。

    items: list of {std_name, category, importance, weight}（required_level 统一 3，gate 0）。
    只插结构行，不插 question_score——供「缺失」断言（无 SCORED 测量）。
    """
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "后端开发工程师", "active", now),
    )
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,1,'confirmed','{}',?)",
        (mid, pid, now),
    )
    item_ids: list[str] = []
    for it in items:
        iid = new_id("c")
        item_ids.append(iid)
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
            (iid, mid, it["std_name"], it["category"], 3, it["importance"], it["weight"], 0),
        )
    uid = new_id("u")
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,1,?)",
        (uid, uid, "hash", "candidate", now),
    )
    session_id = new_id("as")
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id, model_version,"
        " status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (session_id, uid, pid, mid, 1, "completed", now, now),
    )
    conn.commit()
    conn.close()
    return session_id, item_ids


def test_adjudicate_conflict_lower():
    from server.services.aggregation import adjudicate

    # 重大冲突（差 3 ≥ 阈值 2）→ 取低 + 人工复核
    level, review = adjudicate([{"observed_level": 2}, {"observed_level": 5}])
    assert level == 2.0
    assert review is True

    # 一致场景 → round(mean, 2)，无人工复核
    level, review = adjudicate([{"observed_level": 4}, {"observed_level": 4}])
    assert level == 4.0
    assert review is False

    # 空列表 → (None, False)
    level, review = adjudicate([])
    assert level is None
    assert review is False


def test_impute_r_math():
    from server.services.aggregation import _impute_r

    # r = Σ w_i·s_i / Σ w_i，s_i=(score−1)/4
    r = _impute_r([{"weight": 0.5, "score": 5}, {"weight": 0.5, "score": 1}])
    assert abs(r - 0.5) < 1e-6  # (0.5*1.0 + 0.5*0.0)/1.0 = 0.5

    # weight 全 0 → den=0 → 不除零返回 None
    r = _impute_r([{"weight": 0.0, "score": 5}])
    assert r is None

    # 单观察 → r = 该观察自身归一化值 = (3−1)/4 = 0.5
    r = _impute_r([{"weight": 0.3, "score": 3}])
    assert abs(r - 0.5) < 1e-6


def test_impute_no_valid_observation():
    from server.services.aggregation import _impute_r

    # O=∅ → _impute_r 返回 None
    assert _impute_r([]) is None

    # 聚合层：preferred 缺失 + 无任何 SCORED → NO_VALID_OBSERVATION + HUMAN_REVIEW_REQUIRED
    session_id, _ = _seed_session([
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "preferred", "weight": 0.2},
    ])
    agg = aggregate_session_scores(session_id)
    assert agg["observation_status"] == "NO_VALID_OBSERVATION"
    assert agg["review_status"] == "HUMAN_REVIEW_REQUIRED"


def test_required_missing_provisional():
    # required 缺失（无 SCORED 行）→ item 标 provisional + 顶层 HUMAN_REVIEW_REQUIRED
    session_id, item_ids = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.3},
    ])
    agg = aggregate_session_scores(session_id)
    assert agg["review_status"] == "HUMAN_REVIEW_REQUIRED"
    assert agg["provisional"] is True

    py_item = next(it for it in agg["item_scores"] if it["item_id"] == item_ids[0])
    assert py_item["provisional"] is True
    assert py_item["no_data"] is True


# ============ 05-03 追加：报告状态机 / 七项校验 / 版本化 / publish / FAILED ============

def _ensure_admin() -> None:
    """测试库首跑造 admin（幂等，照 test_m7_backend.py）。"""
    conn = get_conn()
    row = conn.execute("SELECT user_id FROM user WHERE username='admin'").fetchone()
    if row is None:
        from passlib.context import CryptContext

        pwd_ctx = CryptContext(schemes=["bcrypt"])
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (new_id("u"), "admin", pwd_ctx.hash("admin"), "admin", now_iso()),
        )
        conn.commit()
    conn.close()


def _admin_token() -> str:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_admin_token()}"}


def _candidate_headers() -> dict:
    """造一个候选人并登录，返回其 Authorization 头。"""
    from passlib.context import CryptContext

    pwd_ctx = CryptContext(schemes=["bcrypt"])
    uid = new_id("u")
    conn = get_conn()
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,1,?)",
        (uid, uid, pwd_ctx.hash("candpass"), "candidate", now_iso()),
    )
    conn.commit()
    conn.close()
    r = client.post("/api/auth/login", json={"username": uid, "password": "candpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed_report_row(report_status: str = "READY", review_status: str | None = "NONE") -> tuple[str, str]:
    """造外键全链 + report 行（给定状态），返回 (report_id, session_id)。"""
    session_id, _ = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.3},
    ])
    conn = get_conn()
    report_id = new_id("rpt")
    conn.execute(
        "INSERT INTO report(report_id, session_id, total_score, gate_passed, report_json,"
        " report_status, review_status, version, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (report_id, session_id, 0.0, 1, "{}", report_status, review_status, 1, now_iso()),
    )
    conn.commit()
    conn.close()
    return report_id, session_id


def _cross_session_question_score(session_id: str) -> None:
    """给 session_id 插一条 question_score，其 question_id 指向另一个 session 的题（触发校验③）。"""
    conn = get_conn()
    s1 = conn.execute(
        "SELECT position_id, model_id, model_version, user_id FROM assessment_session WHERE session_id=?",
        (session_id,),
    ).fetchone()
    s2 = new_id("as")
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id, model_version,"
        " status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (s2, s1["user_id"], s1["position_id"], s1["model_id"], s1["model_version"],
         "completed", now_iso(), now_iso()),
    )
    qb2 = new_id("qb")
    conn.execute(
        "INSERT INTO question_bank(question_id, scope, position_id, std_name, category, qtype,"
        " stem, source, status, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (qb2, "position", s1["position_id"], "沟通能力", "soft_skill", "subjective", "题",
         "human", "active", now_iso()),
    )
    q2 = new_id("aq")
    conn.execute(
        "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq, created_at)"
        " VALUES(?,?,?,?,?)", (q2, s2, qb2, 1, now_iso()),
    )
    item_id = conn.execute(
        "SELECT ci.item_id FROM competency_item ci WHERE ci.model_id=?", (s1["model_id"],)
    ).fetchone()["item_id"]
    conn.execute(
        "INSERT INTO question_score(score_id, session_id, question_id, item_id, score_final,"
        " score_state, created_at) VALUES(?,?,?,?,?,?,?)",
        (new_id("qs"), session_id, q2, item_id, 3, "SCORED", now_iso()),
    )
    conn.commit()
    conn.close()


def test_status_transition_legality():
    # 合法迁移通过；非法迁移 raise
    legal = [
        ("GENERATING", "PROVISIONAL"), ("GENERATING", "READY"), ("GENERATING", "FAILED"),
        ("PROVISIONAL", "PUBLISHED"), ("PROVISIONAL", "FAILED"),
        ("READY", "PUBLISHED"), ("READY", "FAILED"),
    ]
    for f, t in legal:
        _assert_report_transition(f, t)  # 不抛错
    illegal = [
        ("PUBLISHED", "READY"), ("FAILED", "PUBLISHED"), ("PUBLISHED", "PROVISIONAL"),
        ("PUBLISHED", "FAILED"), ("FAILED", "READY"), ("FAILED", "PROVISIONAL"),
    ]
    for f, t in illegal:
        with pytest.raises(ValueError):
            _assert_report_transition(f, t)
    # 枚举：非法状态值 raise
    with pytest.raises(ValueError):
        _assert_report_status("BOGUS")
    assert tuple(REPORT_STATUSES) == ("GENERATING", "PROVISIONAL", "READY", "PUBLISHED", "FAILED")
    assert len(REVIEW_STATUSES) == 6
    assert "HUMAN_REVIEW_REQUIRED" in REVIEW_STATUSES


def test_consistency_check_fails_to_failed():
    from server.services.report import generate_report

    assert "建议录用" in HIRING_REDLINE_WORDS
    session_id, _ = _seed_session([
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "preferred", "weight": 0.2},
    ])
    agg = aggregate_session_scores(session_id)
    # ① 篡改 total_score → 非空
    tampered = dict(agg)
    tampered["total_score"] = 999.0
    assert _run_consistency_checks(tampered, session_id) != []
    # ⑦ 文案含红线词 → 非空
    assert _run_consistency_checks(agg, session_id, report_text="建议录用该候选人") != []
    # 干净 agg → 全过（空列表）
    assert _run_consistency_checks(agg, session_id) == []
    # ③ 跨 session 引用 question → generate_report 写 FAILED 行
    _cross_session_question_score(session_id)
    report = generate_report(session_id)
    assert report["report_status"] == "FAILED"
    rows = _q("SELECT report_status, report_json FROM report WHERE session_id=?", (session_id,))
    assert rows and rows[0]["report_status"] == "FAILED"
    assert "error" in json.loads(rows[0]["report_json"])


def test_version_immutability():
    from server.services.report import generate_report

    session_id, item_ids = _seed_session([
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "preferred", "weight": 0.2},
    ])
    r1 = generate_report(session_id)
    r2 = generate_report(session_id)
    rows = _q("SELECT report_id, version, report_status FROM report WHERE session_id=? ORDER BY version",
              (session_id,))
    assert len(rows) == 2, f"期望 2 行版本化报告，实际 {len(rows)}"
    assert [r["version"] for r in rows] == [1, 2]
    assert rows[1]["report_id"] == r2["report_id"]
    assert r2["report_id"] != r1["report_id"]
    # 旧 version 1 行仍在（无 DELETE 覆盖）——对其提 feedback 验证 FK 不断裂
    conn = get_conn()
    conn.execute(
        "INSERT INTO feedback(feedback_id, report_id, item_id, feedback_text, status, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (new_id("fb"), rows[0]["report_id"], item_ids[0], "异议", "pending", now_iso()),
    )
    conn.commit()
    conn.close()
    # 最新行 = version 2（get_report_by_session 的 ORDER BY created_at DESC 语义）
    latest = _q("SELECT report_id, version FROM report WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
                (session_id,))
    assert latest[0]["version"] == 2


def test_publish_flow():
    _ensure_admin()
    # 候选人越权 → 403
    report_id, _ = _seed_report_row("READY", "NONE")
    r = client.post(f"/api/admin/reports/{report_id}/publish", headers=_candidate_headers(),
                    json={"review_outcome": "CONFIRMED"})
    assert r.status_code == 403
    # admin 发布 → PUBLISHED + publish_confirmed_by + published_at + REVIEW_REPORT_PUBLISH_CONFIRMED
    r = client.post(f"/api/admin/reports/{report_id}/publish", headers=_admin_headers(),
                    json={"review_outcome": "CONFIRMED"})
    assert r.status_code == 200, r.text
    row = _q("SELECT report_status, publish_confirmed_by, published_at FROM report WHERE report_id=?",
             (report_id,))[0]
    assert row["report_status"] == "PUBLISHED"
    assert row["publish_confirmed_by"] and row["published_at"]
    events = _q("SELECT event_type, to_state, actor_type FROM assessment_state_event"
                " WHERE event_type='REVIEW_REPORT_PUBLISH_CONFIRMED'")
    assert any(e["to_state"] == "PUBLISHED" and e["actor_type"] == "admin" for e in events)
    # review 未满足（HUMAN_REVIEW_REQUIRED 且 review_outcome 非 CONFIRMED）→ 409
    rid2, _ = _seed_report_row("READY", "HUMAN_REVIEW_REQUIRED")
    r = client.post(f"/api/admin/reports/{rid2}/publish", headers=_admin_headers(),
                    json={"review_outcome": "REQUIRED"})
    assert r.status_code == 409


def test_generate_failed_visible(monkeypatch):
    from server.api import assessment as assessment_mod

    _ensure_admin()
    session_id, _ = _seed_session([
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "preferred", "weight": 0.2},
    ])

    def _boom(sid):
        raise RuntimeError("mock 生成失败")

    monkeypatch.setattr(assessment_mod, "generate_report", _boom)
    assessment_mod._generate_report_task(session_id)
    rows = _q("SELECT report_status, report_json FROM report WHERE session_id=?", (session_id,))
    assert any(r["report_status"] == "FAILED" for r in rows)
    events = _q("SELECT event_type FROM assessment_state_event"
                " WHERE event_type='TASK_FAILED' AND session_id=?", (session_id,))
    assert events, "TASK_FAILED 事件应已写入"
    # get_report_by_session 返回 report_status='FAILED'（admin 读豁免）
    r = client.get(f"/api/assessment/reports/by-session/{session_id}", headers=_admin_headers())
    assert r.status_code == 200
    assert r.json()["report_status"] == "FAILED"
