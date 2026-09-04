"""报告生成（07 文档 §10.5 五段式 + §10.6 优劣文字段）。

①总分+门槛标签 ②雷达图 required vs actual ③逐项明细表 ④优劣文字段（LLM）⑤逐题回顾。
生成走异步任务（API 层 BackgroundTasks），结果整段 JSON 落 report 表（report_json）。
"""
import json

from ..db import get_conn
from .aggregation import aggregate_session_scores
from .llm import call_llm_json
from .pipeline import new_id, now_iso
from .prompts.report import REPORT_SYSTEM, report_prompt


def _mock_report(system_prompt: str, user_prompt: str) -> dict:
    """离线 mock：从 user prompt 中抽取优势/短板 std_name，模板化输出。"""
    try:
        # user_prompt 中含 JSON 段：优势项/短板项
        lines = user_prompt.splitlines()
        strengths_line = next(ln for ln in lines if ln.startswith("优势项："))
        weaknesses_line = next(ln for ln in lines if ln.startswith("短板项："))
        strengths = json.loads(strengths_line[len("优势项："):])
        weaknesses = json.loads(weaknesses_line[len("短板项："):])
    except (StopIteration, json.JSONDecodeError):
        strengths, weaknesses = [], []
    s_names = "、".join(s.get("std_name", "") for s in strengths) or "（无明显优势项）"
    w_names = "、".join(w.get("std_name", "") for w in weaknesses) or "（无明显短板项）"
    return {
        "strengths_text": f"您在{s_names}方面表现优秀。",
        "weaknesses_text": f"您在{w_names}方面存在不足。",
        "suggestions_text": f"建议您加强{w_names}的学习，可以参考相关文档。",
    }


def _load_question_reviews(session_id: str) -> list[dict]:
    """逐题回顾：题面/回答/双分/证据/理由（07 §10.5 第⑤段）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT qs.question_id, qs.score_live, qs.score_final, qs.score_state,"
        " qs.evidence_quote, qs.reason,"
        " b.stem, b.qtype, b.std_name, b.category"
        " FROM question_score qs"
        " JOIN assessment_question aq ON aq.question_id=qs.question_id"
        " JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE qs.session_id=? ORDER BY aq.seq",
        (session_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        # 捞该题候选人回答（raw_hash 回捞原文，同 scoring 逻辑）
        ans_rows = conn.execute(
            "SELECT content, raw_hash FROM assessment_message"
            " WHERE session_id=? AND question_id=? AND role='user'"
            " ORDER BY created_at, rowid",
            (session_id, d["question_id"]),
        ).fetchall()
        parts = []
        for ar in ans_rows:
            if ar["raw_hash"]:
                raw = conn.execute(
                    "SELECT full_text FROM context_raw WHERE hash=?", (ar["raw_hash"],)
                ).fetchone()
                parts.append(raw["full_text"] if raw else ar["content"])
            else:
                parts.append(ar["content"])
        d["answer"] = "\n".join(parts)
        out.append(d)
    return out


def _collect_evidence_quotes(session_id: str, item_ids: list[str]) -> dict:
    """item_id → [evidence_quote]，供 P-report 绑证据约束（07 §10.6）。"""
    if not item_ids:
        return {}
    conn = get_conn()
    placeholders = ",".join("?" * len(item_ids))
    rows = conn.execute(
        f"SELECT item_id, evidence_quote FROM question_score"
        f" WHERE session_id=? AND item_id IN ({placeholders}) AND evidence_quote IS NOT NULL",
        (session_id, *item_ids),
    ).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["item_id"], []).append(r["evidence_quote"])
    return out


def generate_report(session_id: str) -> dict:
    """生成报告（幂等：同会话重复生成覆盖旧行）。返回完整报告 dict（含 report_id）。"""
    conn = get_conn()
    s = conn.execute(
        "SELECT s.session_id, p.name AS position_name FROM assessment_session s"
        " JOIN position p ON p.position_id=s.position_id WHERE s.session_id=?",
        (session_id,),
    ).fetchone()
    if s is None:
        raise ValueError(f"会话不存在: {session_id}")

    agg = aggregate_session_scores(session_id)
    question_reviews = _load_question_reviews(session_id)

    # 雷达图数据（ECharts）：required vs actual，按 item 顺序对齐；gate/无数据项跳过
    radar_items = [it for it in agg["item_scores"]
                   if not it.get("gate") and it.get("actual_level") is not None]
    radar_data = {
        "indicators": [
            {"name": it["std_name"], "max": 5} for it in radar_items
        ],
        "required": [it["required_level"] or 0 for it in radar_items],
        "actual": [it["actual_level"] for it in radar_items],
    }

    gate_passed = all(g["passed"] for g in agg["gate_items"]) if agg["gate_items"] else True

    # LLM 生成优劣/建议文字（绑证据）
    item_ids = [s["item_id"] for s in agg["strengths"]] + [w["item_id"] for w in agg["weaknesses"]]
    evidence_quotes = _collect_evidence_quotes(session_id, item_ids)
    llm_out = call_llm_json(
        "report", session_id, REPORT_SYSTEM,
        report_prompt(s["position_name"], agg["strengths"], agg["weaknesses"], evidence_quotes),
        mock_fn=_mock_report,
    )

    report_id = new_id("rpt")
    report_data = {
        "report_id": report_id,
        "session_id": session_id,
        "position_name": s["position_name"],
        "total_score": agg["total_score"],
        "gate_passed": gate_passed,
        "gate_details": agg["gate_items"],
        "radar_data": radar_data,
        "item_details": agg["item_scores"],
        "strengths": agg["strengths"],
        "weaknesses": agg["weaknesses"],
        "strengths_text": llm_out.get("strengths_text", ""),
        "weaknesses_text": llm_out.get("weaknesses_text", ""),
        "suggestions_text": llm_out.get("suggestions_text", ""),
        "question_reviews": question_reviews,
        "created_at": now_iso(),
    }

    # 幂等：同会话只留最新一份
    conn.execute("DELETE FROM report WHERE session_id=?", (session_id,))
    conn.execute(
        "INSERT INTO report(report_id, session_id, total_score, gate_passed, report_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (report_id, session_id, agg["total_score"], int(gate_passed),
         json.dumps(report_data, ensure_ascii=False), report_data["created_at"]),
    )
    conn.commit()
    return report_data
