"""报告生成（07 文档 §10.5 五段式 + §10.6 优劣文字段）+ 状态机/版本化（SSOT §21.1）。

①总分+门槛标签 ②雷达图 required vs actual ③逐项明细表 ④优劣文字段（LLM）⑤逐题回顾。
生成走异步任务（API 层 BackgroundTasks），结果整段 JSON 落 report 表（report_json）。

状态机（D-025/T-05-09）：聚合后先跑七项一致性校验（任一失败 → report_status='FAILED'
行，不生成正常报告）；通过则版本化 INSERT（不再 DELETE 覆盖旧行，feedback FK 不悬空），
report_status = PROVISIONAL（provisional 或 HUMAN_REVIEW_REQUIRED）否则 READY。落 report
行后写 report→trace 运行时 trace_link 写点（reported/source，闭合 D-56 五要素）。
"""
import json

from ..db import get_conn
from .aggregation import aggregate_session_scores
from .llm import call_llm_json
from .pipeline import new_id, now_iso
from .prompts.report import REPORT_SYSTEM, report_prompt
from .report_checks import _run_consistency_checks
from .trace_link import link_entity

# 报告状态机枚举（N11：代码校验，无 DB CHECK；D-025）
REPORT_STATUSES = ("GENERATING", "PROVISIONAL", "READY", "PUBLISHED", "FAILED")
# 复核状态枚举（D-60 六值并集：§21.1 五值 + HUMAN_REVIEW_REQUIRED）
REVIEW_STATUSES = ("NONE", "REQUIRED", "IN_PROGRESS", "CONFIRMED", "CLOSED", "HUMAN_REVIEW_REQUIRED")

# 合法迁移图（T-05-09）：终态 PUBLISHED/FAILED 无出边；非终态均可 → FAILED
_REPORT_TRANSITIONS = {
    "GENERATING": ("PROVISIONAL", "READY", "FAILED"),
    "PROVISIONAL": ("PUBLISHED", "FAILED"),
    "READY": ("PUBLISHED", "FAILED"),
    "PUBLISHED": (),
    "FAILED": (),
}


def _assert_report_status(s: str) -> None:
    """report_status 枚举校验：非法值 raise ValueError（T-05-09）。"""
    if s not in REPORT_STATUSES:
        raise ValueError(f"非法 report_status: {s}（允许 {', '.join(REPORT_STATUSES)}）")


def _assert_report_transition(from_state: str, to_state: str) -> None:
    """迁移合法性校验：非法迁移 raise ValueError。"""
    _assert_report_status(from_state)
    _assert_report_status(to_state)
    if to_state not in _REPORT_TRANSITIONS.get(from_state, ()):
        raise ValueError(f"非法 report_status 迁移: {from_state} → {to_state}")


