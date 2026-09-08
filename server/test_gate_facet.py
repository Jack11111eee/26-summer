"""gate qualification facet 化测试（SSOT §8.1 工序⑤ / §16.1，2026-09-08）。

覆盖面（临时讨论稿 §6 测试口径）：
  1) 分类器：六类各覆盖 + 复合断言/经验类 → None + 词表边缘
  2) A 类断言等价合并：同断言不同措辞合并一行；词面近重复/复合断言不合并
  3) v2 渲染：SLAM 场景 7 std_name → facet 控件（enum select + checklist + number）；
     v1 快照已有 open 实例走旧链原样返回
  4) 派生：档序比较（985 满足 211 / 学历答档）：勾选组勾=是 / number 边界（=、>）
  5) 全链：聚合打标 → 渲染 → submit → gate 行结构化结果

全程 LLM_PROVIDER=mock 离线；DB 临时文件。运行：cd server && python -m pytest test_gate_facet.py -v
"""
import json
import os
import sqlite3
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_dir = tempfile.mkdtemp()
_main_db = os.path.join(_tmp_dir, "test_gate_facet.db")
os.environ["DB_PATH"] = _main_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import init_db, get_conn  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()  # 纯服务层测试（无 TestClient，不触发 startup）

# 讨论稿 §1 实测评场景（SLAM 融合开发岗，7 个 gate qualification std_name）
SLAM_ITEMS = [
    "本科及以上学历", "硕士及以上学历", "211硕士及以上学历",
    "计算机相关专业", "相关专业", "相关专业背景", "机器视觉/数学/电子计算机等相关专业",
]


# ---------- 1) 分类器（纯函数，无 DB） ----------

def _classify(std_name: str, category: str = "qualification"):
    from server.services.facet import classify_facet
    return classify_facet(std_name, category)


def test_classifier_education_degree():
    """学历链：档序 专科0→本科1→硕士2→博士3；同措辞多档取最低（宽读法）。"""
    assert _classify("本科及以上学历") == {"facet_key": "education_degree", "params": {"threshold": 1}}
    assert _classify("硕士及以上学历") == {"facet_key": "education_degree", "params": {"threshold": 2}}
    assert _classify("博士学历") == {"facet_key": "education_degree", "params": {"threshold": 3}}
    # 宽读法：「学士或硕士学位」→ 本科（多档取最低）
    assert _classify("学士或硕士学位") == {"facet_key": "education_degree", "params": {"threshold": 1}}
    # 无学历语境词的裸学历词不分类（勾选组 fallback——保守）
    assert _classify("硕士") is None
    assert _classify("硕士及以上") is None
    assert _classify("学历不限") is None


def test_classifier_school_tier():
    """院校档次：档序 普通0→211=1→985=2；「985/211」并读宽取 211；双一流视同 211。"""
    assert _classify("211院校毕业") == {"facet_key": "school_tier", "params": {"threshold": 1}}
    assert _classify("985院校毕业") == {"facet_key": "school_tier", "params": {"threshold": 2}}
    assert _classify("985/211院校") == {"facet_key": "school_tier", "params": {"threshold": 1}}
    assert _classify("双一流院校") == {"facet_key": "school_tier", "params": {"threshold": 1}}


def _cls(std_name):
    return _classify(std_name)


def test_classifier_composite_none():
    """复合断言（学历+院校两轴）：不分类整体勾选组（B2 已裁决行为）。"""
    assert _cls("211硕士及以上学历") is None
    assert _cls("985硕士学历") is None
    assert _cls("211本科学历及以上") is None


def test_classifier_english_level():
    """英语等级：四级4/六级6；能力词（口语听力写作）不成等级 → None。"""
    assert _cls("英语四级及以上") == {"facet_key": "english_level", "params": {"threshold": 4}}
    assert _cls("英语六级") == {"facet_key": "english_level", "params": {"threshold": 6}}
    assert _cls("CET6") == {"facet_key": "english_level", "params": {"threshold": 6}}
    assert _cls("英语四级或六级") == {"facet_key": "english_level", "params": {"threshold": 4}}  # 宽读低档
    assert _cls("英语能力优秀") is None
    assert _cls("英语口语流利") is None
    assert _cls("英语听力好") is None


def test_classifier_number_range():
    """数值断言：std_name 内嵌数字+量纲 → metric 阈值；解析不出 → None。"""
    f = _cls("年龄30岁以上")
    assert f == {"facet_key": "number_range", "params": {"threshold": 30.0, "unit": "岁", "metric": "age"}}
    f = _cls("每周出勤4天及以上")
    assert f == {"facet_key": "number_range", "params": {"threshold": 4.0, "unit": "天/周", "metric": "weekly_days"}}
    # 无数字 / 无 metric 词 → None（长尾勾选组）
    assert _cls("年龄三十岁以上") is None  # 中文数字不解析
    assert _cls("5年以上") is None  # 无 metric 词（经验类由 base 字段承载，不进分类器）


