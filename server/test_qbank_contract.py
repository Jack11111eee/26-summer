"""U5a 题库生成契约修订测试（SSOT §9.4 契约第 1/4 条 + §17 2026-09-09 修订）。

覆盖（任务书测试清单）：
- 档位解耦：required_level=5 → plan 含 hard；required_level=3 → 两档；
  weight 0.9 但 required_level=3 → 仍两档（§17 修订——weight>0.10 作废）；
- 五测量字段：新插入题五字段非空、observable_level_max/min 按难度查表
  （easy=3/2 · medium=4/3 · hard=5/4）、rubric_version="v2"；
- any_of 过渡标记：answer_key list 多元素 → `[any_of] ` 前缀 + 换行 join；
  单元素 list 无前缀（§17 answer_rule 结构化准备——完整实现归 U5b）；
- hard 硬门槛：required_level>4 项 LLM 返回空 questions → 生成任务 FAILED
  （§10.4 检查项 9 前置——无可测 Lv5 的测量路径即落库不完整）；
- QBANK_STRICT_FIELDS 过渡开关：False（默认）存量 NULL 五字段题可被选题 +
  readiness 不拦截（现状不回归）；True 时选题白名单过滤 NULL 行。

规范化说明：check() 复用 test_question_bank.py 的脚本式断言（与该文件共用形态，
pytest 下 FAIL 不抛错——本文件改用 assert 使失败可见）。
DB 隔离：set_db_path 自建临时库（test_phase4_binding 先例）——本文件的种子会往
question_bank_task 写带实时时间戳的行（qbank_tasks 列表端点测试的种子用固定
过去时基、默认页 20 行假设自己组在第 1 页；共享 conftest 库时本文件的新行会
把它的行挤出首页——跨文件库串扰，故必须整文件隔离）。
运行: cd server && python -m pytest test_qbank_contract.py -v
"""
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(prefix="qbc_test_"), "test.db")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 仓库根

import pytest  # noqa: E402

from server.db import get_conn, init_db, set_db_path  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
import server.services.question_bank as qb  # noqa: E402


@pytest.fixture(autouse=True)
def _point_contract_db():
    """function 级：get_conn()/init_db() 指向自建 _tmp_db（隔离于 conftest 会话
    共享库），测试结束复位 None——模块级泄漏会串扰其他文件的 DB 断言。"""
    set_db_path(_tmp_db)
    init_db()  # 幂等，在 _tmp_db 建表
    yield
    set_db_path(None)


def _q(sql: str, params: tuple = ()) -> list:
    conn = get_conn()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _exec(sql: str, params: tuple = ()) -> None:
    conn = get_conn()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _seed(position_name: str, items: list[dict]) -> tuple[str, str]:
    """active 岗位 + confirmed 模型（v1）+ items + QUEUED task 行。

    items 元素形态：{std_name, category, required_level, importance, weight,
    level_reason?, gate?}；level_reason 传 None 时列写 NULL（验证模板回退）。
    """
    conn = get_conn()
    pid, mid, now = new_id("pos"), new_id("m"), now_iso()
    try:
        conn.execute("INSERT INTO position(position_id, name, status, created_at)"
                     " VALUES(?,?,?,?)", (pid, position_name, "active", now))
        conn.execute(
            "INSERT INTO competency_model(model_id, position_id, version, status,"
            " model_json, created_at) VALUES(?,?,?,?,?,?)",
            (mid, pid, 1, "confirmed", json.dumps({"items": items}, ensure_ascii=False), now))
        for it in items:
            conn.execute(
                "INSERT INTO competency_item(item_id, model_id, std_name, category,"
                " required_level, importance, weight, gate, level_reason, evidence_json)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (new_id("c"), mid, it["std_name"], it["category"], it.get("required_level"),
                 it.get("importance", "required"), it.get("weight", 0.1),
                 int(it.get("gate", 0)), it.get("level_reason"),
                 json.dumps(it.get("evidence", []), ensure_ascii=False)))
        conn.execute(
            "INSERT INTO question_bank_task(task_id, position_id, model_id, model_version,"
            " status, created_at) VALUES(?,?,?,?,?,?)",
            (new_id("qbt"), pid, mid, 1, "QUEUED", now))
        conn.commit()
    finally:
        conn.close()
    return pid, mid


