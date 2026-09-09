"""真源全链 E2E（JD 文本 → 画像发布）。

补 test_e2e_full_chain.py 跳过的前半程：现有 e2e 从直插 confirmed 模型 + 题库
开始，本测试从「粘贴真实 JD 文本」起步，一条测试串起阶段 1–6，是「JD 文本→画像」
的完整证明：

  阶段 1  POST /api/admin/jds/import（粘贴 JD 文本）→ 后台 run_parse_pipeline：
          清洗② → mock LLM#1 抽取 → 归岗（新岗位 pending_review）→ 消歧④ → parsed
  阶段 2  管理员 POST /positions/{pid}/review approve → active
  阶段 3  JD#2/#3 同岗位导入 → parse 尾自动聚合（trigger_source='auto:jd-parse'）：
          occ=3 → hard required / soft preferred，权重 Σ=1；v1、v2 两版 draft
  阶段 4  管理员 POST /models/{mid}/confirm → 后台 generate_question_bank
          （4 hard × 3 档 = 12 + 2 soft × 2 档 = 4 题；experience 走表单不生成题）
  阶段 5  候选人 register → create_session（readiness 预检全过）→ start →
          答完场（SSE 流式 + 表单 submit-v2 收口）→ completed
  阶段 6  request_report 202 → 轮询 by-session 至非 GENERATING 终态 →
          管理员 publish → PUBLISHED + REVIEW_REPORT_PUBLISH_CONFIRMED 事件留痕

报告状态口径：mock 评分下 subjective 恒 3 分、objective 5/1 分，混合题型 item 的
measurements 极差恰为 ADJUDICATE_CONFLICT_THRESHOLD(=2) → 必标 human_review →
PROVISIONAL。故断言与 test_e2e_full_chain 同口径 in ("READY", "PROVISIONAL")；
publish 对两态均合法（HUMAN_REVIEW_REQUIRED 时须传 review_outcome="CONFIRMED"）。

构建纪律（与 test_e2e_full_chain 相同）：mock 三件套（LLM_PROVIDER=mock /
JWT_SECRET / 临时 DB）由 server/conftest.py 提供，本文件不设 env；不 import 其它
测试模块（同一进程不 import 两测试模块纪律）。JD 文本须含 _mock_extract 识别的
关键词（Python/MySQL/Redis/Docker/沟通能力/团队协作、「N 年」experience、
「岗位：标题」）；「公司介绍」噪音段置于文末——段首触发 clean_jd 噪音态会吞掉
其后所有要求行。

运行：cd server && python -m pytest test_e2e_jd_to_report.py -q
"""
import json
import re
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from server.db import get_conn, set_db_path, init_db
from server.main import app
from server.services.pipeline import now_iso

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path):
    """每测试独立临时库（set_db_path 隔离，同 test_admin_pagination 范式）：
    全链造岗位/模型/题库任务行较多，用独立库避免污染 conftest 的 session 级共享库
    ——同一进程全套件运行时其它模块的列表/计数断言（如 qbank 列表分页）会被殃及。"""
    set_db_path(str(tmp_path / "jd2r.db"))
    init_db()  # TestClient 不触发 startup 事件，显式建表
    yield
    set_db_path(None)

# mock 观察层实义词命中（interview._EVIDENCE_WORDS：项目/举例/具体/结果/数据/负责）
# 且长度 ≥ MIN_ANSWER_CHARS(20)，保证逐题 VALID_EVIDENCE(spec=2, attr=True) 证据充分
_SUFFICIENT_ANSWER = (
    "我在项目中负责后端模块，用具体数据说明：SQL 优化后 P99 延迟从 300ms 降到 50ms，"
    "这是可复查的结果，也是我最有代表性的工作。"
)

_POS_NAME_RAW = "数据平台开发工程师"   # _mock_extract 抓「岗位：」标题
_POS_NAME = "数据平台开发"             # normalize_title 剥「工程师」后缀

