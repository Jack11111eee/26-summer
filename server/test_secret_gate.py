"""secret 启动校验锁定（REF-6.2/D-077）：默认 secret fail-closed，test-secret 放行。

main.py:59-67 现 fail-closed-always（更严于 D-77 的 warn-in-mock/fail-in-real），
本测试锁定该现状——零生产改动 main.py 逻辑（承接 Task 0 裁决 secret-failclosed-keep）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from server import config
from server.main import _startup, _INSECURE_JWT_DEFAULTS


def test_fail_closed_on_default_secret(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", "change-me-in-.env")
    assert "change-me-in-.env" in _INSECURE_JWT_DEFAULTS
    with pytest.raises(RuntimeError):
        _startup()


def test_fail_closed_on_empty_secret(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", "")
    assert "" in _INSECURE_JWT_DEFAULTS
    with pytest.raises(RuntimeError):
        _startup()


def test_pass_on_test_secret(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", "test-secret")
    # test-secret 不在默认集 → _startup 不 raise（init_db 幂等，conftest 已建表）
    _startup()
