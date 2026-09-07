"""证据排除端到端测试（SSOT §8.5/2026-09-07）。

覆盖九组（端点 / 校验 / 聚合语义 / 读侧合并 / PUT 剥离 / 题库过滤）：
  1) 端点往返：mark→lift→复活（幂等 upsert，lift 不删行）
  2) 目标校验：他岗 JD / 非 parsed / 项不存在 / text 不在 → 400/404/422
  3) 部分排除不影响 r/req（语义锁：全排除才出频次）
  4) 全排除影响 r/req（分子减 JD，分母不变）
  5) 消项：全部 JD 的证据被排除 → 项从产物消失、Σ=1 仍成立
  6) lift 恢复 == 基线
  7) 读侧合并：draft 合并 excluded 条目 / confirmed 快照不合并
  8) PUT 剥离：回传含 excluded 条目 → 存库不含
  9) question_gen 防御过滤：prompt 取第一条未排除证据

LLM#3 全程 provider=mock（离线）。运行：cd server && python -m pytest test_evidence_exclusion.py -q
"""
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）；单文件单库
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_evidence_exclusion.db")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app, raise_server_exceptions=False)


# ---------- 种子与工具 ----------

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


def _admin_headers() -> dict:
    conn = get_conn()
    try:
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
    finally:
        conn.close()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def headers():
    return _admin_headers()


def _seed_position() -> str:
    """active 岗位 + 2 条 parsed JD：
    jd1: Python(Lv3, 证据 e1a/e1b) + MySQL(Lv4, 证据 m1)
    jd2: Python(Lv5, 证据 e2a/e2b) + MySQL(Lv4, 证据 m2) + 沟通能力(soft, 证据 s2)
    Python 跨 JD 等级冲突 → 走 LLM#3（mock 取众数）；MySQL 一致不走。
    """
    pid = new_id("pos")
    _exec(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "证据排除测试岗", "active", now_iso()),
    )

    def _jd(std_items: list[dict], title: str) -> str:
        jd_id = new_id("jd")
        _exec(
            "INSERT INTO jd_record(jd_id, position_id, job_title, company, source_type,"
            " raw_text, std_items_json, status, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (jd_id, pid, title, None, "paste", title + " 原文",
             json.dumps(std_items, ensure_ascii=False), "parsed", now_iso()),
        )
        return jd_id

    jd1 = _jd([
        {"name": "Python", "category": "hard_skill", "importance": "required",
         "required_level": 3, "evidence": ["e1a 精通", "e1b 熟练"], "years": None},
        {"name": "MySQL", "category": "hard_skill", "importance": "required",
         "required_level": 4, "evidence": ["m1 调优"], "years": None},
    ], "测试甲")
    jd2 = _jd([
        {"name": "Python", "category": "hard_skill", "importance": "required",
         "required_level": 5, "evidence": ["e2a 深度", "e2b 实践"], "years": None},
        {"name": "MySQL", "category": "hard_skill", "importance": "required",
         "required_level": 4, "evidence": ["m2 索引"], "years": None},
        {"name": "沟通能力", "category": "soft_skill", "importance": "preferred",
         "required_level": 3, "evidence": ["s2 表达"], "years": None},
    ], "测试乙")
    return pid


def _seed_ids() -> dict:
    """fresh 每用例重种；返回 {pid, jd1, jd2}。"""
    pid = _seed_position()
    rows = _q("SELECT jd_id FROM jd_record WHERE position_id=? ORDER BY created_at, jd_id", (pid,))
    return {"pid": pid, "jd1": rows[0]["jd_id"], "jd2": rows[1]["jd_id"]}


def _mark(headers: dict, pid: str, jd_id: str, std_name: str, category: str, text: str,
          reason: str | None = None):
    return client.post(
        f"/api/admin/positions/{pid}/evidence-exclusions",
        json={"jd_id": jd_id, "std_name": std_name, "category": category,
              "text": text, "reason": reason},
        headers=headers,
    )


def _lift(headers: dict, pid: str, jd_id: str, std_name: str, category: str, text: str):
    return client.request(
        "DELETE",
        f"/api/admin/positions/{pid}/evidence-exclusions",
        json={"jd_id": jd_id, "std_name": std_name, "category": category, "text": text},
        headers=headers,
    )


def _aggregate(pid: str) -> str:
    from server.services.aggregate import run_aggregate
    return run_aggregate(pid, trigger_source="manual")


