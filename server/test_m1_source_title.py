"""M1 源标题优先归岗（SSOT §8 2026-09-07 条目）回归锁。

JSONL 导入行内 job_title 入库不丢；pipeline/reparse 不覆写已存标题、
仅缺失时走 LLM#1 兜底；normalize_title 小写化 + position/alias 匹配
大小写不敏感（COLLATE NOCASE）。LLM_PROVIDER=mock（conftest 注入），
库为本文件自带 tmp 临时库（test_input_limits.py 同范式，不碰 data/app.db）。
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest  # noqa: E402

from server.db import get_conn, init_db, set_db_path  # noqa: E402
from server.services.assign import normalize_title  # noqa: E402
from server.services.pipeline import (  # noqa: E402
    assign_position,
    new_id,
    now_iso,
    run_parse_pipeline,
)


@pytest.fixture()
def _fresh_db(tmp_path, monkeypatch):
    set_db_path(str(tmp_path / "source_title.db"))
    init_db()
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    yield
    set_db_path(None)


def _ensure_admin() -> None:
    from passlib.context import CryptContext

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


def _client_and_headers():
    from fastapi.testclient import TestClient

    from server.main import app

    client = TestClient(app)
    _ensure_admin()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return client, {"Authorization": f"Bearer {r.json()['token']}"}


def _post_jsonl(client, headers, rows: list[dict]) -> dict:
    lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    r = client.post(
        "/api/admin/jds/import-file",
        headers=headers,
        files={"file": ("batch.jsonl", io.BytesIO(lines.encode("utf-8")), "application/jsonl")},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关（同 test_phase4_orphan.py）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _jd_row(jd_id: str) -> dict:
    return _q("SELECT * FROM jd_record WHERE jd_id=?", (jd_id,))[0]


def _position_name(conn_row: dict) -> str:
    rows = _q("SELECT name FROM position WHERE position_id=?", (conn_row["position_id"],))
    return rows[0]["name"] if rows else ""


# mock 抽取名固定为"软件工程师"（_mock_extract 默认；jd_text 不含「岗位：」模式）。
_MOCK_TITLE = "软件工程师"


def test_import_file_persists_job_title(_fresh_db):
    client, headers = _client_and_headers()
    res = _post_jsonl(client, headers, [
        {"company": "c1", "jd_text": "岗位职责：负责视觉算法的研发", "job_title": "视觉算法"},
        {"company": "c2", "jd_text": "岗位职责：负责定位算法的研发", "job_title": "SLAM算法"},
    ])
    assert res["imported"] == 2
    rows = _q(
        "SELECT job_title FROM jd_record WHERE jd_id IN (?,?)", tuple(res["jd_ids"])
    )
    assert {r["job_title"] for r in rows} == {"视觉算法", "SLAM算法"}


def test_import_file_position_key_compat(_fresh_db):
    client, headers = _client_and_headers()
    res = _post_jsonl(client, headers, [
        {"company": "c1", "jd_text": "岗位职责：负责平台研发", "position": "平台开发"},
    ])
    row = _jd_row(res["jd_ids"][0])
    assert row["job_title"] == "平台开发"


def test_import_file_blank_title_falls_back_to_llm(_fresh_db):
    """空白/非字符串/缺失标题静默落 None 走 LLM#1 兜底（TestClient 同步执行后台任务）。"""
    client, headers = _client_and_headers()
    res = _post_jsonl(client, headers, [
        {"company": "c1", "jd_text": "岗位职责：负责研发", "job_title": "   "},
        {"company": "c2", "jd_text": "岗位职责：负责研发", "job_title": 123},
        {"company": "c3", "jd_text": "岗位职责：负责研发"},
    ])
    assert res["imported"] == 3
    rows = _q("SELECT job_title, status FROM jd_record")
    assert len(rows) == 3
    assert all(r["job_title"] == _MOCK_TITLE and r["status"] == "parsed" for r in rows)


def test_pipeline_preserves_source_title(_fresh_db):
    client, headers = _client_and_headers()
    res = _post_jsonl(client, headers, [
        {"company": "c1", "jd_text": "岗位职责：负责视觉算法的研发", "job_title": "视觉算法工程师"},
    ])
    jd_id = res["jd_ids"][0]
    run_parse_pipeline(jd_id)
    row = _jd_row(jd_id)
    assert row["status"] == "parsed"
    assert row["job_title"] == "视觉算法工程师"  # mock 抽取名"软件工程师"未覆写
    assert _position_name(row) == normalize_title("视觉算法工程师") == "视觉算法"


def test_pipeline_null_source_title_falls_back_to_llm(_fresh_db):
    conn = get_conn()
    jd_id = new_id("jd")
    conn.execute(
        "INSERT INTO jd_record(jd_id, position_id, job_title, company, source_type,"
        " raw_text, status, created_at) VALUES(?,?,NULL,'c','paste',?, 'imported',?)",
        (jd_id, None, "岗位职责：负责研发", now_iso()),
    )
    conn.commit()
    conn.close()
    run_parse_pipeline(jd_id)
    row = _jd_row(jd_id)
    assert row["job_title"] == _MOCK_TITLE
    assert _position_name(row) == normalize_title(_MOCK_TITLE) == "软件"


def test_assign_position_case_insensitive(_fresh_db):
    conn = get_conn()
    pid = new_id("pos")
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "NLP算法", "pending_review", now_iso()),
    )
    conn.commit()
    conn.close()
    got_pid, why = assign_position("NLP 算法工程师")
    assert got_pid == pid
    assert why == "matched"
    assert _q("SELECT COUNT(*) c FROM position")[0]["c"] == 1  # 无新岗创建


def test_normalize_title_lowercases():
    assert normalize_title("NLP 算法") == "nlp算法"
    assert normalize_title("SLAM算法") == "slam算法"
    assert normalize_title("") == ""


def test_reparse_preserves_stored_title(_fresh_db):
    client, headers = _client_and_headers()
    res = _post_jsonl(client, headers, [
        {"company": "c1", "jd_text": "岗位职责：负责调度算法的研发", "job_title": "调度算法"},
    ])
    jd_id = res["jd_ids"][0]
    run_parse_pipeline(jd_id)
    before = _jd_row(jd_id)
    r = client.post(f"/api/admin/jds/{jd_id}/reparse", headers=headers)
    assert r.status_code == 200, r.text
    run_parse_pipeline(jd_id)
    after = _jd_row(jd_id)
    assert after["job_title"] == before["job_title"] == "调度算法"
    assert after["position_id"] == before["position_id"]
