"""U6 报告状态、接口、发布与版本闭环测试（SSOT §21.1/§20.2.A/§20.3，2026-09-09）。

覆盖：
- 发布语义收紧（§21.1）：body 缺 review_outcome → 422；HUMAN_REVIEW_REQUIRED 缺有效
  outcome → 409；发布事务后 report_json 内复核字段与表列一致；
- 评分批次（§20.2.A）：completed 已评分会话再调 score_session → ValueError；
  in_progress 重复调用行为不变（删旧重打）；scoring_batch_id 全行落库、报告 JSON
  带批次绑定；rubric_version 从题库读真实值（v2）；
- 序列化统一（§21.1）：by-id 与 by-session 返回键一致（report_status/version 等）；
- 后台任务状态契约（§21.1）：generate_report 返回 FAILED dict → 无 TASK_SUCCEEDED
  (step=report) + 有 TASK_FAILED；
- 一致性校验深化（§21.1 ⑧⑨⑩）：引文消息归属、复核原因一致、综合分完整性反向。

全程 LLM_PROVIDER=mock 离线运行；DB 用 conftest 临时库（gsd-test- 前缀）。
运行：cd server && python -m pytest test_publish_chain.py -v
"""
import json
import os
import sys

import pytest

# 必须在 import server 之前设环境变量（config 在 import 时读取）——conftest 已
# setdefault mock 三件套，此处仅保底（同文件级纪律）
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("JWT_SECRET", "test-secret")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import get_conn, init_db  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.report import generate_report  # noqa: E402
from server.services.report_checks import _run_consistency_checks  # noqa: E402

