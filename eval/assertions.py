"""评测断言库（可迁移，与具体岗位/模型解耦）。

所有断言统一返回 (passed, message) 元组，便于上层聚合展示。
"""


def assert_score_consistency(scores: list[int], max_variance: int = 1) -> tuple[bool, str]:
    """断言多次复跑的分差 ≤ max_variance（默认 1 分）。"""
    if not scores:
        return False, "无分数样本"
    lo, hi = min(scores), max(scores)
    variance = hi - lo
    ok = variance <= max_variance
    return ok, f"scores={scores} max-min={variance} (上限 {max_variance})"


def assert_tier_ordering(strong: float, medium: float, weak: float) -> tuple[bool, str]:
    """断言三档总分排序：strong > medium > weak。"""
    ok = strong > medium > weak
    return ok, f"strong={strong} medium={medium} weak={weak}"


def assert_weakness_identified(report: dict, expected_weakness: str) -> tuple[bool, str]:
    """断言报告中已识别指定短板（report.weaknesses 中含 expected_weakness）。"""
    names = [w.get("std_name", "") for w in report.get("weaknesses", [])]
    ok = expected_weakness in names
    return ok, f"期望短板 '{expected_weakness}' 是否命中：{ok}；实际短板={names}"


def assert_weaknesses_within_tested(report: dict, tested_names: list[str]) -> tuple[bool, str]:
    """断言短板定位落在被测条目集合内（非空 + 无幻影——铺满全量口径）。

    虚拟考生铺满整个分母时短板取 gap×weight 最大前 3（内部排序细节由聚合层
    测试覆盖）；本断言验证 E2E 语义「定位到实测条目」——短板集合非空且其
    std_name 全部属于被测集合。
    """
    names = [w.get("std_name", "") for w in report.get("weaknesses", [])]
    tested = set(tested_names)
    ok = bool(names) and all(n in tested for n in names)
    return ok, f"短板集合={names}（非空且全属被测集合：{ok}）"