def _patch_llm(questions_per_call: list[list[dict]]):
    """打桩 call_llm_json（复刻 test_question_bank._patch_llm 口径，含落 trace）。

    questions_per_call=None 表示不打桩（走 LLM_PROVIDER=mock 的离线 mock 链）；
    每元素是一次调用的 questions 列表（None 元素 = 该次返回空 questions）。
    """
    calls = iter(questions_per_call) if questions_per_call is not None else None

    def fake(call_type, ref_id, system_prompt, user_prompt, mock_fn=None, trace_out=None):
        qs = next(calls)
        if qs is None:
            qs = []
        result = {"questions": qs}
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO llm_trace(trace_id, call_type, ref_id, attempt, prompt, response,"
                " success, error, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (new_id("t"), call_type, ref_id, 1,
                 system_prompt + "\n\n" + user_prompt,
                 json.dumps(result, ensure_ascii=False), 1, None, now_iso()))
            conn.commit()
        finally:
            conn.close()
        return result

    return fake


# ---------- 任务 1：_question_plan 与 weight>0.10 解耦（SSOT §17 修订） ----------

def test_plan_decoupled_from_weight():
    """required_level=5 → 三档；3 → 两档；weight 0.9 + rl 3 → 仍两档（解耦验证）。"""
    plan = qb._question_plan({"category": "hard_skill", "weight": 0.0089, "required_level": 5})
    assert [d for d, _ in plan] == ["easy", "medium", "hard"], plan
    # §17 缺陷直击：算法岗最大权重 0.0089（旧规则全场无 hard）在 rl>4 下必有 hard
    plan = qb._question_plan({"category": "hard_skill", "weight": 0.0089, "required_level": 4})
    assert [d for d, _ in plan] == ["easy", "medium"], plan  # rl=4 不可达 hard（§11.2）
    plan = qb._question_plan({"category": "hard_skill", "weight": 0.9, "required_level": 3})
    assert [d for d, _ in plan] == ["easy", "medium"], plan  # weight 0.9 无 hard——解耦
    plan = qb._question_plan({"category": "hard_skill", "weight": 0.9, "required_level": None})
    assert [d for d, _ in plan] == ["easy", "medium"], plan  # rl 缺失视作不可达 hard
    plan = qb._question_plan({"category": "soft_skill", "weight": 0.01, "required_level": 3})
    assert [d for d, _ in plan] == ["easy", "hard"], plan  # soft 两档不变
    plan = qb._question_plan({"category": "qualification", "weight": 0.9})
    assert plan == [], plan  # exp/qual 不生成题（§9.1）


def test_plan_hard_gate_fails_generation(monkeypatch):
    """硬门槛：required_level>4 项 LLM 返回空 questions → 该 item 无 hard 题，
    生成任务 FAILED（§17/§10.4 检查项 9 前置——不 SUCCEEDED 掩盖落库不完整）。"""
    pid, mid = _seed("硬门槛岗", items=[
        {"std_name": "SLAM建图", "category": "hard_skill", "required_level": 5, "weight": 0.2},
    ])
    # 3 次调用都返回空 questions（easy/medium/hard 三档全空——hard 档落库为 0）
    monkeypatch.setattr(qb, "call_llm_json", _patch_llm([None, None, None]))
    qb.generate_question_bank(pid, mid)
    task = _q("SELECT status, error_msg FROM question_bank_task WHERE model_id=?"
              " ORDER BY created_at DESC LIMIT 1", (mid,))[0]
    assert task["status"] == "FAILED", dict(task)
    assert "测量路径断裂" in (task["error_msg"] or ""), task["error_msg"]
    # easy/medium 档落库的题目保留（失败不回滚），retry 补缺档（WR-03 幂等按档粒度）
    n = _q("SELECT COUNT(*) c FROM question_bank WHERE model_id=?", (mid,))[0]["c"]
    assert n == 0, f"三档全空落库 0 题，实际 {n}"