def _latest_model_items(pid: str) -> list[dict]:
    row = _q(
        "SELECT model_json FROM competency_model"
        " WHERE position_id=? ORDER BY version DESC LIMIT 1", (pid,)
    )
    return json.loads(row[0]["model_json"])["items"]


def _item_by_name(items: list[dict], name: str):
    return next((it for it in items if it["std_name"] == name), None)


# ---------- 1) 端点往返 ----------

def test_endpoint_roundtrip(headers):
    s = _seed_ids()
    r = _mark(headers, s["pid"], s["jd1"], "Python", "hard_skill", "e1a 精通", "污染证据")
    assert r.status_code == 200 and r.json()["excluded"] is True, r.text

    rows = _q("SELECT * FROM evidence_exclusion WHERE position_id=?", (s["pid"],))
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "active"
    assert row["reason"] == "污染证据"
    assert row["excluded_by"] and row["excluded_at"]
    assert row["lifted_by"] is None and row["lifted_at"] is None

    r = _lift(headers, s["pid"], s["jd1"], "Python", "hard_skill", "e1a 精通")
    assert r.status_code == 200 and r.json()["excluded"] is False, r.text
    row = _q("SELECT * FROM evidence_exclusion WHERE position_id=?", (s["pid"],))[0]
    assert row["status"] == "lifted"
    assert row["lifted_by"] and row["lifted_at"]  # 留痕，不删行
    _mark_row_count = _q("SELECT COUNT(*) c FROM evidence_exclusion WHERE position_id=?", (s["pid"],))
    assert _mark_row_count[0]["c"] == 1

    # 复活：同键再 mark → active，reason 覆盖（最后写入者胜）
    r = _mark(headers, s["pid"], s["jd1"], "Python", "hard_skill", "e1a 精通", "重新排除")
    assert r.status_code == 200
    row = _q("SELECT * FROM evidence_exclusion WHERE position_id=?", (s["pid"],))[0]
    assert row["status"] == "active" and row["reason"] == "重新排除"

    # 幂等重复 mark
    r = _mark(headers, s["pid"], s["jd1"], "Python", "hard_skill", "e1a 精通", "重新排除")
    assert r.status_code == 200
    assert _q("SELECT COUNT(*) c FROM evidence_exclusion WHERE position_id=?", (s["pid"],))[0]["c"] == 1

    # GET 列表：含 evidence_matched 与 lifted 行
    r = client.get(f"/api/admin/positions/{s['pid']}/evidence-exclusions", headers=headers)
    assert r.status_code == 200
    lst = r.json()
    assert len(lst) == 1
    assert lst[0]["evidence_matched"] is True


# ---------- 2) 目标校验 ----------

def test_endpoint_validation(headers):
    s = _seed_ids()
    other = _seed_ids()  # 另一岗位的 jd

    # 岗位 404
    r = _mark(headers, "pos_nope", s["jd1"], "Python", "hard_skill", "e1a 精通")
    assert r.status_code == 404

    # jd 属他岗 → 400
    r = _mark(headers, s["pid"], other["jd1"], "Python", "hard_skill", "e1a 精通")
    assert r.status_code == 400

    # (std_name, category) 不在该 jd std_items → 400
    r = _mark(headers, s["pid"], s["jd1"], "不存在项", "hard_skill", "e1a 精通")
    assert r.status_code == 400

    # text 不在该项 evidence → 400
    r = _mark(headers, s["pid"], s["jd1"], "Python", "hard_skill", "不存在的摘录")
    assert r.status_code == 400

    # category 非法 → 422
    r = _mark(headers, s["pid"], s["jd1"], "Python", "bad_cat", "e1a 精通")
    assert r.status_code == 422

    # lift 不存在的行 → 404
    r = _lift(headers, s["pid"], s["jd1"], "Python", "hard_skill", "e1a 精通")
    assert r.status_code == 404

    # 非 parsed JD → 400（插一条 imported）
    jd_imp = new_id("jd")
    _exec(
        "INSERT INTO jd_record(jd_id, position_id, job_title, company, source_type,"
        " raw_text, status, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (jd_imp, s["pid"], "导入中", None, "paste", "x", "imported", now_iso()),
    )
    r = _mark(headers, s["pid"], jd_imp, "Python", "hard_skill", "e1a 精通")
    assert r.status_code == 400


# ---------- 3) 部分排除不影响 r/req ----------

