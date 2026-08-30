"""M5 测评核心后端测试：会话创建/选题、答题（精炼+决策）、打分（客观+主观）。

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db。
运行：cd server && python -m pytest test_m5_backend.py -v
"""
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_m5.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.refine import refine_user_input  # noqa: E402
from server.services.scoring import _score_objective  # noqa: E402
from server import config  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ---------- fixtures ----------

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


def _seed_question_bank(pid: str) -> dict[str, list[str]]:
    """岗位题 + 通用题：hard 7 / soft 3 / experience 2 / qualification 1（通用，走表单）。"""
    conn = get_conn()
    now = now_iso()
    ids: dict[str, list[str]] = {"hard_skill": [], "soft_skill": [], "experience": [], "qualification": []}

    def _add(scope, position_id, std_name, category, difficulty, qtype, stem, answer_key, rubric,
             chain_key=None, chain_seq=None):
        qid = new_id("qb")
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
            " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq, source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (qid, scope, position_id, std_name, category, difficulty, qtype, stem,
             answer_key, rubric, chain_key, chain_seq, "human", "active", now),
        )
        ids[category].append(qid)
        return qid

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
    _add("position", pid, "团队协作", "soft_skill", "easy", "subjective",
         "你如何带新人？", None, "方法/耐心")

    _add("general", None, "后端开发经验", "experience", None, "subjective",
         "介绍你最近一个后端项目。", None, "角色/规模/成果")
    _add("general", None, "项目经验", "experience", None, "subjective",
         "最有挑战的项目？", None, "挑战/解决")

    _add("general", None, "学历", "qualification", None, "subjective",
         "最高学历？", None, "本科及以上")
    conn.commit()
    conn.close()
    return ids


def _auth_headers(username: str = "m5_candidate") -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ---------- 测试 ----------