def test_plan_hard_gate_not_triggered_when_no_hard_tier(monkeypatch):
    """反向边界：required_level=3 → plan 两档无 hard，LLM 空返回不入硬门槛
    （仍 SUCCEEDED——旧的空返回行为对无 hard 项保持；本测试只验证门槛不误伤）。"""
    pid, mid = _seed("无声门槛岗", items=[
        {"std_name": "Redis", "category": "hard_skill", "required_level": 3, "weight": 0.2},
    ])
    monkeypatch.setattr(qb, "call_llm_json", _patch_llm([None, None]))
    qb.generate_question_bank(pid, mid)
    task = _q("SELECT status FROM question_bank_task WHERE model_id=?", (mid,))[0]
    assert task["status"] == "SUCCEEDED", "两档项空返回不走硬门槛（§17 只挂钩 hard 项）"


# ---------- 任务 2：五测量字段落库 + 校验（§9.4 契约第 1 条 + §9.2） ----------

def test_full_generation_chain_writes_five_fields():
    """mock 生成链全跑通：新题五字段非空 + 按难度查表 + rubric_version='v2' +
    measurement_target 取 level_reason / 无 level_reason 时模板回退。"""
    pid, mid = _seed("契约岗", items=[
        {"std_name": "Python", "category": "hard_skill", "required_level": 5,
         "weight": 0.3, "level_reason": "各 JD 等级一致"},
        {"std_name": "Redis", "category": "hard_skill", "required_level": 4,
         "weight": 0.05, "level_reason": None},  # 列 NULL → 模板回退
    ])
    qb.generate_question_bank(pid, mid)  # LLM_PROVIDER=mock 离线链
    task = _q("SELECT status FROM question_bank_task WHERE model_id=?", (mid,))[0]
    assert task["status"] == "SUCCEEDED", dict(task)

    rows = _q("SELECT std_name, difficulty, measurement_target, evidence_requirement,"
              " observable_level_max, observable_level_min, rubric_version"
              " FROM question_bank WHERE model_id=? ORDER BY std_name, difficulty", (mid,))
    assert len(rows) == 5, f"3+2 档，实得 {len(rows)}"  # Python 3 档 + Redis 2 档
    expected_lvl = {"easy": (3, 2), "medium": (4, 3), "hard": (5, 4)}
    for r in rows:
        assert r["measurement_target"], dict(r)  # 五字段非空
        assert r["evidence_requirement"], dict(r)
        assert r["observable_level_max"] and r["observable_level_min"], dict(r)
        assert r["rubric_version"] == "v2", dict(r)  # 新契约标识
        assert (r["observable_level_max"], r["observable_level_min"]) \
            == expected_lvl[r["difficulty"]], dict(r)  # §9.4 表查表正确
    # measurement_target 来源：level_reason 优先 / None 模板回退（std_name 组装）
    py_hard = [r for r in rows if r["std_name"] == "Python"]
    assert all(r["measurement_target"] == "各 JD 等级一致" for r in py_hard)
    redis_any = [r for r in rows if r["std_name"] == "Redis"][0]
    assert "Redis" in redis_any["measurement_target"] and "测量" in redis_any["measurement_target"], \
        dict(redis_any)
    assert redis_any["evidence_requirement"] == "作答需展示对 Redis 的独立/结构化阐述"