def test_classifier_major_group_and_experience():
    """专业组（勾选组无阈值）+ 经验类一律 None + 长尾 None。"""
    assert _cls("计算机相关专业") == {"facet_key": "major_group", "params": {}}
    assert _cls("相关专业背景") == {"facet_key": "major_group", "params": {}}
    assert _cls("机器视觉/数学/电子计算机等相关专业") == {"facet_key": "major_group", "params": {}}
    # experience 一律 None（年限由 years_of_experience base 字段承载）
    assert _classify("5年开发经验", "experience") is None
    assert _classify("本科及以上学历", "experience") is None
    # 长尾
    assert _cls("持有C1驾照") is None
    assert _cls("能适应出差") is None


# ---------- 2) A 类断言等价合并 ----------

def _seed_position_with_jds(items_per_jd: list[list[dict]]) -> str:
    """建 active 岗位 + 多条 parsed JD（std_items_json 注入）。返回 position_id。"""
    pid = new_id("pos")
    conn = get_conn()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "facet 测试岗", "active", now_iso()),
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


def _run_aggregate(pid: str) -> str:
    from server.services.aggregate import run_aggregate
    return run_aggregate(pid, trigger_source="manual")


def _items_of(model_id: str) -> list[dict]:
    conn = get_conn()
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT std_name, category, gate, facet_key, facet_params_json, occurrence_json"
            " FROM competency_item WHERE model_id=? ORDER BY std_name", (model_id,))]
    finally:
        conn.close()


def test_merge_equivalent_degree_same_assertion():
    """A 类合并核心：「本科及以上学历」+「全日制本科学历及以上」→ 一行（更窄措辞保留，
    jds/evidences 并集——r 与 occ 口径随并集走高）。"""
    pid = _seed_position_with_jds([
        [_qual("本科及以上学历")],
        [_qual("全日制本科学历及以上")],
    ])
    mid = _run_aggregate(pid)
    items = [it for it in _items_of(mid) if it["category"] == "qualification"]
    assert len(items) == 1, f"同断言不同措辞应合并为一行，实得 {[i['std_name'] for i in items]}"
    kept = items[0]
    # std_name 取更窄措辞（词更长）
    assert kept["std_name"] == "全日制本科学历及以上"
    assert kept["facet_key"] == "education_degree"
    assert json.loads(kept["facet_params_json"]) == {"threshold": 1}
    # evidences/jds 并集：occ=2（两个 JD）、r=1.0（两组各自 full-jd）
    occ = json.loads(kept["occurrence_json"])
    assert occ["occ"] == 2 and occ["r"] == 1.0


def test_merge_not_cross_facet_or_wordface():
    """不合并面：专业词面近重复（相关专业 vs 相关专业背景）不合并（B 类冻结裁决）；
    复合断言（211硕士及以上学历）不参与；不同档学历（本科 vs 硕士）不同断言不合并。"""
    pid = _seed_position_with_jds([
        [_qual("相关专业")],
        [_qual("相关专业背景")],
        [_qual("211硕士及以上学历")],
        [_qual("本科及以上学历"), _qual("硕士及以上学历")],
    ])
    mid = _run_aggregate(pid)
    names = {it["std_name"] for it in _items_of(mid) if it["category"] == "qualification"}
    # 4 组各自独立：相关专业 / 相关专业背景（词面近重复不合并）、
    # 211硕士及以上学历（复合断言不参与）、本科与硕士（不同断言）
    assert names == {"相关专业", "相关专业背景", "211硕士及以上学历",
                    "本科及以上学历", "硕士及以上学历"}


def test_merge_school_tier_and_english():
    """school_tier / english_level 同档合并；跨 facet 不合。"""
    pid = _seed_position_with_jds([
        [_qual("211院校毕业")],
        [_qual("211院校"), _qual("英语四级")],
        [_qual("CET4")],
    ])
    mid = _run_aggregate(pid)
    items = _items_of(mid)
    by_facet = {}
    for it in items:
        by_facet.setdefault(it["facet_key"] or "None", []).append(it["std_name"])
    assert len(by_facet["school_tier"]) == 1, "两个 211 断言应合并"
    assert len(by_facet["english_level"]) == 1, "四级×2 措辞（英语四级/CET4）应合并"
    assert by_facet["school_tier"] != by_facet["english_level"]