def test_partial_exclusion_keeps_occurrence(headers):
    s = _seed_ids()
    # 排除 jd2 Python 的 1/2 条证据
    r = _mark(headers, s["pid"], s["jd2"], "Python", "hard_skill", "e2a 深度", "污染")
    assert r.status_code == 200
    _aggregate(s["pid"])

    items = _latest_model_items(s["pid"])
    py = _item_by_name(items, "Python")
    assert py is not None
    # r 分子仍含两个 JD（total_jds=2 → r=1.0）
    assert py["occurrence"]["r"] == 1.0
    assert py["occurrence"]["req"] == 1.0
    # 快照无被排除文本，其余 3 条在
    texts = [ev["text"] for ev in py["evidence"]]
    assert "e2a 深度" not in texts
    assert texts == ["e1a 精通", "e1b 熟练", "e2b 实践"]
    # LLM#3 prompt 不含被排除文本（jd_living：mock 调用过，因其等级 3/5 冲突）
    mid = _q("SELECT model_id FROM competency_model WHERE position_id=?"
             " ORDER BY version DESC LIMIT 1", (s["pid"],))[0]["model_id"]
    traces = _q("SELECT prompt FROM llm_trace WHERE call_type='aggregate_level'"
                " AND ref_id=?", (mid,))
    assert traces, "Python 等级冲突应走 LLM#3"
    assert all("e2a 深度" not in t["prompt"] for t in traces)


# ---------- 4) 全排除影响 r/req ----------

def test_full_exclusion_drops_jd_from_occurrence(headers):
    s = _seed_ids()
    # 排除 jd2 Python 的全部 2 条证据
    _mark(headers, s["pid"], s["jd2"], "Python", "hard_skill", "e2a 深度", "污染")
    _mark(headers, s["pid"], s["jd2"], "Python", "hard_skill", "e2b 实践", "污染")
    _aggregate(s["pid"])

    items = _latest_model_items(s["pid"])
    py = _item_by_name(items, "Python")
    assert py is not None
    # jd2 整项撤回：r 1.0 → 0.5（分子只剩 jd1；分母 total_jds=2 不变）
    assert py["occurrence"]["r"] == 0.5
    # req 为条件口径（2026-09-07 自带语义）：required JD 数 ÷ 出现 JD 数 = 1/1 = 1.0
    # （jd1 仍出现且 required）；occ=出现 JD 数 → 1
    assert py["occurrence"]["req"] == 1.0
    assert py["occurrence"]["occ"] == 1
    texts = [ev["text"] for ev in py["evidence"]]
    assert texts == ["e1a 精通", "e1b 熟练"]
    # 全排除后等级冲突消失（只剩 jd1 的 Lv3）→ reason 为「各 JD 等级一致」
    assert py["required_level"] == 3


# ---------- 5) 消项 ----------

def test_full_exclusion_removes_item(headers):
    s = _seed_ids()
    # 沟通能力仅在 jd2 出现：排除其唯一证据 → 项从产物消失，Σ 权重仍 = 1
    r = _mark(headers, s["pid"], s["jd2"], "沟通能力", "soft_skill", "s2 表达", "误抽取")
    assert r.status_code == 200
    _aggregate(s["pid"])

    items = _latest_model_items(s["pid"])
    assert _item_by_name(items, "沟通能力") is None
    # hard_skill 7:3 中 soft 全空 → hard 归一为 1.0
    assert abs(sum(it["weight"] for it in items) - 1.0) < 1e-9
    assert {it["category"] for it in items} == {"hard_skill"}


# ---------- 6) lift 恢复 == 基线 ----------

def test_lift_restores_baseline(headers):
    s = _seed_ids()
    _aggregate(s["pid"])
    base = _latest_model_items(s["pid"])

    _mark(headers, s["pid"], s["jd1"], "Python", "hard_skill", "e1a 精通", "污染")
    _mark(headers, s["pid"], s["jd1"], "Python", "hard_skill", "e1b 熟练", "污染")
    _aggregate(s["pid"])
    mid = _latest_model_items(s["pid"])
    assert _item_by_name(mid, "Python")["occurrence"]["r"] == 0.5  # 确认排除确实生效过

    _lift(headers, s["pid"], s["jd1"], "Python", "hard_skill", "e1a 精通")
    _lift(headers, s["pid"], s["jd1"], "Python", "hard_skill", "e1b 熟练")
    _aggregate(s["pid"])
    restored = _latest_model_items(s["pid"])

    stripped = lambda items: [  # noqa: E731
        {**it, "evidence": sorted(ev["text"] for ev in it["evidence"])}
        for it in items
    ]
    assert stripped(restored) == stripped(base)


# ---------- 7) 读侧合并 ----------

