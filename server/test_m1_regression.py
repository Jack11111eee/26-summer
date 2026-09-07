"""M1 回归清单（REF-7.5）：模块一 §8.1 八项脆弱点回归锁 + mock=3 记档（REF-8.6/D-72）。

八项锁：
  1) 清洗边界 clean_jd（空 JD / 纯标点 / 超长 JD 不抛异常，返回可处理结构）
  2) 抽取异常 normalize_title（无标题 / 纯数字标题不抛异常）
  3) 消歧 disambiguate_items（词典为空跳过 LLM#2 → 降级代码去重，mock 下确定性；
     非空 merges 属性访问 from_/to —— 回归锁 f8accb4 下标 TypeError；
     3c) 抽取 evidence str→list 无损兜底，required_level 缺失仍拒绝）
  4) 权重尾差 Σ=1 _compute_weights（生成器路径精确 ==1.0，尾差由权重最大项吸收；
     编辑器路径 ±0.005 容差——语义见 CONCERNS，勿混用两口径）
  5) 等级冲突 adjudicate（极差 ≥ ADJUDICATE_CONFLICT_THRESHOLD=2 → 取低 + human_review）
  6) 门槛判定 _gate_check（qualification/experience 保守失败，不静默通过）
  7) 版本 diff diff_models（version 不同视为不同模型，不共享判重键）
  8) 管理员权限 require_admin（非 admin 拒绝 403）

mock=3 已知局限（D-72/REF-8.6）：mock interviewer `_mock_score` 恒返回 score=3，
故 b 一致性方差恒 0、c 虚拟考生靠客观题 answer_key 区分强弱；此为已知局限，
不增强 mock、不虚构可变分数（真实一致性/强弱区分需 real LLM，本期不做）。

函数懒导入（RESEARCH Pattern 2）：被断言函数在测试函数体内 from ... import ...，
避免 import 期副作用。全程 mock 三件套由 conftest.py 集中注入（不碰 data/app.db）。
运行：cd server && python -m pytest test_m1_regression.py -q
"""
import json

import pytest


def test_clean_jd_boundaries():
    """1) 清洗边界：空 JD / 纯标点 / 超长 JD 不抛异常，返回 (cleaned, low_confidence)。"""
    from server.services.pipeline import clean_jd

    cleaned, low = clean_jd("")
    assert isinstance(cleaned, str)
    assert low is True  # 空 JD → 低于 CLEAN_MIN_REQ_LEN

    cleaned2, low2 = clean_jd("，。！？；：，。！")
    assert isinstance(cleaned2, str)
    assert low2 is True  # 纯标点无要求内容 → low_confidence 但继续流程

    long_jd = "Python 工程师，负责后端开发。" * 500
    cleaned3, low3 = clean_jd(long_jd)
    assert isinstance(cleaned3, str)
    assert low3 is False  # 超长 JD 长度 >= CLEAN_MIN_REQ_LEN，不标低置信


def test_normalize_title_boundaries():
    """2) 抽取异常：normalize_title 对无标题/纯数字标题不抛异常，返回 str。"""
    from server.services.assign import normalize_title

    assert normalize_title("") == ""
    assert normalize_title("12345") == "12345"  # 纯数字标题不抛异常，原样返回
    assert normalize_title("工程师") == "工程师"  # 单后缀长度保护：去后缀后为空则不去
    assert normalize_title("软件工程师") == "软件"  # 常见后缀归一


def test_disambiguate_no_llm_degradation():
    """3) 消歧：词典为空时跳过 LLM#2，降级代码去重，mock 下确定性不抛异常。"""
    from server.services.pipeline import disambiguate_items

    items = [
        {"name": "Python", "category": "hard_skill"},
        {"name": "Python", "category": "hard_skill"},  # 重复 → 代码级精确去重
        {"name": "MySQL", "category": "hard_skill"},
    ]
    out = disambiguate_items("jd_m1_reg_0001", items)
    assert [it["name"] for it in out] == ["Python", "MySQL"]


def test_disambiguate_nonempty_merges():
    """3b) 消歧非空 merges：MergePair 属性访问 from_/to，不再下标（f8accb4）。

    mock _mock_disambiguate 恒返回空 merges，非空路径从未覆盖，故此处
    monkeypatch mock 返回非空 merges（LLM_PROVIDER=mock 下 call_llm_json
    直接消费其返回值），回归锁 {m.from_: m.to} 属性访问。
    """
    from server.services import pipeline
    from server.services.pipeline import disambiguate_items

    # 词典候选非空才进 LLM#2：先插一条 active 词条
    conn = pipeline.get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO competency_dict(std_name, category, definition,"
        " aliases_json, exclusions_json, created_by, status, created_at, updated_at)"
        " VALUES('Python 开发','hard_skill',NULL,'[]','[]','human','active',?,?)",
        (pipeline.now_iso(), pipeline.now_iso()),
    )
    conn.commit()

    def _mock_nonempty(system_prompt, user_prompt):
        return {"merges": [{"from": "Python", "to": "Python 开发"}]}

    original = pipeline._mock_disambiguate
    pipeline._mock_disambiguate = _mock_nonempty
    try:
        out = disambiguate_items(
            "jd_m1_reg_0002",
            [{"name": "Python", "category": "hard_skill"}],
        )
    finally:
        pipeline._mock_disambiguate = original
    assert out[0]["name"] == "Python 开发"


