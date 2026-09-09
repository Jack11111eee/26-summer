"""报告发布前七项+三项一致性校验 + 录用判断红线词表（D-002/REF-5.9；
⑧⑨⑩ 为 U6 2026-09-09 §21.1 校验语义升级增补——浅检查不算通过）。

generate_report 在聚合后、版本化 INSERT 前调用 _run_consistency_checks；任一失败 →
report_status='FAILED'（不生成正常报告）。校验纯代码执行，不信任 LLM 文案（T-05-08）。
"""
import json

from .. import config as _config_module
from ..db import get_conn

# D-002 红线词表（录用判断表述）集中一处：报告文案含任一 → 校验⑦失败
HIRING_REDLINE_WORDS = ("建议录用", "不予录用", "排名第", "推荐淘汰", "拟录用", "建议淘汰")


def _check_evidence_span_ownership(session_id: str) -> list[str]:
    """⑧ 引文消息归属（§21.1 校验语义升级，U6 2026-09-09）：score 行 evidence_spans_json
    的 source_message_id 必须属于该 session（SQL join 校验——跨 session 引文即断链）。

    「属于对应 question 的消息」的精确归属成本高（span 结构捎带 question 间接关联
    ——validation 需解析每行 JSON 再反查 message），TODO 留待逐行核验扩展
    （本检查至少守住 session 归属——§12.5 跨消息定位的最低线）。
    """
    errors: list[str] = []
    conn = get_conn()
    rows = conn.execute(
        "SELECT score_id, evidence_spans_json FROM question_score"
        " WHERE session_id=? AND evidence_spans_json IS NOT NULL",
        (session_id,),
    ).fetchall()
    for r in rows:
        try:
            spans = json.loads(r["evidence_spans_json"])
        except (json.JSONDecodeError, TypeError):
            errors.append(f"evidence_spans_json 非法 JSON: score_id={r['score_id']}")
            continue
        if not isinstance(spans, list):
            errors.append(f"evidence_spans_json 非数组: score_id={r['score_id']}")
            continue
        for span in spans:
            if not isinstance(span, dict):
                continue
            mid = span.get("source_message_id")
            if mid is None:
                # 定位失败降级形态（quote_hash-only，span 带 None）——合法
                continue
            owner = conn.execute(
                "SELECT session_id FROM assessment_message WHERE message_id=?", (mid,)
            ).fetchone()
            if owner is None or owner["session_id"] != session_id:
                errors.append(
                    f"引文 source_message_id 不属于该 session: score_id={r['score_id']}"
                    f" message_id={mid}")
                break  # 每行报一次即可（错误已定位）
    return errors


def _check_review_reason_consistency(agg: dict) -> list[str]:
    """⑨ 复核原因一致（§21.1，U6）：

    - review_status=HUMAN_REVIEW_REQUIRED 但 review_request_reason（报告读回透传）
      为空 → 报错（复核原因与报告状态一致的校验依据）；
    - reason_code 与 provisional/observation_status 自洽（反方向：UNMEASURED_RATIO_HIGH
      但 unmeasured_ratio ≤ 阈值 → 报错）。

    注：reason code → reason 文本的归类在 report.py _review_request_reason；本检查
    消费 agg（聚合口径 reason code + coverage.unmeasured_ratio）+ report 侧传入的
    review_request_reason（generate_report 组装后调用）。
    """
    errors: list[str] = []
    if agg.get("review_status") == "HUMAN_REVIEW_REQUIRED":
        if not agg.get("_review_request_reason"):
            errors.append("review_status=HUMAN_REVIEW_REQUIRED 但 review_request_reason 为空")
    # reason_code 自洽：UNMEASURED_RATIO_HIGH 但比例实际未超阈（阅后报警形态）
    if agg.get("review_reason_code") == "UNMEASURED_RATIO_HIGH":
        ratio = agg.get("unmeasured_ratio")
        if ratio is None or (isinstance(ratio, (int, float)) and
                             ratio <= _config_module.UNMEASURED_RATIO_THRESHOLD):
            errors.append(
                f"review_reason_code=UNMEASURED_RATIO_HIGH 但 unmeasured_ratio={ratio}"
                f" 未超阈值（与结构化状态不自洽）")
    return errors


