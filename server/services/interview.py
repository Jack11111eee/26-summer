"""面试决策（07 文档 §7，H2 两阶段之决策阶段）。

decide_next_action：基于会话历史 + 当前题 + 最新回答，返回
  {action: followup|next|finish, reason, reply, score_live?, score_live_reason?}

真实模式走 LLM function call `interview_step`；mock 模式规则兜底（离线可跑通）。
finish 由规则触发（最后一题答完），模型不自主结束全场（07 §7.1）。
"""
from .. import config
from ..db import get_conn
from .llm import call_llm_json
from .prompts.interviewer import INTERVIEWER_SYSTEM

MIN_ANSWER_CHARS = 20  # mock 规则：低于此长度追问


def _load_session_question(session_id: str, question_id: str) -> tuple[dict, dict, bool]:
    """返回 (session_row, question_row(join bank), is_last_question)。"""
    conn = get_conn()
    session = conn.execute(
        "SELECT s.*, p.name AS position_name FROM assessment_session s"
        " JOIN position p ON p.position_id=s.position_id WHERE s.session_id=?",
        (session_id,),
    ).fetchone()
    question = conn.execute(
        "SELECT aq.question_id, b.stem, b.category, b.qtype, b.difficulty, b.rubric"
        " FROM assessment_question aq JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE aq.question_id=?",
        (question_id,),
    ).fetchone()
    last = conn.execute(
        "SELECT COUNT(*) c FROM assessment_question"
        " WHERE session_id=? AND answered_at IS NULL AND question_id<>?",
        (session_id, question_id),
    ).fetchone()["c"] == 0
    return dict(session), dict(question), last


def _count_followups(session_id: str, question_id: str) -> int:
    conn = get_conn()
    return conn.execute(
        "SELECT COUNT(*) c FROM assessment_message"
        " WHERE session_id=? AND question_id=? AND role='assistant' AND action='followup'",
        (session_id, question_id),
    ).fetchone()["c"]


def _build_user_prompt(session: dict, question: dict, history: list[dict],
                       user_message: str, is_last: bool) -> str:
    lines = [
        f"岗位：{session['position_name']}",
        f"当前题目（{question['category']}/{question['qtype']}，难度 {question.get('difficulty') or '无'}）：",
        question["stem"],
        "",
        "对话历史：",
    ]
    for m in history:
        role = {"user": "候选人", "assistant": "面试官", "system": "系统"}[m["role"]]
        lines.append(f"{role}：{m['content']}")
    lines.append(f"候选人：{user_message}")
    lines.append("")
    lines.append("系统提示：" + ("这是最后一题。" if is_last else "后面还有题目。"))
    return "\n".join(lines)


def _mock_interview(system_prompt: str, user_prompt: str) -> dict:
    """离线 mock 规则：回答短→followup；否则 next（最后一题→finish）。主观题固定 score_live=3。"""
    last_user = ""
    for line in reversed(user_prompt.splitlines()):
        if line.startswith("候选人："):
            last_user = line[len("候选人："):]
            break
    is_last = "这是最后一题" in user_prompt
    is_objective = "/objective" in user_prompt
    if len(last_user) < MIN_ANSWER_CHARS:
        return {"action": "followup", "reason": "回答过于简短", "reply": "能再具体展开一下吗？",
                "score_live": None if is_objective else 2, "score_live_reason": None if is_objective else "信息不足"}
    action = "finish" if is_last else "next"
    return {"action": action, "reason": "信息足够", "reply": "好的，感谢你的回答。",
            "score_live": None if is_objective else 3, "score_live_reason": None if is_objective else "mock 中档"}


def decide_next_action(session_id: str, question_id: str, user_message: str) -> dict:
    """决策下一步动作。规则优先于 LLM：追问达上限强制 next；最后一题强制 finish。"""
    conn = get_conn()
    session, question, is_last = _load_session_question(session_id, question_id)
    history_rows = conn.execute(
        "SELECT role, content FROM assessment_message WHERE session_id=?"
        " ORDER BY created_at, rowid",
        (session_id,),
    ).fetchall()
    history = [dict(r) for r in history_rows]

    result = call_llm_json(
        "interviewer", session_id, INTERVIEWER_SYSTEM,
        _build_user_prompt(session, question, history, user_message, is_last),
        mock_fn=_mock_interview,
    )

    # 规则护栏（07 §7.1/§7.2）：finish 由规则触发；追问上限 FOLLOWUP_MAX
    followups = _count_followups(session_id, question_id)
    action = result.get("action", "next")
    if action == "followup" and followups >= config.FOLLOWUP_MAX:
        action = "next"
        result["reason"] = f"追问达上限({config.FOLLOWUP_MAX})，强制 next"
    if is_last and action == "next":
        action = "finish"  # 最后一题不存在"下一题"

    return {
        "action": action,
        "reason": result.get("reason", ""),
        "reply": result.get("reply", ""),
        "score_live": result.get("score_live") if question["qtype"] == "subjective" else None,
        "score_live_reason": result.get("score_live_reason") if question["qtype"] == "subjective" else None,
    }