def test_session_creation_and_question_selection():
    """建会话：锚定 confirmed 模型，选题满足配额与排序规则。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers()

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["question_count"] == 10  # hard6 + soft2 + exp2 = 10，qualification 走表单
    assert body["estimated_duration_minutes"] == 20

    sid = body["session_id"]
    sess = _q("SELECT * FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "in_progress"
    assert sess["model_version"] == 1

    # 题序：类目内 required 优先、难度递进
    qs = _q(
        "SELECT aq.seq, b.category, b.difficulty, b.std_name FROM assessment_question aq"
        " JOIN question_bank b ON b.question_id=aq.bank_question_id WHERE aq.session_id=?"
        " ORDER BY aq.seq", (sid,),
    )
    cats = {}
    for q in qs:
        cats.setdefault(q["category"], []).append(q)
    assert len(cats["hard_skill"]) == 6
    assert len(cats["soft_skill"]) == 2
    assert len(cats["experience"]) == 2
    # Python（required, weight 高）应排在 MySQL 之前
    hard_names = [q["std_name"] for q in cats["hard_skill"]]
    assert hard_names.index("Python") < hard_names.index("MySQL")


def test_session_state():
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("m5_state_user")
    sid = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers).json()["session_id"]

    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "in_progress"
    assert body["answered_count"] == 0
    assert body["total_count"] == 10
    assert body["current_question"]["seq"] == 1


def test_refine_threshold():
    """短输入不精炼；长输入精炼且原文归档 context_raw。"""
    short = "我会 Python。"
    refined, h = refine_user_input(short)
    assert refined == short and h is None

    long_text = "我做过很多项目。" * 200  # 2600 字 > 500*2
    refined, h = refine_user_input(long_text)
    assert h is not None
    assert len(refined) <= 200
    row = _q("SELECT full_text FROM context_raw WHERE hash=?", (h,))[0]
    assert row["full_text"] == long_text


def test_objective_scoring():
    score, _ = _score_objective("def", "用 def 定义函数")
    assert score == 5
    score, _ = _score_objective("REPEATABLE", "默认是读已提交")
    assert score == 1
    # 非法正则退化为子串
    score, _ = _score_objective("docker build", "使用 docker build 构建")
    assert score == 5


def test_answer_flow_and_scoring():
    """答题闭环：followup→next→…→finish；终局打分落 question_score；合成 50/50。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("m5_flow_user")
    sid = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers).json()["session_id"]

    questions = _q(
        "SELECT aq.question_id, b.qtype FROM assessment_question aq"
        " JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE aq.session_id=? ORDER BY aq.seq", (sid,),
    )

    # 第一题：短回答触发 followup，再长回答 next
    q1 = questions[0]["question_id"]
    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": q1, "answer": "不知道"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "followup"

    long_answer = "我熟练使用 def 定义函数，也了解装饰器、生成器、上下文管理器等进阶用法，做过性能优化。"
    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": q1, "answer": long_answer}, headers=headers)
    assert r.json()["action"] == "next"
    assert r.json()["next_question_id"] == questions[1]["question_id"]

    # 剩余题全部长回答，最后一题应 finish
    for i, q in enumerate(questions[1:], start=2):
        r = client.post(f"/api/assessment/sessions/{sid}/answer",
                        json={"question_id": q["question_id"], "answer": long_answer * 2},
                        headers=headers)
        assert r.status_code == 200, r.text
        expected = "finish" if i == len(questions) else "next"
        assert r.json()["action"] == expected, f"第{i}题应 {expected}，实得 {r.json()}"

    sess = _q("SELECT status FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "completed"

    # 重复作答已答题 → 409
    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": q1, "answer": long_answer}, headers=headers)
    assert r.status_code == 409

    # 终局打分
    r = client.post(f"/api/assessment/sessions/{sid}/score", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scored_count"] == len(questions)
    assert body["total_questions"] == len(questions)

    # question_score 落库：Python 客观题命中 def → 5 分；主观题 mock score_final=3
    rows = _q(
        "SELECT qs.*, b.qtype FROM question_score qs"
        " JOIN assessment_question aq ON aq.question_id=qs.question_id"
        " JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE qs.session_id=?", (sid,),
    )
    # 无对应 competency_item 的题（题库 std_name 不在本模型内）跳过不入分表——期望值按模型项集合算
    item_names = {r["std_name"] for r in _q(
        "SELECT std_name FROM competency_item WHERE model_id=?", (mid,))}
    expected_scored = _q(
        "SELECT COUNT(*) c FROM assessment_question aq"
        " JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE aq.session_id=? AND aq.answered_at IS NOT NULL"
        f" AND b.std_name IN ({','.join('?' * len(item_names))})",
        (sid, *item_names),
    )[0]["c"]
    assert len(rows) == expected_scored
    assert len(rows) >= 7  # 本测试种子下 Python链3+MySQL链2+沟通1+后端经验1 可匹配
    obj = [r for r in rows if r["qtype"] == "objective"]
    subj = [r for r in rows if r["qtype"] == "subjective"]
    assert all(r["score_live"] is None for r in obj)
    assert any(r["score_final"] == 5 for r in obj)  # 至少 def 命中
    # 主观题：score_live=3(mock) 与 score_final=3(mock) 合成 3
    assert all(r["score_live"] == 3 and r["final_score"] == 3 for r in subj)


def test_form_submission():
    pid, _ = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("m5_form_user")
    sid = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers).json()["session_id"]

    r = client.post(f"/api/assessment/sessions/{sid}/forms/submit",
                    json={"form_type": "resume", "payload": {"name": "张三", "years": 5}},
                    headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "submitted"
    row = _q("SELECT payload_json FROM form_submission WHERE form_id=?",
             (r.json()["form_id"],))[0]
    assert json.loads(row["payload_json"])["name"] == "张三"


def test_config_refine_min_tokens():
    assert config.REFINE_MIN_TOKENS == 500
