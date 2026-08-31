"""首个 admin 种子脚本（05 文档 §6）。

用法：python -m scripts.seed_admin
读 ADMIN_USERNAME / ADMIN_PASSWORD 环境变量；幂等（已存在则跳过）。
"""

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

# 从仓库根运行时保证可 import server.db
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import get_conn, init_db


def main() -> None:
    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    if not username or not password:
        print("缺少 ADMIN_USERNAME / ADMIN_PASSWORD 环境变量")
        sys.exit(1)

    # passlib 导入放函数内：未安装时模块仍可被 import
    from passlib.context import CryptContext

    pwd_ctx = CryptContext(schemes=["bcrypt"])

    init_db()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT user_id FROM user WHERE username = ?", (username,)
        ).fetchone()
        if row:
            print(f"用户 {username} 已存在跳过")
            return
        conn.execute(
            "INSERT INTO user (user_id, username, password_hash, role, is_active, created_at)"
            " VALUES (?, ?, ?, 'admin', 1, ?)",
            (
                f"u_{uuid4().hex[:12]}",
                username,
                pwd_ctx.hash(password),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        print(f"已创建 admin 用户 {username}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
