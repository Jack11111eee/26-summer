"""facet 分类器 + gate 派生管线（SSOT §8.1 工序⑤ / §16.1，2026-09-08）。

两个纯函数，无 LLM、无 DB、无副作用：

- classify_facet(std_name, category)：gate qualification item 的确定性分类。
  关键词词表 + 内嵌数字解析 → {"facet_key": ..., "params": {...}} 或 None（长尾。
  None 的 item 渲染时整组降级勾选组 fallback——勾 = 是，永不 block）。
- derive_gate_payload(facet_answers, items)：v2 表单提交答案展开为逐 item
  真值 dict {std_name: True/False/数值}，供 _gate_check 现有真值表直接消费
  （True 在真值表内；False 命不中真值表即不通过——符合语义）。

档序约定（params.threshold 存档序数字，派生端按档比较）：
  education_degree：专科0 < 本科1 < 硕士2 < 博士3（「学士或硕士学位」宽读法取最低档）
  school_tier：    普通0 < 211=1 < 985=2（985 满足 211 要求；「985/211」并读取低档 211）
  english_level：  未达标0 < 四级4 < 六级6

词表为 v1（实施记录见临时讨论稿 §9），规则边界以本文件词表为准。
"""
from __future__ import annotations

import json
import re

# ---- 学历档序（education_degree.threshold）----
_DEGREE_TIER = {"专科": 0, "大专": 0, "本科": 1, "学士": 1, "硕士": 2, "研究生": 2, "博士": 3}
_TIER_DEGREE = {0: "专科", 1: "本科", 2: "硕士", 3: "博士"}
# 学历语境词：断言「学历/学位/毕业」语义（无语境词的裸学历词不分类，防误伤）
_DEGREE_CTX = ("学历", "学位", "毕业")

# ---- 院校档序（school_tier.threshold）----
_TIER_SCHOOL = {"211": 1, "985": 2}
_TIER_SCHOOL_NAME = {1: "211", 2: "985"}
# 院校语境词（与学历词区分：含院校词但无学历词 → 纯院校断言）
_SCHOOL_WORDS = ("211", "985", "院校", "学校", "大学", "双一流")

# ---- 英语等级（english_level.threshold）----
_ENGLISH_TIER = {"四级": 4, "CET4": 4, "cet4": 4, "CET-4": 4,
                "六级": 6, "CET6": 6, "cet6": 6, "CET-6": 6}
# 英语能力词（口语/听力/写作等）：不成等级，是独立断言 → 勾选组
_ENGLISH_SKILL_WORDS = ("口语", "听力", "写作", "阅读", "翻译", "交流")

# ---- 专业组（major_group：勾选组，无阈值）----
_MAJOR_CTX = ("专业", "学科", "背景")

# ---- 数值断言（number_range）：量纲词表 → (metric, unit) ----
# 维护口径：年龄/岁→age（周岁）；出勤/每周→weekly_days；工龄经验类不进（experience
# 由 base 字段 years_of_experience 承载，category=='experience' 一律不分类）
_NUMBER_METRICS = (
    (("年龄", "周岁", "岁"), "age", "岁"),
    (("出勤", "每周", "周"), "weekly_days", "天/周"),
)
# 数字+量纲抽取模式：「N岁/N天/N年/N周」（中文数字不解析——长尾降级勾选组）
_NUM_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(岁|周岁|天|日|周|年)")


def _extract_number_metric(std_name: str) -> dict | None:
    """std_name 内嵌数字+量纲解析 → {"threshold", "unit", "metric"} 或 None。

    走法：先按 metric 词表命中（无 metric 词的纯数字断言不分类——「3年以上」不知
    在说什么轴），再在该 metric 语境附近取首个数字。metric 相同词面只可能出现一个
    量纲（词表构造保证）。
    """
    m_num = _NUM_PATTERN.search(std_name)
    if m_num is None:
        return None
    for words, metric, unit in _NUMBER_METRICS:
        if any(w in std_name for w in words):
            return {"threshold": float(m_num.group(1)), "unit": unit, "metric": metric}
    return None


def _degree_hit(std_name: str) -> tuple[bool, int | None]:
    """学历断言探测：返回 (是复合断言, 具体档)。命中多档取最低（宽读法）。

    复合断言 = 学历词 + 院校词并存（「211硕士及以上学历」横跨两轴）→ 分类器整体
    返回 None，走勾选组（不解析，见临时讨论稿 §3.1.1 不参与合并条款）。
    """
    tiers = [tier for word, tier in _DEGREE_TIER.items() if word in std_name]
    if not tiers:
        return False, None
    has_school_word = any(w in std_name for w in _SCHOOL_WORDS)
    return has_school_word, min(tiers)