def _check_total_score_integrity(agg: dict) -> list[str]:
    """⑩ 综合分仅完整性满足时存在（§21.1/§20.3 反向，U6）：total_score 非 None 但
    unmeasured_ratio > 阈值 → 报错（① 已覆盖「有值时重算等」；本检查守住「存在性
    前提」——完整性门控被绕过即不得有综合分）。"""
    ratio = agg.get("unmeasured_ratio")
    if (agg.get("total_score") is not None
            and isinstance(ratio, (int, float))
            and ratio > _config_module.UNMEASURED_RATIO_THRESHOLD):
        return [f"total_score={agg.get('total_score')} 非 None 但 unmeasured_ratio={ratio}"
                " 超阈值（无综合分契约被绕过）"]
    return []


def _run_consistency_checks(agg: dict, session_id: str, report_text: str = "",
                            review_request_reason: str | None = None) -> list[str]:
    """七项 + 三项（U6 2026-09-09 增）一致性校验：全过返回 []，任一失败返回错误字符串列表。

    ① 数字可重算（重算 total_score 与 agg["total_score"] 一致，浮点差 < 0.01；
      total_score=None（§20.3 完整性门控无综合分）→ 跳过本项——无值无可重算，
      校验语义是「有总分时重算必等」，不虚构 0 分参与比较）
    ② weight 总和一致（agg 内 item weight 之和 == 模型快照 weight 之和，含 gate）
    ③ 引用 question/message 属于该 session（question_score 的 question_id 反查
       assessment_question 必须同 session）
    ④ model/version 快照非空（assessment_session.model_id/model_version）
    ⑤ 排除态（INVALIDATED/INCOMPLETE/INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED）未进
       正常分母（须出现在 agg["missing_warnings"]）
    ⑥ IMPUTED/REFUSED/required 警告与结构化状态自洽
    ⑦ 文案无录用判断表述（report_text 含 HIRING_REDLINE_WORDS 任一 → 失败）
    ⑧ 引文消息归属（U6，§21.1 校验语义升级）：evidence_spans_json 的
       source_message_id 必须属于该 session（quote_hash-only 降级形态合法）
    ⑨ 复核原因一致（U6）：review_status=HUMAN_REVIEW_REQUIRED 但
       review_request_reason 空 → 报错；reason_code 与结构化状态自洽
       （UNMEASURED_RATIO_HIGH 但 unmeasured_ratio ≤ 阈值 → 报错）
    ⑩ 综合分仅完整性满足时存在（U6，§20.3 反向）：total_score 非 None 但
       unmeasured_ratio 超阈 → 报错
    """
    errors: list[str] = []
    conn = get_conn()

    # ① 数字可重算（total_score=None → 无综合分报告跳过——不冒充 0 分）
    if agg.get("total_score") is not None:
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
    if any(it.get("human_review") for it in agg.get("item_scores", [])) and not (
        agg.get("provisional") and agg.get("review_status") == "HUMAN_REVIEW_REQUIRED"
    ):
        errors.append("item 冲突 human_review 为真但顶层未标 PROVISIONAL/HUMAN_REVIEW_REQUIRED")
    # §20.3 复核原因单列：未测量比例超阈时必须有独立 reason code，不得混进冲突/required
    if agg.get("review_reason_code") == "UNMEASURED_RATIO_HIGH" and not (
        agg.get("total_score") is None
        and agg.get("provisional")
        and agg.get("review_status") == "HUMAN_REVIEW_REQUIRED"
    ):
        errors.append("review_reason_code=UNMEASURED_RATIO_HIGH 但未按无综合分契约落 provisional/HUMAN_REVIEW_REQUIRED")

    # ⑦ 文案无录用判断表述（D-002 红线词表；report_text 由调用方序列化后传入）
    if report_text and any(w in report_text for w in HIRING_REDLINE_WORDS):
        errors.append("文案含录用判断表述（红线词表命中）")

    # ⑧⑨⑩（U6，§21.1 校验语义升级——浅检查不算通过）
    # ⑨ 消费点：reason 文本挂 agg 副本（不惊动调用方 dict；_check 内以 _review_request_reason 读）
    check_agg = {**agg, "_review_request_reason": review_request_reason}
    errors.extend(_check_evidence_span_ownership(session_id))
    errors.extend(_check_review_reason_consistency(check_agg))
    errors.extend(_check_total_score_integrity(agg))

    return errors
