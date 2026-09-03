"""M6 后端测试：打分（双分合成）+ 聚合 + 报告生成（mock 模式，离线可跑）。

运行: cd server && python test_m6_backend.py
"""
import json
import os
import sys
import tempfile

# 隔离测试库：必须在 import server 模块前设置
_tmpdir = tempfile.mkdtemp(prefix="m6_test_")
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test.db")
os.environ["LLM_PROVIDER"] = "mock"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 仓库根

from server.db import get_conn, init_db  # noqa: E402
from server.services.aggregation import aggregate_session_scores  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.report import generate_report  # noqa: E402
from server.services.scoring import score_question, score_session  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def _seed_full_chain() -> dict:
    """造一条完整链：岗位 + confirmed 模型（4 项）+ 题库 + 会话 + 答题 + score_live。

    模型设计（覆盖双分合成 + 优势/短板 + 门槛）：
    - Python(hard, Lv4, w=0.19)：1 客观 + 1 主观
    - 沟通能力(soft, Lv3, w=0.12)：1 主观
    - 后端开发经验(exp, years=3, w=0.08, gate=1)：走表单
    - 本科学历(qual, w=0.01, gate=1)：走表单
    """
    conn = get_conn()
    pid, mid, uid, sid = new_id("pos"), new_id("m"), new_id("u"), new_id("sess")
    now = now_iso()

    conn.execute("INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
                 (pid, "后端开发工程师", "active", now))
    conn.execute("INSERT INTO user(user_id, username, password_hash, role, created_at)"
                 " VALUES(?,?,?,?,?)", (uid, "cand_m6", "x", "candidate", now))

    items = [
        {"item_id": new_id("c"), "std_name": "Python", "category": "hard_skill",
         "required_level": 4, "weight": 0.19, "gate": 0, "years": None},
        {"item_id": new_id("c"), "std_name": "沟通能力", "category": "soft_skill",
         "required_level": 3, "weight": 0.12, "gate": 0, "years": None},
        {"item_id": new_id("c"), "std_name": "后端开发经验", "category": "experience",
         "required_level": None, "weight": 0.08, "gate": 1, "years": 3},
        {"item_id": new_id("c"), "std_name": "本科学历", "category": "qualification",
         "required_level": None, "weight": 0.01, "gate": 1, "years": None},
    ]
    model_json = {"items": [{k: v for k, v in it.items() if k != "item_id"} for it in items]}
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, 1, "confirmed", json.dumps(model_json, ensure_ascii=False), now),
    )
    for it in items:
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, years, gate) VALUES(?,?,?,?,?,?,?,?,?)",
            (it["item_id"], mid, it["std_name"], it["category"], it["required_level"],
             "required", it["weight"], it["years"], it["gate"]),
        )

    # 题库：Python 1 客观 1 主观；沟通 1 主观
    bank = [
        {"qid": new_id("q"), "std_name": "Python", "category": "hard_skill",
         "qtype": "objective", "stem": "Python 中用于数据科学的基础库是？",
         "answer_key": "numpy|pandas|NumPy|Pandas", "rubric": None},
        {"qid": new_id("q"), "std_name": "Python", "category": "hard_skill",
         "qtype": "subjective", "stem": "描述一次用 Python 优化性能的经历。",
         "answer_key": None, "rubric": "结合实例；思路清晰；有结果数据"},
        {"qid": new_id("q"), "std_name": "沟通能力", "category": "soft_skill",
         "qtype": "subjective", "stem": "讲一次跨团队沟通的经历。",
         "answer_key": None, "rubric": "情境/冲突/解法/结果"},
    ]
    for q in bank:
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
            " difficulty, qtype, stem, answer_key, rubric, source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (q["qid"], "position", pid, q["std_name"], q["category"], "medium",
             q["qtype"], q["stem"], q["answer_key"], q["rubric"], "llm_seed", "active", now),
        )

    # 会话 + 选题落 assessment_question
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (sid, uid, pid, mid, 1, "in_progress", now, now),
    )
    aq_ids = []
    for i, q in enumerate(bank, start=1):
        aqid = new_id("aq")
        conn.execute(
            "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq,"
            " asked_at, answered_at, created_at) VALUES(?,?,?,?,?,?,?)",
            (aqid, sid, q["qid"], i, now, now, now),
        )
        aq_ids.append((aqid, q))

    # 答题 + score_live（主观题 mock 给 live=3；客观题 None）
    answers = {
        0: "我用过 numpy 和 pandas 做数据分析。",  # 客观题命中
        1: "在某项目中我用 numpy 向量化把 pandas apply 从 10 分钟压到 30 秒，性能提升 20 倍。",
        2: "推动前端/后端对齐接口规范，组织 3 次评审会，最终落地 OpenAPI 契约。",
    }
    for idx, (aqid, q) in enumerate(aq_ids):
        ans = answers[idx]
        conn.execute(
            "INSERT INTO assessment_message(message_id, session_id, question_id, role, content,"
            " created_at) VALUES(?,?,?,?,?,?)",
            (new_id("msg"), sid, aqid, "user", ans, now),
        )
        score_live = 3 if q["qtype"] == "subjective" else None
        conn.execute(
            "INSERT INTO assessment_message(message_id, session_id, question_id, role, content,"
            " action, score_live, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("msg"), sid, aqid, "assistant", "好的，感谢你的回答。", "next", score_live, now),
        )

    # 表单：经验 5 年（达标）；本科（达标）
    conn.execute(
        "INSERT INTO form_submission(form_id, session_id, user_id, form_type, payload_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (new_id("form"), sid, uid, "resume",
         json.dumps({"years_of_experience": 5, "本科学历": "本科"}, ensure_ascii=False), now),
    )
    conn.commit()
    return {
        "session_id": sid, "position_id": pid, "model_id": mid, "user_id": uid,
        "items": items, "aq_ids": [a for a, _ in aq_ids], "bank": bank,
    }


