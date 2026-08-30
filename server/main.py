"""FastAPI 应用入口：加载 .env、初始化 DB、注册路由、挂载前端静态文件。

启动（开发）：  uvicorn server.main:app --reload --port 8000
启动（演示）：  先 cd web && npm run build，再 uvicorn server.main:app --port 8000
"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    """极简 .env 加载（KEY=VALUE，忽略注释与空行），不引第三方依赖。"""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

from .db import init_db  # noqa: E402  (须在 .env 加载后导入，DB_PATH 才生效)
from .api import auth  # noqa: E402
from .api.admin import jds as admin_jds  # noqa: E402

app = FastAPI(title="岗位胜任力测评系统 - 模块一")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(admin_jds.router)

# 生产：挂载前端构建产物（web/dist 存在时）；API 路由已优先注册，不会被静态文件拦截
_dist = ROOT / "web" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="static")
