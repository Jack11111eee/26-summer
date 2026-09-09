"""岗位生命周期管理后端测试（SSOT §8，2026-09-09 裁决：status/merge 端点 +
options 过滤 + 归岗闭环——inactive 岗不吸收新 JD）。

覆盖四组：
  1) POST /admin/positions/{id}/status：active⇄inactive 状态机（pending 409、同态 409、
     非法 body 400、404、RUNNING 聚合 409）；下架后 readiness 拒开考、测评端列表不可见
  2) POST /admin/positions/{source}/merge：happy path（JD+别名迁移+计数）、子表占用 409、
     目标非 active 409、source==target 400、404、别名冲突 409、不自动重聚合、
     pending_review 壳可作 source
  3) 归岗闭环 assign_position：active/pending_review 名与 alias 照旧匹配（回归）；
     inactive 名 / inactive 岗 alias 落穿建新 pending 壳（新语义）
  4) GET /admin/positions/options：?status=active 过滤、不传全量、非法值 400

LLM_PROVIDER=mock 离线；每测试独立 tmp_path 临时库（set_db_path fixture，test_migration.py
同范式——**不**在模块级写 os.environ["DB_PATH"]：pytest 全进程先经 conftest import
server.config，模块级 env 已不生效，数据会落进 conftest 的共享 session 库，把别的
文件（如 qbank 列表 page=20 分页）的可见集顶爆）。不碰 data/app.db。
运行：cd server && python -m pytest test_position_lifecycle.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn, set_db_path  # noqa: E402
from server.services.pipeline import assign_position, new_id, now_iso  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path):
    """每测试独立临时库：进程内 set_db_path 覆盖（对 conftest session 库零污染），
    结束复位 None。"""
    set_db_path(str(tmp_path / "position_lifecycle.db"))
    init_db()
    yield
    set_db_path(None)


# ---------- 种子工具（test_aggregate_admin.py 同款模式） ----------

def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _seed_position(name: str, st: str = "active") -> str:
    pid = new_id("pos")
    conn = get_conn()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, name, st, now_iso()),
    )
    conn.commit()
    conn.close()
    return pid


def _seed_alias(pid: str, alias: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO position_alias(alias_id, position_id, alias) VALUES(?,?,?)",
        (new_id("pa"), pid, alias),
    )
    conn.commit()
    conn.close()


def _seed_jd(pid: str, job_title: str = "测试岗") -> str:
    jd_id = new_id("jd")
    conn = get_conn()
    conn.execute(
        "INSERT INTO jd_record(jd_id, position_id, job_title, company, source_type,"
        " raw_text, status, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (jd_id, pid, job_title, None, "paste", "JD 原文", "parsed", now_iso()),
    )
    conn.commit()
    conn.close()
    return jd_id


def _seed_confirmed_model(pid: str, version: int = 1) -> str:
    """直插 confirmed 模型（开考链路的岗位面）+ competency_item（hard+soft 各一，
    两类齐备才走 7:3 双类配额而非单类退化 N=10）。"""
    mid = new_id("cm")
    conn = get_conn()
    items = [
        {"std_name": "Python", "category": "hard_skill", "importance": "required",
         "weight": 0.7, "gate": 0},
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "required",
         "weight": 0.3, "gate": 0},
    ]
    model_json = {"position_id": pid, "version": version, "items": items}
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, version, "confirmed", json.dumps(model_json, ensure_ascii=False), now_iso()),
    )
    for it in items:
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("c"), mid, it["std_name"], it["category"], 3, it["importance"],
             it["weight"], int(it.get("gate", 0))),
        )
    conn.commit()
    conn.close()
    return mid


def _seed_question_bank(pid: str, mid: str) -> None:
    """足量岗位题（复用 test_p0_chain._seed_question_bank 的难度链口径：hard 7 + soft 3）。
    本套件只断言 409/可见性，不跑完整答题链，但基线 201 需过 readiness 配额。"""
    conn = get_conn()
    now = now_iso()

    def _add(std_name, category, difficulty, qtype, stem, answer_key, rubric,
             chain_key=None, chain_seq=None):
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, model_id, model_version,"
            " std_name, category, difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq,"
            " source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("qb"), "position", pid, mid, 1, std_name, category, difficulty, qtype,
             stem, answer_key, rubric, chain_key, chain_seq, "human", "active", now),
        )

    _add("Python", "hard_skill", "easy", "objective", "Python 中用什么关键字定义函数？", "def", None,
         "py-chain", 1)
    _add("Python", "hard_skill", "medium", "subjective", "讲一个你用 Python 解决过的性能问题。", None, "场景/数据/结果",
         "py-chain", 2)
    _add("Python", "hard_skill", "hard", "subjective", "如何设计高并发 Python 服务？", None, "并发模型/限流/缓存",
         "py-chain", 3)
    _add("MySQL", "hard_skill", "easy", "objective", "MySQL 默认事务隔离级别是？", "REPEATABLE", None,
         "mysql-chain", 1)
    _add("MySQL", "hard_skill", "medium", "subjective", "讲一次慢查询优化经历。", None, "explain/索引/效果",
         "mysql-chain", 2)
    _add("Redis", "hard_skill", "easy", "objective", "Redis 常用字符串命令？", "GET", None)
    _add("Docker", "hard_skill", "easy", "objective", "构建镜像的命令是？", "docker build", None)
    _add("沟通能力", "soft_skill", "easy", "subjective", "讲一次跨团队沟通的经历。", None, "背景/冲突/结果")
    _add("沟通能力", "soft_skill", "medium", "subjective", "遇到意见分歧怎么处理？", None, "倾听/数据/共识")
    _add("冲突协调", "soft_skill", "medium", "subjective", "讲一次你化解团队冲突的经历。", None, "起因/方法/结果")
    conn.commit()
    conn.close()


def _insert_running_task(pid: str) -> str:
    """手工插一行 RUNNING 聚合任务（模拟在途聚合——不实际跑 run_aggregate）。"""
    tid = new_id("agg_task")
    conn = get_conn()
    conn.execute(
        "INSERT INTO aggregate_task(task_id, position_id, status, trigger_source,"
        " total, llm_total, created_at, started_at) VALUES(?,?,?,?,?,?,?,?)",
        (tid, pid, "RUNNING", "manual", 5, 3, now_iso(), now_iso()),
    )
    conn.commit()
    conn.close()
    return tid


def _ensure_admin() -> None:
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


def _admin_client():
    """admin 登录的 TestClient（本套件 API 均在 admin 面）。"""
    from server.main import app
    client = TestClient(app, raise_server_exceptions=False)
    _ensure_admin()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return client, {"Authorization": f"Bearer {r.json()['token']}"}


def _candidate_client(username: str):
    """候选人注册+登录（readiness / 测评端列表断言用）。"""
    from server.main import app
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return client, {"Authorization": f"Bearer {r.json()['token']}"}


# ---------- 1) status 端点 ----------

def test_status_active_to_inactive_and_back():
    """active→inactive 成功返回新态；inactive→active 还原成功。"""
    client, headers = _admin_client()
    pid = _seed_position("生命周期状态岗")

    r = client.post(f"/api/admin/positions/{pid}/status",
                    json={"status": "inactive"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"position_id": pid, "status": "inactive"}
    assert _q("SELECT status FROM position WHERE position_id=?", (pid,))[0]["status"] == "inactive"

    r = client.post(f"/api/admin/positions/{pid}/status",
                    json={"status": "active"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"position_id": pid, "status": "active"}
    assert _q("SELECT status FROM position WHERE position_id=?", (pid,))[0]["status"] == "active"


def test_status_inactive_blocks_session_and_hidden_from_list():
    """下架后：readiness 拒开考（create_session 409 链路）、测评端 positions 列表不含该岗。"""
    pid = _seed_position("下架可见性岗")
    mid = _seed_confirmed_model(pid)
    _seed_question_bank(pid, mid)

    # 上架态基线：列表可见 + 可开考（201）
    client, headers = _candidate_client("plc_visibility")
    r = client.get("/api/assessment/positions", headers=headers)
    assert r.status_code == 200, r.text
    assert any(p["position_id"] == pid for p in r.json())
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    # 收尾该会话，避免影响后续断言（同一 (user, position) 在途会话会被复用）
    conn = get_conn()
    conn.execute("UPDATE assessment_session SET status='abandoned', abandoned_at=?"
                 " WHERE session_id=?", (now_iso(), sid))
    conn.commit()
    conn.close()

    admin_client, admin_headers = _admin_client()
    r = admin_client.post(f"/api/admin/positions/{pid}/status",
                          json={"status": "inactive"}, headers=admin_headers)
    assert r.status_code == 200, r.text

    # 下架后：列表不含该岗（WHERE p.status='active' 过滤）
    r = client.get("/api/assessment/positions", headers=headers)
    assert r.status_code == 200, r.text
    assert not any(p["position_id"] == pid for p in r.json())

    # 下架后：开考拒（readiness 第 1 项 position active → MODEL_NOT_MEASURABLE 409）
    client2, headers2 = _candidate_client("plc_visibility_2")  # 新用户避开复用分支
    r = client2.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers2)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error_code"] == "MODEL_NOT_MEASURABLE", r.text
    n = _q("SELECT COUNT(*) c FROM assessment_session WHERE session_id=?", (sid,))[0]["c"]
    assert n == 1  # 无新会话创建（仅在架时的那场）


def test_status_same_state_409():
    """目标态=当前态 → 409。"""
    client, headers = _admin_client()
    pid = _seed_position("同态岗")
    r = client.post(f"/api/admin/positions/{pid}/status",
                    json={"status": "active"}, headers=headers)
    assert r.status_code == 409, r.text

    pid2 = _seed_position("同态下架岗", "inactive")
    r = client.post(f"/api/admin/positions/{pid2}/status",
                    json={"status": "inactive"}, headers=headers)
    assert r.status_code == 409, r.text


def test_status_pending_review_409():
    """pending_review 岗走 status 端点 → 409（入口态须经审核流）。"""
    client, headers = _admin_client()
    pid = _seed_position("待审状态机岗", "pending_review")
    r = client.post(f"/api/admin/positions/{pid}/status",
                    json={"status": "active"}, headers=headers)
    assert r.status_code == 409, r.text
    assert "pending_review" in r.json()["detail"]
    # 状态未被改动
    assert _q("SELECT status FROM position WHERE position_id=?", (pid,))[0]["status"] == "pending_review"


def test_status_not_found_and_bad_body():
    """岗位不存在 404；非法 body status 400。"""
    client, headers = _admin_client()
    r = client.post("/api/admin/positions/pos_nonexistent/status",
                    json={"status": "active"}, headers=headers)
    assert r.status_code == 404, r.text

    pid = _seed_position("非法态岗")
    r = client.post(f"/api/admin/positions/{pid}/status",
                    json={"status": "bogus"}, headers=headers)
    assert r.status_code == 400, r.text
    r = client.post(f"/api/admin/positions/{pid}/status", json={}, headers=headers)
    assert r.status_code == 400, r.text


def test_status_inactive_409_while_aggregating():
    """RUNNING 聚合任务在场 → 下架 409（上架方向不受影响）。"""
    client, headers = _admin_client()
    pid = _seed_position("聚合中下架岗")
    _insert_running_task(pid)

    r = client.post(f"/api/admin/positions/{pid}/status",
                    json={"status": "inactive"}, headers=headers)
    assert r.status_code == 409, r.text
    assert "聚合进行中" in r.json()["detail"]
    assert _q("SELECT status FROM position WHERE position_id=?", (pid,))[0]["status"] == "active"


# ---------- 2) merge 端点 ----------

def test_merge_happy_path():
    """target active 无别名、source 挂 2 JD + 2 alias → JD 全迁、alias 迁移（含 source 名）、
    source 消失、响应计数正确、不触发聚合。"""
    client, headers = _admin_client()
    target = _seed_position("合并目标岗")
    source = _seed_position("合并源岗")
    jd1 = _seed_jd(source, "合并源岗")
    jd2 = _seed_jd(source, "另一条")
    _seed_alias(source, "源岗别名一")
    _seed_alias(source, "源岗别名二")

    r = client.post(f"/api/admin/positions/{source}/merge",
                    json={"target_id": target}, headers=headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d == {"source_id": source, "target_id": target, "moved_jds": 2, "moved_aliases": 3}

    # JD 全到 target
    rows = _q("SELECT position_id FROM jd_record WHERE jd_id IN (?,?)", (jd1, jd2))
    assert {x["position_id"] for x in rows} == {target}
    # source 名 + 两个既有 alias 全部挂 target；source 消失
    aliases = {x["alias"]: x["position_id"] for x in
               _q("SELECT alias, position_id FROM position_alias WHERE position_id=?", (target,))}
    assert aliases == {"合并源岗": target, "源岗别名一": target, "源岗别名二": target}
    assert _q("SELECT COUNT(*) c FROM position WHERE position_id=?", (source,))[0]["c"] == 0
    # 不触发聚合：无任务行、无新模型
    assert _q("SELECT COUNT(*) c FROM aggregate_task WHERE position_id=?", (target,))[0]["c"] == 0
    assert _q("SELECT COUNT(*) c FROM competency_model WHERE position_id=?", (target,))[0]["c"] == 0


def test_merge_source_with_model_409():
    """source 有 competency_model 行 → 409，且不动任何行。"""
    client, headers = _admin_client()
    target = _seed_position("模型占用目标岗")
    source = _seed_position("模型占用源岗")
    _seed_jd(source)
    _seed_confirmed_model(source)

    r = client.post(f"/api/admin/positions/{source}/merge",
                    json={"target_id": target}, headers=headers)
    assert r.status_code == 409, r.text
    assert "不可合并" in r.json()["detail"]
    # source 原样保留（岗位、JD、模型行都在）
    assert _q("SELECT COUNT(*) c FROM position WHERE position_id=?", (source,))[0]["c"] == 1
    jds = _q("SELECT position_id FROM jd_record")
    assert any(x["position_id"] == source for x in jds)


def test_merge_source_with_qb_task_409():
    """source 有 question_bank_task 行 → 409。"""
    client, headers = _admin_client()
    target = _seed_position("题库任务目标岗")
    source = _seed_position("题库任务源岗")
    mid = _seed_confirmed_model(source)  # FK 需要模型行；本用例只断言 qbt 占用路径
    conn = get_conn()
    conn.execute(
        "INSERT INTO question_bank_task(task_id, position_id, model_id, model_version,"
        " status, created_at) VALUES(?,?,?,?,?,?)",
        (new_id("qbt"), source, mid, 1, "SUCCEEDED", now_iso()),
    )
    conn.commit()
    conn.close()

    r = client.post(f"/api/admin/positions/{source}/merge",
                    json={"target_id": target}, headers=headers)
    assert r.status_code == 409, r.text
    assert "不可合并" in r.json()["detail"]


def test_merge_target_not_active_409():
    """target 非 active（inactive/pending_review）→ 409。"""
    client, headers = _admin_client()
    for st in ("inactive", "pending_review"):
        source = _seed_position(f"目标非激活源岗{st}")
        target = _seed_position(f"目标非激活岗{st}", st)
        r = client.post(f"/api/admin/positions/{source}/merge",
                        json={"target_id": target}, headers=headers)
        assert r.status_code == 409, r.text
        assert "上架" in r.json()["detail"]
        assert _q("SELECT COUNT(*) c FROM position WHERE position_id=?", (source,))[0]["c"] == 1


def test_merge_source_equals_target_400():
    """source == target → 400。"""
    client, headers = _admin_client()
    pid = _seed_position("自合并岗")
    r = client.post(f"/api/admin/positions/{pid}/merge",
                    json={"target_id": pid}, headers=headers)
    assert r.status_code == 400, r.text


def test_merge_not_found():
    """source 或 target 不存在 → 404。"""
    client, headers = _admin_client()
    target = _seed_position("存在目标岗")
    r = client.post("/api/admin/positions/pos_nonexistent/merge",
                    json={"target_id": target}, headers=headers)
    assert r.status_code == 404, r.text

    source = _seed_position("存在源岗")
    r = client.post(f"/api/admin/positions/{source}/merge",
                    json={"target_id": "pos_nonexistent"}, headers=headers)
    assert r.status_code == 404, r.text


def test_merge_alias_conflict_409():
    """别名冲突预检 → 409 列出冲突项，且校验阶段不动任何行。

    形态 a：source.name 撞第三方岗位的 alias 文本（source 名要插为 target 新 alias，
    撞 position_alias 既有 UNIQUE 行——迁移 source 自身 alias 行只改 position_id 不产生
    冲突，唯一冲突源是 name 插入）；形态 b：source.name 与 target.name 相同（撞名=数据脏）。
    """
    client, headers = _admin_client()
    target = _seed_position("冲突目标岗")
    third = _seed_position("第三方岗")
    _seed_alias(third, "限量别名")

    # a) source 名 == 第三方岗位的 alias 文本
    source = _seed_position("限量别名")
    _seed_jd(source)
    r = client.post(f"/api/admin/positions/{source}/merge",
                    json={"target_id": target}, headers=headers)
    assert r.status_code == 409, r.text
    assert "别名冲突" in r.json()["detail"]
    assert "限量别名" in r.json()["detail"]
    # 校验阶段不动任何行
    assert _q("SELECT COUNT(*) c FROM position WHERE position_id=?", (source,))[0]["c"] == 1
    jds = _q("SELECT position_id FROM jd_record")
    assert any(x["position_id"] == source for x in jds)

    # b) source.name 与 target.name 相同（NOCASE）
    source2 = _seed_position("冲突目标岗")  # 与 target 同名
    r = client.post(f"/api/admin/positions/{source2}/merge",
                    json={"target_id": target}, headers=headers)
    assert r.status_code == 409, r.text
    assert "别名冲突" in r.json()["detail"]
    assert "相同" in r.json()["detail"]
    assert _q("SELECT COUNT(*) c FROM position WHERE position_id=?", (source2,))[0]["c"] == 1


def test_merge_does_not_reaggregate():
    """target 原有模型 → 合并后版本数不变（不自动重聚合——升版本须 diff 人审）。"""
    client, headers = _admin_client()
    target = _seed_position("重聚合目标岗")
    _seed_confirmed_model(target, version=3)
    source = _seed_position("重聚合源岗")
    _seed_jd(source)

    r = client.post(f"/api/admin/positions/{source}/merge",
                    json={"target_id": target}, headers=headers)
    assert r.status_code == 200, r.text
    versions = [x["version"] for x in
                _q("SELECT version FROM competency_model WHERE position_id=?", (target,))]
    assert versions == [3]  # 无新版本
    assert _q("SELECT COUNT(*) c FROM aggregate_task WHERE position_id=?", (target,))[0]["c"] == 0


def test_merge_pending_review_shell_as_source():
    """pending_review 壳作 source 也可合并（pending 壳 486 个是主用途）。"""
    client, headers = _admin_client()
    target = _seed_position("待审壳目标岗")
    source = _seed_position("待审壳源岗", "pending_review")
    jd = _seed_jd(source)
    _seed_alias(source, "待审壳别名")

    r = client.post(f"/api/admin/positions/{source}/merge",
                    json={"target_id": target}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["moved_jds"] == 1
    assert r.json()["moved_aliases"] == 2
    assert _q("SELECT position_id FROM jd_record WHERE jd_id=?", (jd,))[0]["position_id"] == target
    assert _q("SELECT COUNT(*) c FROM position WHERE position_id=?", (source,))[0]["c"] == 0


# ---------- 3) 归岗闭环 ----------

def test_assign_position_matches_active():
    """active 岗名 → 新 JD 归它（回归）。"""
    pid = _seed_position("算法", "active")
    got, why = assign_position("算法工程师")  # normalize 后落 "算法"
    assert got == pid and why == "matched"
    assert _q("SELECT COUNT(*) c FROM position")[0]["c"] >= 1


def test_assign_position_inactive_name_falls_through():
    """inactive 岗名 → 落穿建新 pending 壳（新语义）。"""
    _seed_position("数据分析师", "inactive")
    got, why = assign_position("数据分析师")
    assert why == "new_pending_review"
    rows = _q("SELECT position_id, status FROM position WHERE name='数据分析师'")
    assert len(rows) == 2
    shell = next(x for x in rows if x["position_id"] == got)
    assert shell["status"] == "pending_review"


def test_assign_position_inactive_alias_falls_through():
    """alias 属 inactive 岗 → 落穿建新 pending 壳。"""
    inactive = _seed_position("inactive 别名主岗", "inactive")
    _seed_alias(inactive, "平台开发")
    got, why = assign_position("平台开发")
    assert why == "new_pending_review"
    shell = _q("SELECT status FROM position WHERE position_id=?", (got,))[0]
    assert shell["status"] == "pending_review"


def test_assign_position_matches_pending_review():
    """pending_review 岗名 → 照旧匹配（回归，pending 不被滤掉）。"""
    pid = _seed_position("NLP算法", "pending_review")
    got, why = assign_position("NLP 算法工程师")
    assert got == pid and why == "matched"


def test_assign_position_alias_of_active():
    """active 岗的 alias 照旧命中（回归——join 后过滤不误伤；别名两侧同为
    normalize 后的同形字符串：Web 前端 → web前端）。"""
    pid = _seed_position("前端", "active")
    _seed_alias(pid, "web前端")
    got, why = assign_position("Web 前端")  # normalize → "web前端"
    assert got == pid and why == "alias"


# ---------- 4) options 过滤 ----------

def _seed_options_positions() -> dict[str, str]:
    """造三态各一岗，返回 {status: position_id}。"""
    return {
        "active": _seed_position("选项上架岗", "active"),
        "inactive": _seed_position("选项下架岗", "inactive"),
        "pending_review": _seed_position("选项待审岗", "pending_review"),
    }


def test_options_status_filter():
    """?status=active 只回 active；?status=inactive/pending_review 各回对应集。"""
    client, headers = _admin_client()
    pids = _seed_options_positions()

    r = client.get("/api/admin/positions/options",
                   params={"status": "active"}, headers=headers)
    assert r.status_code == 200, r.text
    got = {x["position_id"] for x in r.json()}
    assert pids["active"] in got
    assert pids["inactive"] not in got
    assert pids["pending_review"] not in got

    r = client.get("/api/admin/positions/options",
                   params={"status": "pending_review"}, headers=headers)
    got = {x["position_id"] for x in r.json()}
    assert pids["pending_review"] in got
    assert pids["active"] not in got
    assert pids["inactive"] not in got


def test_options_no_filter_returns_all():
    """不传 status → 全量（含三态——名称查找语义不能破坏）；空串同全量。"""
    client, headers = _admin_client()
    pids = _seed_options_positions()

    r = client.get("/api/admin/positions/options", headers=headers)
    assert r.status_code == 200, r.text
    got = {x["position_id"] for x in r.json()}
    assert {pids["active"], pids["inactive"], pids["pending_review"]} <= got

    r = client.get("/api/admin/positions/options",
                   params={"status": ""}, headers=headers)
    assert r.status_code == 200, r.text
    got = {x["position_id"] for x in r.json()}
    assert {pids["active"], pids["inactive"], pids["pending_review"]} <= got


def test_options_invalid_status_400():
    """status=bogus → 400。"""
    client, headers = _admin_client()
    r = client.get("/api/admin/positions/options",
                   params={"status": "bogus"}, headers=headers)
    assert r.status_code == 400, r.text
