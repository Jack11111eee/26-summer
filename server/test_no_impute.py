"""U4 无补算/测评范围/无综合分契约测试（SSOT §20.1/§20.1.A/§20.3/§20.4，2026-09-09）。

覆盖：
- 补算消失（验收 9 前半）：11 项观测 + 286 项缺失 → 无 actual_level=3.41 补算行；
- unmeasured_ratio > 0.2 → total_score None + PROVISIONAL + review_reason_code
  =UNMEASURED_RATIO_HIGH（验收 12 核心）；
- 覆盖率五指标字段齐全、分母含 required（验收 7：7/7 必备不漏算）；
- in_scope=0 条目不进总分与覆盖率、报告可区分（report role="reference"）；
- 存量旧报告（imputed 形态行）读取不受影响（API 回放）；
- report_checks ① 对 None 总分跳过。

全程 LLM_PROVIDER=mock 离线运行；DB 用 conftest 临时库（gsd-test- 前缀）。
运行：cd server && python -m pytest test_no_impute.py -v
"""
import json
import os
import sys

import pytest

# 必须在 import server 之前设环境变量（config 在 import 时读取）——conftest 已
# setdefault mock 三件套，此处仅保底（同文件级纪律）
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("JWT_SECRET", "test-secret")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import get_conn, init_db  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.aggregation import aggregate_session_scores  # noqa: E402
from server.services.report import generate_report  # noqa: E402
from server.services.report_checks import _run_consistency_checks  # noqa: E402

init_db()  # TestClient 不触发 startup，显式建表（幂等）
client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _seed_session(items: list[dict]) -> tuple[str, list[str]]:
    """造 position + model + competency_item + session，返回 (session_id, item_ids)。

    items: list of {std_name, category, importance, weight, required_level?, gate?,
    in_scope?}（required_level 默认 3，gate 默认 0，in_scope 默认 NULL=1）。
    不插 question_score——由调用方决定观测形态。
    """
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "AI 算法工程师", "active", now),
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
            " importance, weight, gate, in_scope) VALUES(?,?,?,?,?,?,?,?,?)",
            (iid, mid, it["std_name"], it["category"],
             it.get("required_level", 3), it["importance"], it["weight"],
             int(it.get("gate", 0)), it.get("in_scope")),
        )
    uid = new_id("u")
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,1,?)",
        (uid, uid, "hash", "candidate", now),
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


def _add_scored(conn, session_id: str, item_id: str, level: int) -> None:
    conn.execute(
        "INSERT INTO question_score(score_id, session_id, question_id, item_id, score_final,"
        " score_state, created_at) VALUES(?,?,?,?,?,?,?)",
        (new_id("qs"), session_id, None, item_id, level, "SCORED", now_iso()),
    )


# ============ 验收 9 前半：补算消失 ============

def test_no_imputation_11_observed_286_missing():
    """核验案例复现（修复文档 §十）：11 项观测 + 286 项缺失（scope=297，含 7 required
    全观测）→ 无任何 actual_level=3.41 式补算行；缺失项 actual_level=None、
    status=UNMEASURED、score=None。"""
    # 7.required 全观测 + 4 项普通观测 = 11 观测；286 项缺失（scope=297）
    items = []
    for i in range(7):
        items.append({"std_name": f"必备能力{i}", "category": "hard_skill",
                      "importance": "required", "weight": 0.01})
    items.append({"std_name": "Python", "category": "hard_skill",
                  "importance": "preferred", "weight": 0.02})
    items.append({"std_name": "机器学习", "category": "hard_skill",
                  "importance": "preferred", "weight": 0.02})
    items.append({"std_name": "深度学习", "category": "hard_skill",
                  "importance": "preferred", "weight": 0.02})
    items.append({"std_name": "沟通能力", "category": "soft_skill",
                  "importance": "preferred", "weight": 0.02})
    for i in range(286):
        items.append({"std_name": f"长尾能力{i}", "category": "hard_skill",
                      "importance": "plus", "weight": 0.001})
    session_id, item_ids = _seed_session(items)
    conn = get_conn()
    for iid in item_ids[:11]:  # 前 11 项（7 required + 4 普通）有观测
        _add_scored(conn, session_id, iid, 3)
    conn.commit()
    conn.close()

    agg = aggregate_session_scores(session_id)

    # 无任何补算行：全部缺失项 actual_level=None（不接受任何 3.41 式统一值）
    assert all(
        it["actual_level"] is None
        for it in agg["item_scores"] if it["item_id"] in set(item_ids[11:])
    ), "缺失项不得有个人等级（§20.1 作废比例补算）"
    assert all(
        it["actual_level"] is not None
        for it in agg["item_scores"] if it["item_id"] in set(item_ids[:11])
    ), "已观测项应有等级"
    # 缺失项 UNMEASURED 标记
    unmeasured = [it for it in agg["item_scores"] if it.get("status") == "UNMEASURED"]
    assert len(unmeasured) == 286
    for it in unmeasured:
        assert it["score"] is None and it["no_data"] is True

    # 验收 12 核心：286/297 ≈ 0.963 > 0.2 → total_score None + 复核原因单列
    assert agg["total_score"] is None, "未测量比例超阈 → 无综合分（不以 0 冒充）"
    assert agg["provisional"] is True
    assert agg["review_status"] == "HUMAN_REVIEW_REQUIRED"
    assert agg["review_reason_code"] == "UNMEASURED_RATIO_HIGH"

    # 覆盖率五指标（验收 7：7/7 必备不漏算——分母含 required）
    cov = agg["coverage"]
    assert cov["observed_items"] == 11
    assert cov["scope_items"] == 297
    assert cov["measured_items"] == 11
    assert cov["required_covered"] == 7
    assert cov["required_total"] == 7, "7 个必备项不漏算（作废排 required 的旧分母）"
    assert cov["unmeasured_count"] == 286
    assert cov["weight_coverage"] is not None and 0 < cov["weight_coverage"] < 1
    assert "missing_reasons" in cov

    # 优势/短板不含未测项（无 gap）
    for w in agg["strengths"] + agg["weaknesses"]:
        assert w["item_id"] in set(item_ids[:11]), "未测项不进优势/短板（验收 9）"