def test_insert_rejects_missing_stem_or_bad_qtype(monkeypatch):
    """生成校验（修复文档 §十三.6）：缺 stem / qtype 非法 → 该题不计入有效完成。

    含非 str stem 防御（WR-06 同型 AttributeError 雷——list.stem 不炸循环）。"""
    pid, mid = _seed("校验岗", items=[
        {"std_name": "MySQL", "category": "hard_skill", "required_level": 3, "weight": 0.2},
    ])
    monkeypatch.setattr(qb, "call_llm_json", _patch_llm([
        # easy 档：三题无效（缺 stem / stem 为 list / qtype 非法）+ 一题有效 → 只落 1 题
        [{"stem": "", "difficulty": "easy", "qtype": "objective", "answer_key": "k"},
         {"stem": ["整段是个数组"], "difficulty": "easy", "qtype": "objective", "answer_key": "k"},
         {"stem": "题目", "difficulty": "easy", "qtype": "open_ended", "answer_key": "k"},
         {"stem": "正常题", "difficulty": "easy", "qtype": "objective", "answer_key": "k"}],
        # medium 档：正常 1 题
        [{"stem": "中档题", "difficulty": "medium", "qtype": "subjective",
          "answer_key": None, "rubric": "要点"}],
    ]))
    qb.generate_question_bank(pid, mid)
    task = _q("SELECT status, error_msg FROM question_bank_task WHERE model_id=?"
              " ORDER BY created_at DESC LIMIT 1", (mid,))[0]
    assert task["status"] == "SUCCEEDED", dict(task)
    stems = [r["stem"] for r in _q("SELECT stem FROM question_bank WHERE model_id=?", (mid,))]
    assert stems == ["正常题", "中档题"], f"无效题不入库，实得 {stems}"


# ---------- 任务 4：answer_key any_of 过渡标记（§17 字段层面准备） ----------

def test_mark_any_of():
    """多元素 list → `[any_of] ` 前缀 + 换行 join；单元素 / str / None 不标记。"""
    assert qb._mark_any_of("a|b", ["a", "b"]) == "[any_of] a\nb"
    assert qb._mark_any_of("a", ["a"]) == "a"  # 单元素 list 无前缀
    assert qb._mark_any_of("a", ["a", ""]) == "a"  # 空白元素过滤后单元素
    assert qb._mark_any_of("a", "a") == "a"  # str 透传
    assert qb._mark_any_of(None, None) is None
    assert qb._mark_any_of(None, []) is None  # 空 list 归一 None


def test_generation_marks_any_of_in_answer_key(monkeypatch):
    """生成链上验证：answer_key 多元素 list 落库带 [any_of] 前缀（换行 join）；
    单元素 list 落库无前缀。"""
    pid, mid = _seed("标记岗", items=[
        {"std_name": "Docker", "category": "hard_skill", "required_level": 3, "weight": 0.2},
    ])
    monkeypatch.setattr(qb, "call_llm_json", _patch_llm([
        [{"stem": "Q1", "difficulty": "easy", "qtype": "objective",
          "answer_key": ["镜像", "容器"], "rubric": None}],
        [{"stem": "Q2", "difficulty": "medium", "qtype": "objective",
          "answer_key": ["单选"], "rubric": None}],
    ]))
    qb.generate_question_bank(pid, mid)
    rows = {r["stem"]: r["answer_key"] for r in
            _q("SELECT stem, answer_key FROM question_bank WHERE model_id=?", (mid,))}
    assert rows["Q1"] == "[any_of] 镜像\n容器", rows
    assert rows["Q2"] == "单选", rows


# ---------- 任务 2 配套：QBANK_STRICT_FIELDS 选题过滤（§13 旧题处理过渡） ----------

def _seed_legacy_null_field_bank():
    """存量岗位 + 新模型（hard_skill required_level=3 → 两档）+ 直插五字段 NULL 旧题
    + mock 生成新题（五字段齐全）——两种题并存，供开关两态对比。Pitfall：直插行
    绑同 model/version（legacy 真实形态是旧模型，但过滤谓词只看五字段列，口径一致）。"""
    pid, mid = _seed("过渡岗", items=[
        {"std_name": "Python", "category": "hard_skill", "required_level": 3, "weight": 0.5},
    ])
    # 直插存量旧题：五字段全 NULL（594 题实测形态——DB 列存在但恒空）
    _exec(
        "INSERT INTO question_bank(question_id, scope, position_id, model_id, model_version,"
        " std_name, category, difficulty, qtype, stem, answer_key, rubric, source, status,"
        " created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("q"), "position", pid, mid, 1, "Python", "hard_skill", "easy",
         "objective", "旧题（五字段 NULL）", "旧", None, "imported", "active", now_iso()))
    # mock 生成新题：easy 档幂等命中直插行（跳过）、medium/… 生成新行（五字段齐全）
    qb.generate_question_bank(pid, mid)
    return pid, mid