def _test_dual_scoring(ctx: dict) -> None:
    print("[1] 双分合成（H1）")
    sid = ctx["session_id"]
    # 客观题
    r_obj = score_question(sid, ctx["aq_ids"][0])
    check("客观题命中 answer_key → 5 分", r_obj["score_final"] == 5,
          f"实际 {r_obj['score_final']}")

    # 主观题（mock 给 final=3）
    r_sub = score_question(sid, ctx["aq_ids"][1])
    check("主观题 mock 返回 score_final=3", r_sub["score_final"] == 3,
          f"实际 {r_sub['score_final']}")
    check("主观题返回 evidence_quote+reason",
          bool(r_sub.get("evidence_quote")) and bool(r_sub.get("reason")))

    # 会话级打分
    out = score_session(sid)
    check("score_session 落 3 题", out["scored_count"] == 3, f"实际 {out['scored_count']}")

    conn = get_conn()
    rows = conn.execute(
        "SELECT question_id, score_live, score_final, final_score FROM question_score"
        " WHERE session_id=? ORDER BY question_id",
        (sid,),
    ).fetchall()
    by_qid = {r["question_id"]: dict(r) for r in rows}

    obj = by_qid[ctx["aq_ids"][0]]
    check("客观题 score_live 为 None", obj["score_live"] is None)
    check("客观题 final_score = score_final = 5", obj["final_score"] == 5)

    sub1 = by_qid[ctx["aq_ids"][1]]
    check("主观题 score_live=3", sub1["score_live"] == 3)
    check("主观题 score_final=3 (mock)", sub1["score_final"] == 3)
    check("主观题 final=round(3*0.5+3*0.5)=3", sub1["final_score"] == 3)


def _test_aggregation(ctx: dict) -> None:
    print("[2] 聚合（item 均分 + gap + 权重 + 门槛）")
    agg = aggregate_session_scores(ctx["session_id"])

    by_name = {it["std_name"]: it for it in agg["item_scores"]}
    py = by_name["Python"]
    # Python 两题：客观 5 分 + 主观 3 分 → actual = 4.0
    check("Python actual_level = (5+3)/2 = 4.0", py["actual_level"] == 4.0,
          f"实际 {py['actual_level']}")
    check("Python gap = 4 - 4 = 0", py["gap"] == 0.0, f"实际 {py['gap']}")
    check("Python score = 0.19 * 4/5 * 100 = 15.2", abs(py["score"] - 15.2) < 0.01,
          f"实际 {py['score']}")

    comm = by_name["沟通能力"]
    check("沟通能力 actual=3 gap=0", comm["actual_level"] == 3.0 and comm["gap"] == 0.0)
    check("沟通能力 score = 0.12 * 3/5 * 100 = 7.2", abs(comm["score"] - 7.2) < 0.01)

    exp = by_name["后端开发经验"]
    check("后端经验为门槛项", exp["gate"] is True or exp["gate"] == 1)
    check("后端经验 5 年 ≥ 3 年 → 通过", exp["gate_passed"] is True)
    check("后端经验 score = 0.08 * 100 = 8.0", abs(exp["score"] - 8.0) < 0.01)

    edu = by_name["本科学历"]
    check("本科门槛通过", edu["gate_passed"] is True)
    check("本科 score = 0.01 * 100 = 1.0", abs(edu["score"] - 1.0) < 0.01)

    # 总分 = 15.2 + 7.2 + 8.0 + 1.0 = 31.4
    check("total_score = 31.4", abs(agg["total_score"] - 31.4) < 0.01,
          f"实际 {agg['total_score']}")

    check("strengths 含 Python 和沟通能力（gap≥0）",
          {s["std_name"] for s in agg["strengths"]} == {"Python", "沟通能力"},
          f"实际 {agg['strengths']}")
    check("weaknesses 为空（无 gap<0）", agg["weaknesses"] == [])

    check("gate_items 全通过", all(g["passed"] for g in agg["gate_items"]))


