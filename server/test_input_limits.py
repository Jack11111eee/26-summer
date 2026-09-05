"""输入限额按类型校验（REF-6.3/D-078）：结构校验逻辑正确，不锁生产默认值。

限额常量 None 占位（实施期校准待裁决）；本测试 monkeypatch 成小值验证校验逻辑，
不提交任何生产默认数值（不臆造）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server.config as C
from server.services.input_limits import clamp_pagination_limit, validate_jd_length


def test_jd_length_over_limit_rejected(monkeypatch):
    monkeypatch.setattr(C, "MAX_JD_LENGTH", 100)
    assert validate_jd_length("x" * 100) is True
    assert validate_jd_length("x" * 101) is False


def test_jd_length_unset_allows(monkeypatch):
    monkeypatch.setattr(C, "MAX_JD_LENGTH", None)
    assert validate_jd_length("x" * 10000) is True


def test_pagination_limit_clamped(monkeypatch):
    monkeypatch.setattr(C, "MAX_PAGINATION_LIMIT", 10)
    assert clamp_pagination_limit(100) == 10
    assert clamp_pagination_limit(5) == 5
    assert clamp_pagination_limit(0) == 1


def test_pagination_limit_unset_passthrough(monkeypatch):
    monkeypatch.setattr(C, "MAX_PAGINATION_LIMIT", None)
    assert clamp_pagination_limit(100) == 100