# ============ 验收 12：无综合分契约贯通 ============

def test_full_report_chain_no_total_score():
    """报告链贯通：unmeasured_ratio > 0.2 的会话 generate_report → report 行
    total_score=NULL（DB 层）+ report_json.total_score=null + review_reason_code
    透传（接口序列化一致）。"""
    items = [
        {"std_name": "Python", "category": "hard_skill",
         "importance": "preferred", "weight": 0.5},
    ]
    for i in range(9):
        items.append({"std_name": f"能力{i}", "category": "hard_skill",
                      "importance": "plus", "weight": 0.05})
    session_id, item_ids = _seed_session(items)
    conn = get_conn()
    _add_scored(conn, session_id, item_ids[0], 4)  # 仅 1/10 观测 → 比例 0.9 > 0.2
    conn.commit()
    conn.close()

    report = generate_report(session_id)
    # 报告生成成功（非 FAILED——无综合分是合法状态不是错误）
    assert report["report_status"] in ("PROVISIONAL", "READY"), report
    assert report["total_score"] is None, "report_json.total_score 应为 null"
    assert report["review_reason_code"] == "UNMEASURED_RATIO_HIGH"

    # DB 层：report 行 total_score 为 NULL（非 0——不以 0 冒充）
    rows = _q("SELECT total_score, report_status FROM report WHERE session_id=?", (session_id,))
    assert rows and rows[-1]["total_score"] is None
    assert rows[-1]["report_status"] == "PROVISIONAL"

    # 接口序列化（§20.3 各接口一致）：report_json.total_score=null 即 API 返回值
    # ——本数据面断言与 test_history_row_null_total_score / 兼容回放测试共同覆盖。


def test_report_checks_skip_recompute_when_none():
    """report_checks ① 适配：total_score=None 的 agg → 跳过数字可重算校验（无值
    无可重算，不虚构 0 分参与比较）；有值时校验照常工作。"""
    session_id, _ = _seed_session([
        {"std_name": "沟通能力", "category": "soft_skill",
         "importance": "preferred", "weight": 0.2},
    ])
    # None 总分：① 跳过（不报「总分不可重算」）
    agg_none = {
        "total_score": None,
        "item_scores": [
            {"score": None, "weight": 0.2, "status": "UNMEASURED"},
        ],
        "provisional": True,
        "review_status": "HUMAN_REVIEW_REQUIRED",
        "review_reason_code": "UNMEASURED_RATIO_HIGH",
        "missing_warnings": [],
        "observation_status": None,
    }
    errors = _run_consistency_checks(agg_none, session_id)
    assert not any("总分不可重算" in e for e in errors), f"①应对 None 跳过：{errors}"
    # 有值照常：篡改 total_score → 报错
    agg_num = {
        "total_score": 50.0,
        "item_scores": [{"score": 10.0, "weight": 0.2}],
        "provisional": False,
        "review_status": None,
        "missing_warnings": [],
        "observation_status": None,
    }
    errors = _run_consistency_checks(agg_num, session_id)
    assert any("总分不可重算" in e for e in errors)