init_db()  # TestClient 不触发 startup，显式建表（幂等）
client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _seed_session(items: list[dict], *, status: str = "completed") -> tuple[str, list[str]]:
    """造 position + model + competency_item + session，返回 (session_id, item_ids)。

    items: list of {std_name, category, importance, weight, ...}（required_level 默认 3，
    gate 默认 0）。不插 question_score——由调用方决定观测形态。
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
        (session_id, uid, pid, mid, 1, status, now, now),
    )
    # 默认一道客观题挂第一个 item（答题形态——answer_key 命中可得 SCORED 行）
    if items:
        qid = new_id("qb")
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
            " difficulty, qtype, stem, answer_key, source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (qid, "position", pid, items[0]["std_name"], items[0]["category"], "easy",
             "objective", "Python 中用什么关键字定义函数？", "def", "human", "active", now),
        )
        aqid = new_id("aq")
        conn.execute(
            "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq,"
            " asked_at, answered_at, created_at) VALUES(?,?,?,?,?,?,?)",
            (aqid, session_id, qid, 1, now, now, now),
        )
        conn.execute(
            "INSERT INTO assessment_message(message_id, session_id, question_id, role, content,"
            " created_at) VALUES(?,?,?,?,?,?)",
            (new_id("msg"), session_id, aqid, "user", "我用 def 关键字定义函数。", now),
        )
    conn.commit()
    conn.close()
    return session_id, item_ids


def _ensure_admin() -> None:
    """测试库首跑造 admin（幂等，照 test_phase5_report.py）。"""
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
    _ensure_admin()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _owner_headers(session_id: str) -> dict:
    """报告所属候选人登录头（种子行 password_hash='hash' 不可用——改成本测试密码）。"""
    from passlib.context import CryptContext

    pwd_ctx = CryptContext(schemes=["bcrypt"])
    conn = get_conn()
    row = conn.execute(
        "SELECT s.user_id, u.username FROM assessment_session s"
        " JOIN user u ON u.user_id=s.user_id WHERE s.session_id=?", (session_id,)
    ).fetchone()
    conn.execute(
        "UPDATE user SET password_hash=? WHERE user_id=?", (pwd_ctx.hash("pw-u6"), row["user_id"])
    )
    conn.commit()
    conn.close()
    r = client.post("/api/auth/login", json={"username": row["username"], "password": "pw-u6"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed_report_row(report_status: str = "READY", review_status: str | None = "NONE",
                     report_json: dict | None = None) -> str:
    """造已评分会话 + report 行（给定状态），返回 report_id。"""
    session_id, _ = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.3},
    ])
    conn = get_conn()
    report_id = new_id("rpt")
    conn.execute(
        "INSERT INTO report(report_id, session_id, total_score, gate_passed, report_json,"
        " report_status, review_status, version, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (report_id, session_id, 0.0, 1,
         json.dumps(report_json if report_json is not None else {}, ensure_ascii=False),
         report_status, review_status, 1, now_iso()),
    )
    conn.commit()
    conn.close()
    return report_id


# ============ 任务 2：发布语义收紧（§21.1） ============

def test_publish_missing_outcome_422():
    """body 缺 review_outcome → 422（Pydantic 必填——免审直通默认值已作废）。"""
    headers = _admin_headers()
    report_id = _seed_report_row("READY", "NONE")
    r = client.post(f"/api/admin/reports/{report_id}/publish", headers=headers, json={})
    assert r.status_code == 422, f"缺 review_outcome 应 422，实得 {r.status_code}: {r.text}"
    # 缺 review_note 同为 422（发布须有理由记录）
    r = client.post(f"/api/admin/reports/{report_id}/publish", headers=headers,
                    json={"review_outcome": "CONFIRMED"})
    assert r.status_code == 422, r.text
    # 空白 note 同样拦（min_length=1）
    r = client.post(f"/api/admin/reports/{report_id}/publish", headers=headers,
                    json={"review_outcome": "CONFIRMED", "review_note": "  "})
    assert r.status_code == 422, r.text


def test_publish_ready_with_outcome_200_and_json_sync():
    """READY 报告带合法 outcome → 200 PUBLISHED；发布事务后 report_json 内复核字段与
    表列一致（§21.1 接口一致性：JSON 与表列不得一处新一处旧）。"""
    headers = _admin_headers()
    report_id = _seed_report_row(
        "READY", "NONE", report_json={"report_id": "kept", "total_score": 70.0})
    r = client.post(f"/api/admin/reports/{report_id}/publish", headers=headers,
                    json={"review_outcome": "CONFIRMED", "review_note": "复核通过"})
    assert r.status_code == 200, r.text
    row = _q(
        "SELECT report_status, review_status, review_outcome, review_note, reviewed_at,"
        " report_json FROM report WHERE report_id=?", (report_id,))[0]
    assert row["report_status"] == "PUBLISHED"
    assert row["review_status"] == "CONFIRMED"
    assert row["review_outcome"] == "CONFIRMED"
    assert row["review_note"] == "复核通过"
    # JSON 内复核字段与表列一致（同步更新——不是 JSON 旧值 0/空）
    data = json.loads(row["report_json"])
    assert data["review_outcome"] == "CONFIRMED"
    assert data["review_note"] == "复核通过"
    assert data["reviewed_at"] == row["reviewed_at"]
    # 原有 JSON 字段保留（发布不破坏快照——只补复核键）
    assert data["report_id"] == "kept" and data["total_score"] == 70.0


def test_publish_hrr_requires_explicit_outcome():
    """HUMAN_REVIEW_REQUIRED 报告：缺 outcome 422（必填前端拦）、未知枚举值 409
    「需明确复核结果」；合法枚举（四值）可发布。"""
    headers = _admin_headers()
    # 未知枚举值 → 409（枚举集外——缺省已由 Pydantic 422，此处为「明确但非法」形态）
    report_id = _seed_report_row("PROVISIONAL", "HUMAN_REVIEW_REQUIRED")
    r = client.post(f"/api/admin/reports/{report_id}/publish", headers=headers,
                    json={"review_outcome": "REQUIRED", "review_note": "x"})
    assert r.status_code == 409, f"未知 outcome 应 409，实得 {r.status_code}"
    # 合法枚举：HRR 报告带 UPHELD/PARTIAL/CORRECTED/CONFIRMED 均可发（维持原判/纠正后发布）
    for outcome in ("CONFIRMED", "UPHELD", "PARTIAL", "CORRECTED"):
        rid = _seed_report_row("PROVISIONAL", "HUMAN_REVIEW_REQUIRED")
        r = client.post(f"/api/admin/reports/{rid}/publish", headers=headers,
                        json={"review_outcome": outcome, "review_note": "复核理由"})
        assert r.status_code == 200, f"{outcome} 应可发布，实得 {r.status_code}: {r.text}"


def test_publish_generating_failed_states_rejected():
    """非可发布状态（GENERATING/FAILED/PUBLISHED）→ 409（既有状态机护栏不变）。"""
    headers = _admin_headers()
    for st in ("GENERATING", "FAILED"):
        rid = _seed_report_row(st, "NONE")
        r = client.post(f"/api/admin/reports/{rid}/publish", headers=headers,
                        json={"review_outcome": "CONFIRMED", "review_note": "x"})
        assert r.status_code == 409, f"{st} 不可发布应 409，实得 {r.status_code}"
    # PUBLISHED 已发布 → 409
    rid = _seed_report_row("PUBLISHED", "CONFIRMED")
    r = client.post(f"/api/admin/reports/{rid}/publish", headers=headers,
                    json={"review_outcome": "CONFIRMED", "review_note": "x"})
    assert r.status_code == 409


# ============ 任务 1：评分批次（§20.2.A） ============

def test_completed_scored_session_rejects_rescoring():
    """已完成且有评分行的会话再次调用 score_session → ValueError（历史证据链保护——
    DELETE+重插作废），即使 allow_completed=True（服务端串行链口径）。"""
    from server.services.scoring import score_session

    session_id, _ = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.3},
    ])
    # 首次评分（completed 内部链口径——未评分即 completed 的首次链）
    out = score_session(session_id, allow_completed=True)
    assert out["scoring_batch_id"], "评分结果应带批次 id"
    # 已评分的 completed 会话重调 → 拒绝（双口径：显式 + 串行链豁免）
    with pytest.raises(ValueError, match="管理员修订流程"):
        score_session(session_id, allow_completed=True)
    with pytest.raises(ValueError):
        score_session(session_id)


def test_in_progress_rescoring_semantics_unchanged():
    """进行中会话重复调用维持幂等删旧重打（现行语义——评分尚未终态化不算历史证据）；
    每次调用新批次 id（行级 batch id 全量覆盖）。"""
    from server.services.scoring import score_session

    session_id, _ = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.3},
    ], status="in_progress")
    out1 = score_session(session_id)
    out2 = score_session(session_id)
    assert out1["scoring_batch_id"] != out2["scoring_batch_id"], "两次调用应为不同批次"
    # 幂等删旧重打：不叠加（同题一行，新批次覆盖）
    rows = _q("SELECT scoring_batch_id FROM question_score WHERE session_id=?", (session_id,))
    assert len(rows) == 1, f"删旧重打后应 1 行，实得 {len(rows)}"
    assert rows[0]["scoring_batch_id"] == out2["scoring_batch_id"]


def test_scoring_batch_id_and_rubric_version_persisted():
    """INSERT 全行携带 scoring_batch_id；rubric_version 从题库行读真实值（v2），
    measurement_target 从题库行读——不再硬编码 'v1' 与空目标。"""
    from server.services.scoring import score_session

    session_id, item_ids = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.3},
    ])
    conn = get_conn()
    # 题库行标真实版本 v2 与测量目标（种子默认无——改为显式测试值）
    conn.execute(
        "UPDATE question_bank SET rubric_version='v2', measurement_target='Python 基础掌握'"
        " WHERE std_name='Python'"
    )
    conn.commit()
    conn.close()
    out = score_session(session_id, allow_completed=True)
    rows = _q(
        "SELECT qs.scoring_batch_id, qs.rubric_version, qs.measurement_target"
        " FROM question_score qs WHERE qs.session_id=?", (session_id,))
    assert rows, "评分行应已落库"
    for r in rows:
        assert r["scoring_batch_id"] == out["scoring_batch_id"], "全行须同批次"
        assert r["rubric_version"] == "v2", f"rubric_version 应读题库真实值 v2，实得 {r['rubric_version']}"
        assert r["measurement_target"] == "Python 基础掌握"


def test_report_json_binds_scoring_batch():
    """generate_report → report_json 记录生成所依据的评分批次（归属一致，§20.2.A）。"""
    from server.services.scoring import score_session

    session_id, item_ids = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "required",
         "weight": 0.3},
    ])
    out = score_session(session_id, allow_completed=True)
    report = generate_report(session_id)
    assert report["report_status"] in ("READY", "PROVISIONAL")
    assert report["scoring_batch_id"] == out["scoring_batch_id"], "报告 JSON 应绑定评分批次"
    # DB 层：report 行的 report_json 同步携带
    row = _q("SELECT report_json FROM report WHERE session_id=?"
             " ORDER BY created_at DESC LIMIT 1", (session_id,))[0]
    assert json.loads(row["report_json"])["scoring_batch_id"] == out["scoring_batch_id"]


def test_report_review_request_reason_written():
    """生成时 review_status=HUMAN_REVIEW_REQUIRED → report 行 review_request_reason 落
    归类原因（UNMEASURED_RATIO_HIGH 场景）；报告读回透传（by-session）。"""
    from server.services.scoring import score_session

    # 单 item scope：0 观测（def 命中 Python 客观题——1/1 观测 → 比例 0）→ 需造
    # 大比例未测：10 项仅 1 观测（0.9 > 0.2）→ UNMEASURED_RATIO_HIGH
    items = [{"std_name": "Python", "category": "hard_skill",
              "importance": "preferred", "weight": 0.3}]
    for i in range(9):
        items.append({"std_name": f"未测能力{i}", "category": "hard_skill",
                      "importance": "plus", "weight": 0.05})
    session_id, _ = _seed_session(items)
    score_session(session_id, allow_completed=True)
    report = generate_report(session_id)
    assert report["review_reason_code"] == "UNMEASURED_RATIO_HIGH"
    row = _q("SELECT review_request_reason, report_status FROM report WHERE session_id=?"
             " ORDER BY created_at DESC LIMIT 1", (session_id,))[0]
    assert row["review_request_reason"], "HRR 报告须落复核原因"
    assert "UNMEASURED_RATIO_HIGH" in row["review_request_reason"]
    assert row["report_status"] == "PROVISIONAL"
    # 报告读回透传（序列化统一出口）
    headers = _owner_headers(session_id)
    r = client.get(f"/api/assessment/reports/by-session/{session_id}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["review_request_reason"] == row["review_request_reason"]


# ============ 任务 3：序列化统一（§21.1） ============

def test_by_id_and_by_session_serialization_consistent():
    """by-id 与 by-session 同一报告返回键一致：report_status/version/review_status/
    review_request_reason 均在（生命周期元数据不漂移）。"""
    from server.services.scoring import score_session

    session_id, _ = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "preferred",
         "weight": 0.5},
        {"std_name": "未测能力", "category": "soft_skill", "importance": "plus", "weight": 0.1},
    ])
    score_session(session_id, allow_completed=True)
    report = generate_report(session_id)
    report_id = report["report_id"]
    headers = _owner_headers(session_id)

    r_by_id = client.get(f"/api/assessment/reports/{report_id}", headers=headers)
    assert r_by_id.status_code == 200, r_by_id.text
    r_by_sess = client.get(f"/api/assessment/reports/by-session/{session_id}", headers=headers)
    assert r_by_sess.status_code == 200, r_by_sess.text
    by_id, by_sess = r_by_id.json(), r_by_sess.json()
    # by-id 不再是裸 report_json——生命周期键全部在位（两接口键集一致）
    assert by_id == by_sess, f"两接口序列化应一致，差异键 {set(by_id) ^ set(by_sess)}"
    for key in ("report_status", "version", "review_status", "review_request_reason"):
        assert key in by_id, f"by-id 应含 {key}"
    assert by_id["report_status"] == report["report_status"]
    assert by_id["version"] == report["version"]
    assert by_id["report_id"] == report_id


# ============ 任务 4：后台任务状态契约（§21.1） ============

def test_run_report_task_failed_dict_no_success_event(monkeypatch):
    """generate_report 返回 FAILED dict（不抛异常）→ 无 TASK_SUCCEEDED(step=report)、
    有 TASK_FAILED（payload 带 error 摘要）——事件状态与真实报告状态不得矛盾。"""
    from server.api import assessment as assessment_mod

    session_id, _ = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "preferred", "weight": 0.3},
    ])

    def _fake_generate(sid):
        return {"report_id": "rpt_x", "session_id": sid, "report_status": "FAILED",
                "error": "校验失败：总分不可重算"}

    monkeypatch.setattr(assessment_mod, "generate_report", _fake_generate)
    assessment_mod._run_report_task(session_id)
    events = _q("SELECT event_type, payload_json FROM assessment_state_event"
                " WHERE session_id=? ORDER BY sequence_no", (session_id,))
    types = [e["event_type"] for e in events]
    # 评分子步照常成功（真实链先评分后报告）
    assert "TASK_SUCCEEDED" in types and any(
        json.loads(e["payload_json"]).get("step") == "score"
        for e in events if e["event_type"] == "TASK_SUCCEEDED"), events
    # 报告子步：FAILED 返回值 → 无 step=report 的成功事件；有 TASK_FAILED
    assert not any(
        e["event_type"] == "TASK_SUCCEEDED" and json.loads(e["payload_json"] or "{}").get("step") == "report"
        for e in events), f"FAILED 报告不得记 TASK_SUCCEEDED(step=report)，实得 {events}"
    failed = [e for e in events if e["event_type"] == "TASK_FAILED"]
    assert failed, "应有 TASK_FAILED 事件"
    assert "校验失败" in (failed[0]["payload_json"] or "")


def test_run_report_task_skips_completed_scored_session(monkeypatch):
    """重试链（FAILED 重入 / 超龄接管）：已评分 completed 会话 → 评分子步跳过
    （无 TASK_SUCCEEDED(step=score)、无删旧重打），报告子步照常以既有评分行生成。"""
    from server.api import assessment as assessment_mod
    from server.services.scoring import score_session

    session_id, _ = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "preferred", "weight": 0.3},
    ])
    first = score_session(session_id, allow_completed=True)

    assessment_mod._run_report_task(session_id)
    rows = _q("SELECT scoring_batch_id FROM question_score WHERE session_id=?", (session_id,))
    assert all(r["scoring_batch_id"] == first["scoring_batch_id"] for r in rows), \
        "已评分会话重入串行链不得换批次（审计链保护）"
    events = _q("SELECT event_type, payload_json FROM assessment_state_event"
                " WHERE session_id=? ORDER BY sequence_no", (session_id,))
    score_success = [e for e in events if e["event_type"] == "TASK_SUCCEEDED"
                     and json.loads(e["payload_json"] or "{}").get("step") == "score"]
    assert not score_success, "跳过评分子步不应记 TASK_SUCCEEDED(step=score)"
    report_success = [e for e in events if e["event_type"] == "TASK_SUCCEEDED"
                      and json.loads(e["payload_json"] or "{}").get("step") == "report"]
    assert report_success, "报告子步应照常成功（既有评分行生成）"


# ============ 任务 5：一致性校验深化（§21.1 ⑧⑨⑩） ============

def test_check_evidence_span_ownership():
    """⑧ 引文消息归属：span source_message_id 属于本 session → 过；跨 session → 报错；
    quote_hash-only（None）降级形态合法。"""
    session_id, _ = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "preferred", "weight": 0.3},
    ])
    conn = get_conn()
    my_msg = conn.execute(
        "SELECT message_id FROM assessment_message WHERE session_id=?", (session_id,)
    ).fetchone()["message_id"]

    # 正例：本 session 消息 + quote_hash-only → 无错
    conn.execute(
        "INSERT INTO question_score(score_id, session_id, item_id, evidence_spans_json,"
        " created_at) VALUES(?,?,?,?,?)",
        (new_id("qs"), session_id,
         conn.execute("SELECT item_id FROM competency_item LIMIT 1").fetchone()["item_id"],
         json.dumps([{"source_message_id": my_msg, "start_offset": 0, "end_offset": 3},
                     {"quote_hash": "x", "source_message_id": None}]),
         now_iso()),
    )
    conn.commit()
    conn.close()
    clean_agg = {"item_scores": [{"weight": 0.3}], "total_score": None,
                 "missing_warnings": []}
    assert _run_consistency_checks(clean_agg, session_id) == []

    # 反例：另一个 session 的消息 → 报错
    other_sid, _ = _seed_session([
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "preferred", "weight": 0.2},
    ])
    conn = get_conn()
    other_msg = conn.execute(
        "SELECT message_id FROM assessment_message WHERE session_id=?", (other_sid,)
    ).fetchone()["message_id"]
    item_id = conn.execute(
        "SELECT item_id FROM competency_item WHERE model_id=("
        " SELECT model_id FROM assessment_session WHERE session_id=?) LIMIT 1",
        (session_id,)).fetchone()["item_id"]
    conn.execute(
        "INSERT INTO question_score(score_id, session_id, item_id, evidence_spans_json,"
        " created_at) VALUES(?,?,?,?,?)",
        (new_id("qs"), session_id, item_id,
         json.dumps([{"source_message_id": other_msg, "start_offset": 0, "end_offset": 3}]),
         now_iso()),
    )
    conn.commit()
    conn.close()
    errors = _run_consistency_checks(clean_agg, session_id)
    assert any("source_message_id" in e for e in errors), errors

    # 整链：generate_report → FAILED 行（校验失败照旧 FAILED 路径）
    report = generate_report(session_id)
    assert report["report_status"] == "FAILED"


def test_check_review_reason_consistency():
    """⑨ 复核原因一致：HRR 但 reason 空 → 报错；UNMEASURED_RATIO_HIGH 但比例未超阈
    → 报错；reason 齐 + 比例真超 → 过。"""
    session_id, _ = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "preferred", "weight": 0.3},
    ])
    base = {"item_scores": [{"weight": 0.3}], "total_score": None, "missing_warnings": [],
            "review_status": None, "provisional": False, "observation_status": None,
            "review_reason_code": None, "unmeasured_ratio": 0.0}

    # 反例 1：HRR 但 review_request_reason 空
    bad1 = {**base, "review_status": "HUMAN_REVIEW_REQUIRED", "provisional": True}
    errors = _run_consistency_checks(bad1, session_id, review_request_reason=None)
    assert any("review_request_reason 为空" in e for e in errors), errors

    # 反例 2：reason_code 与比例不自洽（code 在但比例 ≤ 阈值）
    bad2 = {**base, "review_reason_code": "UNMEASURED_RATIO_HIGH", "unmeasured_ratio": 0.1}
    errors = _run_consistency_checks(bad2, session_id, review_request_reason="x")
    assert any("未超阈值" in e for e in errors), errors

    # 正例：HRR + reason 齐 + 比例真超阈（无综合分契约全链自洽）
    good = {**base, "review_status": "HUMAN_REVIEW_REQUIRED", "provisional": True,
            "review_reason_code": "UNMEASURED_RATIO_HIGH", "unmeasured_ratio": 0.9,
            "total_score": None}
    assert _run_consistency_checks(good, session_id,
                                   review_request_reason="UNMEASURED_RATIO_HIGH：超阈") == []


def test_check_total_score_integrity():
    """⑩ 综合分仅完整性满足时存在（反向）：total_score 非 None 但 unmeasured_ratio
    超阈 → 报错；比例未超阈有总分 → 过。"""
    session_id, _ = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "preferred", "weight": 0.3},
    ])
    base = {"item_scores": [{"weight": 0.3, "score": 45.0}], "total_score": 45.0,
            "missing_warnings": [], "review_status": None, "provisional": False,
            "observation_status": None, "review_reason_code": None}

    # 反例：有总分但比例超阈（门控被绕过形态）
    bad = {**base, "unmeasured_ratio": 0.9}
    errors = _run_consistency_checks(bad, session_id)
    assert any("无综合分契约被绕过" in e for e in errors), errors

    # 正例：有总分且比例未超阈
    good = {**base, "unmeasured_ratio": 0.1}
    assert _run_consistency_checks(good, session_id) == []
