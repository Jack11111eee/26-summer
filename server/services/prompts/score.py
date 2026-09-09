"""P-score 终局逐题评分提示词。版本: v1 (2026-08-30)；U5b 锚点约束增补 (2026-09-09)

测评结束后逐题主观评分（07 文档 §10.1，temperature=0）。
输出须为 JSON 对象，结构: {"score","evidence_quote","reason"}

U5b（SSOT §9.4 契约第 2 条 + §17 主观评分锚点约束，2026-09-09）：prompt 增携带
题目 measurement_target 与锚点区间 [observable_level_min, observable_level_max]，
替代「通用 Dreyfus 五级 + 一句 rubric」的脱靶评分；SYSTEM 增锚定与理由约束。
返回 schema 不变（score 1-5 整数；LLM 不碰数字边界——范围校验归代码 _validate_score）。
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

## 锚点约束（SSOT §9.4/§17，2026-09-09）
- 评分须锚定在本题测量目标与锚点区间内；
- 理由需引用回答原文、指出命中要点与缺失要点；
- 不得以题干未要求的标准扣分。"""


def score_prompt(question: dict, answer: str, position_context: str, *,
                 measurement_target: str | None = None,
                 level_range: tuple[int, int] | None = None) -> str:
    """P-score 用户侧提示词。

    measurement_target / level_range（§9.4 契约第 2 条，U5b 增参）：
    - measurement_target：题目测量目标（题库行 NULL 时传 None → 段落省略）；
    - level_range：锚点区间 (observable_level_min, observable_level_max)
      （题库行 NULL 时调用方按难度默认查表传入）。
    兼容性：两参缺省（None）时输出与旧版形态一致（既有调用/测试不破）。
    """
    lines = [f"岗位：{position_context}"]
    if measurement_target:
        lines.append(f"测量目标：{measurement_target}")
    if level_range is not None:
        lines.append(f"锚点区间：Lv{level_range[0]} ~ Lv{level_range[1]}（评分不得高于 Lv{level_range[1]}）")
    lines.append(f"题目：{question['stem']}")
    lines.append(f"评分要点：{question.get('rubric', '')}")
    lines.append(f"候选人回答：{answer}")
    return "\n".join(lines)
