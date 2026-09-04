"""Phase 2 动态选题测试（REF-3.1/3.2/3.6/4.1——SSOT §10.2/§10.3/§10.5/§10.6）。

- 配额纯函数四样例（§10.2 表逐行）+ tier 目标（§10.3 公式与 soft=2 边界）
- 会话创建零预选（SC-1）；每次 next 动态实例化；followup 不增实例（REF-4.1）
- experience/qualification 不进普通选题（SC-2 前半）
- required 刚性例外（§10.5：N 耗尽后 medium 补选 + REQUIRED_EXCEPTION_GRANTED 事件；
  无候选 → PATH_UNAVAILABLE 不静默）
- legacy 会话（selection_reason 全 NULL）续答走旧 seq 派发不 500（Q5 迁移冒烟）

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db。单文件单进程。
运行：cd server && python -m pytest test_phase2_selection.py -v
"""
import json
import math
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase2_selection.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server import config  # noqa: E402
from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.question_selection import (  # noqa: E402
    largest_remainder_73,
    plan_quotas,
    tier_targets,
)

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)

# 测试用 N：直接读 config 常量（测试值非生产默认语义标注——Anti-pattern 4）
_TEST_N = config.ORDINARY_PLAN_N


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ---------- fixtures（test_p0_chain 种子模式复制；单文件单进程纪律） ----------

def _seed_position_with_confirmed_model() -> tuple[str, str]:
    """建 active 岗位 + confirmed 模型 + competency_item（required hard×2 + required soft×1）。"""
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
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "required", "weight": 0.25},
    ]
    items.append(
        {"std_name": "Docker", "category": "hard_skill", "importance": "preferred", "weight": 0.1})
    items.append(
        {"std_name": "团队协作", "category": "soft_skill", "importance": "preferred", "weight": 0.1})
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


def _seed_question_bank(pid: str, *, hard_extra: int = 0, soft_extra: int = 0) -> None:
    """岗位题：hard 7+ / soft 3+（N=10 → hard 7 / soft 3 的 tier 结构满足量）。

    required 题挂在 required item 上（Python/MySQL/沟通能力）；
    preferred 挂 Docker/团队协作（缺位时 tier targets 自动 clamp 到可用项）。
    """
    conn = get_conn()
    now = now_iso()

    def _add(std_name, category, difficulty, rubric):
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
            " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq, source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("qb"), "position", pid, std_name, category, difficulty, "subjective",
             f"{std_name} {difficulty} 题", None, rubric, None, None, "human", "active", now),
        )

    # hard_skill：Python×3 + MySQL×3 + Docker×1（Python easy/medium/hard 无链单题）
    for d in ("easy", "medium", "hard"):
        _add("Python", "hard_skill", d, "判据A")
        _add("MySQL", "hard_skill", d, "判据B")
    _add("Docker", "hard_skill", "medium", "判据C")
    for _ in range(hard_extra):
        _add("Docker", "hard_skill", "medium", "判据C")

    # soft_skill：沟通能力×3（required）+ 团队协作（preferred）
    for d in ("easy", "medium", "hard"):
        _add("沟通能力", "soft_skill", d, "判据D")
    for _ in range(soft_extra):
        _add("团队协作", "soft_skill", "medium", "判据E")
    conn.commit()
    conn.close()


def _auth_headers(username: str = "p2_sel_candidate") -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


_LONG_ANSWER = (
    "我熟练使用 Python 完成后端开发，熟悉常见的数据结构与算法，"
    "并且在多个项目中处理过性能问题、并发问题与数据库优化，有可量化结果。"
)


# ---------- 纯函数断言（§10.2 / §10.3） ----------

def test_largest_remainder_73():
    """§10.2 表逐行：N=9/10/11/15 → (6,3)/(7,3)/(8,3)/(11,4)。"""
    assert largest_remainder_73(9) == (6, 3)
    assert largest_remainder_73(10) == (7, 3)
    assert largest_remainder_73(11) == (8, 3)
    assert largest_remainder_73(15) == (11, 4)


def test_tier_targets():
    """§10.3：soft quota=2 → 1/1/0；quota=7 → 4/3/0；题量不足 clamp 先保 required。"""
    assert tier_targets(2, {"required": 5, "preferred": 5, "plus": 5}) == \
        {"required": 1, "preferred": 1, "plus": 0}
    t = tier_targets(7, {"required": 9, "preferred": 9, "plus": 9})
    assert t["required"] == math.ceil(7 * 0.8 / 1.7)
    assert t["preferred"] == math.ceil(7 * 0.6 / 1.7)
    assert t["plus"] == 7 - t["required"] - t["preferred"]
    # 边界 clamp：soft 可用 req 只有 0 → required 无可保，先保 preferred（§10.3 优先级）
    t0 = tier_targets(2, {"required": 0, "preferred": 2, "plus": 0})
    assert t0["required"] == 0 and t0["preferred"] > 0 and t0["plus"] == 0