def test_report_checks_reason_code_contract():
    """⑥ 扩展：review_reason_code=UNMEASURED_RATIO_HIGH 但顶层未满足无综合分契约
    （total_score 有值/un-provisional）→ 校验报错；契约完整则过。"""
    session_id, _ = _seed_session([
        {"std_name": "沟通能力", "category": "soft_skill",
         "importance": "preferred", "weight": 0.2},
    ])
    bad = {
        "total_score": 66.6,  # 有综合分但报 UNMEASURED_RATIO_HIGH → 契约矛盾
        "item_scores": [{"score": 66.6, "weight": 0.2}],
        "provisional": True,
        "review_status": "HUMAN_REVIEW_REQUIRED",
        "review_reason_code": "UNMEASURED_RATIO_HIGH",
        "missing_warnings": [],
        "observation_status": None,
        "unmeasured_ratio": 0.9,  # U6 ⑨：ratio 键齐（code 与比例自洽）
    }
    reason = "UNMEASURED_RATIO_HIGH：超阈"
    errors = _run_consistency_checks(bad, session_id, review_request_reason=reason)
    assert any("UNMEASURED_RATIO_HIGH" in e for e in errors), errors
    good = dict(bad)
    good["total_score"] = None
    good["item_scores"] = [{"score": None, "weight": 0.2}]
    assert not any("UNMEASURED_RATIO_HIGH" in e for e in _run_consistency_checks(
        good, session_id, review_request_reason=reason))


# ============ 验收 7/§20.4：覆盖率五指标 ============

def test_coverage_five_metrics_boundary():
    """覆盖率五指标齐全 + 分母含 required + 分母为 0 → 比率 null（不适用）。

    场景 a：2 required（1 观测）+ 1 preferred（0 观测）——必备项不从分母排除；
    场景 b：全 reference（in_scope=0）→ scope=0 → weight_coverage=null。
    """
    # a. required 进分母：7/7 必备模式
    items = [
        {"std_name": "必备A", "category": "hard_skill", "importance": "required", "weight": 0.3},
        {"std_name": "必备B", "category": "hard_skill", "importance": "required", "weight": 0.3},
        {"std_name": "普通A", "category": "soft_skill", "importance": "preferred", "weight": 0.4},
    ]
    session_id, item_ids = _seed_session(items)
    conn = get_conn()
    _add_scored(conn, session_id, item_ids[0], 4)  # 仅必备A 观测
    conn.commit()
    conn.close()
    agg = aggregate_session_scores(session_id)
    cov = agg["coverage"]
    assert set(cov.keys()) == {
        "answered_questions", "planned_questions", "observed_items", "scope_items",
        "measured_items", "weight_coverage", "required_covered", "required_total",
        "unmeasured_count", "missing_reasons",
    }, f"coverage 键集应恰为五指标十键：{sorted(cov.keys())}"
    assert cov["observed_items"] == 1
    assert cov["scope_items"] == 3, "分母含 required（作废排必备旧口径，验收 7）"
    assert cov["required_covered"] == 1
    assert cov["required_total"] == 2
    assert cov["unmeasured_count"] == 2
    # 已测权重 / 范围权重 = 0.3/1.0
    assert cov["weight_coverage"] == 0.3

    # b. 空 scope（全 reference）：比率字段 null 显不适用
    session_id2, _ = _seed_session([
        {"std_name": "资料项A", "category": "hard_skill", "importance": "plus",
         "weight": 0.1, "in_scope": 0},
    ])
    agg2 = aggregate_session_scores(session_id2)
    cov2 = agg2["coverage"]
    assert cov2["scope_items"] == 0
    assert cov2["weight_coverage"] is None, "分母为零显示不适用（null）而非 0%/100%"
    assert cov2["unmeasured_count"] == 0
    # scope=0 → 门控不触发（比例定义域外），不至于误报 NO_VALID/无综合分
    # （模型空 scope 为数据面边界——无计分项时无门控意义）


# ============ §20.1.A：in_scope 范围分流 ============

