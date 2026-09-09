"""报告生成（07 文档 §10.5 五段式 + §10.6 优劣文字段）+ 状态机/版本化（SSOT §21.1）。

①总分+门槛标签 ②雷达图 required vs actual ③逐项明细表 ④优劣文字段（LLM）⑤逐题回顾。
生成走异步任务（API 层 BackgroundTasks），结果整段 JSON 落 report 表（report_json）。

状态机（D-025/T-05-09）：聚合后先跑七项一致性校验（任一失败 → report_status='FAILED'
行，不生成正常报告）；通过则版本化 INSERT（不再 DELETE 覆盖旧行，feedback FK 不悬空），
report_status = PROVISIONAL（provisional 或 HUMAN_REVIEW_REQUIRED）否则 READY。落 report
行后写 report→trace 运行时 trace_link 写点（reported/source，闭合 D-56 五要素）。
"""
import json

from .. import config
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


def _latest_scoring_batch_id(session_id: str) -> str | None:
    """该会话最新评分批次（SSOT §20.2.A）：CREATE MAX(created_at, rowid) 的批次行。

    rowid 并列兜底同 created_at 的批次间排序（同秒多批极端形态）；无批次行
    （存量会话/测试直插评分行）返回 None——报告照生成（无批次概念的历史形态）。
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT scoring_batch_id FROM question_score"
        " WHERE session_id=? AND scoring_batch_id IS NOT NULL"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return row["scoring_batch_id"] if row else None


def _review_request_reason(agg: dict, session_id: str) -> str | None:
    """复核原因归类文本（SSOT §21.1 复核原因与报告状态一致的校验依据）。

    review_status=HUMAN_REVIEW_REQUIRED 时按触发源归类：
    - review_reason_code=UNMEASURED_RATIO_HIGH → 转可读文本（U4 单列 reason code
      属结构化口径，表列承载人读归类）；
    - observation_status=NO_VALID_OBSERVATION → 无有效观测；
    - required 缺失（覆盖 required_covered < required_total）→ 必备项缺失；
    - 其余（§19 冲突上浮）→ 观测冲突待复核。
    非 HUMAN_REVIEW_REQUIRED → None（无复核要求即无复核原因）。
    """
    if agg.get("review_status") != "HUMAN_REVIEW_REQUIRED":
        return None
    if agg.get("review_reason_code") == "UNMEASURED_RATIO_HIGH":
        return "UNMEASURED_RATIO_HIGH：正式范围内未测量比例超阈值（无综合分）"
    if agg.get("observation_status") == "NO_VALID_OBSERVATION":
        return "NO_VALID_OBSERVATION：正式范围内无有效观测"
    cov = agg.get("coverage") or {}
    if cov.get("required_total") and (cov.get("required_covered") or 0) < cov["required_total"]:
        return "REQUIRED_ITEM_MISSING：必备能力项存在未测量项（§20.2）"
    return "SCORE_CONFLICT：观测冲突待人工复核（§19）"


def _insert_report_row(conn, session_id: str, *, status: str, report_json: dict,
                       review_status: str | None = None, total_score: float | None = 0.0,
                       gate_passed: int = 0, report_id: str | None = None,
                       review_request_reason: str | None = None) -> str:
    """写终态 report 行：优先把 GENERATING 占位行原地转终态（复用版本，不残留占位行），
    无占位则版本化 INSERT。返回 report_id。发布字段本计划置 NULL。

    review_request_reason（§21.1 人工复核字段，U6 2026-09-09）：生成时若
    review_status=HUMAN_REVIEW_REQUIRED 落归类原因（报告读回透传——「复核原因与
    报告状态一致」的校验依据）。

    total_score 可 None（§20.3 完整性门控：未测量比例超阈 → 无综合分，不以 0 冒充；
    列已迁移 NULLABLE；GENERATING/FAILED 占位由调用方写 0.0 保持兼容）。"""
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
            " report_status=?, review_status=?, review_request_reason=?, created_at=?"
            " WHERE report_id=? AND report_status='GENERATING'",
            (report_id, total_score, gate_passed,
             json.dumps(report_json, ensure_ascii=False), status, review_status,
             review_request_reason, now_iso(),
             placeholder["report_id"]),
        )
        return report_id
    version = 1 + (conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM report WHERE session_id=?", (session_id,)
    ).fetchone()[0] or 0)
    conn.execute(
        "INSERT INTO report(report_id, session_id, total_score, gate_passed, report_json,"
        " report_status, review_status, review_request_reason, version, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (report_id, session_id, total_score, gate_passed,
         json.dumps(report_json, ensure_ascii=False), status, review_status,
         review_request_reason, version, now_iso()),
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


def _detect_bad_case_divergence(session_id: str) -> int:
    """双分背离检测（REF-5.11/D-075）：|score_live - score_final| ≥ 阈值 → INSERT
    bad_case_candidate（status='pending'），永不 UPDATE question_score 的 score 字段（D-031）。

    阈值为 None（占位待裁决）时直接返回 0 不检测——不臆造数值。幂等：同
    (session_id, item_id, question_id) 已有 pending 候选则跳过（报告版本化重复生成不重复建）。
    返回本次新建候选行数。

    独立小事务：函数内部自开连接、自 commit/close（不借调用方 conn）——2026-09-08
    事故复盘（generate_report 持 RESERVED 锁进 LLM 调用 → llm_trace 落库 5s 超时
    database is locked 全进程写库 500）：INSERT 在进 LLM 调用前必须已释放写锁。
    """
    threshold = config.BAD_CASE_DIVERGENCE_THRESHOLD
    if threshold is None:
        return 0
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT question_id, item_id, score_live, score_final FROM question_score"
            " WHERE session_id=? AND score_live IS NOT NULL AND score_final IS NOT NULL",
            (session_id,),
        ).fetchall()
        created = 0
        for r in rows:
            divergence = abs((r["score_live"] or 0) - (r["score_final"] or 0))
            if divergence < threshold:
                continue
            qid = r["question_id"]
            exists = conn.execute(
                "SELECT 1 FROM bad_case_candidate WHERE session_id=? AND item_id=?"
                " AND status='pending' AND question_id IS ?",
                (session_id, r["item_id"], qid),
            ).fetchone()
            if exists is not None:
                continue
            conn.execute(
                "INSERT INTO bad_case_candidate(candidate_id, session_id, item_id, question_id,"
                " score_live, score_final, divergence, status, detected_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (new_id("bc"), session_id, r["item_id"], qid,
                 r["score_live"], r["score_final"], divergence, "pending", now_iso()),
            )
            created += 1
        conn.commit()
        return created
    finally:
        conn.close()


def generate_report(session_id: str) -> dict:
    """生成报告（版本化：同会话重复生成追加新版本行，不覆盖旧行——REF-5.9 SC-3）。

    流程：聚合 → 七项一致性校验（任一失败 → report_status='FAILED' 行，不生成正常
    报告）→ 版本化 INSERT（version = session 内 MAX+1）→ report→trace trace_link 写点。
    返回 report_data 附加 report_status/version 键。

    连接纪律（2026-09-08 事故复盘）：进入 LLM 调用（call_llm_json）前 conn 不得持有
    未提交写事务（llm_trace/失败收尾都另开连接写库，撞 RESERVED 锁 5s 超时全进程
    database is locked）；异常路径 finally 统一 rollback 清事务释放写锁（正常路径
    末尾已 commit，rollback 为无害 no-op），不 close（现状 get_conn 靠 GC 回收）。
    """
    conn = get_conn()
    try:
        s = conn.execute(
            "SELECT s.session_id, p.name AS position_name FROM assessment_session s"
            " JOIN position p ON p.position_id=s.position_id WHERE s.session_id=?",
            (session_id,),
        ).fetchone()
        if s is None:
            raise ValueError(f"会话不存在: {session_id}")

        agg = aggregate_session_scores(session_id)
        question_reviews = _load_question_reviews(session_id)
        # 双分背离候选检测（REF-5.11）：已改独立小事务（函数内部自开连接、自
        # commit/close）——本 conn 进 LLM 调用时不再持 RESERVED 锁（D-031 不改分）
        _detect_bad_case_divergence(session_id)

        # 雷达图数据（ECharts）：required vs actual，按 item 顺序对齐；gate/无数据项跳过
        radar_items = [it for it in agg["item_scores"]
                       if not it.get("gate") and it.get("actual_level") is not None]
        radar_data = {
            "indicators": [{"name": it["std_name"], "max": 5, "imputed": bool(it.get("imputed"))} for it in radar_items],
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
                # score=None（UNMEASURED/reference）保持 None——「无结果」而非 0
                # （§20.1 作废补算；§20.3 未测项得分为无结果）；Report.vue fmtScore(None)='—'
                {**it, "score": round(it["score"], 2) if it.get("score") is not None else None}
                for it in agg["item_scores"]
            ],
            "strengths": agg["strengths"],
            "weaknesses": agg["weaknesses"],
            "strengths_text": llm_out.get("strengths_text", ""),
            "weaknesses_text": llm_out.get("weaknesses_text", ""),
            "suggestions_text": llm_out.get("suggestions_text", ""),
            "question_reviews": question_reviews,
            "review_status": agg.get("review_status"),
            "review_reason_code": agg.get("review_reason_code"),
            "observation_status": agg.get("observation_status"),
            "provisional": agg.get("provisional", False),
            "coverage": agg.get("coverage", {}),
            # §20.2.A 批次绑定（U6）：报告 JSON 记录生成所依据的评分批次 id，
            # 与 question_score.scoring_batch_id 行一致（归属一致）；无批次行
            # （存量/测试直插形态）为 None——报告照生成。
            "scoring_batch_id": _latest_scoring_batch_id(session_id),
            "created_at": now_iso(),
        }
        # §21.1 复核原因（U6）：HUMAN_REVIEW_REQUIRED 时的归类文本，报告读回透传
        review_request_reason = _review_request_reason(agg, session_id)

        # 七项一致性校验（聚合后、版本化 INSERT 前）；⑦ 只校验 LLM 产出的文案段（不信任 LLM 文案，
        # 而非候选人可控文本——WR-06）
        llm_text = "\n".join(filter(None, (
            llm_out.get("strengths_text"),
            llm_out.get("weaknesses_text"),
            llm_out.get("suggestions_text"),
        )))
        errors = _run_consistency_checks(agg, session_id, report_text=llm_text,
                                         review_request_reason=review_request_reason)
        if errors:
            _insert_report_row(
                conn, session_id, status="FAILED",
                report_json={"error": "; ".join(errors)[:200]},
                review_status=agg.get("review_status"), report_id=report_id,
                review_request_reason=review_request_reason,
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
            review_request_reason=review_request_reason,
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
    finally:
        # 兜底清事务（正常路径已 commit → no-op；异常路径丢未决写、释放写锁）
        conn.rollback()
