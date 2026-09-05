"""pytest 统一收集 linchpin（D-69/Wave 0）：mock 三件套集中注入 + session 级临时 DB fixture。

pytest 在收集任何测试模块前先 import 本 conftest，故此处 env 注入先于 server.config
的 import 时读取，使全阶段测试共用同一临时库、不串库、不碰 data/app.db。
"""
import os
import sys
import tempfile

# 先于任何 server.* import：把 repo 根（server/ 的父目录）加入 sys.path，
# 使 `import server.db` 在 `cd server && python -m pytest` 下仍可解析。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# mock 三件套：setdefault 不覆盖已设值（T-06-04）；DB_PATH 指向 gsd-test- 前缀临时库
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(prefix="gsd-test-"), "app.db"))

import pytest  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _session_db():
    """session 级：整个收集进程只 init 一次临时库（TestClient 跳过 startup，需显式建表）。"""
    init_db()
    yield


@pytest.fixture(scope="function")
def conn():
    """只读连接的便捷 fixture：返回 get_conn()，测试结束 close（供后续测试模块复用）。"""
    c = get_conn()
    try:
        yield c
    finally:
        c.close()
