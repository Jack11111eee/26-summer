"""gate 判定规则重设计测试（U3——SSOT §16.2 资格条件的判定规则，2026-09-09）。

覆盖面（工单五任务 × 讨论稿验收 13/14/15）：
  1) 数值方向（验收 14）：「30 岁以下」+ 35 → UNSATISFIED；「30 岁以上」+ 35 →
     SATISFIED；方向解析不出 → PENDING_CONFIRMATION；旧 params 无 operator →
     gte 兼容（compare_number 直测）
  2) 合并限定保留（验收 15）：「本科及以上学历」+「全日制本科学历及以上」不合并
  3) 专项经验（验收 13）：10 年通用年限 vs「NLP相关经验」/「CAD使用经验」→
     PENDING_CONFIRMATION（不自动通过）；通用措辞维持现状
  4) 资格四状态：gate_items.status 四值 + passed 语义映射（PENDING→false +
     reason 前缀「待确认：」）；aggregate_session_scores 全链
  5) 表单校验强化：isfinite/bool/极端值拒绝（FORM_INVALID_NUMBER）；「其他」
     学历 → PENDING_CONFIRMATION

全程 LLM_PROVIDER=mock 离线；DB 临时文件。运行：cd server && python -m pytest test_gate_rules.py -v
"""
import json
import math
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_dir = tempfile.mkdtemp()
_main_db = os.path.join(_tmp_dir, "test_gate_rules.db")
os.environ["DB_PATH"] = _main_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import init_db, get_conn  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()  # 纯服务层测试（无 TestClient，不触发 startup）


def _q(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ---------- 1) 数值方向（SSOT §16.2「数值条件必须保存比较运算符」） ----------

def test_direction_parse_lt():
    """「30 岁以下」→ operator=lt（SSOT §16.2 例：「30 岁以下」=lt 30）。"""
    from server.services.facet import classify_facet
    f = classify_facet("年龄30岁以下", "qualification")
    assert f is not None and f["params"]["operator"] == "lt"
    assert f["params"]["threshold"] == 30.0


def test_direction_parse_gte_gt_lte_range():
    """方向词表：岁以上→gt、及以上→gte、不超过→lte、N~M→range。「以下/以上」
    整词含边界；「大于等于/不低于」复合词先于短前缀（大于/低于）命中。"""
    from server.services.facet import classify_facet
    cases = {
        "年龄30岁以上": "gt",
        "年龄45岁及以上": "gte",
        "每周出勤不超过5天": "lte",
        "年龄在30~45岁之间": "range",
        "年龄大于等于30岁": "gte",
        "年龄不低于30岁": "gte",
        "年龄小于30岁": "lt",
        "年龄大于30岁": "gt",
    }
    for name, expect_op in cases.items():
        f = classify_facet(name, "qualification")
        assert f is not None, f"{name} 应分类 number_range"
        assert f["params"]["operator"] == expect_op, f"{name} 期望 {expect_op}，实得 {f['params']['operator']}"


def test_direction_unparsed_pending():
    """方向解析不出（无方向词的裸数值断言）→ parsed:false + 派生 PENDING_CONFIRMATION，
    gate_reason 写「条件方向未能解析，需人工确认」（§16.2：无法解析方向不自动判定）。"""
    from server.services.facet import classify_facet, derive_gate_payload, PENDING
    f = classify_facet("年龄35岁", "qualification")
    assert f is not None, "裸数值+metric 应仍分类 number_range（分类不打回）"
    assert f["params"].get("parsed") is False, "无方向词应打 direction_unparsed 标记"
    assert f["params"]["operator"] == "gte", "无法识别方向的默认 gte（兼容存量）"
    items = [{"std_name": "年龄35岁", "category": "qualification",
              "facet_key": f["facet_key"], "facet_params_json": json.dumps(f["params"])}]
    out = derive_gate_payload({"number_age": 40}, items)
    assert out["年龄35岁"] == PENDING, "方向未解析不自动判定 → PENDING_CONFIRMATION"


