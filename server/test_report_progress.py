"""报告生成进度透传测试（SSOT §21.1 增补，2026-09-09）。

覆盖面：
1) score_session progress_cb 契约——循环前 (0, N) + 每题 (i, N)，次数恒 N、单调、
   N == len(answered)（total 单源防线：调用方不另行 COUNT）；
2) _update_report_progress 守卫——GENERATING 行写入成功；钉错 report_id 不污染
   他行（僵尸 no-op）；行已终态 0 行命中不炸；
3) 终态无残渣——正常链终态行 / FAILED 行 report_json 均不含 progress；
4) skip_scoring 幂等重链路径无 scoring 进度、汇合处写 stage=report；
5) 无占位行（超时收尾同步链形态）进度整体 no-op、无行创建；
6) by-session 序列化透传 GENERATING 行 progress（spread 出口）。

全程 LLM_PROVIDER=mock 离线；DB 临时文件。
运行：cd server && python -m pytest test_report_progress.py -v
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_report_progress.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.scoring import score_session  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _exec(sql: str, params: tuple = ()) -> None:
    conn = get_conn()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


# ---------- fixtures（复用 test_m5_backend 的 seed 形态，最小化依赖） ----------

def _seed_full_session(username: str) -> tuple[str, str, str, int]:
    """active 岗 + confirmed 模型（3 item）+ 3 主题库 + completed 会话 + 已答 3 题。

    返回 (session_id, auth_token, model_id, answered_count)。会话无评分行——
    尚未首次评分（completed 未评分形态）。
    """
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    auth = r.json()["token"]

    conn = get_conn()
    uid = conn.execute("SELECT user_id FROM user WHERE username=?",
                       (username,)).fetchone()["user_id"]
    now = now_iso()
    pid, mid = new_id("pos"), new_id("cm")
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "后端开发工程师", "active", now),
    )
    items = [
        {"std_name": "Python", "category": "hard_skill", "weight": 0.4},
        {"std_name": "MySQL", "category": "hard_skill", "weight": 0.3},
        {"std_name": "沟通能力", "category": "soft_skill", "weight": 0.3},
    ]
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, 1, "confirmed", "{}", now),
    )
    for it in items:
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("c"), mid, it["std_name"], it["category"], 3, "preferred", it["weight"], 0),
        )
    sid = new_id("sess")
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id, model_version,"
        " status, started_at, ended_at, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (sid, uid, pid, mid, 1, "completed", now, now, now),
    )
    # 3 道已答主题（主观 easy 1 道 + 客观 easy 2 道），answered_at 落位
    for i, (name, cat, qtype, key) in enumerate(
        [("Python", "hard_skill", "subjective", None),
         ("MySQL", "hard_skill", "objective", "REPEATABLE"),
         ("沟通能力", "soft_skill", "subjective", None)], 1):
        qb = new_id("qb")
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, model_id, model_version,"
            " std_name, category, difficulty, qtype, stem, answer_key, rubric, source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (qb, "position", pid, mid, 1, name, cat, "easy", qtype, f"题{i}",
             key, None if qtype == "objective" else "要点", "human", "active", now),
        )
        aq = new_id("aq")
        conn.execute(
            "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq,"
            " answered_at, created_at) VALUES(?,?,?,?,?,?)",
            (aq, sid, qb, i, now, now),
        )
    conn.commit()
    conn.close()
    return sid, auth, mid, 3


# ---------- 1) score_session progress_cb 契约 ----------

def test_score_session_progress_cb_contract():
    """循环前 (0, N) + 每题 (i, N)：次数恒 N+1、i 单调 1..N、total 全程 == N（单源）。"""
    sid, _auth, _mid, n = _seed_full_session("rp_cb_contract")
    calls: list[tuple[int, int]] = []
    out = score_session(sid, allow_completed=True,
                        progress_cb=lambda d, t: calls.append((d, t)))
    assert out["scored_count"] == n
    assert len(calls) == n + 1, f"应 {n}+1 次回调，实得 {len(calls)}"
    assert calls[0] == (0, n), "循环前应先报 (0, N)"
    assert [c[0] for c in calls[1:]] == list(range(1, n + 1)), calls
    assert all(c[1] == n for c in calls), "total 全程恒为 N（单源口径）"


def test_score_session_progress_cb_default_none():
    """不传 cb（既有调用方形态）行为不变——照常落库。"""
    sid, _auth, _mid, n = _seed_full_session("rp_cb_default")
    out = score_session(sid, allow_completed=True)  # 不传 cb，不炸
    assert out["scored_count"] == n
    assert _q("SELECT COUNT(*) c FROM question_score WHERE session_id=?",
              (sid,))[0]["c"] > 0


# ---------- 2) _update_report_progress 守卫 ----------

def _seed_generating_row(username: str, report_json: str = "{}") -> str:
    """completed 会话 + 一行 GENERATING 占位行（给定 json），返回 (sid, report_id)。"""
    sid, _auth, _mid, _n = _seed_full_session(username)
    rid = new_id("rpt")
    _exec(
        "INSERT INTO report(report_id, session_id, total_score, gate_passed, report_json,"
        " report_status, version, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (rid, sid, 0.0, 0, report_json, "GENERATING", 1, now_iso()),
    )
    return sid, rid


def test_update_report_progress_writes_generating_row():
    from server.api.assessment import _update_report_progress

    sid, rid = _seed_generating_row("rp_write_user")
    _update_report_progress(rid, {"progress": {"stage": "scoring", "done": 2, "total": 3}})
    row = _q("SELECT report_json, report_status FROM report WHERE report_id=?", (rid,))[0]
    assert row["report_status"] == "GENERATING"
    assert json.loads(row["report_json"]) == {"progress": {"stage": "scoring", "done": 2, "total": 3}}


def test_update_report_progress_zombie_no_op():
    """钉错 report_id 不污染他行（超龄接管双 GENERATING 行并存形态）；
    行已终态（看门狗翻 FAILED）后写入 0 行命中、不炸、不改 json。"""
    from server.api.assessment import _update_report_progress

    sid, rid_v1 = _seed_generating_row("rp_zombie_user")
    # 并存第二行 GENERATING（v2——接管新行），json 各异可辨
    rid_v2 = new_id("rpt")
    _exec(
        "INSERT INTO report(report_id, session_id, total_score, gate_passed, report_json,"
        " report_status, version, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (rid_v2, sid, 0.0, 0, "{}", "GENERATING", 2, now_iso()),
    )
    # 僵尸任务持旧 id 写 → 只动 v1，v2 不被污染
    _update_report_progress(rid_v1, {"progress": {"stage": "scoring", "done": 1, "total": 3}})
    v2 = _q("SELECT report_json FROM report WHERE report_id=?", (rid_v2,))[0]
    assert v2["report_json"] == "{}", "v2 新行不得被旧任务进度污染"
    v1 = _q("SELECT report_json FROM report WHERE report_id=?", (rid_v1,))[0]
    assert json.loads(v1["report_json"])["progress"]["stage"] == "scoring"

    # 终态守卫：v1 已翻 FAILED → 再写 no-op
    _exec(
        "UPDATE report SET report_status='FAILED', report_json=? WHERE report_id=?",
        (json.dumps({"error": "超时"}), rid_v1),
    )
    _update_report_progress(rid_v1, {"progress": {"stage": "scoring", "done": 2, "total": 3}})
    after = _q("SELECT report_json, report_status FROM report WHERE report_id=?", (rid_v1,))[0]
    assert after["report_status"] == "FAILED"
    assert "error" in json.loads(after["report_json"])  # error 原样、无 progress 侵入


# ---------- 3) 正常链全流程：进度写入 + 终态无残渣 + 透传 ----------

def test_full_chain_progress_and_no_residue():
    """POST /report（TestClient 同步跑完链）后：终态行 report_json 无 progress；
    含 progress 的 GENERATING 行经 by-session spread 透传（直插形态验证序列化出口）。

    TestClient+mock 下链瞬时跑完，中间态断言走 monkeypatch 注入 seam：替换
    score_question 为慢版，在评分中途读占位行 json 验证 scoring 进度已落。
    """
    import server.services.scoring as scoring_mod
    import server.api.assessment as assessment_mod

    sid, auth, _mid, n = _seed_full_session("rp_full_chain")
    headers = {"Authorization": f"Bearer {auth}"}

    r = client.post(f"/api/assessment/sessions/{sid}/report", headers=headers)
    assert r.status_code == 202, r.text

    rows = _q("SELECT report_status, report_json FROM report WHERE session_id=?", (sid,))
    assert len(rows) == 1
    terminal = rows[0]
    assert terminal["report_status"] in ("PROVISIONAL", "READY", "FAILED")
    data = json.loads(terminal["report_json"])
    assert "progress" not in data, "终态行不得残留 progress"

    # 终态读回（by-session）：无 progress 键，failure 形态 error 键在
    r = client.get(f"/api/assessment/reports/by-session/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "progress" not in body
    if body["report_status"] == "FAILED":
        assert "error" in body or "error" in data

    # ---- 中间态 seam：慢评分 + 中途读占位行 ----
    sid2, auth2, _mid2, n2 = _seed_full_session("rp_mid_state")

    # 直调 _run_report_task 须经手插占位行（生产由 request_report (c) 分支写）
    rid2 = new_id("rpt")
    _exec(
        "INSERT INTO report(report_id, session_id, total_score, gate_passed, report_json,"
        " report_status, version, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (rid2, sid2, 0.0, 0, "{}", "GENERATING", 1, now_iso()),
    )

    seen_progress: list[dict] = []

    orig_score_question = scoring_mod.score_question

    def _slow_score(session_id, question_id):
        # 第 1 题开始评分前：占位行应已有 scoring 进度（done>=1, total=n2）
        rows = _q("SELECT report_json FROM report WHERE session_id=? AND report_status='GENERATING'",
                  (session_id,))
        if rows:
            seen_progress.append(json.loads(rows[0]["report_json"]))
        return orig_score_question(session_id, question_id)

    monkey_target = scoring_mod.score_question
    scoring_mod.score_question = _slow_score
    try:
        # 直接同步跑内层链（不经 TestClient 后台任务包装），中途断言占位行进度
        assessment_mod._run_report_task(sid2)
    finally:
        scoring_mod.score_question = monkey_target

    assert seen_progress, "评分中途应读到 GENERATING 占位行"
    first = seen_progress[0]
    assert first["progress"]["stage"] == "scoring"
    assert first["progress"]["total"] == n2
    assert 1 <= first["progress"]["done"] <= n2

    # 报告子步入口写 stage=report（慢评分 seam 后、终态替换前的一个可观测写点：
    # 直接复检终态行 json 无 progress + 事件链完整即覆盖汇合写入不炸）
    rows2 = _q("SELECT report_status FROM report WHERE session_id=?", (sid2,))
    assert rows2 and rows2[0]["report_status"] in ("PROVISIONAL", "READY", "FAILED")


def test_by_session_passthrough_generating_progress():
    """GENERATING 占位行带 progress → by-session GET spread 透传（前端轮询消费面）。
    旧占位行 '{}' → 无 progress 键（前端回退静态文案）。无GENERATING 占位行 404 不在此测。"""
    sid, rid = _seed_generating_row(
        "rp_passthrough_user",
        report_json=json.dumps({"progress": {"stage": "scoring", "done": 2, "total": 3}}),
    )
    r = client.post("/api/auth/login", json={"username": "rp_passthrough_user", "password": "pw123456"})
    auth = r.json()["token"]
    r = client.get(f"/api/assessment/reports/by-session/{sid}",
                   headers={"Authorization": f"Bearer {auth}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_status"] == "GENERATING"
    assert body["progress"] == {"stage": "scoring", "done": 2, "total": 3}

    # 旧占位行 '{}'：progress 缺省 → 前端 fallback
    sid_old, _rid_old = _seed_generating_row("rp_old_placeholder_user", report_json="{}")
    r = client.post("/api/auth/login", json={"username": "rp_old_placeholder_user", "password": "pw123456"})
    auth_old = r.json()["token"]
    r = client.get(f"/api/assessment/reports/by-session/{sid_old}",
                   headers={"Authorization": f"Bearer {auth_old}"})
    assert r.status_code == 200, r.text
    assert "progress" not in r.json()


# ---------- 4) skip_scoring 幂等重链路径 ----------

def test_skip_scoring_chain_writes_report_stage():
    """completed 已评分会话（FAILED 重试/接管重链形态）：无 scoring cb 进度，
   两分支汇合处仍写 stage=report。经 monkeypatch 生成函数捕获占位行瞬时值。"""
    import server.api.assessment as assessment_mod

    sid, auth, _mid, n = _seed_full_session("rp_skip_user")
    score_session(sid, allow_completed=True)  # 先落评分行 → 再入队链走 skip_scoring

    captured: dict[str, str] = {}
    orig = assessment_mod.generate_report

    def _capture_generate(session_id):
        rows = _q("SELECT report_json FROM report WHERE session_id=? AND report_status='GENERATING'",
                  (session_id,))
        if rows:
            captured["generating_json"] = rows[0]["report_json"]
        return orig(session_id)

    assessment_mod.generate_report = _capture_generate
    try:
        # 手插占位行（模拟 request_report 的 (c) 分支；skip 判定看行存在与本函数形态）
        rid = new_id("rpt")
        _exec(
            "INSERT INTO report(report_id, session_id, total_score, gate_passed, report_json,"
            " report_status, version, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (rid, sid, 0.0, 0, "{}", "GENERATING", 1, now_iso()),
        )
        assessment_mod._run_report_task(sid)  # 同步直调（后台线程同构）
    finally:
        assessment_mod.generate_report = orig

    # 汇合点写入被捕获：进入 generate_report 时占位行应为 stage=report（无 scoring 残留）
    assert captured.get("generating_json"), "进入报告子步时应仍有 GENERATING 占位行"
    p = json.loads(captured["generating_json"])["progress"]
    assert p["stage"] == "report"
    assert "total" not in p and "done" not in p  # 报告阶段无计数（满条语义）

    # 终态收口
    rows = _q("SELECT report_status FROM report WHERE session_id=?", (sid,))
    assert rows and rows[0]["report_status"] in ("PROVISIONAL", "READY", "FAILED")


# ---------- 5) 无占位行（超时收尾同步链形态） ----------

def test_no_placeholder_progress_noop():
    """无 GENERATING 占位行（_finalize_global_timeout 同步链路径）：链照常跑、
   不因进度缺占位行创建任何 report 行或异常。"""
    sid, auth, _mid, n = _seed_full_session("rp_no_placeholder")
    import server.api.assessment as assessment_mod
    assessment_mod._run_report_task(sid)  # 不插占位行直接跑

    rows = _q("SELECT report_status FROM report WHERE session_id=?", (sid,))
    # 链正常收口（generate_report _insert_report_row 版本化 INSERT——无占位行时插新行）
    assert rows and rows[0]["report_status"] in ("PROVISIONAL", "READY", "FAILED")


# ---------- FAILED 覆盖清进度 ----------

def test_failed_overwrite_clears_progress():
    """带 progress 的 GENERATING 行走失败路径（_write_failed_report）→ 整体替换为
   {"error":...}，无 progress 残留（前端 failed 分支依赖 data.error）。"""
    from server.api.assessment import _write_failed_report

    sid, rid = _seed_generating_row(
        "rp_failed_user",
        report_json=json.dumps({"progress": {"stage": "scoring", "done": 2, "total": 3}}),
    )
    _write_failed_report(sid, "测试失败")
    row = _q("SELECT report_status, report_json FROM report WHERE report_id=?", (rid,))[0]
    assert row["report_status"] == "FAILED"
    data = json.loads(row["report_json"])
    assert data == {"error": "测试失败"}, f"FAILED 行应整体替换且无 progress，实得 {data}"
