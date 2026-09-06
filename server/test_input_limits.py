"""输入限额按类型校验（REF-6.3/D-078）：结构校验逻辑正确 + 已裁决生产默认值 + 接线。

限额常量已裁决（2026-09-06 第十轮收口，SSOT §14）：MAX_JD_LENGTH=10000、
MAX_JD_FILE_LINES=500、MAX_PAGINATION_LIMIT=100。测试既有 monkeypatch 小值
验证校验逻辑（不依赖生产默认），也有生产默认值回归测试（锁裁决不被改回），
含 /admin/jds/import-file 行数上限 400 接线。
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

import pytest  # noqa: E402

import server.config as C  # noqa: E402
from server.services.input_limits import (  # noqa: E402
    clamp_pagination_limit,
    validate_jd_file_lines,
    validate_jd_length,
)


def test_jd_length_over_limit_rejected(monkeypatch):
    monkeypatch.setattr(C, "MAX_JD_LENGTH", 100)
    assert validate_jd_length("x" * 100) is True
    assert validate_jd_length("x" * 101) is False


def test_jd_length_unset_allows(monkeypatch):
    """None 放行语义保留（validator 对 None 限额的契约不随裁决移除）。"""
    monkeypatch.setattr(C, "MAX_JD_LENGTH", None)
    assert validate_jd_length("x" * 10000) is True


def test_jd_length_production_default():
    """已裁决生产默认 10000（2026-09-06）：超限拒绝、真实 JD 量级放行。"""
    assert C.MAX_JD_LENGTH == 10000
    assert validate_jd_length("x" * 10000) is True
    assert validate_jd_length("x" * 10001) is False


def test_jd_file_lines_production_default():
    """JSONL 行数上限已裁决 500：第 500 行放行、第 501 行拒绝。"""
    assert C.MAX_JD_FILE_LINES == 500
    assert validate_jd_file_lines(500) is True
    assert validate_jd_file_lines(501) is False
    assert validate_jd_file_lines(0) is True


def test_pagination_limit_clamped(monkeypatch):
    monkeypatch.setattr(C, "MAX_PAGINATION_LIMIT", 10)
    assert clamp_pagination_limit(100) == 10
    assert clamp_pagination_limit(5) == 5
    assert clamp_pagination_limit(0) == 1


def test_pagination_limit_unset_passthrough(monkeypatch):
    monkeypatch.setattr(C, "MAX_PAGINATION_LIMIT", None)
    assert clamp_pagination_limit(100) == 100


def test_pagination_limit_production_default():
    """分页上限已裁决 100：超限钳到 100。"""
    assert C.MAX_PAGINATION_LIMIT == 100
    assert clamp_pagination_limit(100) == 100
    assert clamp_pagination_limit(100000) == 100


# ---------- /admin/jds/import-file 行数上限 400 接线（MAX_JD_FILE_LINES=500） ----------


@pytest.fixture()
def _admin_env(tmp_path, monkeypatch):
    from server.db import init_db, set_db_path

    set_db_path(str(tmp_path / "limits.db"))
    init_db()
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    yield
    set_db_path(None)


def _admin_headers(client):
    from passlib.context import CryptContext

    from server.db import get_conn
    from server.services.pipeline import new_id, now_iso

    conn = get_conn()
    row = conn.execute("SELECT user_id FROM user WHERE username='admin'").fetchone()
    if row is None:
        pwd_ctx = CryptContext(schemes=["bcrypt"])
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (new_id("u"), "admin", pwd_ctx.hash("admin"), "admin", now_iso()),
        )
        conn.commit()
    conn.close()
    import server.main as m

    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_import_file_over_line_limit_rejected(_admin_env):
    from fastapi.testclient import TestClient

    from server.main import app

    client = TestClient(app)
    h = _admin_headers(client)
    lines = "\n".join(
        json.dumps({"company": f"c{i}", "jd_text": f"岗位描述 {i}"})
        for i in range(C.MAX_JD_FILE_LINES + 1)
    )
    r = client.post(
        "/api/admin/jds/import-file",
        headers=h,
        files={"file": ("batch.jsonl", io.BytesIO(lines.encode("utf-8")), "application/jsonl")},
    )
    assert r.status_code == 400, r.text
    assert str(C.MAX_JD_FILE_LINES) in r.text


def test_import_file_within_line_limit_passes(_admin_env):
    from fastapi.testclient import TestClient

    from server.main import app

    client = TestClient(app)
    h = _admin_headers(client)
    lines = "\n".join(
        json.dumps({"company": f"c{i}", "jd_text": f"岗位描述 {i}"})
        for i in range(3)
    )
    r = client.post(
        "/api/admin/jds/import-file",
        headers=h,
        files={"file": ("batch.jsonl", io.BytesIO(lines.encode("utf-8")), "application/jsonl")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 3
