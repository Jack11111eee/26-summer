"""Phase 5 报告契约测试：adjudicate 裁决 / IMPUTED 补算 / required 缺失 PROVISIONAL / O=∅ NO_VALID_OBSERVATION。

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db。
运行：cd server && python -m pytest test_phase5_report.py -v

纯函数（adjudicate/_impute_r/_normalize_score）懒导入：Task 2 先落地 adjudicate/
_normalize_score，Task 3 落地 _impute_r——懒导入让 Task 2 子集先可收集（同 05-01
_locate_span 先例）。
"""
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase5_report.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.aggregation import aggregate_session_scores  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _seed_session(items: list[dict]) -> tuple[str, list[str]]:
    """造 position + model + competency_item（含 importance）+ session，返回 (session_id, item_ids)。

    items: list of {std_name, category, importance, weight}（required_level 统一 3，gate 0）。
    只插结构行，不插 question_score——供「缺失」断言（无 SCORED 测量）。
    """
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "后端开发工程师", "active", now),
    )
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,1,'confirmed','{}',?)",
        (mid, pid, now),
    )
    item_ids: list[str] = []
    for it in items:
        iid = new_id("c")
        item_ids.append(iid)
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
            (iid, mid, it["std_name"], it["category"], 3, it["importance"], it["weight"], 0),
        )
    uid = new_id("u")
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,1,?)",
        (uid, "cand_report", "hash", "candidate", now),
    )
    session_id = new_id("as")
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id, model_version,"
        " status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (session_id, uid, pid, mid, 1, "completed", now, now),
    )
    conn.commit()
    conn.close()
    return session_id, item_ids


def test_adjudicate_conflict_lower():
    from server.services.aggregation import adjudicate

    # 重大冲突（差 3 ≥ 阈值 2）→ 取低 + 人工复核
    level, review = adjudicate([{"observed_level": 2}, {"observed_level": 5}])
    assert level == 2.0
    assert review is True

    # 一致场景 → round(mean, 2)，无人工复核
    level, review = adjudicate([{"observed_level": 4}, {"observed_level": 4}])
    assert level == 4.0
    assert review is False

    # 空列表 → (None, False)
    level, review = adjudicate([])
    assert level is None
    assert review is False


def test_impute_r_math():
    from server.services.aggregation import _impute_r

    # r = Σ w_i·s_i / Σ w_i，s_i=(score−1)/4
    r = _impute_r([{"weight": 0.5, "score": 5}, {"weight": 0.5, "score": 1}])
    assert abs(r - 0.5) < 1e-6  # (0.5*1.0 + 0.5*0.0)/1.0 = 0.5

    # weight 全 0 → den=0 → 不除零返回 None
    r = _impute_r([{"weight": 0.0, "score": 5}])
    assert r is None

    # 单观察 → r = 该观察自身归一化值 = (3−1)/4 = 0.5
    r = _impute_r([{"weight": 0.3, "score": 3}])
    assert abs(r - 0.5) < 1e-6


def test_impute_no_valid_observation():
    from server.services.aggregation import _impute_r

    # O=∅ → _impute_r 返回 None
    assert _impute_r([]) is None

    # 聚合层：preferred 缺失 + 无任何 SCORED → NO_VALID_OBSERVATION + HUMAN_REVIEW_REQUIRED
    session_id, _ = _seed_session([
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "preferred", "weight": 0.2},
    ])
    agg = aggregate_session_scores(session_id)
    assert agg["observation_status"] == "NO_VALID_OBSERVATION"
    assert agg["review_status"] == "HUMAN_REVIEW_REQUIRED"


def test_required_missing_provisional():
    # required 缺失（无 SCORED 行）→ item 标 provisional + 顶层 HUMAN_REVIEW_REQUIRED
    session_id, item_ids = _seed_session([
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.3},
    ])
    agg = aggregate_session_scores(session_id)
    assert agg["review_status"] == "HUMAN_REVIEW_REQUIRED"
    assert agg["provisional"] is True

    py_item = next(it for it in agg["item_scores"] if it["item_id"] == item_ids[0])
    assert py_item["provisional"] is True
    assert py_item["no_data"] is True