def test_compare_number_operators():
    """compare_number 五运算符直测 + 旧 params 无 operator → gte 兼容（验收存量）。"""
    from server.services.facet import compare_number
    assert compare_number(35, {"threshold": 30, "operator": "lt"}) is False   # 30 岁以下 + 35
    assert compare_number(29, {"threshold": 30, "operator": "lt"}) is True
    assert compare_number(30, {"threshold": 30, "operator": "lte"}) is True   # 整词含边界
    assert compare_number(35, {"threshold": 30, "operator": "gt"}) is True   # 30 岁以上 + 35
    assert compare_number(30, {"threshold": 30, "operator": "gte"}) is True
    assert compare_number(38, {"threshold": 30, "upper": 45, "operator": "range"}) is True
    assert compare_number(46, {"threshold": 30, "upper": 45, "operator": "range"}) is False
    # 旧 params 无 operator → gte（2026-09-09 前存量数据不回填不迁移）
    assert compare_number(35, {"threshold": 30}) is True
    assert compare_number(29, {"threshold": 30}) is False
    # 缺边界 / 非数值 → False（保守）
    assert compare_number(35, {"threshold": None, "operator": "gte"}) is False
    assert compare_number("abc", {"threshold": 30, "operator": "gte"}) is False


def test_derive_number_by_direction():
    """验收 14 全链（派生端）：「30 岁以下」输入 35 → False（UNSATISFIED——明确未满足，
    非待确认）；「30 岁以上」输入 35 → True（SATISFIED）。"""
    from server.services.facet import classify_facet, derive_gate_payload
    items = []
    for name in ("年龄30岁以下", "年龄30岁以上"):
        f = classify_facet(name, "qualification")
        items.append({"std_name": name, "category": "qualification",
                      "facet_key": f["facet_key"], "facet_params_json": json.dumps(f["params"])})
    out = derive_gate_payload({"number_age": 35}, items)
    assert out == {"年龄30岁以下": False, "年龄30岁以上": True}


# ---------- 2) 合并限定保留（SSOT §16.2「合并限定保留」） ----------

def _seed_position_with_jds(items_per_jd: list[list[dict]]) -> str:
    """建 active 岗位 + 多条 parsed JD（std_items_json 注入）。返回 position_id。"""
    pid = new_id("pos")
    conn = get_conn()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "gate_rules 测试岗", "active", now_iso()),
    )
    conn.commit()
    conn.close()
    for items in items_per_jd:
        jd_id = new_id("jd")
        conn = get_conn()
        conn.execute(
            "INSERT INTO jd_record(jd_id, position_id, job_title, company, source_type,"
            " raw_text, std_items_json, status, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (jd_id, pid, None, None, "paste", "JD 原文",
             json.dumps(items, ensure_ascii=False), "parsed", now_iso()),
        )
        conn.commit()
        conn.close()
    return pid


def _qual(name, evidence="ev"):
    return {"name": name, "category": "qualification", "importance": "required",
            "required_level": None, "evidence": [evidence]}


def test_merge_fulltime_qualifier_not_merged():
    """验收 15：「本科及以上学历」与「全日制本科学历及以上」不再进同一合并组
    （学习形式限定词是指断言的组成部分——指纹增列限定集合，不同即不合并）。"""
    from server.services.aggregate import run_aggregate
    pid = _seed_position_with_jds([
        [_qual("本科及以上学历")],
        [_qual("全日制本科学历及以上")],
    ])
    mid = run_aggregate(pid, trigger_source="manual")
    items = [it for it in _q(
        "SELECT std_name, facet_key, facet_params_json FROM competency_item"
        " WHERE model_id=? AND category='qualification'", (mid,))]
    names = {it["std_name"] for it in items}
    assert names == {"本科及以上学历", "全日制本科学历及以上"}, (
        f"学习形式限定不一致不得合并（验收 15），实得 {names}")
    for it in items:
        assert it["facet_key"] == "education_degree"
        assert json.loads(it["facet_params_json"])["threshold"] == 1


def test_merge_same_qualifiers_still_merged():
    """限定集合一致的学历断言仍合并（不因新指纹全量误杀正常合并）。"""
    from server.services.aggregate import run_aggregate
    pid = _seed_position_with_jds([
        [_qual("本科及以上学历")],
        [_qual("本科或以上学历")],
    ])
    mid = run_aggregate(pid, trigger_source="manual")
    items = _q("SELECT std_name FROM competency_item WHERE model_id=?"
               " AND category='qualification'", (mid,))
    assert len(items) == 1, f"同断言无限定差异应合并，实得 {[i['std_name'] for i in items]}"


# ---------- 3) 专项经验与通用年限分离（SSOT §16.2「通用年限不证明专项年限」） ----------

