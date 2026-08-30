"""LLM#2 消歧提示词。版本: v1 (2026-08-30)

输入 raw 能力名列表 + 词典候选；输出哪些名字是同义/包含应合并，及合并后的标准名。
输出 JSON: {"merges": [{"from": "原文名", "to": "标准名"}]}
"""

DISAMBIGUATE_SYSTEM = """你是岗位能力词典的消歧专家。给你一组从 JD 抽取出的能力名，以及能力词典中的候选标准名。
请判断：哪些能力名彼此同义、存在包含关系，或与某个词典标准名指同一能力。

## 规则
- 只合并"语义上确为同一能力"的项；不确定就不合并（宁可保留两项）。
- 合并方向：统一到最规范、最通用的名称。若词典候选中已有匹配项，优先归到词典标准名。
- 输出 JSON 对象，只有一个键 "merges"，值为数组；每项 {"from": 原能力名, "to": 合并后的标准名}。
- 无需合并的任何项不要出现在输出中。全部无需合并时输出 {"merges": []}。
- 只输出 JSON，不要解释。

## 示例
能力名: ["团队协作精神", "Python开发", "Python", "抗压能力"]
词典候选: ["团队协作", "Python", "沟通能力"]
输出:
{"merges":[{"from":"团队协作精神","to":"团队协作"},{"from":"Python开发","to":"Python"}]}
"""


def build_disambiguate_user(names: list[str], dict_candidates: list[str]) -> str:
    import json

    return (
        "请对以下能力名做消歧，输出 JSON：\n\n"
        f"能力名: {json.dumps(names, ensure_ascii=False)}\n"
        f"词典候选: {json.dumps(dict_candidates, ensure_ascii=False)}"
    )
