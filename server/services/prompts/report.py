"""P-report 报告文字生成提示词。版本: v1 (2026-08-30)

测评报告五段式之第④段：优势/短板/建议自然语言（07 文档 §10.5/§10.6，temperature=0）。
输出须为 JSON 对象，结构: {"strengths_text","weaknesses_text","suggestions_text"}
"""
import json

REPORT_SYSTEM = """你是一名资深的职业发展顾问。

## 任务
根据候选人的测评结果（优势项、短板项、评分证据），生成自然语言的评价和建议。

## 输出格式（JSON）
{
  "strengths_text": "优势描述（2-3 句话）",
  "weaknesses_text": "短板描述（2-3 句话）",
  "suggestions_text": "针对性建议（3-5 条，每条一句话，用顿号或分号分隔）"
}

## 约束
- 只能基于给定的优势/短板项和评分证据，不得编造未提及的能力
- 语言要具体、可操作（不要"多学习"这种空话）
- 引用具体的评分证据（evidence_quote）
"""


def report_prompt(position_name: str, strengths: list, weaknesses: list,
                  evidence_quotes: dict) -> str:
    """生成报告 user prompt。evidence_quotes: {item_id: [quote, ...]}"""
    return f"""岗位：{position_name}
优势项：{json.dumps(strengths, ensure_ascii=False)}
短板项：{json.dumps(weaknesses, ensure_ascii=False)}
评分证据：{json.dumps(evidence_quotes, ensure_ascii=False)}

请生成评价和建议。"""