# 3 条同岗位 JD 抽取（_mock_extract 关键词全命中）并消歧后的期望能力项全集
_EXPECTED_ITEMS = {
    "Python", "MySQL", "Redis", "Docker",          # hard_skill
    "沟通能力", "团队协作",                          # soft_skill
    "相关工作经验",                                  # experience（gate，年限 5）
}


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """只读查询：开连接→读→关（SQLite 单写防持锁阻塞 API 写入）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _one(sql: str, params: tuple = ()) -> dict:
    rows = _q(sql, params)
    assert rows, f"查询无结果: {sql}"
    return rows[0]


def _admin_headers() -> dict:
    """测试库首跑造 admin（bcrypt 直插 user 行，幂等；m7 模式）→ login 换 token。"""
    from passlib.context import CryptContext

    from server.services.pipeline import new_id
    conn = get_conn()
    row = conn.execute("SELECT user_id FROM user WHERE username='jd2r_admin'").fetchone()
    if row is None:
        pwd_ctx = CryptContext(schemes=["bcrypt"])
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (new_id("u"), "jd2r_admin", pwd_ctx.hash("admin123456"), "admin", now_iso()),
        )
        conn.commit()
    conn.close()
    r = client.post("/api/auth/login",
                    json={"username": "jd2r_admin", "password": "admin123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _candidate_headers(username: str) -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _post_jd(admin: dict, jd_text: str) -> dict:
    """粘贴导入；TestClient 下响应返回前 run_parse_pipeline（含自动聚合）已同步跑完。"""
    r = client.post("/api/admin/jds/import",
                    json={"jd_text": jd_text, "company": "jd2r_probe"}, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


# 「岗位：」→ _mock_extract 抓 job_title；技能词 = mock extract 正则；
# 「N 年」→ experience 项；噪音段（公司介绍/福利待遇）置于文末——段首触发 clean_jd
# 噪音态会吞掉其后直到「任职要求」之前的所有要求行。
JD_TEXT_TEMPLATE = """岗位：{title}
职位描述：
1. 精通 Python，熟悉常用数据结构。
2. 熟悉 MySQL 数据库，有慢查询优化经验。
3. 熟悉 Redis、Docker 等工具。
4. 良好的沟通能力与团队协作精神。
任职要求：
- 5 年以上后端开发经验。
- 计算机相关专业本科及以上学历。
公司介绍：某某科技提供有竞争力的薪酬与福利待遇。
"""


def _jd_text(title: str) -> str:
    return JD_TEXT_TEMPLATE.format(title=title)


# ---------- 主链 ----------

def test_full_chain_from_jd_text():
    admin = _admin_headers()

    # -- 阶段 1：JD#1 导入 + parse（建立 pending_review 岗位，不聚合） --
    jd1 = _post_jd(admin, _jd_text(_POS_NAME_RAW))
    jd1_row = _one("SELECT status, position_id FROM jd_record WHERE jd_id=?", (jd1["jd_id"],))
    assert jd1_row["status"] == "parsed", jd1_row  # 清洗→抽取→归岗→消歧全过
    pid = jd1_row["position_id"]
    assert pid, "JD#1 应已归岗（assign_position 未命中 → 新建岗位）"

    # 新岗位 pending_review；parse 尾自动聚合被 WR-08 拦（仅 active 岗位聚合）
    pos = _one("SELECT name, status FROM position WHERE position_id=?", (pid,))
    assert pos["name"] == _POS_NAME, pos
    assert pos["status"] == "pending_review", pos
    assert _q("SELECT model_id FROM competency_model WHERE position_id=?", (pid,)) == []

    # -- 阶段 2：管理员审批岗位（pending_review → active） --
    r = client.post(f"/api/admin/positions/{pid}/review",
                    json={"action": "approve"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"

    # -- 阶段 3：JD#2/#3 归一同岗（标题归一匹配）→ parse 尾自动聚合两次（v1/v2） --
    _post_jd(admin, _jd_text(_POS_NAME_RAW))
    _post_jd(admin, _jd_text(_POS_NAME_RAW))
    tasks = _q("SELECT task_id FROM aggregate_task WHERE position_id=?", (pid,))
    assert len(tasks) == 2, tasks  # JD#1 未聚合；JD#2/#3 各触发一次

    # 最新聚合任务：JD#3 parse 尾自动触发（批内收尾），已同步跑完
    task = _one(
        "SELECT task_id, status, trigger_source, total, done, llm_total, llm_done, model_id"
        " FROM aggregate_task WHERE position_id=?"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (pid,))
    assert task["status"] == "SUCCEEDED", task
    assert task["trigger_source"] == "auto:jd-parse", "聚合应由 parse 尾自动触发（SSOT §8.4）"
    assert task["done"] == task["total"], task
    assert task["llm_total"] == 0, task  # 3 条 JD 等级全一致 → LLM#3 不必上（一致性早退）

    # 模型 v2 draft：occ=3 全量证据
    model = _one(
        "SELECT model_id, version, status FROM competency_model WHERE position_id=?"
        " ORDER BY version DESC LIMIT 1", (pid,))
    assert model["status"] == "draft", model
    assert model["version"] == 2, model  # JD#2→v1、JD#3→v2
    assert task["model_id"] == model["model_id"], (task, model)

    items = _q("SELECT std_name, category, importance, weight, gate FROM competency_item"
               " WHERE model_id=?", (model["model_id"],))
    assert {it["std_name"] for it in items} == _EXPECTED_ITEMS, items
    hard = [it for it in items if it["category"] == "hard_skill"]
    soft = [it for it in items if it["category"] == "soft_skill"]
    exp = [it for it in items if it["category"] == "experience"]
    assert (len(hard), len(soft), len(exp)) == (4, 2, 1), items
    # occ=3 + 条件 req=1.0 → hard 全 required（三重判据满足）；soft 上限 preferred
    assert all(it["importance"] == "required" for it in hard), items
    assert all(it["importance"] == "preferred" for it in soft), items
    assert exp[0]["gate"] == 1 and exp[0]["weight"] == 0.0, items  # 年限 gate 走表单，不占权重池
    # 权重：类间 hard 0.7 / soft 0.3 配比 × 类内 importance 系数，Σ 严格 = 1（§8.2）
    assert abs(sum(it["weight"] for it in items) - 1.0) < 1e-6, items
    assert abs(sum(it["weight"] for it in hard) - 0.7) < 1e-6, hard
    assert abs(sum(it["weight"] for it in soft) - 0.3) < 1e-6, soft

    # -- 阶段 4：管理员 confirm → 后台题库生成（mock 模板题） --
    r = client.post(f"/api/admin/models/{model['model_id']}/confirm", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed", r.text

    qbt = _one(
        "SELECT task_id, status, total, done FROM question_bank_task"
        " WHERE position_id=? AND model_id=? ORDER BY created_at DESC LIMIT 1",
        (pid, model["model_id"]))
    assert qbt["status"] == "SUCCEEDED", qbt
    assert qbt["done"] == qbt["total"] and qbt["total"] == 16, qbt  # 4×3 档 + 2×2 档

    questions = _q(
        "SELECT std_name, category, difficulty, qtype FROM question_bank"
        " WHERE model_id=? AND model_version=? AND status='active'",
        (model["model_id"], model["version"]))
    hard_qs = [qn for qn in questions if qn["category"] == "hard_skill"]
    soft_qs = [qn for qn in questions if qn["category"] == "soft_skill"]
    assert (len(hard_qs), len(soft_qs)) == (12, 4), questions
    # required 项全覆盖 + 7:3 配额可行（readiness 第 4/5 项基线：hard≥7 / soft≥3）
    assert {qn["std_name"] for qn in questions} == _EXPECTED_ITEMS - {"相关工作经验"}, questions
    assert not any(qn["std_name"] == "相关工作经验" for qn in questions), "experience 不生成题（§9.1）"

    # -- 阶段 5：候选人完整答场（含表单收口）→ completed --
    cand = _candidate_headers("jd2r_cand_01")
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=cand)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    _answer_whole_session(sid, cand)

    # -- 阶段 6：request_report → 轮询终态 → 管理员 publish → PUBLISHED --
    r = client.post(f"/api/assessment/sessions/{sid}/report", headers=cand)
    assert r.status_code == 202, r.text
    rpt = _poll_report_terminal(sid, cand)
    assert rpt.get("coverage"), "coverage 应非空"
    assert isinstance(rpt.get("total_score"), (int, float))
    assert isinstance(rpt.get("strengths_text", ""), str)

    r = client.post(f"/api/admin/reports/{rpt['report_id']}/publish",
                    json={"review_outcome": "CONFIRMED", "review_note": "e2e"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["report_status"] == "PUBLISHED"

    row = _one("SELECT report_status, publish_confirmed_by, published_at"
               " FROM report WHERE report_id=?", (rpt["report_id"],))
    assert row["report_status"] == "PUBLISHED"
    assert row["publish_confirmed_by"] and row["published_at"]
    evs = _q("SELECT event_type, to_state FROM assessment_state_event WHERE session_id=?",
             (sid,))
    assert any(e["event_type"] == "REVIEW_REPORT_PUBLISH_CONFIRMED"
               and e["to_state"] == "PUBLISHED" for e in evs), evs


# ---------- 支撑 ----------

def _poll_report_terminal(sid: str, headers: dict) -> dict:
    """轮询 by-session 至非 GENERATING；断言 READY/PROVISIONAL（口径见文件头说明）。"""
    deadline = datetime.now() + timedelta(seconds=10)
    body = None
    while datetime.now() < deadline:
        r = client.get(f"/api/assessment/reports/by-session/{sid}", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        if body["report_status"] != "GENERATING":
            break
        time.sleep(0.2)
    assert body, "轮询窗口内未拿到报告"
    assert body["report_status"] in ("READY", "PROVISIONAL"), body["report_status"]
    return body


def _answer_whole_session(sid: str, headers: dict) -> None:
    """答完整场：SSE 流式逐题 + 表单 submit-v2 收口（复刻 full_chain 驱动模式）。"""
    r = client.post(f"/api/assessment/sessions/{sid}/start", headers=headers)
    assert r.status_code in (200, 409), r.text
    guard = 0
    while True:
        guard += 1
        assert guard < 100, "答题循环超限（题目持续派发异常）"
        r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
        assert r.status_code == 200, r.text
        cur = r.json()["current_question"]
        if cur is None:
            break
        resp = _stream_answer(sid, headers, cur["question_id"], _SUFFICIENT_ANSWER)
        assert resp["action"] in ("next", "finish", "form"), resp
        if resp["action"] == "form":
            m = re.search(r"📎\[form:([^\]]+)\]", resp.get("reply", ""))
            assert m, f"reply 应含 📎[form:id]，实得 {resp['reply']!r}"
            r = client.post(
                f"/api/assessment/sessions/{sid}/forms/submit-v2",
                json={"form_instance_id": m.group(1), "schema_version": "v1",
                      "expected_revision": 1, "payload": {"years_of_experience": 5}},
                headers=headers,
            )
            assert r.status_code in (200, 201), r.text
            assert r.json()["action"] in ("finish", "next"), r.text
    sess = _q("SELECT status FROM assessment_session WHERE session_id=?", (sid,))
    assert sess[0]["status"] == "completed", sess


def _stream_answer(sid: str, headers: dict, question_id: str, answer: str) -> dict:
    """流式消费 POST /answer → 组回 JSON 同构 dict（同 full_chain 模式）。"""
    with client.stream("POST", f"/api/assessment/sessions/{sid}/answer",
                       json={"question_id": question_id, "answer": answer},
                       headers=headers) as r:
        assert r.status_code == 200, f"answer 应 200，实得 {r.status_code}"
        lines = [ln for ln in r.iter_lines() if ln.startswith("data: ")]
    events = [json.loads(ln[6:]) for ln in lines]
    decision = next(e for e in events if e["type"] == "decision")
    done = next(e for e in events if e["type"] == "done")
    reply = "".join(e["content"] for e in events if e["type"] == "reply")
    return {"action": done["action"], "reply": reply,
            "question_id": question_id,
            "next_question_id": done.get("next_question_id"),
            "score_live": decision.get("score_live")}
