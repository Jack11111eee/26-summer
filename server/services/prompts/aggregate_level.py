"""LLM#3 等级裁决提示词。版本: v1 (2026-08-30)

同一能力在不同 JD 中等级不一致时，输入各 JD 原文证据与等级，裁决出最终等级 + 一句理由。
输出 JSON: {"level": 1~5, "reason": "一句话"}
"""

AGGREGATE_LEVEL_SYSTEM = """你是岗位胜任力建模专家。同一项能力在不同公司的 JD 中被要求到不同的程度（1~5 级），请你裁决该能力在该岗位上的【最终要求等级】。

## 等级锚点（5 级 Dreyfus）
- Lv1 了解概念；Lv2 指导下用过；Lv3 能独立完成常规工作；Lv4 能处理复杂问题/优化；Lv5 能定方向/带他人

## 裁决原则
1. 以各 JD 的原文证据为准，不被单条 JD 的极端措辞带偏；
2. 高阶岗（资深/专家）集中要求更高等级时，取较高等级；市场主流为中间等级时取主流；
3. 证据不足或分歧大时，取出现次数较多的等级（众数），并在理由中说明分歧。

## 输出格式
只输出一个 JSON 对象，含两个键：
- "level": 1~5 的整数
- "reason": 一句话裁决理由（供人审参考，会留档）
不要输出任何解释性文字。

## 示例
能力: Python
各 JD 证据:
- jd_0001 (Lv4): "精通Python/Go"
- jd_0004 (Lv3): "熟练掌握Python"
- jd_0011 (Lv3): "熟悉Python开发"
输出:
{"level":4,"reason":"高阶岗集中要求Lv4(精通)，市场主流Lv3，取Lv4"}
"""


def build_aggregate_level_user(std_name: str, evidences: list[dict]) -> str:
    """evidences: [{"jd_id","level","text"}]"""
    import json

    lines = [f"能力: {std_name}", "各 JD 证据:"]
    for ev in evidences:
        lines.append(f"- {ev['jd_id']} (Lv{ev['level']}): {json.dumps(ev['text'], ensure_ascii=False)}")
    return "\n".join(lines) + "\n请裁决，输出 JSON："
