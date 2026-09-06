"""终局逐题评分（SSOT §12.4 / §18——02-05 契约修正）。

客观题：代码匹配 answer_key（正则优先，退化关键词包含）；answer_key 缺失 →
score_state=INVALIDATED（题库无效，不进正常分母——取代旧「按最低分记」语义）。
主观题：P-score（LLM，temperature≈0），按 raw_hash 回捞原文输入（评分不受精炼影响，§8）。

score_state 生产三态（02-05）：SCORED（正常评分）/ REFUSED（拒答封存，
§18 特殊状态值 score_value=0）/ INVALIDATED（answer_key 空的客观题）。
score_live 仅导航参考值（D-26——不参与任何 final 计算，无 50/50 合成）。

枚举位预留不生产（D-28 口径集）：INSUFFICIENT_EVIDENCE / NOT_ADMINISTERED /
INCOMPLETE（完整 imputation 属 Phase 5；常量在位供校验与 Phase 5 生产）。
"""
import hashlib
import json
import re

from ..db import get_conn
from .llm import call_llm_json
from .pipeline import new_id, now_iso
from .prompts.score import SCORE_SYSTEM, score_prompt
from .trace_link import link_entity

# score_state 六态（D-28；N11 代码校验惯例——Phase 2 生产前三态，枚举位供 Phase 5）
SCORE_STATES = (
    "SCORED",
    "REFUSED",
    "INSUFFICIENT_EVIDENCE",
    "NOT_ADMINISTERED",
    "INVALIDATED",
    "INCOMPLETE",
)


# ---------- 客观题代码判分 ----------

# WR-14：answer_key 长度上限与候选人回答截断长度（防病态正则灾难性回溯）
_MAX_KEY_LEN = 512
MAX_ANSWER_LEN = 64 * 1024  # WR-07：输入侧（assessment）与评分侧同口径公开设定的上限
_MAX_ANSWER_LEN = MAX_ANSWER_LEN  # 旧私有名（模块内既有引用保持）


def _score_objective(answer_key: str, answer: str) -> tuple[int, str]:
    """answer_key 命中 → 5 分，否则 1 分。

    WR-14 防护（正则判定逻辑本体保留）：
    - 含显式正则结构（| 分支、字符类、量词组等"有意写成正则"的形态）→ 按正则匹配，
      非法正则退化子串；
    - 其余（含裸元字符如 "C+"、"*"）一律 re.escape 字面匹配——LLM 生成的 key 含
      未转义量词时会静默改变语义（"C+" 匹配任何含 C 的回答），字面匹配杜绝该类误判；
    - key 限长 + 回答截断，收窄灾难性回溯面（慢性 ReDoS）。

    answer_key 缺失/空白不在本函数处理——score_question 客观分支先判空 key 升
    INVALIDATED（02-05 语义替换：旧 CR-01「空串正则恒命中 + 按最低分记」拆为
    「题库无效」脱离普通评分通道）。
    """
    key = answer_key[:_MAX_KEY_LEN]
    text = (answer or "")[:_MAX_ANSWER_LEN]

    if _looks_like_regex(key):
        try:
            hit = re.search(key, text) is not None
        except re.error:
            hit = key.lower() in text.lower()
    else:
        # 字面匹配（含裸量词等不构成有效正则意图的元字符）
        hit = key.lower() in text.lower()
    return (5, f"命中答案要点: {answer_key}") if hit else (1, f"未命中答案要点: {answer_key}")


def _looks_like_regex(key: str) -> bool:
    """判定 key 是否显式声明为正则：仅 |（分支）与字符类 [...]{...} 视为正则意图。

    裸量词（+、*、?）跟在普通字符后不视为正则声明——凭其静默改变语义的风险
    大于收益（"C+"、"V*" 这类 key 几乎都是想表达字面文本）。
    """
    return bool(re.search(r"\||\[[^\]]*\]|\([^)]*\)[?*+]", key))


def _mock_score(system_prompt: str, user_prompt: str) -> dict:
    return {"score": 3, "evidence_quote": "mock quote", "reason": "mock reason"}


def _fetch_answer_text(session_id: str, question_id: str) -> str:
    """取该题全部候选人回答；有 raw_hash 的按 hash 回捞原文拼接（P-score 用原文）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT content, raw_hash FROM assessment_message"
        " WHERE session_id=? AND question_id=? AND role='user' ORDER BY created_at, rowid",
        (session_id, question_id),
    ).fetchall()
    parts = []
    for r in rows:
        if r["raw_hash"]:
            raw = conn.execute(
                "SELECT full_text FROM context_raw WHERE hash=?", (r["raw_hash"],)
            ).fetchone()
            parts.append(raw["full_text"] if raw else r["content"])
        else:
            parts.append(r["content"])
    return "\n".join(parts)


def _latest_user_message_id(session_id: str, question_id: str) -> str | None:
    """该题最新一条 user 消息的 message_id（evidence_span 的 source_message_id）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT message_id FROM assessment_message"
        " WHERE session_id=? AND question_id=? AND role='user'"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (session_id, question_id),
    ).fetchone()
    return row["message_id"] if row else None


