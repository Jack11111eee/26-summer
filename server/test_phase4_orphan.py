"""Phase 4 orphan 路由修复测试（04-02，REF-7.1——SSOT §28 第 4 步）。

覆盖：GET /api/admin/jds/orphan 返回孤儿 JD 列表（非 404）——字段口径锁定
【[04-009] 选项 B 现有实现】= 字段子集 {jd_id,job_title,company,source_type,status,created_at}
+ WHERE position_id IS NULL AND status != 'failed'；并断言 /jds/orphan 先于
/jds/{jd_id} 匹配（200 而非 404「JD 不存在」）。

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db；单文件单进程。
运行：cd server && python -m pytest test_phase4_orphan.py -v
"""
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase4_orphan.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


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


def _seed_orphan_jds() -> None:
    """种子 jd_record：一个非 failed 孤儿（imported）+ 一个 failed 孤儿。"""
    conn = get_conn()
    now = now_iso()
    conn.execute(
        "INSERT INTO jd_record(jd_id, position_id, job_title, company, source_type,"
        " raw_text, status, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (new_id("jd"), None, "后端开发工程师", "甲公司", "paste", "JD 原文 A", "imported", now),
    )
    conn.execute(
        "INSERT INTO jd_record(jd_id, position_id, job_title, company, source_type,"
        " raw_text, status, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (new_id("jd"), None, "失败岗位", "乙公司", "paste", "JD 原文 B", "failed", now),
    )
    conn.commit()
    conn.close()


def test_orphan_returns_list_not_404() -> None:
    _seed_orphan_jds()
    # 种子就位：2 行孤儿（imported + failed）
    assert len(_q("SELECT jd_id FROM jd_record WHERE position_id IS NULL")) == 2
    r = client.get("/api/admin/jds/orphan", headers=_admin_headers())
    # 核心断言：/jds/orphan 先于 /jds/{jd_id} 匹配 → 200 列表而非 404「JD 不存在」
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list), data
    # 排除 failed 孤儿，只含非 failed 孤儿
    assert len(data) == 1, data
    assert data[0]["status"] == "imported"
    assert all(row["status"] != "failed" for row in data)
    # 字段口径锁定【[04-009] 选项 B】：字段子集恰为 6 列
    assert set(data[0].keys()) == {
        "jd_id", "job_title", "company", "source_type", "status", "created_at"
    }
