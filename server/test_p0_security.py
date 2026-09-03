"""P0 越权测试矩阵（REF-1.1/REF-1.2）：候选人资源级所有权校验（IDOR 修复的证明测试）。

覆盖：candidate B 访问 candidate A 的 session/report/feedback 全部读写路由 → 404；
admin 读豁免（200）/写拒绝（404）；admin 自有资源 200（owner 判定优先）；owner 主链不回归。

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db。单文件单进程。
运行：cd server && python -m pytest test_p0_security.py -v
"""
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_p0.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ---------- fixtures（m5 种子模式） ----------

def _seed_position_with_confirmed_model() -> tuple[str, str]:
    """建 active 岗位 + confirmed 模型 + competency_item。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "后端开发工程师", "active", now),
    )
    items = [
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.3},
        {"std_name": "MySQL", "category": "hard_skill", "importance": "required", "weight": 0.25},
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "preferred", "weight": 0.2},
        {"std_name": "后端开发经验", "category": "experience", "importance": "required", "weight": 0.25},
    ]
    model_json = {"position_id": pid, "version": 1, "items": items}
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, 1, "confirmed", json.dumps(model_json, ensure_ascii=False), now),
    )
    for it in items:
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("c"), mid, it["std_name"], it["category"], 3, it["importance"], it["weight"], 0),
        )
    conn.commit()
    conn.close()
    return pid, mid


def _seed_question_bank(pid: str) -> None:
    """岗位题：hard 6 / soft 2 / experience 2（配 10 题会话）。"""
    conn = get_conn()
    now = now_iso()

    def _add(scope, position_id, std_name, category, difficulty, qtype, stem, answer_key, rubric):
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
            " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq, source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("qb"), scope, position_id, std_name, category, difficulty, qtype, stem,
             answer_key, rubric, None, None, "human", "active", now),
        )

    _add("position", pid, "Python", "hard_skill", "easy", "objective",
         "Python 中用什么关键字定义函数？", "def", None)
    _add("position", pid, "Python", "hard_skill", "medium", "subjective",
         "讲一个你用 Python 解决过的性能问题。", None, "有具体场景/有数据/有方法")
    _add("position", pid, "Python", "hard_skill", "hard", "subjective",
         "如何设计一个高并发 Python 服务？", None, "并发模型/限流/缓存")
    _add("position", pid, "MySQL", "hard_skill", "easy", "objective",
         "MySQL 默认事务隔离级别是？", "REPEATABLE", None)
    _add("position", pid, "MySQL", "hard_skill", "medium", "subjective",
         "讲一次慢查询优化经历。", None, "explain/索引/效果")
    _add("position", pid, "Redis", "hard_skill", "easy", "objective",
         "Redis 常用字符串命令？", "GET", None)
    _add("position", pid, "沟通能力", "soft_skill", "easy", "subjective",
         "讲一次跨团队沟通的经历。", None, "背景/冲突/结果")
    _add("position", pid, "沟通能力", "soft_skill", "medium", "subjective",
         "遇到意见分歧怎么处理？", None, "倾听/数据/共识")
    _add("general", None, "后端开发经验", "experience", None, "subjective",
         "介绍你最近一个后端项目。", None, "角色/规模/成果")
    _add("general", None, "后端开发经验", "experience", None, "subjective",
         "最有挑战的项目？", None, "挑战/结果")
    conn.commit()
    conn.close()


def _auth_headers(username: str = "p0_candidate") -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _ensure_admin() -> None:
    """测试库首跑造 admin（m7 模式：CryptContext bcrypt 直插 user 行，幂等）。"""
    conn = get_conn()
    row = conn.execute("SELECT user_id FROM user WHERE username='p0_admin'").fetchone()
    if row is None:
        from passlib.context import CryptContext

        pwd_ctx = CryptContext(schemes=["bcrypt"])
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (new_id("u"), "p0_admin", pwd_ctx.hash("admin123456"), "admin", now_iso()),
        )
        conn.commit()
    conn.close()


_ensure_admin()


def _admin_headers() -> dict:
    r = client.post("/api/auth/login", json={"username": "p0_admin", "password": "admin123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ---------- 种子链 ----------

_LONG_ANSWER = (
    "我熟练使用 Python 完成后端开发，熟悉常见的数据结构与算法，"
    "并且在多个项目中处理过性能问题、并发问题与数据库优化，有可量化结果。"
)


def _answer_whole_session(sid: str, headers: dict) -> None:
    """把一场会话全部题答完（长回答触发 next/finish），不出现任何 score 直调。"""
    while True:
        r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
        assert r.status_code == 200, r.text
        cur = r.json()["current_question"]
        if cur is None:
            break
        r = client.post(
            f"/api/assessment/sessions/{sid}/answer",
            json={"question_id": cur["question_id"], "answer": _LONG_ANSWER},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        if r.json()["action"] == "finish":
            break


def _seed_a_full_chain() -> tuple[str, str, dict]:
    """产出 A 的完整链：completed 会话 + report 行，返回 (A_sid, A_rid, A_headers)。

    种子链硬约束（01-03 稳定性）：会话先 finish 置 completed 再 POST /report；
    全程不出现 score_session 直调。
    """
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p0_candidate_a")
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]

    _answer_whole_session(sid, headers)
    # completed 再 POST /report（TestClient 下 background task 同步执行，report 行已落库）
    r = client.post(f"/api/assessment/sessions/{sid}/report", headers=headers)
    assert r.status_code == 202, r.text
    rows = _q("SELECT report_id FROM report WHERE session_id=?", (sid,))
    assert rows, "种子链 report 行应已落库（TestClient 同步执行 background task）"
    return sid, rows[0]["report_id"], headers


def _seed_in_progress_session(headers: dict) -> str:
    """建一个只答 1 题、未 finish 的 in_progress 小会话（owner score 断言专用）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    cur = r.json()["current_question"]
    r = client.post(
        f"/api/assessment/sessions/{sid}/answer",
        json={"question_id": cur["question_id"], "answer": _LONG_ANSWER},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "next", "只答 1 题后应仍 in_progress"
    return sid


# ---------- 矩阵 ----------

def test_candidate_cannot_read_others():
    """B 读 A 的 session/report → 404。"""
    a_sid, a_rid, _ = _seed_a_full_chain()
    b_headers = _auth_headers("p0_candidate_b")

    r = client.get(f"/api/assessment/sessions/{a_sid}", headers=b_headers)
    assert r.status_code == 404, f"越权读会话应 404，实得 {r.status_code}"
    r = client.get(f"/api/assessment/reports/by-session/{a_sid}", headers=b_headers)
    assert r.status_code == 404, f"越权读报告(by-session)应 404，实得 {r.status_code}"
    r = client.get(f"/api/assessment/reports/{a_rid}", headers=b_headers)
    assert r.status_code == 404, f"越权读报告应 404，实得 {r.status_code}"


def test_candidate_cannot_write_others():
    """B 写 A 的 session/report → 404（写越权为 404 而非 409）。"""
    a_sid, a_rid, _ = _seed_a_full_chain()
    b_headers = _auth_headers("p0_candidate_b")

    aq = _q(
        "SELECT aq.question_id FROM assessment_question aq WHERE aq.session_id=? ORDER BY aq.seq LIMIT 1",
        (a_sid,),
    )
    r = client.post(
        f"/api/assessment/sessions/{a_sid}/answer",
        json={"question_id": aq[0]["question_id"], "answer": _LONG_ANSWER},
        headers=b_headers,
    )
    assert r.status_code == 404, f"越权答题应 404，实得 {r.status_code}"
    r = client.post(
        f"/api/assessment/sessions/{a_sid}/forms/submit",
        json={"form_type": "resume", "payload": {"name": "B", "years": 1}},
        headers=b_headers,
    )
    assert r.status_code == 404, f"越权表单提交应 404，实得 {r.status_code}"
    r = client.post(f"/api/assessment/sessions/{a_sid}/score", headers=b_headers)
    assert r.status_code == 404, f"越权评分应 404，实得 {r.status_code}"
    r = client.post(f"/api/assessment/sessions/{a_sid}/report", headers=b_headers)
    assert r.status_code == 404, f"越权触发报告应 404，实得 {r.status_code}"
    r = client.post(
        f"/api/assessment/reports/{a_rid}/feedback",
        json={"item_id": "ci_x", "feedback_text": "分数有异议"},
        headers=b_headers,
    )
    assert r.status_code == 404, f"越权反馈应 404，实得 {r.status_code}"


def test_admin_read_exemption_write_denied():
    """admin 读 A 的资源 200（读豁免）；admin 写 A 的资源 404（owner-only，D-03）。"""
    a_sid, a_rid, _ = _seed_a_full_chain()
    admin = _admin_headers()

    r = client.get(f"/api/assessment/sessions/{a_sid}", headers=admin)
    assert r.status_code == 200, f"admin 读会话应 200（读豁免），实得 {r.status_code}"
    r = client.get(f"/api/assessment/reports/by-session/{a_sid}", headers=admin)
    assert r.status_code == 200, f"admin 读报告(by-session)应 200，实得 {r.status_code}"
    r = client.get(f"/api/assessment/reports/{a_rid}", headers=admin)
    assert r.status_code == 200, f"admin 读报告应 200，实得 {r.status_code}"

    aq = _q(
        "SELECT aq.question_id FROM assessment_question aq WHERE aq.session_id=? ORDER BY aq.seq LIMIT 1",
        (a_sid,),
    )
    r = client.post(
        f"/api/assessment/sessions/{a_sid}/answer",
        json={"question_id": aq[0]["question_id"], "answer": _LONG_ANSWER},
        headers=admin,
    )
    assert r.status_code == 404, f"admin 写答题应 404（owner-only），实得 {r.status_code}"
    r = client.post(
        f"/api/assessment/sessions/{a_sid}/forms/submit",
        json={"form_type": "resume", "payload": {"name": "adm", "years": 1}},
        headers=admin,
    )
    assert r.status_code == 404, f"admin 写表单应 404，实得 {r.status_code}"
    r = client.post(f"/api/assessment/sessions/{a_sid}/score", headers=admin)
    assert r.status_code == 404, f"admin 写评分应 404，实得 {r.status_code}"
    r = client.post(f"/api/assessment/sessions/{a_sid}/report", headers=admin)
    assert r.status_code == 404, f"admin 写报告触发应 404，实得 {r.status_code}"
    r = client.post(
        f"/api/assessment/reports/{a_rid}/feedback",
        json={"item_id": "ci_x", "feedback_text": "admin 反馈"},
        headers=admin,
    )
    assert r.status_code == 404, f"admin 写反馈应 404，实得 {r.status_code}"


def test_owner_main_chain_unaffected():
    """owner 主链不回归：A 本人 GET session 200；POST answer 200；in_progress 会话 POST /score 200。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p0_owner_chain")
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]

    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text

    cur = r.json()["current_question"]
    r = client.post(
        f"/api/assessment/sessions/{sid}/answer",
        json={"question_id": cur["question_id"], "answer": _LONG_ANSWER},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # score 断言用 in_progress 会话（未 finish）——01-03 completed 护栏落地后该断言不得翻红
    sid2 = _seed_in_progress_session(headers)
    r = client.post(f"/api/assessment/sessions/{sid2}/score", headers=headers)
    assert r.status_code == 200, f"owner in_progress 会话评分应 200，实得 {r.status_code}"


def test_admin_own_resources():
    """admin 建自己会话 → GET 200（owner 判定恒优先于角色豁免，Pitfall 10）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    admin = _admin_headers()
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=admin)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    r = client.get(f"/api/assessment/sessions/{sid}", headers=admin)
    assert r.status_code == 200, f"admin 访问自己会话应 200，实得 {r.status_code}"


def test_admin_trace_still_works():
    """admin GET /api/admin/trace/by-session/{A_sid} → 200（既有路由回归确认）。"""
    a_sid, _, _ = _seed_a_full_chain()
    admin = _admin_headers()
    r = client.get(f"/api/admin/trace/by-session/{a_sid}", headers=admin)
    assert r.status_code == 200, f"admin trace 应 200，实得 {r.status_code}"