def test_plan_quotas_single_category():
    """纯 hard 岗位（categories_present 只含 hard）→ N 全归 hard（大类退化）。"""
    quotas = plan_quotas(_TEST_N, {"hard_skill": {"required": 8, "preferred": 8, "plus": 8}})
    hard_total = sum(quotas["hard_skill"].values())
    assert hard_total == _TEST_N
    assert "soft_skill" not in quotas


# ---------- API 级动态选题断言（SC-1 / SC-2 / REF-4.1） ----------

def test_session_creation_no_preselection():
    """建会话后 assessment_question 行数 = 0（SC-1 首断言）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p2_sel_nopre")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    n = _q("SELECT COUNT(*) c FROM assessment_question WHERE session_id=?", (sid,))[0]["c"]
    assert n == 0, f"会话创建应零预选（实得 {n} 行）"


def _answer_one(sid, headers, answer=_LONG_ANSWER) -> dict:
    """取当前题并提交一次回答，返回响应 json。"""
    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    cur = r.json()["current_question"]
    assert cur is not None, "get_session 应已有派发实例"
    r = client.post(
        f"/api/assessment/sessions/{sid}/answer",
        json={"question_id": cur["question_id"], "answer": answer},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_dynamic_dispatch_per_next():
    """第 1 次 GET 派发首题；每答一题 aq 行数递增；selection_reason 七键可解析（D-18）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p2_sel_dyn")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]

    # 第一次 GET 派发首题（1 个未答实例）
    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    cur = r.json()["current_question"]
    assert cur is not None, "首次 GET 应触发首题派发"
    n = _q("SELECT COUNT(*) c FROM assessment_question WHERE session_id=?", (sid,))[0]["c"]
    assert n == 1, f"首题派发后应恰 1 实例，实得 {n}"

    answered = 0
    while True:
        resp = _answer_one(sid, headers)
        answered += 1
        n = _q("SELECT COUNT(*) c FROM assessment_question WHERE session_id=?", (sid,))[0]["c"]
        # aq 行数 = 已答主问题数 +（最后一题答完后实例数 == 已答数）
        assert n == answered or n == answered + 1 and resp["action"] != "finish", \
            f"第 {answered} 次作答后实例数 {n} 应等于已答数（或 +1 未答实例）"
        if resp["action"] == "finish":
            break
        n_after = _q(
            "SELECT COUNT(*) c FROM assessment_question WHERE session_id=?", (sid,))[0]["c"]
        assert n_after == answered + 1, \
            f"next 后应即时派发下一实例（{answered}+1），实得 {n_after}"

    # selection_reason JSON 结构：七键 + nth（D-18）
    rows = _q(
        "SELECT aq.selection_reason FROM assessment_question aq WHERE aq.session_id=?"
        " AND aq.selection_reason IS NOT NULL", (sid,))
    assert rows, "动态实例应有 selection_reason"
    for row in rows:
        reason = json.loads(row["selection_reason"])
        for key in ("layer", "predicate", "category", "tier", "chain_followed", "weight", "seed", "nth"):
            assert key in reason, f"selection_reason 缺 {key}: {reason}"