def _test_report(ctx: dict) -> None:
    print("[3] 报告生成（五段式）")
    rpt = generate_report(ctx["session_id"])

    check("report_id 存在", bool(rpt.get("report_id")))
    check("total_score 一致", abs(rpt["total_score"] - 31.4) < 0.01)
    check("gate_passed=True", rpt["gate_passed"] is True)
    check("gate_details 2 条", len(rpt["gate_details"]) == 2)

    radar = rpt["radar_data"]
    check("radar 含 Python/沟通 2 项",
          [i["name"] for i in radar["indicators"]] == ["Python", "沟通能力"])
    check("radar required = [4,3]", radar["required"] == [4, 3])
    check("radar actual = [4.0,3.0]", radar["actual"] == [4.0, 3.0])

    check("strengths_text 包含 Python 与 沟通能力",
          "Python" in rpt["strengths_text"] and "沟通能力" in rpt["strengths_text"])
    check("mock 模式 suggestions_text 非空", bool(rpt["suggestions_text"]))

    check("question_reviews 3 条", len(rpt["question_reviews"]) == 3)
    obj_rev = next(q for q in rpt["question_reviews"] if q["qtype"] == "objective")
    check("逐题回顾含 answer", "numpy" in obj_rev["answer"])
    check("逐题回顾含 score_final", obj_rev["score_final"] == 5)

    # 落库 + 幂等
    conn = get_conn()
    rpt_id_1 = rpt["report_id"]
    rpt2 = generate_report(ctx["session_id"])
    n = conn.execute("SELECT COUNT(*) c FROM report WHERE session_id=?",
                     (ctx["session_id"],)).fetchone()["c"]
    check("重复生成幂等（同会话仅 1 行 report）", n == 1, f"实际 {n}")
    check("重新生成 report_id 更新", rpt2["report_id"] != rpt_id_1)

    # llm_trace 落 'report' 类型
    tr = conn.execute("SELECT COUNT(*) c FROM llm_trace WHERE call_type='report'").fetchone()
    check("P-report 调用落 llm_trace (call_type='report')", tr["c"] >= 1, f"实际 {tr['c']}")


def _test_feedback_api(ctx: dict) -> None:
    print("[4] feedback 表写入")
    from server.api.assessment import submit_feedback
    conn = get_conn()
    rpt_row = conn.execute("SELECT report_id FROM report WHERE session_id=?",
                           (ctx["session_id"],)).fetchone()
    # submit_feedback 新签名（所有权校验）：直调需补传种子用户 dict
    seed_user = {
        "user_id": ctx["user_id"], "username": "cand_m6", "role": "candidate", "is_active": 1,
    }
    result = submit_feedback(
        rpt_row["report_id"],
        {"item_id": ctx["items"][0]["item_id"], "feedback_text": "Python 分给低了"},
        user=seed_user,
    )
    check("返回 feedback_id", bool(result["feedback_id"]))
    check("status=pending", result["status"] == "pending")
    row = conn.execute("SELECT * FROM feedback WHERE feedback_id=?",
                       (result["feedback_id"],)).fetchone()
    check("feedback 落库且 status='pending'",
          row is not None and row["status"] == "pending")


if __name__ == "__main__":
    init_db()
    ctx = _seed_full_chain()
    _test_dual_scoring(ctx)
    _test_aggregation(ctx)
    _test_report(ctx)
    _test_feedback_api(ctx)
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)