def test_specialized_experience_detection():
    """专项/通用经验识别：技术词/英文命中 → 专项；通用措辞 → 通用；不明 → 专项
    （保守——宁可误判专项进待确认，也不放过通用年限误通过）。"""
    from server.services.aggregation import _is_specialized_experience
    # 专项（技术词）
    for name in ("NLP相关经验", "CAD使用经验", "模型部署经验", "算法研究经验",
                 "3D建模研发经验", "工业设计经验", "前端开发经验"):
        assert _is_specialized_experience(name) is True, name
    # 专项（英文/字母组合兜底）
    for name in ("ROS开发经验", "SLAM算法", "AIGC研发经验", "Gmapping相关开发经验"):
        assert _is_specialized_experience(name) is True, name
    # 通用（词表措辞）
    for name in ("工作经验", "工作年限", "相关工作经验", "开发经验", "项目经验"):
        assert _is_specialized_experience(name) is False, name


def test_gate_check_specialized_experience_pending():
    """验收 13：总年限 10 年使「NLP相关经验」「CAD使用经验」不再自动通过——
    _gate_check 返回 PENDING_CONFIRMATION + reason 写「专项经验需要专项事实，
    通用年限不适用」。"""
    from server.services.aggregation import _gate_check, GATE_PENDING
    for std_name in ("NLP相关经验", "CAD使用经验", "模型部署经验"):
        passed, reason, status = _gate_check(
            {"std_name": std_name, "category": "experience", "years": 3},
            {"years_of_experience": 10},
        )
        assert passed is False, f"{std_name} 不得由通用年限自动判通过（验收 13）"
        assert status == GATE_PENDING
        assert std_name in reason and "专项事实" in reason


def test_gate_check_general_experience_unchanged():
    """通用经验措辞维持现状：years_of_experience 与要求年限直接比较。"""
    from server.services.aggregation import _gate_check
    passed, reason, status = _gate_check(
        {"std_name": "工作经验", "category": "experience", "years": 3},
        {"years_of_experience": 10},
    )
    assert passed is True and status is None
    passed, _, _ = _gate_check(
        {"std_name": "相关工作经验", "category": "experience", "years": 3},
        {"years_of_experience": 2},
    )
    assert passed is False  # 明确未满足（UNSATISFIED——非待确认）


def test_gate_check_number_direction_pending():
    """number_range 方向未解析经 _gate_check 兜底：PENDING + reason
    「条件方向未能解析，需人工确认」。"""
    from server.services.aggregation import _gate_check, GATE_PENDING
    item = {"std_name": "年龄35岁", "category": "qualification", "facet_key": "number_range"}
    passed, reason, status = _gate_check(
        item, {"年龄35岁": "PENDING_CONFIRMATION"})
    assert passed is False and status == GATE_PENDING
    assert "方向未能解析" in reason


# ---------- 4) 资格四状态（aggregate_session_scores 全链消费） ----------

