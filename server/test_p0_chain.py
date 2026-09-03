"""P0 主链串行 + completed 护栏 + 开考可测量性检查测试（REF-5.10/REF-8.2/REF-3.5/REF-8.5）。

零步断裂修复的直接证明：候选人在 API 完成整场答题后仅调 POST /report（不调 /score），
question_score 应已落库且报告雷达/逐题评分非空（断言不经 Python 直调 score_session 掩盖）。

护栏（B-1 三分支 + 服务层）：
- completed 会话再调 POST /score → 409（服务层护栏，与 report 行无关）
- in_progress 会话调 POST /report → 409（非法前置）
- completed 且已有 report 行再调 POST /report → 409（不重复触发评分/报告）
- completed 且尚无 report 行再调 POST /report → 202（串行链正常入口 + 失败后重试）

串行链事件：TASK_QUEUED / TASK_STARTED / SESSION_ENTERED_SCORING / TASK_SUCCEEDED（评分子步 +
报告子步至少各一）。

开考可测量性检查（§10.4，REF-3.5/REF-8.5）：
- 题库生成中（task QUEUED/RUNNING）→ 409 QUESTION_BANK_GENERATING，绝不建会话
- 题库不完整（task SUCCEEDED/FAILED 但配额/required 覆盖不足）→ 409 QUESTION_BANK_INCOMPLETE
- 模型不可测量（items 空或全部 gate / 岗位非 active）→ 409 MODEL_NOT_MEASURABLE
- 存量种子（无 task 行 + 题库足量）→ 201 不误伤（Pitfall 3 兼容）
- GET /api/admin/todos 含 question_bank_not_ready 键（D-13）

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db；单文件单进程。
运行：cd server && python -m pytest test_p0_chain.py -v
"""
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_p0_chain.db")
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


# ---------- fixtures（m5 种子模式复制，不 import test_m5 模块——单文件单进程纪律） ----------

def _seed_position_with_confirmed_model() -> tuple[str, str]:
    """建 active 岗位 + confirmed 模型 + competency_item（hard/soft/experience 各若干）。"""
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
    """岗位题 + 通用题：hard 7 / soft 3 / experience 2（含 py/mysql 难度链）。"""
    conn = get_conn()
    now = now_iso()

    def _add(scope, position_id, std_name, category, difficulty, qtype, stem, answer_key, rubric,
             chain_key=None, chain_seq=None):
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
            " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq, source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("qb"), scope, position_id, std_name, category, difficulty, qtype, stem,
             answer_key, rubric, chain_key, chain_seq, "human", "active", now),
        )

    # hard_skill：Python easy→medium→hard 整链 + MySQL easy→medium 链 + Redis/Docker 单题
    _add("position", pid, "Python", "hard_skill", "easy", "objective",
         "Python 中用什么关键字定义函数？", "def", None, "py-chain", 1)
    _add("position", pid, "Python", "hard_skill", "medium", "subjective",
         "讲一个你用 Python 解决过的性能问题。", None, "有具体场景/有数据/有方法", "py-chain", 2)
    _add("position", pid, "Python", "hard_skill", "hard", "subjective",
         "如何设计一个高并发 Python 服务？", None, "并发模型/限流/缓存", "py-chain", 3)
    _add("position", pid, "MySQL", "hard_skill", "easy", "objective",
         "MySQL 默认事务隔离级别是？", "REPEATABLE", None, "mysql-chain", 1)
    _add("position", pid, "MySQL", "hard_skill", "medium", "subjective",
         "讲一次慢查询优化经历。", None, "explain/索引/效果", "mysql-chain", 2)
    _add("position", pid, "Redis", "hard_skill", "easy", "objective",
         "Redis 常用字符串命令？", "GET", None)
    _add("position", pid, "Docker", "hard_skill", "easy", "objective",
         "构建镜像的命令是？", "docker build", None)

    _add("position", pid, "沟通能力", "soft_skill", "easy", "subjective",
         "讲一次跨团队沟通的经历。", None, "背景/冲突/结果")
    _add("position", pid, "沟通能力", "soft_skill", "medium", "subjective",
         "遇到意见分歧怎么处理？", None, "倾听/数据/共识")

    _add("general", None, "后端开发经验", "experience", None, "subjective",
         "介绍你最近一个后端项目。", None, "角色/规模/成果")
    _add("general", None, "后端开发经验", "experience", None, "subjective",
         "最有挑战的项目？", None, "挑战/解决")
    conn.commit()
    conn.close()


