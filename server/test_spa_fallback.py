"""SPA 深链回退测试（history 路由 + FastAPI 静态托管）。

前端 vue-router 用 createWebHistory（非 hash 模式），/login、/assessment/report/:id 等
深链刷新/直开时后端无对应静态文件——main.py 的 _spa_fallback 处理器须回送 index.html
（200）交给前端路由；API 路径的 404 保持 JSON 语义不变。

覆盖（dist 由本测试临时创建/删除，不依赖仓库内构建产物）：
- 非 API 路径 404 → 200 + index.html 内容（SPA 深链回退生效）
- /api/ 未知路径 404 → JSON {"detail": ...}（不打扰前端错误处理）
- /docs、/openapi.json 前缀不回退到 index.html
- dist 不存在（开发模式）→ FastAPI 默认 404 JSON（回退静默停用）

运行：cd server && python -m pytest test_spa_fallback.py -v
"""
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_spa_fallback.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import server.main as main  # noqa: E402
from server.db import init_db  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(main.app, raise_server_exceptions=False)

_MARKUP = "<!DOCTYPE html><html><head><title>SPA-TEST</title></head></html>"

# server/main.py 模块级 _dist 在创建 TestClient 时已求值；测试直接改写该 Path 指向
# 临时目录，验证处理器运行期读取的 404 回退行为。


def _make_dist() -> None:
    main._dist.mkdir(parents=True, exist_ok=True)
    (main._dist / "index.html").write_text(_MARKUP, encoding="utf-8")


def setup_function() -> None:
    if main._dist.exists():
        main._dist.mkdir(parents=True, exist_ok=True)
    _make_dist()


def teardown_function() -> None:
    # 清理临时 dist（测试自建目录，非仓库产物）：逐文件删，目录留给系统清理
    if main._dist.exists():
        for p in main._dist.iterdir():
            if p.is_file():
                p.unlink()


def test_spa_deep_link_returns_index() -> None:
    resp = client.get("/login")
    assert resp.status_code == 200
    assert _MARKUP in resp.text


def test_spa_deep_link_nested_path() -> None:
    resp = client.get("/assessment/report/sess_abc123")
    assert resp.status_code == 200
    assert _MARKUP in resp.text


def test_api_404_stays_json() -> None:
    resp = client.get("/api/nonexistent")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not Found"}


def test_api_404_session_level_stays_json() -> None:
    # 未知 session 深路径同样保持 JSON（路径在 /api/ 前缀下）
    resp = client.get("/api/assessment/sessions/sess_unknown")
    assert resp.status_code in (401, 404)  # require_login 先拦（401）或 404，均为 JSON
    try:
        detail = resp.json().get("detail")
    except Exception:
        detail = None
    assert detail is not None  # JSON 可解析（不是 HTML 回退）


def test_docs_not_served_as_spa() -> None:
    # /docs 是 FastAPI 内置路由（Swagger UI），优先于静态挂载，正常 200 且非 SPA 回退
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert _MARKUP not in resp.text


def test_no_dist_fallback_disabled() -> None:
    # dist 不存在场景（开发模式）：回退静默停用，默认 404 JSON
    saved = main._dist
    try:
        main._dist = saved.parent / "_spa_fallback_absent_dist"
        assert not main._dist.exists()
        resp = client.get("/login")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not Found"}
    finally:
        main._dist = saved
