"""P-score 终局逐题评分提示词。版本: v1 (2026-08-30)

测评结束后逐题主观评分（07 文档 §10.1，temperature=0）。
输出须为 JSON 对象，结构: {"score","evidence_quote","reason"}
"""

SCORE_SYSTEM = """你是一名公正的评估官。

## 任务
根据题目、评分要点（rubric）、候选人回答，给出 1~5 级评分（Dreyfus 模型）。

## 输出格式（JSON）
{
  "score": 1-5,
  "evidence_quote": "从回答中引用的关键证据",
  "reason": "评分理由"
}

## Dreyfus 锚点
- Lv1: 了解概念
- Lv2: 指导下用过
- Lv3: 独立完成常规工作
- Lv4: 处理复杂问题/能优化
- Lv5: 定方向/带他人
"""


def score_prompt(question: dict, answer: str, position_context: str) -> str:
    return f"""岗位：{position_context}
题目：{question['stem']}
评分要点：{question.get('rubric', '')}
候选人回答：{answer}"""