def _auth_headers(username: str = "p0_chain_candidate") -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ---------- 答题闭环（长答案 > 20 字符，不触发 followup） ----------

_LONG_ANSWER = (
    "我熟练使用 Python 完成后端开发，熟悉常见的数据结构与算法，"
    "并且在多个项目中处理过性能问题、并发问题与数据库优化，有可量化结果。"
)


def _answer_whole_session(sid: str, headers: dict) -> list[dict]:
    """把一场会话全部题答完（长回答触发 next/finish），返回题目列表。"""
    questions = _q(
        "SELECT question_id FROM assessment_question WHERE session_id=? ORDER BY seq", (sid,),
    )
    assert questions, "会话应有题目"
    for i, q in enumerate(questions, start=1):
        r = client.post(
            f"/api/assessment/sessions/{sid}/answer",
            json={"question_id": q["question_id"], "answer": _LONG_ANSWER},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        expected = "finish" if i == len(questions) else "next"
        assert r.json()["action"] == expected, f"第{i}题应 {expected}，实得 {r.json()['action']}"
    sess = _q("SELECT status FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "completed"
    return questions


def _seed_completed_session_direct(username: str) -> str:
    """直插 completed 会话 + 已答题（不跑 API 答题闭环、不触发生成链）。

    构造"completed 且尚无 report 行"形态（B-1 分支 c：后台链失败后的重试入口）。
    """
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "后端开发工程师", "active", now),
    )
    items = [
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 1.0},
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
    qid = new_id("qb")
    conn.execute(
        "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
        " difficulty, qtype, stem, answer_key, rubric, source, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (qid, "position", pid, "Python", "hard_skill", "easy", "objective",
         "Python 中用什么关键字定义函数？", "def", None, "human", "active", now),
    )
    uid = conn.execute(
        "SELECT user_id FROM user WHERE username=?", (username,)
    ).fetchone()["user_id"]
    sid = new_id("sess")
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, ended_at, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (sid, uid, pid, mid, 1, "completed", now, now, now),
    )
    aqid = new_id("aq")
    conn.execute(
        "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq,"
        " asked_at, answered_at, created_at) VALUES(?,?,?,?,?,?,?)",
        (aqid, sid, qid, 1, now, now, now),
    )
    conn.execute(
        "INSERT INTO assessment_message(message_id, session_id, question_id, role, content, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (new_id("msg"), sid, aqid, "user", "我用 def 关键字定义函数，也常用 lambda 与嵌套函数。", now),
    )
    conn.commit()
    conn.close()
    return sid


# ---------- 开考检查种子（01-04，question_bank_task 三态） ----------

def _insert_qb_task(pid: str, mid: str, model_version: int, task_status: str) -> None:
    """直插 question_bank_task 行（01-04 新表；status 代码校验枚举）。"""
    conn = get_conn()
    conn.execute(
        "INSERT INTO question_bank_task(task_id, position_id, model_id, model_version,"
        " status, created_at) VALUES(?,?,?,?,?,?)",
        (new_id("qbt"), pid, mid, model_version, task_status, now_iso()),
    )
    conn.commit()
    conn.close()


def _assert_session_not_created(pid: str) -> None:
    """失败态绝不创建会话（成功标准 3：杜绝 0 题会话静默开考）。"""
    c = _q("SELECT COUNT(*) c FROM assessment_session WHERE position_id=?", (pid,))[0]["c"]
    assert c == 0, f"该岗位不应创建会话，实得 {c} 行"