def test_no_experience_in_selection():
    """整场答完后所有实例 category ⊆ {hard_skill, soft_skill}（SC-2 前半）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    # 额外放经验题进题库：证明 selection 不吃 experience
    conn = get_conn()
    conn.execute(
        "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
        " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq, source, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("qb"), "general", None, "后端开发经验", "experience", None, "subjective",
         "介绍你最近一个后端项目。", None, "角色/规模/成果", None, None, "human", "active", now_iso()),
    )
    conn.commit()
    conn.close()
    headers = _auth_headers("p2_sel_noexp")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    while True:
        resp = _answer_one(sid, headers)
        if resp["action"] == "finish":
            break

    cats = {r["category"] for r in _q(
        "SELECT b.category FROM assessment_question aq"
        " JOIN question_bank b ON b.question_id=aq.bank_question_id WHERE aq.session_id=?", (sid,))}
    assert cats <= {"hard_skill", "soft_skill"}, f"普通选题出现 {cats}（experience 应剔除）"


def test_followup_does_not_create_instance():
    """followup 答次不增 aq 行数（REF-4.1：followup 为实例内子轮次）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p2_sel_fu")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]

    # 第一次提交（长答）→ next
    resp = _answer_one(sid, headers, _LONG_ANSWER)
    assert resp["action"] == "next" or resp["action"] == "finish"

    # 若 next：取当前题短答触发 followup，实例数不变
    if resp["action"] == "next":
        before = _q("SELECT COUNT(*) c FROM assessment_question WHERE session_id=?", (sid,))[0]["c"]
        r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
        qid = r.json()["current_question"]["question_id"]
        r = client.post(
            f"/api/assessment/sessions/{sid}/answer",
            json={"question_id": qid, "answer": "不知道"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["action"] == "followup", "短答应触发 followup"
        after = _q("SELECT COUNT(*) c FROM assessment_question WHERE session_id=?", (sid,))[0]["c"]
        assert after == before, f"followup 不应增实例（{before} → {after}）"


# ---------- required 刚性例外（§10.5） ----------

def _rows_for(sid: str) -> int:
    return _q("SELECT COUNT(*) c FROM assessment_question WHERE session_id=?", (sid,))[0]["c"]


def test_required_exception_after_exhaustion():
    """普通计划耗尽后有未覆盖 required item → 补选 medium + REQUIRED_EXCEPTION_GRANTED。

    构造（plan <interfaces>「题库题数刚好只满足配额且该 item 的题排序靠后」）：
    - 5 个 required hard item，N=10 → hard 7 → required tier 目标 4——层②逐轮
      按权重选未覆盖 required（Python/算法/Redis/Kafka 各 1 题），权重最低的
      MySQL（required、题在池中）在第 5 轮时 required tier 槽位已满 → 普通计划
      全程不覆盖 → N 题后例外补选其 medium（§10.5）→ REQUIRED_EXCEPTION_GRANTED；
    - 沟通能力（required soft）：唯一 medium 题挂 model_id='other'（版本近似
      排除出候选池，readiness 的 std_name 覆盖检查仍通过）→ 例外也无候选 →
      PATH_UNAVAILABLE 事件留痕（不静默），会话照常 finish 推进不 500。
    """
    import sqlite3 as _s
    conn = get_conn()
    pid, mid = new_id("pos"), new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "后端开发工程师", "active", now),
    )
    items = [
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.30},
        {"std_name": "算法", "category": "hard_skill", "importance": "required", "weight": 0.28},
        {"std_name": "Redis", "category": "hard_skill", "importance": "required", "weight": 0.26},
        {"std_name": "Kafka", "category": "hard_skill", "importance": "required", "weight": 0.24},
        # 权重最低的 required hard——层②四轮后被 required tier 目标（=4）挡在普通计划外
        {"std_name": "MySQL", "category": "hard_skill", "importance": "required", "weight": 0.20},
        {"std_name": "Docker", "category": "hard_skill", "importance": "preferred", "weight": 0.10},
        # 唯一 medium 题挂他人 model_id：普通候选池排除（例外无候选 → PATH_UNAVAILABLE）
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "required", "weight": 0.25},
        {"std_name": "团队协作", "category": "soft_skill", "importance": "preferred", "weight": 0.10},
        {"std_name": "跨部门协作", "category": "soft_skill", "importance": "plus", "weight": 0.05},
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

    def _add(std_name, category, difficulty, model_id=None):
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
            " model_id, difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq,"
            " source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("qb"), "position", pid, std_name, category, model_id, difficulty,
             "subjective", f"{std_name} {difficulty} 题", None, "判据", None, None,
             "human", "active", now),
        )

    # required hard：前四权重各 1 题（层②覆盖）；MySQL 2 道 medium（例外目标一）
    for std in ("Python", "算法", "Redis", "Kafka"):
        _add(std, "hard_skill", "medium")
    for _ in range(2):
        _add("MySQL", "hard_skill", "medium")
    # preferred hard：Docker×3 占 pref 3 槽
    for _ in range(3):
        _add("Docker", "hard_skill", "medium")
    # 沟通能力（required soft）：medium 挂他人 model_id → 候选池排除（例外目标二）
    _add("沟通能力", "soft_skill", "medium", model_id="cm_other")
    # soft pref×2 + plus×1 占满 soft 3 槽
    for _ in range(2):
        _add("团队协作", "soft_skill", "medium")
    _add("跨部门协作", "soft_skill", "medium")
    conn.commit()
    conn.close()
    headers = _auth_headers("p2_sel_exc")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]

    # 答完普通 N 题（每题长答 → next；决策 finish 已在池未空时降级 next）
    for _ in range(_TEST_N):
        resp = _answer_one(sid, headers)
        assert resp["action"] == "next", \
            f"普通计划前 {_TEST_N} 题应 next，实得 {resp['action']}"

    # 第 N+1 次选题：MySQL 例外补选 medium（§10.5 只允许 medium）
    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    exc_q = r.json()["current_question"]
    assert exc_q is not None, "N 题后应有 MySQL 例外实例（N+1）"
    mysql_rows = _q(
        "SELECT b.std_name, b.difficulty FROM assessment_question aq"
        " JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE aq.session_id=? AND b.std_name='MySQL'", (sid,))
    assert mysql_rows, "MySQL 例外实例应已落库"
    assert all(row["difficulty"] == "medium" for row in mysql_rows), \
        f"例外补选只允许 medium，实得 {mysql_rows}"

    events = _q(
        "SELECT event_type, payload_json FROM assessment_state_event WHERE session_id=?"
        " ORDER BY sequence_no", (sid,))
    types = [e["event_type"] for e in events]
    assert "REQUIRED_EXCEPTION_GRANTED" in types, \
        f"例外分支应写 REQUIRED_EXCEPTION_GRANTED，实得 {types}"

    # 继续作答至 finish：沟通能力无 medium/hard 候选 → PATH_UNAVAILABLE 不静默
    while True:
        resp = _answer_one(sid, headers)
        if resp["action"] == "finish":
            break
    types = [e["event_type"] for e in _q(
        "SELECT event_type FROM assessment_state_event WHERE session_id=?", (sid,))]
    assert "PATH_UNAVAILABLE" in types, \
        f"例外耗尽应落 PATH_UNAVAILABLE，实得事件集 {types}"
    sess = _q("SELECT status FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "completed", "PATH_UNAVAILABLE 后会话应照常 finish 不 500"


# ---------- legacy 会话续答冒烟（Q5 迁移） ----------

def test_legacy_session_continues():
    """手工直插旧形态会话（无 selection_reason）+ 未答预选实例 2 行 → 续答走旧 seq 派发不 500。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p2_sel_legacy")

    # 取该用户 user_id
    import base64
    # 建 API 会话拿合法 user 再直插旧行更简单——用 register 用户的 user_id
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    # 用新会话的 position/model 直插旧形态目标会话
    conn = get_conn()
    uid_row = conn.execute(
        "SELECT user_id FROM user WHERE username='p2_sel_legacy'").fetchone()
    uid = uid_row["user_id"]
    sid = new_id("sess")
    now = now_iso()
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (sid, uid, pid, mid, 1, "in_progress", now, now),
    )
    # 直插 2 行未答预选实例（旧行：6 旧列 + question_type='legacy' 默认；不写 selection_reason）
    bank_ids = [r["question_id"] for r in conn.execute(
        "SELECT question_id FROM question_bank WHERE position_id=?"
        " AND category='hard_skill' ORDER BY created_at, rowid LIMIT 2", (pid,)).fetchall()]
    assert len(bank_ids) == 2
    for i, bid in enumerate(bank_ids, start=1):
        conn.execute(
            "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq,"
            " created_at) VALUES(?,?,?,?,?)",
            (new_id("aq"), sid, bid, i, now),
        )
    conn.commit()
    conn.close()

    # 续答第 1 题（长答触发 next）→ 200，next_question_id 指向旧行 seq=2（不 500）
    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    cur = r.json()["current_question"]
    assert cur is not None, "legacy 会话 GET 应返回旧预选首题"
    assert cur["question_id"] == _q(
        "SELECT question_id FROM assessment_question WHERE session_id=? ORDER BY seq",
        (sid,))[0]["question_id"], "legacy 会话应按 seq 顺序派发"

    r = client.post(
        f"/api/assessment/sessions/{sid}/answer",
        json={"question_id": cur["question_id"], "answer": _LONG_ANSWER},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] in ("next", "finish"), body
    legacy_rows = _q(
        "SELECT question_id FROM assessment_question WHERE session_id=? ORDER BY seq", (sid,))
    if body["action"] == "next" and body.get("next_question_id"):
        assert body["next_question_id"] == legacy_rows[1]["question_id"], \
            "legacy 续答 next 应指向旧行 seq 下一题"
