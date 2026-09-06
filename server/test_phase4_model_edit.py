"""Phase 4 模型编辑字段校验测试（04-02，REF-7.2——SSOT §28 第 4 步）。

覆盖：ModelItem 解析期拒绝 NaN/∞ weight 与 NaN/∞ years（parse_obj 单测；HTTP 层
NaN/∞ 的 422 响应因 Starlette JSONResponse allow_nan=False 无法序列化 input 值恒 500，
故 NaN/∞ 走 Pydantic 单测 + 一个 HTTP 层「拒绝且不落库」用例）；HTTP 层覆盖
weight>1（422）、required_level 越界（422）、importance 非法枚举（422）、
years 负数（422）、同 category 重复 std_name（400，保留 Σ=100%）、
权重合计 0.5（400 Σ=100%）、合法编辑（200 + competency_item 重建）。

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db；单文件单进程。
运行：cd server && python -m pytest test_phase4_model_edit.py -v
"""
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase4_model_edit.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from server.api.admin.models import ModelItem  # noqa: E402
from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
# raise_server_exceptions=False：importance 非法枚举在 RED 阶段撞 DB CHECK（IntegrityError），
# 关闭重抛以断言 HTTP 状态码（422）而非让测试崩在异常上
client = TestClient(app, raise_server_exceptions=False)


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