def test_in_scope_zero_excluded_from_score_and_coverage():
    """in_scope=0 条目：不进总分、不进覆盖率分母、item_scores 标 role="reference"
    （报告可区分）；NULL 视为 1（存量默认正式范围）。"""
    items = [
        {"std_name": "Python", "category": "hard_skill",
         "importance": "preferred", "weight": 0.5, "in_scope": 1},
        {"std_name": "生物背景", "category": "experience",
         "importance": "plus", "weight": 0.3, "in_scope": 0},
        {"std_name": "海外教育背景", "category": "experience",
         "importance": "plus", "weight": 0.2, "in_scope": 0},
        {"std_name": "NULL范围项", "category": "hard_skill",
         "importance": "preferred", "weight": 0.5},  # in_scope 不写 → NULL 视为 1
    ]
    session_id, item_ids = _seed_session(items)
    conn = get_conn()
    _add_scored(conn, session_id, item_ids[0], 5)
    # 给 reference 项也塞一条 SCORED——验证即使有分数记录也不进观察/覆盖率
    _add_scored(conn, session_id, item_ids[1], 4)
    conn.commit()
    conn.close()

    agg = aggregate_session_scores(session_id)

    # role="reference" 标记（报告可区分——§20.1.A 三类条目之 reference-only）
    by_id = {it["item_id"]: it for it in agg["item_scores"]}
    ref_a = by_id[item_ids[1]]
    ref_b = by_id[item_ids[2]]
    assert ref_a["role"] == "reference" and ref_b["role"] == "reference"
    # reference 不出等级、不进总分（score=None）
    assert ref_a["actual_level"] is None and ref_a["score"] is None
    # NULL 视为 1：items[3] 无 in_scope → 计入 scope
    assert "role" not in by_id[item_ids[3]] or by_id[item_ids[3]].get("role") != "reference"

    # 覆盖率分母不含 reference（scope=2：Python + NULL范围项；2 个 reference 出局）
    cov = agg["coverage"]
    assert cov["scope_items"] == 2
    assert cov["observed_items"] == 1, "reference 项的 SCORED 不进观察覆盖"
    assert cov["unmeasured_count"] == 1

    # unmeasured_ratio = 1/2 = 0.5 > 0.2 → 无综合分（reference 缺席不算未测量）
    assert agg["total_score"] is None
    assert agg["review_reason_code"] == "UNMEASURED_RATIO_HIGH"


def test_in_scope_zero_not_in_report_radar_or_strengthen():
    """generate_report 全链：reference 项不进雷达（actual_level=None 天然排除）、
    不进优势短板（无 gap），item_details 保留 role 标记供前端区分。"""
    items = [
        {"std_name": "Python", "category": "hard_skill",
         "importance": "preferred", "weight": 0.7, "in_scope": 1},
        {"std_name": "长尾资料", "category": "hard_skill",
         "importance": "plus", "weight": 0.3, "in_scope": 0},
    ]
    session_id, item_ids = _seed_session(items)
    conn = get_conn()
    _add_scored(conn, session_id, item_ids[0], 5)
    conn.commit()
    conn.close()

    report = generate_report(session_id)
    # 雷达只含 Python（reference actual_level=None 不进雷达）
    names = [ind["name"] for ind in report["radar_data"]["indicators"]]
    assert names == ["Python"], names
    # item_details 保留 role（报告可区分）
    det = {it["item_id"]: it for it in report["item_details"]}
    assert det[item_ids[1]]["role"] == "reference"
    # 比例 0/1=0 ≤ 0.2 → 有总分（仅 Python：0.7×1.0×100=70）
    assert report["total_score"] is not None
    assert abs(report["total_score"] - 70.0) < 0.01


# ============ 旧报告兼容（红线）：imputed 形态存量行不受影响 ============

