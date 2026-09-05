"""报告发布前七项一致性校验 + 录用判断红线词表（D-002/REF-5.9）。

generate_report 在聚合后、版本化 INSERT 前调用 _run_consistency_checks；任一失败 →
report_status='FAILED'（不生成正常报告）。校验纯代码执行，不信任 LLM 文案（T-05-08）。
"""
from ..db import get_conn

# D-002 红线词表（录用判断表述）集中一处：报告文案含任一 → 校验⑦失败
HIRING_REDLINE_WORDS = ("建议录用", "不予录用", "排名第", "推荐淘汰", "拟录用", "建议淘汰")


def _run_consistency_checks(agg: dict, session_id: str, report_text: str = "") -> list[str]:
    """七项一致性校验：全过返回 []，任一失败返回错误字符串列表。

    ① 数字可重算（重算 total_score 与 agg["total_score"] 一致，浮点差 < 0.01）
    ② weight 总和一致（agg 内 item weight 之和 == 模型快照 weight 之和，含 gate）
    ③ 引用 question/message 属于该 session（question_score 的 question_id 反查
       assessment_question 必须同 session）
    ④ model/version 快照非空（assessment_session.model_id/model_version）
    ⑤ 排除态（INVALIDATED/INCOMPLETE/INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED）未进
       正常分母（须出现在 agg["missing_warnings"]）
    ⑥ IMPUTED/REFUSED/required 警告与结构化状态自洽
    ⑦ 文案无录用判断表述（report_text 含 HIRING_REDLINE_WORDS 任一 → 失败）
    """
    errors: list[str] = []
    conn = get_conn()

    # ① 数字可重算
    recomputed = round(sum(it.get("score") or 0.0 for it in agg.get("item_scores", [])), 2)
    if abs(recomputed - (agg.get("total_score") or 0.0)) >= 0.01:
        errors.append(f"总分不可重算: agg={agg.get('total_score')} recomputed={recomputed}")

    # ② weight 总和一致（agg vs 模型快照，含 gate）
    agg_weight = round(sum(it.get("weight") or 0.0 for it in agg.get("item_scores", [])), 4)
    db_weight = round(conn.execute(
        "SELECT COALESCE(SUM(ci.weight), 0) FROM competency_item ci"
        " JOIN assessment_session s ON s.model_id=ci.model_id WHERE s.session_id=?",
        (session_id,),
    ).fetchone()[0], 4)
    if abs(agg_weight - db_weight) >= 0.005:
        errors.append(f"weight 总和不一致: agg={agg_weight} db={db_weight}")

    # ③ 引用 question/message 属于该 session
    bad = conn.execute(
        "SELECT COUNT(*) c FROM question_score qs"
        " LEFT JOIN assessment_question aq ON aq.question_id=qs.question_id"
        " WHERE qs.session_id=? AND qs.question_id IS NOT NULL"
        "   AND (aq.question_id IS NULL OR aq.session_id != qs.session_id)",
        (session_id,),
    ).fetchone()["c"]
    if bad:
        errors.append(f"{bad} 条 question_score 引用不属于该 session 的 question")

    # ④ model/version 快照非空
    sess = conn.execute(
        "SELECT model_id, model_version FROM assessment_session WHERE session_id=?",
        (session_id,),
    ).fetchone()
    if sess is None or not sess["model_id"] or sess["model_version"] is None:
        errors.append("session 缺少 model_id/model_version 快照")

    # ⑤ 排除态未进正常分母（须出现在 missing_warnings）
    _EXCLUDED_STATES = ("INVALIDATED", "INCOMPLETE", "INSUFFICIENT_EVIDENCE", "NOT_ADMINISTERED")
    excluded_rows = conn.execute(
        "SELECT item_id, score_state FROM question_score WHERE session_id=?"
        " AND score_state IN (?,?,?,?)",
        (session_id, *_EXCLUDED_STATES),
    ).fetchall()
    warn_keys = {(w.get("item_id"), w.get("reason")) for w in agg.get("missing_warnings", [])}
    for r in excluded_rows:
        if (r["item_id"], r["score_state"]) not in warn_keys:
            errors.append(f"排除态 question_score 未进 missing_warnings: {r['item_id']}/{r['score_state']}")

    # ⑥ IMPUTED/REFUSED/required 警告与结构化状态自洽
    if agg.get("provisional") and agg.get("review_status") != "HUMAN_REVIEW_REQUIRED":
        errors.append("provisional 为真但 review_status 非 HUMAN_REVIEW_REQUIRED")
    if agg.get("review_status") == "HUMAN_REVIEW_REQUIRED" and not (
        agg.get("provisional") or agg.get("observation_status") == "NO_VALID_OBSERVATION"
    ):
        errors.append("review_status=HUMAN_REVIEW_REQUIRED 但既非 required 缺失也非 O=∅")

    # ⑦ 文案无录用判断表述（D-002 红线词表；report_text 由调用方序列化后传入）
    if report_text and any(w in report_text for w in HIRING_REDLINE_WORDS):
        errors.append("文案含录用判断表述（红线词表命中）")

    return errors