def _seed_draft_model() -> str:
    """建 active 岗位 + draft 模型 + 一条 competency_item，返回 model_id。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "后端开发工程师", "active", now),
    )
    items = [
        {"std_name": "Python", "category": "hard_skill", "importance": "required",
         "weight": 0.5, "required_level": 3, "years": 3, "gate": 0},
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "preferred",
         "weight": 0.5, "required_level": 3, "years": None, "gate": 0},
    ]
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, 1, "draft", json.dumps({"position_id": pid, "version": 1, "items": items},
                                          ensure_ascii=False), now),
    )
    conn.execute(
        "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
        " importance, weight, years, gate) VALUES(?,?,?,?,?,?,?,?,?)",
        (new_id("c"), mid, "Python", "hard_skill", 3, "required", 0.5, 3, 0),
    )
    conn.commit()
    conn.close()
    return mid


def _valid_items() -> list[dict]:
    """合法 body 基线：权重合计 1.0、字段合规。"""
    return [
        {"std_name": "Python", "category": "hard_skill", "weight": 0.5,
         "required_level": 3, "importance": "required", "years": 3},
        {"std_name": "沟通能力", "category": "soft_skill", "weight": 0.5,
         "required_level": 3, "importance": "preferred", "years": None},
    ]


# ---------- ModelItem 解析期 NaN/∞ 校验（parse_obj 单测） ----------

def test_model_item_rejects_nan_inf_weight() -> None:
    """weight 拒绝 NaN/∞（allow_inf_nan=False；NaN 现由 ge=0 兜底，inf 依赖 allow_inf_nan）。"""
    with pytest.raises(ValidationError):
        ModelItem.model_validate(
            {"std_name": "Python", "category": "hard_skill", "weight": float("nan"),
             "required_level": 3, "importance": "required", "years": 3},
        )
    with pytest.raises(ValidationError):
        ModelItem.model_validate(
            {"std_name": "Python", "category": "hard_skill", "weight": float("inf"),
             "required_level": 3, "importance": "required", "years": 3},
        )


def test_model_item_rejects_nan_inf_years() -> None:
    """years 拒绝 NaN/∞（allow_inf_nan=False + ge=0）。"""
    with pytest.raises(ValidationError):
        ModelItem.model_validate(
            {"std_name": "Python", "category": "hard_skill", "weight": 0.5,
             "required_level": 3, "importance": "required", "years": float("nan")},
        )
    with pytest.raises(ValidationError):
        ModelItem.model_validate(
            {"std_name": "Python", "category": "hard_skill", "weight": 0.5,
             "required_level": 3, "importance": "required", "years": float("inf")},
        )


# ---------- HTTP 层字段级校验 ----------

def test_update_model_rejects_weight_gt_1() -> None:
    mid = _seed_draft_model()
    items = [
        {"std_name": "Python", "category": "hard_skill", "weight": 1.5,
         "required_level": 3, "importance": "required", "years": 3},
    ]
    r = client.put(f"/api/admin/models/{mid}", json={"items": items}, headers=_admin_headers())
    assert r.status_code == 422, r.text


def test_update_model_rejects_required_level_out_of_range() -> None:
    mid = _seed_draft_model()
    headers = _admin_headers()
    for bad_level in (6, 0):
        items = [
            {"std_name": "Python", "category": "hard_skill", "weight": 0.5,
             "required_level": bad_level, "importance": "required", "years": 3},
            {"std_name": "沟通能力", "category": "soft_skill", "weight": 0.5,
             "required_level": 3, "importance": "preferred", "years": None},
        ]
        r = client.put(f"/api/admin/models/{mid}", json={"items": items}, headers=headers)
        assert r.status_code == 422, r.text


def test_update_model_rejects_bad_importance() -> None:
    mid = _seed_draft_model()
    items = [
        {"std_name": "Python", "category": "hard_skill", "weight": 0.5,
         "required_level": 3, "importance": "bad", "years": 3},
        {"std_name": "沟通能力", "category": "soft_skill", "weight": 0.5,
         "required_level": 3, "importance": "preferred", "years": None},
    ]
    r = client.put(f"/api/admin/models/{mid}", json={"items": items}, headers=_admin_headers())
    assert r.status_code == 422, r.text


def test_update_model_rejects_negative_years() -> None:
    mid = _seed_draft_model()
    items = [
        {"std_name": "Python", "category": "hard_skill", "weight": 0.5,
         "required_level": 3, "importance": "required", "years": -1},
        {"std_name": "沟通能力", "category": "soft_skill", "weight": 0.5,
         "required_level": 3, "importance": "preferred", "years": None},
    ]
    r = client.put(f"/api/admin/models/{mid}", json={"items": items}, headers=_admin_headers())
    assert r.status_code == 422, r.text


def test_update_model_rejects_duplicate_std_name_same_category() -> None:
    mid = _seed_draft_model()
    items = [
        {"std_name": "Python", "category": "hard_skill", "weight": 0.5,
         "required_level": 3, "importance": "required", "years": 3},
        {"std_name": "Python", "category": "hard_skill", "weight": 0.5,
         "required_level": 3, "importance": "required", "years": 3},
    ]
    r = client.put(f"/api/admin/models/{mid}", json={"items": items}, headers=_admin_headers())
    assert r.status_code == 400, r.text


def test_update_model_preserves_weight_sum_check() -> None:
    mid = _seed_draft_model()
    items = [
        {"std_name": "Python", "category": "hard_skill", "weight": 0.5,
         "required_level": 3, "importance": "required", "years": 3},
    ]
    r = client.put(f"/api/admin/models/{mid}", json={"items": items}, headers=_admin_headers())
    assert r.status_code == 400, r.text


def test_update_model_rejects_nan_weight_http() -> None:
    """HTTP 层 NaN 用例：raw content 提交 NaN 字面量（httpx json= 对 NaN 抛 ValueError
    allow_nan=False）——NaN 权重不得落库（解析期拒绝；响应 500 因 Starlette
    JSONResponse 无法序列化 input=nan，故断言「非 200 且 competency_item 不被污染」）。"""
    mid = _seed_draft_model()
    headers = _admin_headers()
    headers["Content-Type"] = "application/json"
    body = ('{"items": [{"std_name": "Python", "category": "hard_skill", "weight": NaN,'
            ' "required_level": 3, "importance": "required", "years": 3},'
            ' {"std_name": "沟通能力", "category": "soft_skill", "weight": 0.5,'
            ' "required_level": 3, "importance": "preferred", "years": null}]}')
    r = client.put(f"/api/admin/models/{mid}", content=body, headers=headers)
    assert r.status_code != 200, r.text
    rows = _q("SELECT weight FROM competency_item WHERE model_id=?", (mid,))
    assert len(rows) == 1
    assert rows[0]["weight"] == 0.5


def test_update_model_accepts_valid_edit() -> None:
    mid = _seed_draft_model()
    items = _valid_items()
    r = client.put(f"/api/admin/models/{mid}", json={"items": items}, headers=_admin_headers())
    assert r.status_code == 200, r.text
    # competency_item 表按 items 重建（2 行，与提交一致）
    rows = _q(
        "SELECT std_name, category, weight FROM competency_item WHERE model_id=? ORDER BY std_name",
        (mid,),
    )
    assert [row["std_name"] for row in rows] == ["Python", "沟通能力"]
    assert sum(row["weight"] for row in rows) == 1.0
    # WR-04：编辑后 model_json 保留 position_id/version 等非 items 元数据（不因
    # ModelUpdateBody 仅声明 items + Pydantic extra='ignore' 被丢弃）
    mrow = _q("SELECT position_id, model_json FROM competency_model WHERE model_id=?", (mid,))[0]
    model_json = json.loads(mrow["model_json"])
    assert model_json.get("position_id") == mrow["position_id"], model_json
    assert model_json.get("version") == 1, model_json
