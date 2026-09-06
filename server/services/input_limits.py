"""输入限额按类型校验（REF-6.3/D-078）：限额常量集中在 config.py，本模块提供就近校验纯函数。

各限额值为 None（占位，实施期校准待用户裁决）时跳过校验（不生效——不臆造默认值）；
已裁决值（MAX_ANSWER_LEN=64*1024 在 scoring.py、MAX_CONTEXT_TOKENS=8000 在 config.py）沿用。
接口层校验调用本模块纯函数（当限额值裁决后生效，None 时放行）。
"""
from .. import config


def validate_jd_length(text: str) -> bool:
    """JD 文本长度校验：超限返回 False（拒绝）；限额 None（未裁决）时放行。"""
    if config.MAX_JD_LENGTH is None:
        return True
    return len(text or "") <= config.MAX_JD_LENGTH


def validate_jd_file_lines(line_count: int) -> bool:
    """JSONL 批量导入行数校验：超限返回 False（拒绝）。已裁决 500（2026-09-06）。"""
    return line_count <= config.MAX_JD_FILE_LINES


def clamp_pagination_limit(limit: int) -> int:
    """分页 limit 钳制：超限钳到上限（下限 1）；限额 None（未裁决）时原样返回。"""
    if limit < 1:
        return 1
    if config.MAX_PAGINATION_LIMIT is None:
        return limit
    return min(limit, config.MAX_PAGINATION_LIMIT)