def _insert_report_row(conn, session_id: str, *, status: str, report_json: dict,
                       review_status: str | None = None, total_score: float = 0.0,
                       gate_passed: int = 0, report_id: str | None = None) -> str:
    """写终态 report 行：优先把 GENERATING 占位行原地转终态（复用版本，不残留占位行），
    无占位则版本化 INSERT。返回 report_id。发布字段本计划置 NULL。"""
    _assert_report_status(status)
    if report_id is None:
        report_id = new_id("rpt")
    placeholder = conn.execute(
        "SELECT report_id FROM report WHERE session_id=? AND report_status='GENERATING'"
        " ORDER BY created_at DESC, version DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if placeholder is not None:
        conn.execute(
            "UPDATE report SET report_id=?, total_score=?, gate_passed=?, report_json=?,"
            " report_status=?, review_status=?, created_at=?"
            " WHERE report_id=? AND report_status='GENERATING'",
            (report_id, total_score, gate_passed,
             json.dumps(report_json, ensure_ascii=False), status, review_status, now_iso(),
             placeholder["report_id"]),
        )
        return report_id
    version = 1 + (conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM report WHERE session_id=?", (session_id,)
    ).fetchone()[0] or 0)
    conn.execute(
        "INSERT INTO report(report_id, session_id, total_score, gate_passed, report_json,"
        " report_status, review_status, version, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (report_id, session_id, total_score, gate_passed,
         json.dumps(report_json, ensure_ascii=False), status, review_status, version, now_iso()),
    )
    return report_id


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
        "SELECT qs.item_id, qs.question_id, qs.score_live, qs.score_final, qs.score_state,"
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
    """生成报告（版本化：同会话重复生成追加新版本行，不覆盖旧行——REF-5.9 SC-3）。

    流程：聚合 → 七项一致性校验（任一失败 → report_status='FAILED' 行，不生成正常
    报告）→ 版本化 INSERT（version = session 内 MAX+1）→ report→trace trace_link 写点。
    返回 report_data 附加 report_status/version 键。
    """
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
        "indicators": [{"name": it["std_name"], "max": 5} for it in radar_items],
        "required": [it["required_level"] or 0 for it in radar_items],
        "actual": [it["actual_level"] for it in radar_items],
    }

    gate_passed = all(g["passed"] for g in agg["gate_items"]) if agg["gate_items"] else True

    # LLM 生成优劣/建议文字（绑证据）；trace_out 拿 report LLM 调 trace_id（供 trace_link）
    item_ids = [s["item_id"] for s in agg["strengths"]] + [w["item_id"] for w in agg["weaknesses"]]
    evidence_quotes = _collect_evidence_quotes(session_id, item_ids)
    trace_out: list[str] = []
    llm_out = call_llm_json(
        "report", session_id, REPORT_SYSTEM,
        report_prompt(s["position_name"], agg["strengths"], agg["weaknesses"], evidence_quotes),
        mock_fn=_mock_report,
        trace_out=trace_out,
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
        "item_details": [
            {**it, "score": round(it.get("score") or 0.0, 2)}
            for it in agg["item_scores"]
        ],
        "strengths": agg["strengths"],
        "weaknesses": agg["weaknesses"],
        "strengths_text": llm_out.get("strengths_text", ""),
        "weaknesses_text": llm_out.get("weaknesses_text", ""),
        "suggestions_text": llm_out.get("suggestions_text", ""),
        "question_reviews": question_reviews,
        "review_status": agg.get("review_status"),
        "observation_status": agg.get("observation_status"),
        "provisional": agg.get("provisional", False),
        "coverage": agg.get("coverage", {}),
        "created_at": now_iso(),
    }

    # 七项一致性校验（聚合后、版本化 INSERT 前）；⑦ 需 report_data 全文，故组装后跑
    errors = _run_consistency_checks(
        agg, session_id, report_text=json.dumps(report_data, ensure_ascii=False)
    )
    if errors:
        _insert_report_row(
            conn, session_id, status="FAILED",
            report_json={"error": "; ".join(errors)[:200]},
            review_status=agg.get("review_status"), report_id=report_id,
        )
        conn.commit()
        return {"report_id": report_id, "session_id": session_id,
                "report_status": "FAILED", "error": "; ".join(errors)[:200]}

    # 状态机推进：provisional 或 HUMAN_REVIEW_REQUIRED → PROVISIONAL，否则 READY
    report_status = "PROVISIONAL" if (
        agg.get("provisional") or agg.get("review_status") == "HUMAN_REVIEW_REQUIRED"
    ) else "READY"

    _insert_report_row(
        conn, session_id, status=report_status,
        review_status=agg.get("review_status"),
        total_score=agg["total_score"], gate_passed=int(gate_passed),
        report_json=report_data, report_id=report_id,
    )

    # report→trace 运行时 trace_link 写点（D-56 闭合五要素审计链）
    if trace_out:
        link_entity(conn, trace_id=trace_out[0], entity_type="report",
                    entity_id=report_id, link_role="reported")
        link_entity(conn, trace_id=trace_out[0], entity_type="assessment_session",
                    entity_id=session_id, link_role="source")

    conn.commit()
    report_data["report_status"] = report_status
    report_data["version"] = conn.execute(
        "SELECT version FROM report WHERE report_id=?", (report_id,)
    ).fetchone()[0]
    return report_data