def test_extract_evidence_str_tolerant():
    """3c) 抽取 evidence 兜底：LLM 偶发返回纯字符串 → mode=before 收窄为 [str]（2026-09-06 放量实测）。

    evidence 是原文短语抄录，str→[str] 无损单向；required_level 缺失不做兜底
    （语义缺失静默补默认值会掩盖坏输出——该族靠 prompt 根因修复：few-shot
    补 qualification 示例，见 prompts/extract.py v2）。
    """
    from server.schemas import ExtractItem

    # 纯字符串 evidence（B 族失效形态）→ 单元素列表，不抛异常
    it = ExtractItem(name="本科以上学历", category="qualification", required_level=3,
                     importance="required", evidence="本科以上学历")
    assert it.evidence == ["本科以上学历"]

    # 正常 list 输入不受影响
    it2 = ExtractItem(name="Python", category="hard_skill", required_level=4,
                      importance="required", evidence=["精通Python"])
    assert it2.evidence == ["精通Python"]

    # required_level 缺失仍必须被拒（回归锁：不静默兜底语义缺失）
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractItem(name="计算机相关专业", category="qualification",
                   importance="required", evidence=["计算机相关专业"])


def test_compute_weights_sum_one():
    """4) 权重尾差 Σ=1：生成器路径 _compute_weights 精确 ==1.0（尾差由最大项吸收）。

    编辑器路径 ±0.005 容差为另一口径（api/admin/models.py 人审编辑 Σ 校验），
    与本生成器「精确 Σ=1」语义不同——回归锁二者不混用（见 CONCERNS）。
    """
    from server.services.aggregate import _compute_weights

    def _it(std_name, category, importance):
        return {"std_name": std_name, "category": category, "importance": importance}

    items = [
        _it("Python", "hard_skill", "required"),
        _it("MySQL", "hard_skill", "required"),
        _it("Redis", "hard_skill", "preferred"),
        _it("沟通能力", "soft_skill", "required"),
        _it("协作能力", "soft_skill", "preferred"),
    ]
    _compute_weights(items)
    total = sum(it["weight"] for it in items)
    assert total == pytest.approx(1.0, abs=1e-9)  # 尾差吸收后 Σ 严格 =1.0


def test_adjudicate_conflict_takes_lowest():
    """5) 等级冲突：极差 ≥ 阈值=2 → 取低 + human_review=True（不可静默覆盖）。"""
    from server.services.aggregation import adjudicate

    level, review = adjudicate([{"observed_level": 1}, {"observed_level": 3}])
    assert level == 1.0  # 冲突取低
    assert review is True  # 留人工标记

    # 一致场景：取均值，无人工标记
    level2, review2 = adjudicate([{"observed_level": 3}, {"observed_level": 3}])
    assert level2 == 3.0
    assert review2 is False


def test_gate_check_conservative_fail():
    """6) 门槛判定：qualification 缺字段/experience 年限不足 → 保守失败（不静默通过）。"""
    from server.services.aggregation import _gate_check

    passed, reason = _gate_check(
        {"std_name": "本科学历", "category": "qualification"}, {},
    )
    assert passed is False
    assert "未提供" in reason

    passed2, _ = _gate_check(
        {"std_name": "本科学历", "category": "qualification"}, {"本科学历": "本科"},
    )
    assert passed2 is True

    passed3, _ = _gate_check(
        {"std_name": "后端开发经验", "category": "experience", "years": 3},
        {"years_of_experience": 5},
    )
    assert passed3 is True


def test_model_version_diff():
    """7) 版本 diff：version 不同视为不同模型，diff_models 按 (std_name|category) 对齐。"""
    from server.api.admin.models import diff_models
    from server.db import get_conn
    from server.services.pipeline import new_id, now_iso

    conn = get_conn()
    pid = new_id("pos")
    mid_v1 = new_id("cm")
    mid_v2 = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "测试岗位", "active", now),
    )
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid_v1, pid, 1, "confirmed",
         json.dumps({"items": [{"std_name": "Python", "category": "hard_skill",
                                "required_level": 3, "weight": 1.0}]}), now),
    )
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid_v2, pid, 2, "confirmed",
         json.dumps({"items": [{"std_name": "Python", "category": "hard_skill",
                                "required_level": 4, "weight": 1.0}]}), now),
    )
    conn.commit()
    conn.close()

    changes = diff_models(mid_v2, mid_v1)["changes"]
    assert any(c["std_name"] == "Python" and c["change"] == "field" for c in changes)