def _locate_span(answer_text: str, quote: str, source_message_id: str | None) -> dict | None:
    """在原文中定位 quote，返回结构化 span。定位失败返回 None（调用方降级）。

    offset 按 Python str.find/len（code point 语义，§12.5）；多命中取最早（Claude's Discretion）；
    quote_hash = sha256(quote.encode('utf-8'))（D-003「LLM 不碰数字」——offset/hash 全代码计算）。
    """
    if not quote:
        return None
    idx = answer_text.find(quote)
    if idx == -1:
        return None  # mock "mock quote" / LLM 改写非原文 → 降级
    return {
        "source_message_id": source_message_id,
        "source_content_type": "raw",
        "start_offset": idx,
        "end_offset": idx + len(quote),
        "quote_hash": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
    }


def _build_evidence_spans(answer_text: str, evidence_quote: str | None,
                          source_message_id: str | None) -> str | None:
    """定位 evidence_quote → evidence_spans_json；定位失败降级 quote_hash only。"""
    if not evidence_quote:
        return None
    span = _locate_span(answer_text, evidence_quote, source_message_id)
    if span is not None:
        return json.dumps([span])
    return json.dumps([{
        "quote_hash": hashlib.sha256(evidence_quote.encode("utf-8")).hexdigest(),
        "source_message_id": None,
        "source_content_type": None,
        "start_offset": None,
        "end_offset": None,
    }])


def score_question(session_id: str, question_id: str) -> dict:
    """对单题终局判分。返回 {score_final, evidence_quote, reason, score_state,
    evidence_spans_json, trace_id}。

    客观题 answer_key 空 → score_state=INVALIDATED + score_final=None（题库无效，
    不落 1/不落 5——脱离普通评分通道，REF-5.2/8.1）；其余正常判分 score_state=SCORED。
    evidence_spans_json 结构化权威（source_message_id/offset/quote_hash）；主观题 trace_id
    为成功 LLM trace 的 trace_id（供 trace_link 关联），客观/INVALIDATED 分支为 None。
    """
    conn = get_conn()
    q = conn.execute(
        "SELECT aq.question_id, aq.session_id, b.stem, b.qtype, b.answer_key, b.rubric,"
        " s.position_id, p.name AS position_name"
        " FROM assessment_question aq"
        " JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " JOIN assessment_session s ON s.session_id=aq.session_id"
        " JOIN position p ON p.position_id=s.position_id"
        " WHERE aq.question_id=?",
        (question_id,),
    ).fetchone()
    if q is None:
        raise ValueError(f"题目不存在: {question_id}")
    q = dict(q)
    answer_text = _fetch_answer_text(session_id, question_id)
    source_message_id = _latest_user_message_id(session_id, question_id)

    if q["qtype"] == "objective":
        if not (q["answer_key"] or "").strip():
            # 02-05：题库无效（客观题缺 answer_key）→ INVALIDATED（REF-5.2/8.1），
            # 不再按最低分记——WR-14 正则防护逻辑本体保留（有 key 的题照旧判分）
            return {
                "score_final": None,
                "evidence_quote": None,
                "reason": "题库无效：客观题缺 answer_key（REF-5.2/8.1）",
                "score_state": "INVALIDATED",
                "evidence_spans_json": None,
                "trace_id": None,
            }
        score, reason = _score_objective(q["answer_key"], answer_text)
        evidence_quote = answer_text[:60]
        return {"score_final": score, "evidence_quote": evidence_quote,
                "reason": reason, "score_state": "SCORED",
                "evidence_spans_json": _build_evidence_spans(
                    answer_text, evidence_quote, source_message_id),
                "trace_id": None}

    trace_out: list[str] = []
    result = call_llm_json(
        "score", question_id, SCORE_SYSTEM,
        score_prompt(q, answer_text, q["position_name"]),
        mock_fn=_mock_score,
        trace_out=trace_out,
    )
    evidence_quote = result.get("evidence_quote", "")
    return {
        "score_final": int(result["score"]),
        "evidence_quote": evidence_quote,
        "reason": result.get("reason", ""),
        "score_state": "SCORED",
        "evidence_spans_json": _build_evidence_spans(answer_text, evidence_quote, source_message_id),
        "trace_id": trace_out[0] if trace_out else None,
    }


# ---------- 会话级打分 ----------

def _find_item_id(model_id: str, std_name: str, category: str) -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT item_id FROM competency_item WHERE model_id=? AND std_name=? AND category=?",
        (model_id, std_name, category),
    ).fetchone()
    return row["item_id"] if row else None


