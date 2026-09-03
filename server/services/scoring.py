"""终局逐题评分（07 文档 §10，R1 双分合成）。

客观题：代码匹配 answer_key（正则优先，退化关键词包含）。
主观题：P-score（LLM，temperature≈0），按 raw_hash 回捞原文输入（评分不受精炼影响，§8）。
合成：final = round(score_live*0.5 + score_final*0.5)；客观题仅代码分。
"""
import json
import re

from ..db import get_conn
from .llm import call_llm_json
from .pipeline import new_id, now_iso
from .prompts.score import SCORE_SYSTEM, score_prompt


# ---------- 客观题代码判分 ----------

def _score_objective(answer_key: str, answer: str) -> tuple[int, str]:
    """answer_key 命中 → 5 分，否则 1 分。先按正则试，非法正则退化为子串包含。

    answer_key 缺失/空白 → 按最低分记（CR-01：空串正则 re.search('', x) 恒命中，
    任何回答会白得 5 分，属评分正确性缺陷）。
    """
    if not (answer_key or "").strip():
        return 1, "answer_key 缺失（题目配置异常），按最低分记"
    try:
        hit = re.search(answer_key, answer) is not None
    except re.error:
        hit = answer_key.lower() in answer.lower()
    return (5, f"命中答案要点: {answer_key}") if hit else (1, f"未命中答案要点: {answer_key}")


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


def score_question(session_id: str, question_id: str) -> dict:
    """对单题终局判分。返回 {score_final, evidence_quote, reason}。"""
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

    if q["qtype"] == "objective":
        score, reason = _score_objective(q["answer_key"] or "", answer_text)
        return {"score_final": score, "evidence_quote": answer_text[:60], "reason": reason}

    result = call_llm_json(
        "score", question_id, SCORE_SYSTEM,
        score_prompt(q, answer_text, q["position_name"]),
        mock_fn=_mock_score,
    )
    return {
        "score_final": int(result["score"]),
        "evidence_quote": result.get("evidence_quote", ""),
        "reason": result.get("reason", ""),
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
    conn = get_conn()
    row = conn.execute(
        "SELECT score_live FROM assessment_message"
        " WHERE session_id=? AND question_id=? AND score_live IS NOT NULL"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (session_id, question_id),
    ).fetchone()
    return row["score_live"] if row else None


def score_session(session_id: str, *, allow_completed: bool = False) -> dict:
    """对会话内所有已回答题目打分并落 question_score。

    completed 护栏（REF-8.2）：会话已结束即拒绝重复评分（API 与直调双路径都被护）；
    服务端串行链（request_report 后台任务）经 allow_completed=True 内部豁免（D-03/D-08）。
    幂等仅限 in_progress 会话内重复调用（completed 由护栏拒绝，不再触发删旧重打）。

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
        "SELECT aq.question_id, b.std_name, b.category, b.qtype"
        " FROM assessment_question aq JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE aq.session_id=? AND aq.answered_at IS NOT NULL",
        (session_id,),
    ).fetchall()

    # 1) 内存计算（含 LLM 调用，此时本 conn 未持写事务）
    pending_rows: list[tuple] = []
    for q in answered:
        r = score_question(session_id, q["question_id"])
        score_live = _latest_score_live(session_id, q["question_id"]) if q["qtype"] == "subjective" else None
        score_final = r["score_final"]
        if score_live is not None:
            final = round(score_live * 0.5 + score_final * 0.5)
        else:
            final = score_final
        item_id = _find_item_id(session["model_id"], q["std_name"], q["category"])
        if item_id is None:
            # 题库 std_name 在模型中无对应项（通用题）——跳过不入分表
            continue
        pending_rows.append(
            (new_id("qs"), session_id, q["question_id"], item_id,
             score_live, score_final, final, r["evidence_quote"], r["reason"], now_iso())
        )

    # 2) 单事务写库
    conn.execute("DELETE FROM question_score WHERE session_id=?", (session_id,))
    conn.executemany(
        "INSERT INTO question_score(score_id, session_id, question_id, item_id,"
        " score_live, score_final, final_score, evidence_quote, reason, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        pending_rows,
    )
    conn.commit()
    return {"session_id": session_id, "scored_count": len(answered)}
