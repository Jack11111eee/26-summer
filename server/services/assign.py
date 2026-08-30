"""归岗：job_title 规范化与岗位/别名匹配。"""
import re

# 常见后缀噪声，归一化时去除
_SUFFIXES = ["工程师", "开发工程师", "实习生", "专员", "经理", "（急招）", "(急招)"]


def normalize_title(title: str) -> str:
    """去空格/大小写/常见后缀，用于岗位名与别名的稳定匹配。"""
    if not title:
        return ""
    t = re.sub(r"\s+", "", title.strip())
    for suf in _SUFFIXES:
        if t.endswith(suf) and len(t) > len(suf):
            # 仅当去掉后缀后仍非空才去除（避免"工程师"本身被清空）
            t = t[: -len(suf)]
            break
    return t