def _latest_score_live(session_id: str, question_id: str) -> int | None:
    """score_live 参考值读取（D-26：仅供导航/审计参考，不参与任何 final 计算）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT score_live FROM assessment_message"
        " WHERE session_id=? AND question_id=? AND score_live IS NOT NULL"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (session_id, question_id),
    ).fetchone()
    return row["score_live"] if row else None


def score_session(session_id: str, *, allow_completed: bool = False) -> dict:
    """对会话内所有已回答题目打分并落 question_score（score_state 三态生产）。

    completed 护栏（REF-8.2）：会话已结束即拒绝重复评分（API 与直调双路径都被护）；
    服务端串行链（request_report 后台任务）经 allow_completed=True 内部豁免（D-03/D-08）。
    幂等仅限 in_progress 会话内重复调用（completed 由护栏拒绝，不再触发删旧重打）。

    分母契约（02-05）：
    - seal_reason='refused'（02-04 二次 DECLINED 封存）→ score_state='REFUSED'、
      score_final=0（§18 特殊状态值），不调 score_question（拒答不产生能力证据）；
    - 客观题缺 answer_key（score_question 返回 INVALIDATED）→ score_final=None 透传；
    - 其余 → score_state='SCORED'，score_final 独立落库（无 50/50 合成——D-26）。

    实现注意：先在内存里算完全部行（含 LLM 调用），最后一次写库——避免外层
    conn 持写事务时 LLM trace 用新连接写库导致 database is locked。
    """
    conn = get_conn()
    session = conn.execute(
        "SELECT model_id, status FROM assessment_session WHERE session_id=?", (session_id,)
    ).fetchone()
    if session is None:
        raise ValueError(f"会话不存在: {session_id}")
    if session["status"] == "completed" and not allow_completed:
        raise ValueError("会话已结束，不允许重复评分")
    # in_progress 放行（重复调用删旧重打）

    answered = conn.execute(
        "SELECT aq.question_id, aq.seal_reason, aq.item_id,"
        " b.std_name, b.category, b.qtype"
        " FROM assessment_question aq JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE aq.session_id=? AND aq.answered_at IS NOT NULL",
        (session_id,),
    ).fetchall()

    # 1) 内存计算（含 LLM 调用，此时本 conn 未持写事务）
    pending_rows: list[tuple] = []
    trace_links: list[tuple[str, str, str]] = []  # (trace_id, score_id, question_id)
    for q in answered:
        # item_id 取值：优先实例列（02-02 v2.0 item 绑定），NULL 回退 competency_item 查询（过渡）
        item_id = q["item_id"] or _find_item_id(session["model_id"], q["std_name"], q["category"])
        if item_id is None:
            # 题库 std_name 在模型中无对应项（通用题）——跳过不入分表
            continue

        if q["seal_reason"] == "refused":
            # 拒答封存（02-04 二次 DECLINED）：score_value=0 特殊状态值（§18），
            # 不调 score_question（拒答不产生能力证据，REFUSED 行不经 LLM 评分）
            pending_rows.append(
                (new_id("qs"), session_id, q["question_id"], item_id,
                 None, 0, "REFUSED", None, "拒答（§18 score_value=0 特殊状态值）",
                 None, "v1", None, None, now_iso())
            )
            continue

        r = score_question(session_id, q["question_id"])
        # score_live 参考值（D-26——不参与 final 计算，仅落库供导航/审计）
        score_live = _latest_score_live(session_id, q["question_id"]) \
            if q["qtype"] == "subjective" else None
        if r["score_state"] == "INVALIDATED":
            # 客观题缺 answer_key：score_final=None（不落 1/不落 5，脱离普通评分通道）
            pending_rows.append(
                (new_id("qs"), session_id, q["question_id"], item_id,
                 None, None, "INVALIDATED", r["evidence_quote"], r["reason"],
                 None, "v1", None, None, now_iso())
            )
            continue
        score_id = new_id("qs")
        pending_rows.append(
            (score_id, session_id, q["question_id"], item_id,
             score_live, r["score_final"], r["score_state"],
             r["evidence_quote"], r["reason"], r["evidence_spans_json"],
             "v1", "p-score-1", None, now_iso())
        )
        # 运行时 score→trace 写点（D-020）：仅主观题产 LLM trace（客观/INVALIDATED trace_id=None）
        if q["qtype"] == "subjective" and r.get("trace_id"):
            trace_links.append((r["trace_id"], score_id, q["question_id"]))

    # 2) 单事务写库
    # gate 行非评分重算面（03-01）：DELETE 只清评分行（gate_result IS NULL），
    # 表单链 gate 结构化结果必须幸存——顺序链 _generate_report_task 与 UI request_report
    # 都走 score_session，吞掉 gate 行会导致表单链死循环（gate 永不采集→finish 不可达）。
    conn.execute("DELETE FROM question_score WHERE session_id=? AND gate_result IS NULL", (session_id,))
    conn.executemany(
        "INSERT INTO question_score(score_id, session_id, question_id, item_id,"
        " score_live, score_final, score_state, evidence_quote, reason,"
        " evidence_spans_json, rubric_version, scorer_version, measurement_target, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        pending_rows,
    )
    for trace_id, score_id, question_id in trace_links:
        link_entity(conn, trace_id=trace_id, entity_type="question_score",
                    entity_id=score_id, link_role="scored")
        link_entity(conn, trace_id=trace_id, entity_type="assessment_question",
                    entity_id=question_id, link_role="source")
    conn.commit()
    return {"session_id": session_id, "scored_count": len(answered)}