def test_get_model_merges_draft_not_confirmed(headers):
    s = _seed_ids()
    _aggregate(s["pid"])
    mid = _q("SELECT model_id FROM competency_model WHERE position_id=?"
             " ORDER BY version DESC LIMIT 1", (s["pid"],))[0]["model_id"]

    _mark(headers, s["pid"], s["jd2"], "Python", "hard_skill", "e2a 深度", "污染")

    # draft：合并 excluded 条目（带留痕字段）
    r = client.get(f"/api/admin/positions/{s['pid']}/model", headers=headers)
    assert r.status_code == 200
    py = _item_by_name(r.json()["model"]["items"], "Python")
    flagged = [ev for ev in py["evidence"] if ev.get("excluded")]
    assert len(flagged) == 1
    assert flagged[0]["text"] == "e2a 深度"
    assert flagged[0]["reason"] == "污染"
    assert flagged[0]["excluded_by"] and flagged[0]["excluded_at"]

    # confirmed：返回入库快照不合并
    _exec("UPDATE competency_model SET status='confirmed', confirmed_by=NULL WHERE model_id=?", (mid,))
    r = client.get(f"/api/admin/positions/{s['pid']}/model", headers=headers)
    assert r.status_code == 200
    py = _item_by_name(r.json()["model"]["items"], "Python")
    assert not any(ev.get("excluded") for ev in py["evidence"])


# ---------- 8) PUT 剥离 ----------

def test_put_strips_excluded_entries(headers):
    s = _seed_ids()
    _aggregate(s["pid"])
    _mark(headers, s["pid"], s["jd2"], "Python", "hard_skill", "e2a 深度", "污染")
    mid = _q("SELECT model_id FROM competency_model WHERE position_id=?"
             " ORDER BY version DESC LIMIT 1", (s["pid"],))[0]["model_id"]

    # GET（含合并 flagged 条目）→ items 原样回 PUT
    r = client.get(f"/api/admin/positions/{s['pid']}/model", headers=headers)
    items = r.json()["model"]["items"]
    assert any(ev.get("excluded") for it in items for ev in it.get("evidence", []))
    r = client.put(f"/api/admin/models/{mid}", json={"items": items}, headers=headers)
    assert r.status_code == 200, r.text

    # 存库双层均不含 excluded 条目
    stored_json = json.loads(
        _q("SELECT model_json FROM competency_model WHERE model_id=?", (mid,))[0]["model_json"]
    )
    assert not any(ev.get("excluded") for it in stored_json["items"] for ev in it.get("evidence", []))
    for row in _q("SELECT evidence_json FROM competency_item WHERE model_id=?", (mid,)):
        assert not any(ev.get("excluded") for ev in json.loads(row["evidence_json"] or "[]"))


# ---------- 9) question_gen 防御过滤 ----------

def test_question_gen_skips_excluded_background(headers):
    s = _seed_ids()
    mid = new_id("cm")
    _exec(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json,"
        " confirmed_by, confirmed_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (mid, s["pid"], 1, "confirmed", json.dumps({
            "position_id": s["pid"], "version": 1,
            "items": [{"std_name": "Python", "category": "hard_skill",
                       "required_level": 3, "importance": "required", "gate": 0}],
        }, ensure_ascii=False), None, None, now_iso()),
    )
    _exec(
        "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
        " importance, weight, years, gate, level_reason, occurrence_json, evidence_json)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("c"), mid, "Python", "hard_skill", 3, "required", 1.0, None, 0, None,
         "{}", json.dumps([
             {"jd_id": "jd_x", "level": 3, "text": "A 被排除背景", "excluded": True},
             {"jd_id": "jd_x", "level": 3, "text": "B 有效背景"},
         ], ensure_ascii=False)),
    )

    from server.services.question_bank import generate_question_bank
    generate_question_bank(s["pid"], mid)

    # question_gen trace 的 ref_id 是 item_id（call_llm_json 以 item_id 留痕）
    item_rows = _q("SELECT item_id FROM competency_item WHERE model_id=?", (mid,))
    assert item_rows, "seed 的 competency_item 应存在"
    iid = item_rows[0]["item_id"]
    traces = _q(
        "SELECT prompt FROM llm_trace WHERE call_type='question_gen'"
        " AND ref_id=? ORDER BY created_at", (iid,))
    assert traces, "应已生成题目 trace"
    all_prompts = "\n".join(t["prompt"] for t in traces)
    assert "B 有效背景" in all_prompts
    assert "A 被排除背景" not in all_prompts