def _seed_empty_items_confirmed_model() -> str:
    """active 岗位 + confirmed 模型 items=[]（REF-8.5 不可测量形态其一）。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "空模型岗位", "active", now),
    )
    model_json = {"position_id": pid, "version": 1, "items": []}
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, 1, "confirmed", json.dumps(model_json, ensure_ascii=False), now),
    )
    conn.commit()
    conn.close()
    return pid


def _seed_inactive_position_with_full_setup() -> str:
    """pending_review 岗位 + confirmed 模型 + 足量题库（W-2 inactive 分支，直插合法）。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    conn = get_conn()
    conn.execute("UPDATE position SET status='pending_review' WHERE position_id=?", (pid,))
    conn.commit()
    conn.close()
    return pid


def _ensure_admin() -> None:
    """测试库首跑造 admin（m7 模式，bcrypt 直插）。"""
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


def _admin_headers() -> dict:
    """admin 登录取 headers（todos 断言用）。"""
    _ensure_admin()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ---------- 测试 ----------

def test_ui_main_chain_score_report_serial():
    """候选人完成整场答题后不调 POST /score，直接 POST /report → 202 且评分/报告非空。

    零步断裂（前端从不调 /score 导致报告恒 no_data）修复的直接证明——
    断言不经 Python 直调 score_session 掩盖。
    """
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p0_chain_main")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]

    _answer_whole_session(sid, headers)

    # 不调 POST /score，直接 POST /report —— TestClient 下 background task 同步执行完毕
    r = client.post(f"/api/assessment/sessions/{sid}/report", headers=headers)
    assert r.status_code == 202, r.text

    # 评分已落库（服务端串行链完成，非候选人显式触发）
    scored = _q("SELECT COUNT(*) c FROM question_score WHERE session_id=?", (sid,))[0]["c"]
    assert scored > 0, f"question_score 应 > 0（零步断裂未修复），实得 {scored}"

    # 报告雷达非空 + 非 gate 项无 no_data
    r = client.get(f"/api/assessment/reports/by-session/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    rpt = r.json()
    assert len(rpt["radar_data"]["indicators"]) > 0, "radar_data.indicators 应非空"
    non_gate = [it for it in rpt["item_details"] if not it.get("gate")]
    assert len(non_gate) > 0, "种子模型应含非 gate 项"
    assert all(not it.get("no_data") for it in non_gate), \
        f"非 gate 项不应 no_data：{[it['std_name'] for it in non_gate if it.get('no_data')]}"


def test_completed_session_guardrail():
    """同一场已有 report 行后：completed 再调 POST /score → 409；再调 POST /report → 409。

    报告行数仍为 1——重复评分/报告被拒（不重复触发串行链）。
    """
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p0_chain_guard")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]

    _answer_whole_session(sid, headers)

    # 先正常生成报告（completed 且尚无 report 行 → 分支 c，202）
    r = client.post(f"/api/assessment/sessions/{sid}/report", headers=headers)
    assert r.status_code == 202, r.text
    n_report = _q("SELECT COUNT(*) c FROM report WHERE session_id=?", (sid,))[0]["c"]
    assert n_report == 1

    # completed 再调 POST /score → 409（服务层护栏，与 report 行无关）
    r = client.post(f"/api/assessment/sessions/{sid}/score", headers=headers)
    assert r.status_code == 409, f"completed 会话评分应 409，实得 {r.status_code}"

    # completed 且已有 report 行再调 POST /report → 409（成功标准 5"再调"，拒绝重复触发）
    r = client.post(f"/api/assessment/sessions/{sid}/report", headers=headers)
    assert r.status_code == 409, f"已生成报告再请求应 409，实得 {r.status_code}"
    n_after = _q("SELECT COUNT(*) c FROM report WHERE session_id=?", (sid,))[0]["c"]
    assert n_after == 1, "报告行数应仍为 1（重复触发被拒，不重复评分/报告）"


def test_in_progress_report_rejected():
    """in_progress 会话（答题中途）POST /report → 409（非法前置：报告必须在完成后请求）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p0_chain_inprog")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]

    # 只答 1 题，不 finish
    q = _q("SELECT question_id FROM assessment_question WHERE session_id=? ORDER BY seq", (sid,))[0]
    r = client.post(
        f"/api/assessment/sessions/{sid}/answer",
        json={"question_id": q["question_id"], "answer": _LONG_ANSWER},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "next"
    sess = _q("SELECT status FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "in_progress"

    r = client.post(f"/api/assessment/sessions/{sid}/report", headers=headers)
    assert r.status_code == 409, f"in_progress 会话请求报告应 409，实得 {r.status_code}"


def test_completed_without_report_retriggers():
    """completed 且尚无 report 行（直插种子，不跑生成链）POST /report → 202 且 question_score > 0。

    B-1 分支 c：D-08 串行链正常入口，亦是后台链失败后的重试路径。
    """
    headers = _auth_headers("p0_chain_retry")
    sid = _seed_completed_session_direct("p0_chain_retry")

    assert _q("SELECT COUNT(*) c FROM report WHERE session_id=?", (sid,))[0]["c"] == 0

    r = client.post(f"/api/assessment/sessions/{sid}/report", headers=headers)
    assert r.status_code == 202, r.text

    scored = _q("SELECT COUNT(*) c FROM question_score WHERE session_id=?", (sid,))[0]["c"]
    assert scored > 0, f"重入串行链应完成评分，实得 question_score={scored}"


def test_serial_chain_events():
    """主链完成后事件表含 TASK_QUEUED / TASK_STARTED / SESSION_ENTERED_SCORING /
    TASK_SUCCEEDED（评分子步 + 报告子步至少各一）；同 session sequence_no 无重复。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p0_chain_events")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]

    _answer_whole_session(sid, headers)

    r = client.post(f"/api/assessment/sessions/{sid}/report", headers=headers)
    assert r.status_code == 202, r.text

    events = _q(
        "SELECT event_type, from_state, to_state, actor_type, payload_json, sequence_no"
        " FROM assessment_state_event WHERE session_id=? ORDER BY sequence_no",
        (sid,),
    )
    assert events, "主链完成后应有事件行"
    types = [e["event_type"] for e in events]

    assert "TASK_QUEUED" in types, "应含 TASK_QUEUED"
    assert "TASK_STARTED" in types, "应含 TASK_STARTED"
    assert "SESSION_ENTERED_SCORING" in types, "应含 SESSION_ENTERED_SCORING"

    # SESSION_ENTERED_SCORING 为事实类事件（D-10 无 SCORING 快照态）：from/to 均 in_progress
    scoring = [e for e in events if e["event_type"] == "SESSION_ENTERED_SCORING"]
    assert all(
        e["from_state"] == "in_progress" and e["to_state"] == "in_progress" for e in scoring
    ), f"SESSION_ENTERED_SCORING from/to 应为 in_progress，实得 {scoring}"

    succeeded_steps = [
        json.loads(e["payload_json"]).get("step")
        for e in events
        if e["event_type"] == "TASK_SUCCEEDED" and e["payload_json"]
    ]
    assert "score" in succeeded_steps, "TASK_SUCCEEDED 应含评分子步（step=score）"
    assert "report" in succeeded_steps, "TASK_SUCCEEDED 应含报告子步（step=report）"

    seqs = [e["sequence_no"] for e in events]
    assert len(set(seqs)) == len(seqs), f"sequence_no 不得重复，实得 {seqs}"
    assert seqs == sorted(seqs), "sequence_no 应递增"


# ---------- 开考可测量性检查三态（01-04，REF-3.5/REF-8.5） ----------

def test_question_bank_generating_blocks_session():
    """题库生成中（task 行 QUEUED）→ 409 QUESTION_BANK_GENERATING，绝不建会话。

    即使题库当前已足量（生成中状态优先于实际题量判定——判定逻辑 D-12）。
    """
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    _insert_qb_task(pid, mid, 1, "QUEUED")
    headers = _auth_headers("p0_chain_gen")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 409, f"生成中岗位开考应 409，实得 {r.status_code}: {r.text}"
    assert r.json()["detail"]["error_code"] == "QUESTION_BANK_GENERATING", r.text
    _assert_session_not_created(pid)


def test_question_bank_incomplete_blocks_session():
    """题库不完整（task SUCCEEDED 但题库仅 1 题，配额不满）→ 409 QUESTION_BANK_INCOMPLETE。"""
    pid, mid = _seed_position_with_confirmed_model()
    # 仅插 1 题（远低于 CATEGORY_QUOTA hard 6 / soft 2 / experience 2）
    conn = get_conn()
    conn.execute(
        "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
        " difficulty, qtype, stem, answer_key, rubric, source, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("qb"), "position", pid, "Python", "hard_skill", "easy", "objective",
         "Python 中用什么关键字定义函数？", "def", None, "human", "active", now_iso()),
    )
    conn.commit()
    conn.close()
    _insert_qb_task(pid, mid, 1, "SUCCEEDED")
    headers = _auth_headers("p0_chain_inc")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 409, f"题库不足配额开考应 409，实得 {r.status_code}: {r.text}"
    assert r.json()["detail"]["error_code"] == "QUESTION_BANK_INCOMPLETE", r.text
    _assert_session_not_created(pid)