def test_require_admin_rejects_non_admin():
    """8) 管理员权限：require_admin 拒绝非 admin 身份（403）。"""
    from fastapi import HTTPException

    from server.core.security import require_admin

    with pytest.raises(HTTPException) as exc_info:
        require_admin({"role": "candidate"})
    assert exc_info.value.status_code == 403

    assert require_admin({"role": "admin"}) == {"role": "admin"}


def test_map_importance_conditional_req_via_hybrid():
    """9) 混合口径①：条件 req 达标 + 绝对 req 不达标 → required（ASOT §8.1 2026-09-07 裁决）。

    低出现率高条件达标：出现 4/10 JD、其中 3 JD 标 required。
    绝对口径 req=0.3 < 0.5（旧口径不判 required）；条件口径 req=0.75 ≥ 0.5，
    r=0.4 ≥ 0.25、occ=4 ≥ 3 → required。
    """
    from server.services.aggregate import _map_importance

    assert _map_importance(0.4, 0.75, 4, "hard_skill") == "required"


def test_map_importance_occ_floor_blocks():
    """9b) 混合口径②：occ=2 < REQ_MIN_OCCURRENCE=3 → required 被门槛挡下。

    r=1.0、条件 req=1.0 全达标，唯 occ 不足 → preferred（r ≥ R_THRESHOLD），
    统计证据下限不因高比率放宽。
    """
    from server.services.aggregate import _map_importance

    assert _map_importance(1.0, 1.0, 2, "hard_skill") == "preferred"
    # 顺带锁 r 门：occ 足但 r < 0.25 → 也不判 required
    assert _map_importance(0.2, 1.0, 5, "hard_skill") == "plus"


def test_map_importance_soft_skill_capped_preferred():
    """9c) 混合口径③：soft_skill 高 r 高条件 req 仍 preferred（软技能排除 required）。"""
    from server.services.aggregate import _map_importance

    assert _map_importance(1.0, 1.0, 10, "soft_skill") == "preferred"
    # gate 类目同样不可判 required（类目过滤只放行 hard_skill）
    assert _map_importance(1.0, 1.0, 10, "qualification") == "preferred"
    assert _map_importance(1.0, 1.0, 10, "experience") == "preferred"


def test_map_importance_preferred_plus_unchanged():
    """9d) 混合口径④：preferred/plus 判据回归不变——未达 required 时仅看 r。

    未达 required 的三条路：条件 req 不足 / r 门不足 / occ 门不足，
    落点均由 r ≥ R_THRESHOLD 单独决定。
    """
    from server.services.aggregate import _map_importance

    # 条件 req 不足但 r 高 → preferred
    assert _map_importance(0.6, 0.3, 6, "hard_skill") == "preferred"
    # 全不足 r → plus
    assert _map_importance(0.4, 0.3, 4, "hard_skill") == "plus"
    assert _map_importance(0.1, 0.9, 5, "soft_skill") == "plus"
    # 边界：恰在阈值上（>=）判 required
    assert _map_importance(0.25, 0.5, 3, "hard_skill") == "required"
    # 边界：条件 req 恰差一线（0.4999）、r 够 preferred 门 → preferred
    assert _map_importance(0.6, 0.4999, 3, "hard_skill") == "preferred"


def test_run_aggregate_occurrence_json_contains_occ():
    """9e) 落库 occurrence_json 增 occ 键且 req 存条件口径值（2026-09-07 语义变更）。

    种子：5 JD 中 3 出现（其中 3 标 required）→ r=0.6、条件 req=1.0、occ=3。
    落库断言：occurrence = {r:0.6, req:1.0, occ:3}（旧绝对口径 req 应为 0.6——锁条件口径）。
    """
    from server.db import get_conn
    from server.services.aggregate import run_aggregate
    from server.services.pipeline import new_id, now_iso

    conn = get_conn()
    pid = new_id("pos")
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "occ 键回归岗", "active", now_iso()),
    )
    for i in range(5):
        jd_id = new_id("jd")
        items = [{"name": "CUDA", "category": "hard_skill", "importance": "required",
                  "required_level": 3, "evidence": ["CUDA 编程"]}] if i < 3 else []
        conn.execute(
            "INSERT INTO jd_record(jd_id, position_id, job_title, company, source_type,"
            " raw_text, std_items_json, status, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (jd_id, pid, "测试岗", None, "paste", "JD 原文",
             json.dumps(items, ensure_ascii=False), "parsed", now_iso()),
        )
    conn.commit()

    model_id = run_aggregate(pid)
    row = conn.execute(
        "SELECT occurrence_json, importance FROM competency_item WHERE model_id=?",
        (model_id,),
    ).fetchone()
    occ = json.loads(row["occurrence_json"])
    assert occ == {"r": 0.6, "req": 1.0, "occ": 3}
    assert row["importance"] == "required"  # hard_skill + 条件 req=1.0 + r=0.6 + occ=3 全达标
