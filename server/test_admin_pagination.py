"""管理员列表接口服务端分页测试（岗位库三表 / 能力词典 / 用户管理）。

覆盖：GET /admin/positions、/admin/positions/options、/admin/positions/pending、
/admin/jds/orphan、/admin/dict、/admin/users 的分页契约——返回 {items, total}，
page_size 默认 20，page 翻页正确。

全程 LLM_PROVIDER=mock 离线运行；每测试用 tmp_path 独立临时库（set_db_path 隔离，
不串库、不碰 data/app.db）。
运行：cd server && python -m pytest test_admin_pagination.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn, set_db_path  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path):
    """每测试独立临时库：set_db_path 指向 tmp_path，init 建表，结束复位 None。"""
    set_db_path(str(tmp_path / "pagination.db"))
    init_db()  # TestClient 不触发 startup 事件，显式建表
    yield
    set_db_path(None)


client = TestClient(app)


def _ensure_admin() -> None:
    conn = get_conn()
    row = conn.execute("SELECT user_id FROM user WHERE username='admin'").fetchone()
    if row is None:
        from passlib.context import CryptContext

        pwd_ctx = CryptContext(schemes=["bcrypt"])
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (new_id("u"), "admin", pwd_ctx.hash("admin"), "admin", now_iso()),
        )
        conn.commit()
    conn.close()


def _admin_headers() -> dict:
    _ensure_admin()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed(n: int) -> None:
    """种子 n 个 active 岗位 + n 个孤儿 JD + n 个词典词条 + n 个候选用户 + 3 个待审岗位。"""
    conn = get_conn()
    now = now_iso()
    for i in range(n):
        conn.execute(
            "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
            (new_id("pos"), f"岗位{i:02d}", "active", now),
        )
        conn.execute(
            "INSERT INTO jd_record(jd_id, position_id, job_title, company, source_type,"
            " raw_text, status, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("jd"), None, f"孤儿JD{i:02d}", "公司", "paste", "原文", "imported", now),
        )
        conn.execute(
            "INSERT INTO competency_dict(std_name, category, definition, exclusions_json,"
            " aliases_json, created_by, status, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (f"技能{i:02d}", "hard_skill", None, "[]", "[]", "human", "active", now, now),
        )
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (new_id("u"), f"user{i:02d}", "x", "candidate", now),
        )
    for i in range(3):
        conn.execute(
            "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
            (new_id("pos"), f"待审岗位{i}", "pending_review", now),
        )
    conn.commit()
    conn.close()


def test_positions_pagination() -> None:
    _seed(25)
    h = _admin_headers()
    d = client.get("/api/admin/positions", headers=h).json()
    assert set(d.keys()) == {"items", "total"}, d
    assert d["total"] == 28  # 25 active + 3 pending
    assert len(d["items"]) == 20  # 默认 page_size=20
    d2 = client.get("/api/admin/positions?page=2", headers=h).json()
    assert d2["total"] == 28
    assert len(d2["items"]) == 8
    d3 = client.get("/api/admin/positions?page_size=5", headers=h).json()
    assert d3["total"] == 28
    assert len(d3["items"]) == 5


def test_position_options_full_list() -> None:
    _seed(25)
    h = _admin_headers()
    d = client.get("/api/admin/positions/options", headers=h).json()
    assert isinstance(d, list), d
    assert len(d) == 28
    assert set(d[0].keys()) == {"position_id", "name"}


def test_pending_positions_pagination() -> None:
    _seed(25)
    h = _admin_headers()
    d = client.get("/api/admin/positions/pending", headers=h).json()
    assert set(d.keys()) == {"items", "total"}, d
    assert d["total"] == 3
    assert len(d["items"]) == 3


def test_orphan_jds_pagination() -> None:
    _seed(25)
    h = _admin_headers()
    d = client.get("/api/admin/jds/orphan?page_size=10&page=2", headers=h).json()
    assert d["total"] == 25
    assert len(d["items"]) == 10
    d3 = client.get("/api/admin/jds/orphan?page_size=10&page=3", headers=h).json()
    assert len(d3["items"]) == 5


def test_dict_pagination_and_filter() -> None:
    _seed(25)
    h = _admin_headers()
    d = client.get("/api/admin/dict", headers=h).json()
    assert set(d.keys()) == {"items", "total"}, d
    assert d["total"] == 25
    assert len(d["items"]) == 20
    # 筛选仍生效（只种了 hard_skill）
    d2 = client.get("/api/admin/dict", params={"category": "soft_skill"}, headers=h).json()
    assert d2["total"] == 0
    assert d2["items"] == []


def test_users_pagination() -> None:
    _seed(25)
    h = _admin_headers()
    d = client.get("/api/admin/users", headers=h).json()
    assert set(d.keys()) == {"items", "total"}, d
    assert d["total"] == 26  # 25 候选 + 1 admin
    assert len(d["items"]) == 20
    d2 = client.get("/api/admin/users?page=2", headers=h).json()
    assert len(d2["items"]) == 6


def test_positions_jd_count_uses_index() -> None:
    """回归：jd_count 相关子查询必须走 idx_jd_position（防 schema 改动悄悄丢索引，
    列表页退回全表 SCAN ~0.7-1s/请求而无感知——迁移 #16 的守护测试）。"""
    _seed(3)
    conn = get_conn()
    try:
        plans = conn.execute(
            "EXPLAIN QUERY PLAN SELECT p.position_id, p.name, p.status,"
            " (SELECT COUNT(*) FROM jd_record j WHERE j.position_id=p.position_id)"
            " AS jd_count FROM position p ORDER BY p.created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    detail = " | ".join(str(tuple(r)[3]) if len(tuple(r)) > 3 else str(tuple(r)) for r in plans)
    # 子查询不允许再出现全表 SCAN j（应 SEARCH ... USING INDEX idx_jd_position）
    has_scan = any("SCAN j" in str(tuple(r)) for r in plans)
    assert not has_scan, f"jd_count 子查询退回全表 SCAN: {detail}"
    assert any("idx_jd_position" in str(tuple(r)) for r in plans), detail