def test_old_report_with_imputed_rows_still_readable():
    """存量旧报告 JSON（含 imputed=true/score 数值的补算形态行）读取不受影响——
    API 层回放照常返回字段（只读按旧口径解释，不重算不迁移，§20.1 过渡期）。

    手工插入 imputed 形态 report 行（模拟 2026-09-09 前生成的报告）→ get_report
    返回原 JSON（imputed 字段透传出）。"""
    # 模拟旧报告 JSON：item_details 行含 imputed=True + actual_level=3.41 补算值
    old_json = {
        "report_id": "rpt_old",
        "session_id": "whatever",
        "total_score": 60.24,
        "item_details": [
            {"item_id": "c_old1", "std_name": "Python", "actual_level": 4.0,
             "imputed": False, "score": 52.5, "gate": False, "gap": -1.0},
            {"item_id": "c_old2", "std_name": "沟通能力", "actual_level": 3.41,
             "imputed": True, "score": 18.9, "gate": False, "gap": 0.59},
        ],
        "coverage": {
            "observed_count": 1, "imputed_count": 345, "total_measureable": 356,
            "coverage_ratio": 0.0028, "missing_reasons": [],
        },
        "review_status": None,
        "provisional": False,
    }
    # 完整外键链（report.session_id → session → model）
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    uid = new_id("u")
    sid = new_id("as")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "兼容岗", "active", now),
    )
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status,"
        " model_json, created_at) VALUES(?,?,1,'confirmed','{}',?)",
        (mid, pid, now),
    )
    conn.execute(
        "INSERT INTO competency_item(item_id, model_id, std_name, category,"
        " required_level, importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
        ("c_old1", mid, "Python", "hard_skill", 3, "required", 0.3, 0),
    )
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,1,?)", (uid, uid, "hash", "candidate", now),
    )
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (sid, uid, pid, mid, 1, "completed", now, now),
    )
    report_id = new_id("rpt")
    conn.execute(
        "INSERT INTO report(report_id, session_id, total_score, gate_passed, report_json,"
        " report_status, review_status, version, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (report_id, sid, 60.24, 1, json.dumps(old_json, ensure_ascii=False),
         "PUBLISHED", "NONE", 1, now),
    )
    conn.commit()
    conn.close()

    # API 层回放（admin 读豁免——先造 admin；loader 会合并 report_status/version）
    from passlib.context import CryptContext
    conn = get_conn()
    if conn.execute("SELECT 1 FROM user WHERE username='admin'").fetchone() is None:
        pwd_ctx = CryptContext(schemes=["bcrypt"])
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (new_id("u"), "admin", pwd_ctx.hash("admin"), "admin", now_iso()),
        )
        conn.commit()
    conn.close()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['token']}"}

    # 按 id 读取：imputed 形态字段原样透传（旧 JSON 兼容红线）
    r = client.get(f"/api/assessment/reports/{report_id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    imp = [it for it in body["item_details"] if it.get("imputed")]
    assert imp and imp[0]["actual_level"] == 3.41, "旧补算行应原样透传"
    assert body["total_score"] == 60.24
    assert body["coverage"]["imputed_count"] == 345

    # by-session 读取同构（最新行即该行——接口序列化统一）
    r = client.get(f"/api/assessment/reports/by-session/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["item_details"][1]["imputed"] is True

    # 历史列表（§20.3 接口面）：completed 行显示该报告 total_score 有值照常、None → null
    r = client.get("/api/assessment/sessions", headers=headers)
    assert r.status_code == 200, r.text
    rows = [s for s in r.json()["items"] if s["session_id"] == sid]
    if rows:  # admin 读豁免可见（hidden 行不滤）
        assert rows[0]["total_score"] == 60.24


# ============ 历史行无综合分（验收 12 接口面）============

def test_history_row_null_total_score():
    """历史列表行 total_score：无综合分 → None（History.vue 显示「未形成综合分」；
    不得以 0 冒充）。造一场 unmeasured_ratio>0.2 完成会话 + 生成报告后以本人查列表。"""
    session_id, _ = _seed_session([
        {"std_name": "Python", "category": "hard_skill",
         "importance": "preferred", "weight": 0.6},
        {"std_name": "未测A", "category": "soft_skill", "importance": "plus", "weight": 0.2},
        {"std_name": "未测B", "category": "soft_skill", "importance": "plus", "weight": 0.2},
    ])
    # 0/3 观测 → unmeasured_ratio=1.0 → NO_VALID_OBSERVATION + total None
    generate_report(session_id)

    # 以本人（candidate）登录查列表（list_sessions WHERE user_id=本人）
    from passlib.context import CryptContext
    pwd_ctx = CryptContext(schemes=["bcrypt"])
    conn = get_conn()
    uid = conn.execute(
        "SELECT s.user_id, u.username FROM assessment_session s"
        " JOIN user u ON u.user_id=s.user_id WHERE s.session_id=?", (session_id,)
    ).fetchone()
    # 种子用户密码哈希不可用（'hash'）——直接改成本测试密码
    conn.execute(
        "UPDATE user SET password_hash=? WHERE user_id=?",
        (pwd_ctx.hash("pw-u4-hist"), uid["user_id"]),
    )
    conn.commit()
    conn.close()
    r = client.post("/api/auth/login",
                    json={"username": uid["username"], "password": "pw-u4-hist"})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    r = client.get("/api/assessment/sessions", headers=headers)
    assert r.status_code == 200, r.text
    row = [s for s in r.json()["items"] if s["session_id"] == session_id]
    assert row, "本人历史列表应含该会话"
    assert row[0]["total_score"] is None, "无综合分历史行 total_score=None（不以 0 冒充）"
