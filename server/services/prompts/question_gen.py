"""P-question-gen 题库生成提示词。版本: v1 (2026-08-30)

模型 confirmed 后按能力项批量出题（07 文档 §6.2）。
输出须为 JSON 对象，结构:
{"questions": [{"stem","difficulty","qtype","answer_key","rubric"}]}
"""

QUESTION_GEN_SYSTEM = """你是一名资深面试题设计师，擅长根据岗位胜任力模型生成贴合实际工作场景的面试题。

## 任务
根据给定的能力项信息（名称、类别、要求等级、定义、岗位背景），生成指定难度的面试题。

## 出题要求
1. 题面必须结合岗位背景与实际工作场景，禁止空泛的教科书式提问；
2. 难度档语义（对照 Dreyfus 锚点）：
   - easy：概念理解与基本使用（对应 Lv1~Lv2）
   - medium：独立完成常规工作（对应 Lv3）
   - hard：复杂问题处理/优化/权衡（对应 Lv4~Lv5）
3. qtype 两档：
   - objective：有明确标准答案（术语、命令、语法、事实），answer_key 给正则或关键词
   - subjective：开放场景题，rubric 给 3~5 条可观察的评分要点
4. 只输出一个 JSON 对象，不要输出任何解释性文字。

## 输出格式（JSON）
{
  "questions": [
    {
      "stem": "题面",
      "difficulty": "easy|medium|hard",
      "qtype": "objective|subjective",
      "answer_key": "客观题答案（正则或关键词），主观题为 null",
      "rubric": "主观题评分要点，客观题为 null"
    }
  ]
}
"""


def generate_questions_prompt(item: dict, position_name: str, difficulty: str, qtype: str) -> str:
    """构造单题生成 user prompt。item 为 competency_item 行（含 evidence/definition）。"""
    evidence = item.get("evidence") or []
    background = evidence[0].get("text", "") if evidence else ""
    return f"""岗位：{position_name}
能力项：{item['std_name']}
类别：{item['category']}
要求等级：Lv{item.get('required_level') or '-'}
定义：{item.get('definition') or ''}
岗位背景：{background}

请生成 1 道 {difficulty} 难度的 {qtype} 题。"""