def _seed_session_with_gate_items(items: list[dict]) -> tuple[str, str]:
    """建 confirmed 模型（gate items 全集）+ in_progress 会话。返回 (session_id, user_id)。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    sid = new_id("sess")
    uid = new_id("u")
    now = now_iso()
    conn.execute("INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
                 (pid, "四状态测试岗", "active", now))
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,1,?)", (uid, f"u{uid[-6:]}", "x", "candidate", now))
    model_json = {"position_id": pid, "version": 1, "items": items}
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)", (mid, pid, 1, "confirmed", json.dumps(model_json, ensure_ascii=False), now))
    for it in items:
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, gate,"
            " years, facet_key, facet_params_json) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("c"), mid, it["std_name"], it["category"], 1,
             it.get("years"), it.get("facet_key"),
             json.dumps(it["facet_params"], ensure_ascii=False)
             if it.get("facet_params") is not None else None))
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (sid, uid, pid, mid, 1, "in_progress", now, now))
    conn.commit()
    conn.close()
    return sid, uid


# gate items：专项经验 + 通用经验 + 方向未解析年龄 + 学历（旧链 payload 命中真值表）
_GATE_ITEMS = [
    {"std_name": "NLP相关经验", "category": "experience", "years": 3},
    {"std_name": "工作经验", "category": "experience", "years": 3},
    {"std_name": "年龄35岁", "category": "qualification", "facet_key": "number_range",
     "facet_params": {"threshold": 35.0, "unit": "岁", "metric": "age",
                      "operator": "gte", "parsed": False}},
    {"std_name": "本科及以上学历", "category": "qualification"},
]


def test_aggregate_session_scores_four_states():
    """gate_items 增 status 四状态 + passed 语义映射（任务 4 全链）：
    SATISFIED→true / UNSATISFIED→false / PENDING_CONFIRMATION→false +
    reason 前缀「待确认：」；原有字段（item_id/std_name/passed/reason/facet_key）
    全保留（Report.vue 现消费方不破坏）。"""
    from server.services.aggregation import aggregate_session_scores
    sid, uid = _seed_session_with_gate_items(_GATE_ITEMS)
    # 旧链 form_submission：通用年限 10 + 方向未解析项给 PENDING 哨兵 + 学历勾选
    conn = get_conn()
    conn.execute(
        "INSERT INTO form_submission(form_id, session_id, user_id, form_type, payload_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (new_id("form"), sid, uid, "gate_combined",
         json.dumps({"years_of_experience": 10, "年龄35岁": "PENDING_CONFIRMATION"}, ensure_ascii=False),
         now_iso()),
    )
    conn.commit()
    conn.close()

    agg = aggregate_session_scores(sid)
    gate = {g["std_name"]: g for g in agg["gate_items"]}
    # SATISFIED：通用经验 10 ≥ 3
    assert gate["工作经验"]["status"] == "SATISFIED" and gate["工作经验"]["passed"] is True
    # PENDING_CONFIRMATION：专项经验（验收 13）
    g = gate["NLP相关经验"]
    assert g["status"] == "PENDING_CONFIRMATION" and g["passed"] is False
    assert g["reason"].startswith("待确认：") and "专项事实" in g["reason"]
    # PENDING_CONFIRMATION：方向未解析（任务 1）
    g = gate["年龄35岁"]
    assert g["status"] == "PENDING_CONFIRMATION" and g["passed"] is False
    assert "方向未能解析" in g["reason"]
    # UNSATISFIED：qualification 缺字段（保守明确未满足）
    g = gate["本科及以上学历"]
    assert g["status"] == "UNSATISFIED" and g["passed"] is False
    assert g["reason"] == "本科及以上学历: 未提供或不达标"
    # 原有字段全保留（兼容红线——只增不改不删）
    for std_name, gi in gate.items():
        for field in ("item_id", "std_name", "passed", "reason", "facet_key"):
            assert field in gi, f"{std_name} 缺原有字段 {field}"
    # item_scores 侧 gate 行同步带 gate_status
    item_scores = {s["std_name"]: s for s in agg["item_scores"] if s.get("gate")}
    assert item_scores["NLP相关经验"]["gate_status"] == "PENDING_CONFIRMATION"
    assert item_scores["工作经验"]["gate_status"] == "SATISFIED"


def test_gate_status_enum_complete():
    """四状态枚举完整定义（NOT_APPLICABLE 本期只入枚举不生产——preferred gate 条件
    数据模型暂缺）；无表单 payload 的全缺答路径只产 SATISFIED/UNSATISFIED/
    PENDING_CONFIRMATION。"""
    from server.services.aggregation import GATE_STATUSES, aggregate_session_scores
    assert GATE_STATUSES == ("SATISFIED", "UNSATISFIED", "PENDING_CONFIRMATION", "NOT_APPLICABLE")
    sid, _uid = _seed_session_with_gate_items(_GATE_ITEMS)
    agg = aggregate_session_scores(sid)  # 无任何表单 payload（全缺答路径）
    produced = {g.get("status") for g in agg["gate_items"]}
    assert produced <= set(GATE_STATUSES), produced
    git = {g["std_name"]: g["status"] for g in agg["gate_items"]}
    assert git == {"NLP相关经验": "PENDING_CONFIRMATION",  # 专项（无表单年限也 PENDING）
                   "工作经验": "UNSATISFIED",              # 缺答明确未满足
                   "年龄35岁": "UNSATISFIED",              # 缺答（哨兵）明确未满足
                   "本科及以上学历": "UNSATISFIED"}


# ---------- 5) 表单校验强化（SSOT §16.2「服务端类型校验」） ----------

_FORM_FIELDS = [
    {"name": "years_of_experience", "label": "与岗位相关的工作年限（年）", "type": "number",
     "required": True, "max_len": 10},
    {"name": "number_age", "label": "年龄（周岁）", "type": "number", "required": True},
    {"name": "number_weekly_days", "label": "每周出勤天数（天）", "type": "number",
     "required": True},
]


def test_validate_number_isfinite_bool_extremes():
    """数字字段校验（任务 5）：isfinite / bool 拒绝 / 极端值拒绝 / 0 合法。"""
    from server.services.forms import _validate_payload
    FROM, NAME = "FORM_INVALID_NUMBER", None
    # 合法：0（零年经验合法不拒绝）与正常值
    assert _validate_payload(_FORM_FIELDS, {"years_of_experience": 0, "number_age": 30,
                                             "number_weekly_days": 3}) == (None, None)
    # 0 岁与 0 天也合法
    assert _validate_payload(_FORM_FIELDS, {"years_of_experience": 5, "number_age": 0,
                                             "number_weekly_days": 0}) == (None, None)
    # bool 拒绝（isinstance(True, int) 为真须显式排除）
    assert _validate_payload(_FORM_FIELDS, {"years_of_experience": True, "number_age": 30,
                                             "number_weekly_days": 3}) == (FROM, "years_of_experience")
    # 字符串数字拒绝（类型混淆）
    assert _validate_payload(_FORM_FIELDS, {"years_of_experience": "10", "number_age": 30,
                                             "number_weekly_days": 3}) == (FROM, "years_of_experience")
    # NaN / inf 拒绝（isfinite）
    assert _validate_payload(_FORM_FIELDS, {"years_of_experience": float("nan"), "number_age": 30,
                                             "number_weekly_days": 3}) == (FROM, "years_of_experience")
    assert _validate_payload(_FORM_FIELDS, {"years_of_experience": float("inf"), "number_age": 30,
                                             "number_weekly_days": 3}) == (FROM, "years_of_experience")
    # 极端值越界拒绝（years 0-60 / age 0-150 / weekly_days 0-7）
    assert _validate_payload(_FORM_FIELDS, {"years_of_experience": 61, "number_age": 30,
                                             "number_weekly_days": 3}) == (FROM, "years_of_experience")
    assert _validate_payload(_FORM_FIELDS, {"years_of_experience": -1, "number_age": 30,
                                             "number_weekly_days": 3}) == (FROM, "years_of_experience")
    assert _validate_payload(_FORM_FIELDS, {"years_of_experience": 5, "number_age": 151,
                                             "number_weekly_days": 3}) == (FROM, "number_age")
    assert _validate_payload(_FORM_FIELDS, {"years_of_experience": 5, "number_age": 30,
                                             "number_weekly_days": 8}) == (FROM, "number_weekly_days")
    # 范围边界合法（60/150/7 各自上界）
    assert _validate_payload(_FORM_FIELDS, {"years_of_experience": 60, "number_age": 150,
                                             "number_weekly_days": 7}) == (None, None)
    assert math.isfinite(0)  # 0 是有限数（同语义自证）


def test_education_other_option_pending():
    """「其他」学历出口（任务 5）：选项渲染五档 + derive 进 PENDING_CONFIRMATION
    （不参与档序判定，gate_reason 写「学历为其他情况，需人工确认」）。"""
    from server.services.facet import classify_facet, derive_gate_payload, EDU_OTHER_OPTION, PENDING
    # 渲染选项含「其他」出口（forms._FACET_SELECT_FIELDS）
    from server.services.forms import _FACET_SELECT_FIELDS
    options = _FACET_SELECT_FIELDS["education_degree"][2]
    assert options == ["专科", "本科", "硕士", "博士", EDU_OTHER_OPTION]
    # derive：其他 → PENDING（不自动判过/不过）
    f = classify_facet("本科及以上学历", "qualification")
    items = [{"std_name": "本科及以上学历", "category": "qualification",
              "facet_key": "education_degree", "facet_params_json": json.dumps(f["params"])}]
    out = derive_gate_payload({"education_degree": EDU_OTHER_OPTION}, items)
    assert out["本科及以上学历"] == PENDING
    # _gate_check 兜底：PENDING 哨兵 → 待确认 reason
    from server.services.aggregation import _gate_check, GATE_PENDING
    passed, reason, status = _gate_check(
        {"std_name": "本科及以上学历", "category": "qualification",
         "facet_key": "education_degree"},
        {"本科及以上学历": PENDING})
    assert passed is False and status == GATE_PENDING
    assert "其他情况" in reason and "人工确认" in reason


# ---------- 6) 旧 params 兼容（facet 打标列存量子集） ----------

def test_old_params_without_operator_gte_compat():
    """旧 params 无 operator（存量 facet_params_json）→ derive 按 gte 兼容
    （不回填不迁移；已 confirmed 模型不重打标）。"""
    from server.services.facet import derive_gate_payload
    items = [{"std_name": "年龄30岁以上", "category": "qualification",
              "facet_key": "number_range",
              "facet_params_json": json.dumps({"threshold": 30.0, "unit": "岁", "metric": "age"})}]
    # 旧存量：30 岁输入（gte 语义边界含）→ True；35 → True；29 → False
    assert derive_gate_payload({"number_age": 30}, items) == {"年龄30岁以上": True}
    assert derive_gate_payload({"number_age": 35}, items) == {"年龄30岁以上": True}
    assert derive_gate_payload({"number_age": 29}, items) == {"年龄30岁以上": False}