def test_model_not_measurable_blocks_session():
    """confirmed 模型 items 为空 → 409 MODEL_NOT_MEASURABLE（REF-8.5），不建会话。"""
    pid = _seed_empty_items_confirmed_model()
    headers = _auth_headers("p0_chain_mnm")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 409, f"空模型开考应 409，实得 {r.status_code}: {r.text}"
    assert r.json()["detail"]["error_code"] == "MODEL_NOT_MEASURABLE", r.text
    _assert_session_not_created(pid)


def test_inactive_position_blocks_session():
    """非 active 岗位（pending_review）+ confirmed 模型 + 足量题库 → 409 MODEL_NOT_MEASURABLE。

    W-2：status != 'active' 复用 MODEL_NOT_MEASURABLE 作为"岗位不可开测"语义载体。
    """
    pid = _seed_inactive_position_with_full_setup()
    headers = _auth_headers("p0_chain_inactive")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 409, f"未上架岗位开考应 409，实得 {r.status_code}: {r.text}"
    assert r.json()["detail"]["error_code"] == "MODEL_NOT_MEASURABLE", r.text
    _assert_session_not_created(pid)


def test_legacy_seed_without_task_row_passes():
    """存量种子形态（无 task 行 + 题库足量，m5 直插模式）→ 201 不误伤（Pitfall 3 兼容）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p0_chain_legacy")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, f"存量足量种子应 201 放行，实得 {r.status_code}: {r.text}"
    c = _q("SELECT COUNT(*) c FROM assessment_session WHERE position_id=?", (pid,))[0]["c"]
    assert c == 1, f"放行后应恰好创建 1 个会话，实得 {c}"


def test_admin_todos_includes_question_bank_not_ready():
    """存在非 SUCCEEDED task 行的岗位时 GET /api/admin/todos 含 question_bank_not_ready 且 >= 1（D-13）。"""
    pid, mid = _seed_position_with_confirmed_model()
    _insert_qb_task(pid, mid, 1, "RUNNING")

    r = client.get("/api/admin/todos", headers=_admin_headers())
    assert r.status_code == 200, r.text
    todos = r.json()
    assert "question_bank_not_ready" in todos, f"todos 应含 question_bank_not_ready 键，实得 {todos}"
    assert todos["question_bank_not_ready"] >= 1, \
        f"存在 RUNNING task 行，question_bank_not_ready 应 >= 1，实得 {todos['question_bank_not_ready']}"