# ---------- 3) v2 渲染（SLAM 场景） ----------

def _seed_session_with_items(std_names: list[str]) -> tuple[str, str]:
    """建 confirmed 模型（gate qualification items 全集）+ 会话。返回 (session_id, user_id)。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    sid = new_id("sess")
    uid = new_id("u")
    now = now_iso()
    conn.execute("INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
                 (pid, "SLAM 融合开发", "active", now))
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,1,?)", (uid, f"u{uid[-6:]}", "x", "candidate", now))
    items = [{"std_name": sn, "category": "qualification", "gate": 1} for sn in std_names]
    model_json = {"position_id": pid, "version": 1, "items": items}
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)", (mid, pid, 1, "confirmed", json.dumps(model_json, ensure_ascii=False), now))
    for it in items:
        facet = _cls(it["std_name"])
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, gate,"
            " facet_key, facet_params_json) VALUES(?,?,?,?,?,?,?)",
            (new_id("c"), mid, it["std_name"], "qualification", 1,
             facet["facet_key"] if facet else None,
             json.dumps(facet["params"], ensure_ascii=False) if facet else None))
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (sid, uid, pid, mid, 1, "in_progress", now, now))
    conn.commit()
    conn.close()
    return sid, uid


def test_v2_render_slam_scenario():
    """SLAM 场景 7 std_name → v2 快照：年限 number + 学历 select + 勾选组
    （复合断言「211硕士及以上学历」按 B2 裁决归勾选组——清单 G16 的『档次 select』
    预期为讨论稿 §3.1.1 概念图，以 B2 显式行为定义与本测试为收口）。"""
    sid, _ = _seed_session_with_items(SLAM_ITEMS)
    conn = get_conn()
    try:
        from server.services.forms import render_form_instance
        form = render_form_instance(conn, sid)
        conn.commit()  # render 接 conn 不 commit（D-06）——测试侧显式提交落库
    finally:
        conn.close()

    fields = form["fields"]
    by_name = {f["name"]: f for f in fields}
    # base 字段（标签改版，name 不变）
    assert by_name["years_of_experience"]["label"] == "与岗位相关的工作年限（年）"
    assert by_name["years_of_experience"]["type"] == "number"
    # 学历 enum select：宿主 2 个（本科及以上/硕士及以上——A 类合并语义在聚合侧，
    # 此处为渲染侧同 facet 归并）
    edu = by_name.get("education_degree")
    assert edu is not None and edu["type"] == "select"
    assert edu["options"] == ["专科", "本科", "硕士", "博士"]
    assert set(edu["items"]) == {"本科及以上学历", "硕士及以上学历"}
    # 勾选组：复合断言 + 专业类共 5 项
    checked = by_name.get("checked")
    assert checked is not None and checked["type"] == "checklist"
    assert set(checked["options"]) == {
        "211硕士及以上学历", "计算机相关专业", "相关专业", "相关专业背景",
        "机器视觉/数学/电子计算机等相关专业"}
    assert checked["required"] is False  # 开放点 4：不做整组必填
    # 快照 schema_version=v2 落库
    row = _q("SELECT schema_version, status FROM form_instance WHERE session_id=?", (sid,))[0]
    assert row["schema_version"] == "v2" and row["status"] == "rendered"


def test_v2_render_enum_school_english():
    """school_tier / english_level / number_range 渲染形态。"""
    sid, _ = _seed_session_with_items(
        ["211院校毕业", "985院校毕业", "英语六级", "年龄30岁以上", "持有C1驾照"])
    conn = get_conn()
    try:
        from server.services.forms import render_form_instance
        form = render_form_instance(conn, sid)
        conn.commit()
    finally:
        conn.close()
    by_name = {f["name"]: f for f in form["fields"]}
    assert by_name["school_tier"]["options"] == ["其他（非 211/985）", "211", "985"]
    assert set(by_name["school_tier"]["items"]) == {"211院校毕业", "985院校毕业"}
    assert by_name["english_level"]["options"] == ["均未通过", "四级", "六级"]
    num = by_name.get("number_age")
    assert num is not None and num["type"] == "number"
    assert num["label"] == "年龄（周岁）"
    assert set(num["items"]) == {"年龄30岁以上"}
    assert set(by_name["checked"]["options"]) == {"持有C1驾照"}


def test_v1_snapshot_open_replay_old_chain():
    """v1 快照已有 open rendered 实例：render 复用原样返回（不迁移不重渲染，
    快照不可变语义）；submit 走旧链（payload 原样喂 _gate_check、原样落库）。"""
    sid, uid = _seed_session_with_items(["本科及以上学历"])
    # 直插 v1 快照 rendered 实例（v1 fields：二值 select 是/否）
    v1_fields = [
        {"name": "years_of_experience", "label": "工作年限（年）", "type": "number",
         "required": True, "max_len": 10},
        {"name": "本科及以上学历", "label": "本科及以上学历", "type": "select",
         "required": True, "options": ["是", "否"]},
    ]
    fi_id = new_id("fi")
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO form_instance(form_instance_id, session_id, form_type, schema_version,"
            " schema_snapshot, status, revision, created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (fi_id, sid, "gate_combined", "v1",
             json.dumps({"form_type": "gate_combined", "title": "资格核验", "fields": v1_fields},
                        ensure_ascii=False), "rendered", 1, now_iso()),
        )
        from server.services.forms import render_form_instance, validate_and_submit
        # ① render 复用 v1 实例（不重渲染 v2）
        form = render_form_instance(conn, sid)
        assert form["form_instance_id"] == fi_id
        names = [f["name"] for f in form["fields"]]
        assert names == ["years_of_experience", "本科及以上学历"], names
        # ② v1 payload 原样提交：本科及以上学历=是 → _gate_check 真值表命中
        result = validate_and_submit(conn, session_id=sid, form_instance_id=fi_id,
                                     payload={"years_of_experience": 5, "本科及以上学历": "是"},
                                     expected_revision=1,
                                     user={"user_id": uid})
        assert result["ok"] is True, result
        conn.rollback()  # 测试内不落库（复用已有行状态）
    finally:
        conn.close()


def _q(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ---------- 4) 派生 ----------

def _derive(ans: dict, items: list[dict]) -> dict:
    from server.services.facet import derive_gate_payload
    return derive_gate_payload(ans, items)


def _item_with_facet(std_name, facet_key, params):
    return {"std_name": std_name, "category": "qualification",
            "facet_key": facet_key, "facet_params_json": json.dumps(params) if params is not None else None}


def test_derive_education_chain():
    """硕士答学历 select：本科及以上 True、硕士及以上 True、博士要求 False。"""
    items = [
        _item_with_facet("本科及以上学历", "education_degree", {"threshold": 1}),
        _item_with_facet("硕士及以上学历", "education_degree", {"threshold": 2}),
        _item_with_facet("博士学历", "education_degree", {"threshold": 3}),
    ]
    out = _derive({"education_degree": "硕士"}, items)
    assert out == {"本科及以上学历": True, "硕士及以上学历": True, "博士学历": False}
    # 专科答档：全 False
    out = _derive({"education_degree": "专科"}, items)
    assert out == {"本科及以上学历": False, "硕士及以上学历": False, "博士学历": False}


def test_derive_school_tier_985_satisfies_211():
    """985 满足 211：985 答档 → 211 要求 True、985 要求 True；211 答档 → 985 要求 False。"""
    items = [
        _item_with_facet("211院校毕业", "school_tier", {"threshold": 1}),
        _item_with_facet("985院校毕业", "school_tier", {"threshold": 2}),
    ]
    out = _derive({"school_tier": "985"}, items)
    assert out == {"211院校毕业": True, "985院校毕业": True}
    out = _derive({"school_tier": "211"}, items)
    assert out == {"211院校毕业": True, "985院校毕业": False}
    out = _derive({"school_tier": "其他（非 211/985）"}, items)
    assert out == {"211院校毕业": False, "985院校毕业": False}


def test_derive_english_and_checklist():
    """英语等级档比较；勾选组勾=是（含 major_group 与长尾 NULL）。"""
    items = [
        _item_with_facet("英语四级", "english_level", {"threshold": 4}),
        _item_with_facet("英语六级", "english_level", {"threshold": 6}),
        _item_with_facet("计算机相关专业", "major_group", {}),
        _item_with_facet("持有C1驾照", None, None),
    ]
    out = _derive({"english_level": "四级", "checked": ["计算机相关专业"]}, items)
    assert out == {"英语四级": True, "英语六级": False,
                   "计算机相关专业": True, "持有C1驾照": False}


def test_derive_number_boundary():
    """number 边界：= 阈值通过（≥ 语义）、< 阈值不通过、缺答不通过。"""
    items = [_item_with_facet("年龄30岁以上", "number_range",
                              {"threshold": 30.0, "unit": "岁", "metric": "age"})]
    assert _derive({"number_age": 30}, items) == {"年龄30岁以上": True}   # 边界 =
    assert _derive({"number_age": 31}, items) == {"年龄30岁以上": True}   # >
    assert _derive({"number_age": 29}, items) == {"年龄30岁以上": False}  # <
    assert _derive({}, items) == {"年龄30岁以上": False}                  # 缺答 False（保守）


def test_derive_education_wideread_lowest_tier():
    """宽读法阈值合并：A 类合并场景派生（「学士或硕士学位」→ 本科要求）。"""
    items = [_item_with_facet("学士或硕士学位", "education_degree", {"threshold": 1})]
    assert _derive({"education_degree": "本科"}, items) == {"学士或硕士学位": True}
    assert _derive({"education_degree": "专科"}, items) == {"学士或硕士学位": False}


# ---------- 5) 全链：聚合打标 → v2 渲染 → submit → gate 行 ----------

def test_full_chain_render_submit_gate_rows():
    """聚合（facet 打标 + A 类合并）→ 建会话渲染 v2 → submit facet 答案 →
    gate 行结构化（真值表派生命中 True/False）→ payload 两段式可复现。"""
    # ① 聚合打标 + 合并（两个同断言本科 + 专业类 + 复合断言）
    pid = _seed_position_with_jds([
        [_qual("本科及以上学历", "e1")],
        [_qual("全日制本科学历及以上", "e2"), _qual("英语六级", "e3")],
        [_qual("计算机相关专业", "e4"), _qual("211硕士及以上学历", "e5")],
    ])
    mid = _run_aggregate(pid)

    # ② confirmed 模型 + 会话
    conn = get_conn()
    sid = new_id("sess")
    uid = new_id("u")
    now = now_iso()
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,1,?)", (uid, f"u{uid[-6:]}", "x", "candidate", now))
    conn.execute("UPDATE competency_model SET status='confirmed' WHERE model_id=?", (mid,))
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (sid, uid, pid, mid, 1, "in_progress", now, now))
    conn.commit()
    # ③ 渲染 v2
    from server.services.forms import render_form_instance, validate_and_submit
    form = render_form_instance(conn, sid)
    fields = {f["name"]: f for f in form["fields"]}
    assert set(fields) == {"years_of_experience", "education_degree", "english_level", "checked"}
    assert set(fields["education_degree"]["items"]) == {"全日制本科学历及以上"}  # A 类合并后唯一学历行
    fi_id = form["form_instance_id"]
    # ④ submit：本科 + 六级 + 勾专业；复合断言不勾（= 否）
    payload = {"years_of_experience": 6, "education_degree": "本科",
               "english_level": "六级", "checked": ["计算机相关专业"]}
    result = validate_and_submit(conn, session_id=sid, form_instance_id=fi_id,
                                 payload=payload, expected_revision=1,
                                 user={"user_id": uid})
    assert result["ok"] is True, result
    conn.commit()  # render/submit 接 conn 不 commit（D-06）——测试侧显式提交落库
    rows = _q("SELECT qs.gate_result, ci.std_name, ci.facet_key FROM question_score qs"
              " JOIN competency_item ci ON ci.item_id=qs.item_id"
              " WHERE qs.session_id=? AND qs.gate_result IS NOT NULL", (sid,))
    by_name = {r["std_name"]: r["gate_result"] for r in rows}
    assert by_name == {"全日制本科学历及以上": "true", "英语六级": "true",
                       "计算机相关专业": "true", "211硕士及以上学历": "false"}
    # ⑤ payload 两段式落库（facet 原始答案 + derived，审计可复现）
    stored = json.loads(_q("SELECT payload_json FROM form_instance WHERE form_instance_id=?",
                           (fi_id,))[0]["payload_json"])
    assert stored["schema_version"] == "v2"
    assert stored["facet_answers"] == payload
    assert stored["derived"] == {"全日制本科学历及以上": True, "英语六级": True,
                                 "计算机相关专业": True, "211硕士及以上学历": False}
    conn.close()


def test_facet_of_reads_labels_not_reclassify():
    """facet_of：读已打标结果（含 params json 解析）；NULL/空 key → None（勾选组降级）。"""
    from server.services.facet import facet_of
    assert facet_of({"facet_key": "education_degree",
                     "facet_params_json": '{"threshold": 2}'}) == {
        "facet_key": "education_degree", "params": {"threshold": 2}}
    assert facet_of({"facet_key": None, "facet_params_json": None}) is None
    assert facet_of({"facet_key": "major_group", "facet_params_json": "{}"}) == {
        "facet_key": "major_group", "params": {}}
    # 坏 json 容错：params 退 {}（分类打标列理论不坏，防御）
    assert facet_of({"facet_key": "major_group", "facet_params_json": "{bad"}) == {
        "facet_key": "major_group", "params": {}}
