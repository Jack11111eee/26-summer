"""P-interviewer 面试官系统指令。版本: v1 (2026-08-30)

每轮对话的决策阶段（非流式 function call，07 文档 §7.1）。
输出须为 JSON 对象，结构:
{"action","reason","reply","score_live"?,"score_live_reason"?}
"""

INTERVIEWER_SYSTEM = """你是一名专业面试官，正在进行多轮对话测评。

## 你的任务
根据候选人的回答，决定下一步行动：followup（追问）/ next（下一题）/ finish（结束面试）。

## 输出格式（function call）
{
  "action": "followup|next|finish",
  "reason": "决策理由",
  "reply": "回复内容",
  "score_live": 1-5（仅主观题）,
  "score_live_reason": "评分理由（仅主观题）"
}

## 追问规则
- 回答含糊/未覆盖考察点/出现可深挖细节 → followup
- 回答完整或已追问 2 次 → next
- 所有题目完成 → finish（由规则触发，你不主动结束）
"""


def build_interview_context(session_id: str, conn) -> list[dict]:
    """从 assessment_message 重建对话历史（OpenAI messages 格式）。"""
    rows = conn.execute(
        "SELECT role, content FROM assessment_message WHERE session_id=?"
        " ORDER BY created_at, rowid",
        (session_id,),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]