def _selection_candidates(pid: str, mid: str) -> list:
    """select_next_question 的候选池加载（层①——暴露 strict 过滤的实际效果）。

    走 question_selection._load_candidate_rows（与 select_next_question 同一查询，
    避免开 session 的 user/事件开销）。"""
    from server.services.question_selection import _load_candidate_rows
    conn = get_conn()
    try:
        return _load_candidate_rows(conn, pid, mid, 1)
    finally:
        conn.close()


def test_strict_fields_default_off_keeps_legacy_selectable():
    """QBANK_STRICT_FIELDS=False（默认）：存量 NULL 五字段题可被选题（现状不回归）。"""
    from server import config
    assert config.QBANK_STRICT_FIELDS is False  # 默认关——存量岗位可开考的前提
    pid, mid = _seed_legacy_null_field_bank()
    rows = _q("SELECT COUNT(*) c FROM question_bank WHERE model_id=?"
              " AND measurement_target IS NULL", (mid,))[0]
    assert rows["c"] >= 1, "种子应存在五字段 NULL 的存量行"
    candidates = _selection_candidates(pid, mid)
    std_names = {c["std_name"] for c in candidates}
    assert "Python" in std_names, "默认关：NULL 字段题仍在候选池（现状行为）"
    # readiness 同口径不过滤
    from server.services.readiness import _question_count_by_category
    conn = get_conn()
    try:
        counts = _question_count_by_category(conn, pid, mid, 1)
    finally:
        conn.close()
    assert counts.get("hard_skill", 0) >= 2, counts


def test_strict_fields_on_filters_legacy_rows(monkeypatch):
    """QBANK_STRICT_FIELDS=True：选题白名单只认五字段齐全的 active 题（任一 NULL
    视为「待审核」不入选）；strict_fields_sql 谓词两态切换精确。"""
    from server import config
    assert qb.strict_fields_sql() == "1=1"  # False → 不加谓词
    pid, mid = _seed_legacy_null_field_bank()
    monkeypatch.setattr(config, "QBANK_STRICT_FIELDS", True)
    assert qb.strict_fields_sql("qb").startswith("qb.measurement_target IS NOT NULL")
    # question_selection/readiness 读 config 属性（from .. import config 同对象）
    candidates = _selection_candidates(pid, mid)
    null_rows = [c for c in candidates if c["measurement_target"] is None]
    assert not null_rows, f"strict=True 不应有 NULL 行，实得 {[c['stem'] for c in null_rows]}"
    assert candidates, "五字段齐全的新生成题仍在候选池"
    for c in candidates:  # 谓词五字段逐项核验
        assert c["measurement_target"] is not None
        assert c["evidence_requirement"] is not None
        assert c["observable_level_max"] is not None
        assert c["observable_level_min"] is not None
        assert c["rubric_version"] is not None
    # readiness 计数同口径过滤（开考预检与运行时选题白名单一致——防两处口径漂移）
    from server.services.readiness import _question_count_by_category
    conn = get_conn()
    try:
        counts = _question_count_by_category(conn, pid, mid, 1)
    finally:
        conn.close()
    strict_total = counts.get("hard_skill", 0)
    all_total = _q("SELECT COUNT(*) c FROM question_bank WHERE model_id=?"
                   " AND status='active' AND category='hard_skill'", (mid,))[0]["c"]
    assert strict_total < all_total, \
        f"strict=True 应过滤存量 NULL 行：{strict_total} < {all_total}"