def classify_facet(std_name: str, category: str) -> dict | None:
    """gate qualification item → facet 分类（纯函数）。

    返回 {"facet_key": "education_degree"|"school_tier"|"english_level"|
    "number_range"|"major_group", "params": {...}} 或 None（长尾 fallback）。

    优先级（多重命中取首）：复合断言检测 → education_degree > school_tier >
    english_level > number_range > major_group。experience 类一律 None（年限由
    base 字段承载，category=='experience' 不进本分类器——清单 B2 边界）。
    """
    if category != "qualification":
        return None

    # 复合断言（学历+院校两轴）：整体不分类，勾选组
    is_composite, degree_tier = _degree_hit(std_name)
    has_school_word = any(w in std_name for w in _SCHOOL_WORDS)
    has_degree_word = any(w in std_name for w in _DEGREE_TIER)
    if has_degree_word and has_school_word:
        return None

    # 1) education_degree：学历词 + 学历语境词
    if degree_tier is not None and any(w in std_name for w in _DEGREE_CTX):
        return {"facet_key": "education_degree", "params": {"threshold": degree_tier}}

    # 2) school_tier：211/985/双一流（985/211 并读取低档）+ 院校语境
    if has_school_word and not has_degree_word:
        tier = 1  # 985/211 并读（含 985 且含 211）与「双一流」均视同 211 档要求
        if "985" in std_name and "211" not in std_name:
            tier = 2
        return {"facet_key": "school_tier", "params": {"threshold": tier}}

    # 3) english_level：等级词（四级/六级/CET4/CET6）；能力词（口语等）不成等级
    en_tiers = [t for w, t in _ENGLISH_TIER.items() if w in std_name]
    if en_tiers:
        if any(w in std_name for w in _ENGLISH_SKILL_WORDS):
            return None  # 「英语口语流利（六级）」类：技能为主，不做成等级单选
        return {"facet_key": "english_level", "params": {"threshold": min(en_tiers)}}

    # 4) number_range：内嵌数字 + metric 词表
    num_facet = _extract_number_metric(std_name)
    if num_facet is not None:
        return {"facet_key": "number_range", "params": num_facet}

    # 5) major_group：专业范围类（勾选组，无阈值解析）
    if any(w in std_name for w in _MAJOR_CTX):
        return {"facet_key": "major_group", "params": {}}

    return None


def facet_of(item: dict) -> dict | None:
    """competency_item 行（含 facet_key/facet_params_json 列）→ 分类 dict 或 None。

    读已打标结果，不重跑分类器（渲染/报告端唯一入口）。facet_key NULL（存量行）
    → None → 勾选组 fallback。
    """
    key = item.get("facet_key")
    if not key:
        return None
    params = {}
    if item.get("facet_params_json"):
        try:
            params = json.loads(item["facet_params_json"])
        except (TypeError, json.JSONDecodeError):
            params = {}
    return {"facet_key": key, "params": params}


def _enum_truth(answer: str, tier_map: dict[str, int]) -> bool | None:
    """枚举答案（文案）→ 档序数字；不认识的文案 → None（调用方按 False 处理）。"""
    tier = tier_map.get(answer)
    return tier


def derive_gate_payload(facet_answers: dict, items: list[dict]) -> dict:
    """facet 答案 → 逐 item 真值 dict {std_name: True/False/数值}（纯函数）。

    输入：
    - facet_answers：v2 提交的 facet 原始答案（快照 field.name 为键）——
      枚举 facet 为文案（如 "硕士"）、number_range 为数值、勾选组为数组
      {"checked": [...]} 的形态（FormCard checklist 提交数组，此处兼容裸数组）。
    - items：gate qualification items（competency_item 行 dict，含 facet 打标列）。

    输出：{std_name: True/False}。experience 的 years_of_experience 不经过本函数
    （base 字段直接在 _gate_check 数字比较），故本函数只处理 qualification items。
    默认全部 False（无对应答案即不达标——保守，与 _gate_check 无字段语义一致）。
    """
    out: dict = {}
    # 勾选组答案归一：数组 → set（farm: {"checked": [...]} 兼容）
    checked: set[str] = set()
    if isinstance(facet_answers.get("checked"), list):
        checked = set(facet_answers["checked"])

    for it in items:
        std_name = it["std_name"]
        facet = facet_of(it)
        if facet is None:
            # 长尾/存量 NULL：勾选组语义，勾 = 是
            out[std_name] = std_name in checked
            continue
        key = facet["facet_key"]
        params = facet.get("params") or {}
        if key == "education_degree":
            tier = _enum_truth(str(facet_answers.get("education_degree", "")),
                               {"专科": 0, "本科": 1, "硕士": 2, "博士": 3})
            need = params.get("threshold")
            out[std_name] = bool(tier is not None and need is not None and tier >= need)
        elif key == "school_tier":
            tier = _enum_truth(str(facet_answers.get("school_tier", "")),
                               {"其他": 0, "211": 1, "985": 2})
            need = params.get("threshold")
            out[std_name] = bool(tier is not None and need is not None and tier >= need)
        elif key == "english_level":
            tier = _enum_truth(str(facet_answers.get("english_level", "")),
                               {"均未通过": 0, "四级": 4, "六级": 6})
            need = params.get("threshold")
            out[std_name] = bool(tier is not None and need is not None and tier >= need)
        elif key == "number_range":
            metric = params.get("metric")
            field_name = f"number_{metric}" if metric else None
            raw = facet_answers.get(field_name) if field_name else None
            try:
                actual = float(raw)
            except (TypeError, ValueError):
                actual = None
            need = params.get("threshold")
            out[std_name] = bool(actual is not None and need is not None and actual >= need)
        else:  # major_group
            out[std_name] = std_name in checked
    return out
