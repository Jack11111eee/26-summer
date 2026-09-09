"""U5b 评分契约改造测试（SSOT §17 / §12.5 / §9.4 契约 2-3 条，2026-09-09）。

覆盖断言：
- 客观题结构化判分 `_score_objective_v2`（三答案键形态）：
  MDP 第十题回归全矩阵（any_of 新形态 + Markdown/全角/无空格/缺元素/否定/单关键词/标准答案）；
  旧 `|` 存量键兼容（不 re.search）；整段说明文本要点包含计数（≥0.6 判 5 / ≥0.3 判 3）；
  否定窗口过滤（否定句不判 5）；
- 正确性与等级分离：客观题命中 5 > observable_level_max → 结构化截断（reason 注明）；
  未命中 1 不受 observable_level_min 约束；
- 跨消息证据定位（§12.5）：span 各归各消息（偏移相对该消息原文）；
  跨消息引文拆段；找不到 → located=false 全 NULL；绝不挂最后一条消息；
- 主观评分输出严格校验 `_validate_score`：非 int/float、bool、NaN/inf、小数、越界、
  超锚点上限 → (None, 原因)——INSUFFICIENT_EVIDENCE 排除态（§9.4 契约第 3 条）；
- 主观 prompt 携带 measurement_target 与锚点区间（§9.4 契约第 2 条）。

运行：cd server && python -m pytest test_scoring_contract.py -v
"""
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(prefix="u5b_score_"), "test_scoring_contract.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import init_db, get_conn, set_db_path  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()  # 幂等，在 _tmp_db 建表

# ---------- fixtures ----------


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞后续写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _seed_objective_question(*, answer_key: str | None, difficulty: str = "medium",
                             observable_level_max: int | None = None,
                             observable_level_min: int | None = None,
                             measurement_target: str | None = None) -> tuple[str, str]:
    """直插客观题 + 会话 + 实例，返回 (session_id, question_id)。

    measurement fields（U5a 新题形态）由参数显式给；缺省 NULL = 存量旧行。
    """
    conn = get_conn()
    try:
        now = now_iso()
        uid, pid, mid, sid = new_id("u"), new_id("pos"), new_id("cm"), new_id("sess")
        qbid, aqid = new_id("qb"), new_id("aq")
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, created_at)"
            " VALUES(?,?,?,?,?)", (uid, uid, "x", "candidate", now))
        conn.execute(
            "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
            (pid, "U5b 测试岗", "active", now))
        conn.execute(
            "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
            " VALUES(?,?,?,?,?,?)", (mid, pid, 1, "confirmed", "{}", now))
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, gate)"
            " VALUES(?,?,?,?,?)", (new_id("ci"), mid, "机器学习", "hard_skill", 0))
        conn.execute(
            "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
            " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (sid, uid, pid, mid, 1, "completed", now, now))
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, model_id, model_version,"
            " std_name, category, difficulty, qtype, stem, answer_key, rubric,"
            " measurement_target, observable_level_max, observable_level_min, rubric_version,"
            " source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (qbid, "position", pid, mid, 1, "机器学习", "hard_skill", difficulty, "objective",
             "U5b 客观题（答案键形态测试）。", answer_key, None,
             measurement_target, observable_level_max, observable_level_min, "v2",
             "human", "active", now))
        conn.execute(
            "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq,"
            " asked_at, answered_at, created_at) VALUES(?,?,?,?,?,?,?)",
            (aqid, sid, qbid, 1, now, now, now))
        conn.commit()
        return sid, aqid
    finally:
        conn.close()


def _seed_subjective_question(*, difficulty: str = "medium",
                              observable_level_max: int | None = None,
                              observable_level_min: int | None = None,
                              measurement_target: str | None = None) -> tuple[str, str]:
    """直插主观题 + 会话 + 实例（U5a 五字段 / NULL 两态）。"""
    conn = get_conn()
    try:
        now = now_iso()
        uid, pid, mid, sid = new_id("u"), new_id("pos"), new_id("cm"), new_id("sess")
        qbid, aqid = new_id("qb"), new_id("aq")
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, created_at)"
            " VALUES(?,?,?,?,?)", (uid, uid, "x", "candidate", now))
        conn.execute(
            "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
            (pid, "U5b 主观岗", "active", now))
        conn.execute(
            "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
            " VALUES(?,?,?,?,?,?)", (mid, pid, 1, "confirmed", "{}", now))
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, gate)"
            " VALUES(?,?,?,?,?)", (new_id("ci"), mid, "机器学习", "hard_skill", 0))
        conn.execute(
            "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
            " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (sid, uid, pid, mid, 1, "in_progress", now, now))
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, model_id, model_version,"
            " std_name, category, difficulty, qtype, stem, answer_key, rubric,"
            " measurement_target, observable_level_max, observable_level_min, rubric_version,"
            " source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (qbid, "position", pid, mid, 1, "机器学习", "hard_skill", difficulty, "subjective",
             "U5b 主观题（锚点携带测试）。", None, "概念/例子/取舍",
             measurement_target, observable_level_max, observable_level_min, "v2",
             "human", "active", now))
        conn.execute(
            "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq,"
            " asked_at, answered_at, created_at) VALUES(?,?,?,?,?,?,?)",
            (aqid, sid, qbid, 1, now, now, now))
        conn.commit()
        return sid, aqid
    finally:
        conn.close()


def _add_user_message(sid: str, qid: str, text: str) -> str:
    """插一条用户回答消息，返回 message_id（§12.5 各消息独立定位的种子）。"""
    conn = get_conn()
    try:
        mid = new_id("msg")
        conn.execute(
            "INSERT INTO assessment_message(message_id, session_id, question_id, role, content,"
            " created_at) VALUES(?,?,?,?,?,?)",
            (mid, sid, qid, "user", text, now_iso()))
        conn.commit()
        return mid
    finally:
        conn.close()


_MDP_KEY = ("[any_of] MDP五元组：(S, A, P, R, γ)\n(S, A, P, R, γ)\n"
            "状态空间、动作空间、状态转移概率、奖励函数、折扣因子")
# 本场原答案（已用原答案复现误判：全角/半角括号与 Markdown 加粗形态差异）
_MDP_ORIGINAL_ANSWER = (
    "MDP五元组：**(S, A, P, R, γ)**，其中 S 是状态集合，A 是动作集合，"
    "P 是状态转移概率，R 是奖励函数，γ 是折扣因子。"
)


# ---------- 任务 1：结构化答案规则判分器（MDP 第十题回归矩阵）----------


def test_mdp_original_answer_scores_5():
    """MDP 第十题回归（验收 3 核心）：本场原答案（Markdown 加粗圆括号形态）→ 5 分。"""
    from server.services.scoring import _score_objective_v2
    score, reason = _score_objective_v2(_MDP_KEY, _MDP_ORIGINAL_ANSWER)
    assert score == 5, f"原答案应 5 分（旧形态误判 1 分缺陷回归），reason={reason}"


def test_mdp_paren_space_markdown_variants_score_5():
    """不同括号/空格/Markdown 形态 → 5 分。"""
    from server.services.scoring import _score_objective_v2
    variants = [
        "MDP五元组：(S,A,P,R,γ)。",  # 无空格
        "MDP 的五元组是 **（S，A，P，R，γ）**。",  # 全角+加粗
        "MDP 五元组: `S, A, P, R, γ` 的组合。",  # code 块
        "MDP 由状态空间、动作空间、状态转移概率、奖励函数和折扣因子构成。",  # 中文要素别名
    ]
    for ans in variants:
        score, _ = _score_objective_v2(_MDP_KEY, ans)
        assert score == 5, f"等价形态应 5 分：{ans}"


def test_mdp_fullwidth_parenthesis_hits():
    """全角逗号括号（S，A，P，R，γ）→ 命中（归一化全半角统一）。"""
    from server.services.scoring import _score_objective_v2
    score, _ = _score_objective_v2(_MDP_KEY, "MDP五元组：（S，A，P，R，γ）。")
    assert score == 5


def test_mdp_missing_one_element_not_5():
    """缺一个元素（四元组 (S, A, P, R)）→ 非 5。"""
    from server.services.scoring import _score_objective_v2
    score, _ = _score_objective_v2(_MDP_KEY, "MDP五元组：(S, A, P, R)，S 状态，A 动作，P 转移，R 奖励。")
    assert score != 5, "缺折扣因子 γ 的四元组不应判 5"


def test_mdp_negation_not_5():
    """否定正确答案的句子（含全部关键词）→ 不判 5。"""
    from server.services.scoring import _score_objective_v2
    score, _ = _score_objective_v2(
        _MDP_KEY, "MDP 不是马尔可夫决策过程，没有五元组 (S, A, P, R, γ) 的概念。")
    assert score != 5, "否定句不得仅凭关键词存在判 5（SSOT §17）"
    # 枚举段否定形态：「并不包含A、B、C…」中文否定作用于整个顿号链
    score2, _ = _score_objective_v2(
        _MDP_KEY, "MDP 中并不包含状态空间、动作空间、状态转移概率、奖励函数、折扣因子这些东西。")
    assert score2 != 5, "枚举段否定不得判 5"


def test_mdp_single_keyword_not_5():
    """只出现一个关键词（γ）→ 不判 5。"""
    from server.services.scoring import _score_objective_v2
    score, _ = _score_objective_v2(_MDP_KEY, "γ")
    assert score != 5


def test_mdp_standard_answer_itself_scores_5():
    """标准答案本身 → 5 分（自我命中）。"""
    from server.services.scoring import _score_objective_v2
    for line in ("MDP五元组：(S, A, P, R, γ)", "(S, A, P, R, γ)",
                 "状态空间、动作空间、状态转移概率、奖励函数、折扣因子"):
        score, _ = _score_objective_v2(_MDP_KEY, f"{line}。")
        assert score == 5, f"标准答案行应 5 分：{line}"


def test_legacy_pipe_key_compatible():
    """旧 `|` 存量键兼容：拆 | 候选包含匹配（不 re.search——SSOT 作废 | 猜正则）。"""
    from server.services.scoring import _score_objective_v2
    # 答其一 → 5（旧「栅格地图|拓扑地图」被当正则分支的误判修复）
    score, reason = _score_objective_v2("栅格地图|拓扑地图", "路径规划常用栅格地图表示环境。")
    assert score == 5, f"存量 | 键答其一应 5 分：{reason}"
    # 正则元字符不再被解释：`docker (build|run)` 按字面候选处理不执行正则
    score2, _ = _score_objective_v2("docker build|docker run", "使用 docker build 构建镜像")
    assert score2 == 5
    # 全不中 → 1
    score3, _ = _score_objective_v2("栅格地图|拓扑地图", "我用voxel地图")
    assert score3 == 1


def test_descriptor_text_keypoint_counting():
    """整段说明文本形态：要点包含计数 ≥0.6 判 5 / ≥0.3 判 3 / <0.3 判 1。"""
    from server.services.scoring import _score_objective_v2
    key = ("Redis 持久化有两种方式：RDB 快照（定时全量）与 AOF 日志（增量追加），"
           "各有优劣")
    # 全要点命中（RDB/AOF 双提）
    score5, _ = _score_objective_v2(
        key, "Redis 持久化用 RDB 定时快照和 AOF 追加日志两种，各有优劣。")
    assert score5 == 5
    # 部分命中（只提 RDB）→ 3 档（首版保守两档）
    score3, _ = _score_objective_v2(
        key, "我只知道 RDB（redis database）快照。")
    assert score3 == 3, f"部分命中应 3 分"
    # 几乎不命中 → 1
    score1, _ = _score_objective_v2(key, "这道题我不会。")
    assert score1 == 1


def test_single_token_key_degenerate():
    """单要点键（'def'）退化整串包含——库里常见最简键不炸。"""
    from server.services.scoring import _score_objective_v2
    assert _score_objective_v2("def", "用 def 定义函数")[0] == 5
    assert _score_objective_v2("def", "用 lambda 定义函数")[0] == 1


# ---------- 任务 2：正确性与等级分离（observable_level_max 截断）----------


def test_easy_level_max_caps_objective_5():
    """easy 题上限 3：客观题命中 5 → score_final=3 + reason 注明截断（非静默 min）。"""
    from server.services.scoring import score_question
    sid, qid = _seed_objective_question(
        answer_key="[any_of] def\ndefine", difficulty="easy",
        observable_level_max=3, observable_level_min=2,
        measurement_target="对 Python 的基础概念理解测量")
    _add_user_message(sid, qid, "用 def 定义函数。")
    r = score_question(sid, qid)
    assert r["score_final"] == 3, f"easy 上限 3 应截断 5→3：{r}"
    assert r["score_state"] == "SCORED"
    assert "依题目测量上限 3 调整为 3" in r["reason"], f"截断必须写进 reason：{r['reason']}"


def test_easy_level_max_caps_subjective_mock_llm():
    """easy 主观题（mock 恒 3 分）：observable_level_max=3 时 3 分合法不过截断链。"""
    from server.services.scoring import score_question
    sid, qid = _seed_subjective_question(
        difficulty="easy", observable_level_max=3, observable_level_min=2,
        measurement_target="对 Python 的基础概念理解测量")
    _add_user_message(sid, qid, "我在项目里用过 Python 做数据分析，有结果数据。")
    r = score_question(sid, qid)
    # mock _mock_score 恒 3；easy max=3 → 合法（不触发 INSUFFICIENT_EVIDENCE）
    assert r["score_final"] == 3 and r["score_state"] == "SCORED", r


def test_miss_1_not_raised_by_level_min():
    """未命中=1 不受 observable_level_min 约束（锚点起点非判分下限）。"""
    from server.services.scoring import score_question
    sid, qid = _seed_objective_question(
        answer_key="[any_of] 唯一要点词", difficulty="easy",
        observable_level_max=3, observable_level_min=2)
    _add_user_message(sid, qid, "完全无关的回答")
    r = score_question(sid, qid)
    assert r["score_final"] == 1, f"未命中应 1 分（不被 level_min 顶高）：{r}"


def test_null_anchor_no_constraint():
    """旧行 observable_level_max NULL → 不约束（存量兼容）。"""
    from server.services.scoring import score_question
    sid, qid = _seed_objective_question(answer_key="[any_of] def\ndefine", difficulty="medium")
    _add_user_message(sid, qid, "用 def 定义函数。")
    r = score_question(sid, qid)
    assert r["score_final"] == 5, f"无锚点行命中 5 不截断：{r}"


# ---------- 任务 3：跨消息证据定位（§12.5 禁令）----------


def test_span_first_message_not_last():
    """两条消息、quote 出自第一条 → span.source_message_id=第一条（不挂最后一条）。"""
    from server.services.scoring import _build_evidence_spans
    msg1 = ("msg_first", "首先，MDP 由五元组 (S, A, P, R, γ) 定义，γ 是折扣因子。")
    msg2 = ("msg_second", "补充：上面说的第五个元素就是折扣因子 γ。")
    spans = json.loads(_build_evidence_spans([msg1, msg2], "(S, A, P, R, γ)"))
    assert len(spans) == 1
    assert spans[0]["source_message_id"] == "msg_first", \
        f"第一条消息的引文必须挂第一条（§12.5 禁令核心）：{spans}"
    assert spans[0]["start_offset"] == msg1[1].find("(S, A, P, R, γ)")
    assert spans[0]["end_offset"] == spans[0]["start_offset"] + len("(S, A, P, R, γ)")
    assert spans[0].get("located") is True


def test_span_second_message():
    """quote 只在第二条消息 → 绑定第二条。"""
    from server.services.scoring import _build_evidence_spans
    msg1 = ("msg_first", "第一轮概述了概念。")
    msg2 = ("msg_second", "第二轮展开：五元组是 (S, A, P, R, γ)。")
    spans = json.loads(_build_evidence_spans([msg1, msg2], "(S, A, P, R, γ)"))
    assert spans[0]["source_message_id"] == "msg_second"
    assert spans[0]["start_offset"] == msg2[1].find("(S, A, P, R, γ)")


def test_span_cross_message_split():
    """跨消息引文：单消息找不到完整 quote → 拆段各归各消息。"""
    from server.services.scoring import _build_evidence_spans
    msg1 = ("msg_first", "MDP 的组成要素")
    msg2 = ("msg_second", "包括状态空间与折扣因子 γ。")
    # quote 跨界：第一段在 msg1、第二段在 msg2
    spans = json.loads(_build_evidence_spans([msg1, msg2], "MDP 的组成要素包括状态空间与折扣因子"))
    assert len(spans) == 2, f"跨消息引文应拆 2 段：{spans}"
    assert spans[0]["source_message_id"] == "msg_first"
    assert spans[0]["start_offset"] == 0
    assert msg1[1][spans[0]["start_offset"]:spans[0]["end_offset"]] == "MDP 的组成要素"
    assert spans[1]["source_message_id"] == "msg_second"
    assert msg2[1][spans[1]["start_offset"]:spans[1]["end_offset"]] == "包括状态空间与折扣因子"


def test_span_locate_failure_explicit():
    """找不到任何消息完整命中 → located=false 全 NULL（不以 hash-only 冒充已定位）。"""
    from server.services.scoring import _build_evidence_spans
    msg1 = ("msg_first", "候选人第一轮回答。")
    msg2 = ("msg_second", "候选人第二轮回答。")
    for span_key, quote in (("spans", "不存在的引文"), ("mock", "mock quote")):
        spans = json.loads(_build_evidence_spans([msg1, msg2], quote))
        assert len(spans) == 1
        s = spans[0]
        assert s["source_message_id"] is None and s["start_offset"] is None \
            and s["end_offset"] is None and s["source_content_type"] is None
        assert s["located"] is False, f"定位失败必须显式 located=false（{span_key}）"
        assert s["quote_hash"]  # hash 保留供对账


def test_score_question_spans_bind_correct_message_db():
    """db 链路：两条消息的客观题评分——evidence_span 绑定第一个含引文的消息。"""
    from server.services.scoring import score_question
    sid, qid = _seed_objective_question(answer_key="[any_of] def\ndefine")
    m1 = _add_user_message(sid, qid, "我用 def 定义函数。")
    m2 = _add_user_message(sid, qid, "如前所述。")
    r = score_question(sid, qid)
    spans = json.loads(r["evidence_spans_json"])
    assert spans[0]["source_message_id"] == m1, \
        f"db 链路 span 应绑第一条消息 {m1}，实得 {spans[0]['source_message_id']}（≠ 最后一条 {m2}）"


def test_joined_text_offset_never_attached():
    """拼接文本偏移绝不挂消息（§12.5 禁令的形态锁）：只有一条消息时偏移=该消息内。"""
    from server.services.scoring import _build_evidence_spans
    long_head = "候选人 lengthy preamble。" * 30  # 拉开与 joined 偏移的差
    quote = "关键要点在末尾"
    text = long_head + quote
    spans = json.loads(_build_evidence_spans([("m_only", text)], quote))
    assert spans[0]["start_offset"] == text.find(quote), \
        "偏移必须相对该消息原文（唯一消息时 joined==原文，出现差值即错挂形态）"


# ---------- 任务 5：主观评分输出严格校验 ----------


def test_validate_score_rejects_bad_type():
    """非法 score（True/"abc"/None/缺键）→ (None, 原因)——排除态判据。"""
    from server.services.scoring import _validate_score
    for bad in (True, "abc", None, [3], {"v": 3}):
        score, err = _validate_score({"score": bad}, None)
        assert score is None and err, f"非法类型应拒：{bad!r}"
    score, err = _validate_score({}, None)
    assert score is None and "score" in err


def test_validate_score_rejects_out_of_range():
    """越界（0/6/-1/NaN/inf）与含小数 → (None, 原因)。"""
    from server.services.scoring import _validate_score
    for bad in (0, 6, -1, float("nan"), float("inf"), 2.5, 3.7):
        score, err = _validate_score({"score": bad}, None)
        assert score is None and err, f"非法值应拒：{bad!r}"


def test_validate_score_accepts_valid():
    """合法 1-5 整数 → 原样通过。"""
    from server.services.scoring import _validate_score
    for good in (1, 3, 5):
        score, err = _validate_score({"score": good}, None)
        assert score == good and err is None


def test_validate_score_rejects_above_level_max():
    """score > observable_level_max（有值时）→ 拒（不截断不静默接受——§9.4 契约第 3 条）。"""
    from server.services.scoring import _validate_score
    score, err = _validate_score({"score": 4}, 3)
    assert score is None and "上限" in err, "超锚点上限必须显式拒绝（非静默 min）"
    # max=None（旧行）不约束
    score2, err2 = _validate_score({"score": 4}, None)
    assert score2 == 4 and err2 is None


def test_invalid_llm_score_becomes_insufficient_evidence(monkeypatch):
    """db 链路：LLM 评分输出非法（6/"abc"）→ INSUFFICIENT_EVIDENCE + score_final=None。"""
    from server.services import scoring
    sid, qid = _seed_subjective_question(difficulty="hard")  # NULL 锚点→查表 [4,5]，6 越界量表
    _add_user_message(sid, qid, "我在项目里负责高并发服务设计，有限流与缓存，有量化结果。")
    for bad in (6, "abc", True):
        def _bad_score(system_prompt, user_prompt):
            return {"score": bad, "evidence_quote": "项目里", "reason": "无论理由"}
        monkeypatch.setattr(scoring, "_mock_score", _bad_score)
        r = scoring.score_question(sid, qid)
        assert r["score_state"] == "INSUFFICIENT_EVIDENCE", \
            f"非法 score {bad!r} 应走 INSUFFICIENT_EVIDENCE：{r}"
        assert r["score_final"] is None, "非法输出不生成正常低分记录（§17）"
        assert "评分输出非法" in r["reason"]
        assert r["trace_id"]  # 已成功 LLM trace 仍关联（供复核路径）


def test_invalid_score_above_anchor_becomes_insufficient_evidence(monkeypatch):
    """db 链路：输出 5 但 easy 锚点 max=3 → INSUFFICIENT_EVIDENCE（不静默切成 3）。"""
    from server.services import scoring
    sid, qid = _seed_subjective_question(
        difficulty="easy", observable_level_max=3, observable_level_min=2)
    _add_user_message(sid, qid, "独立完成过常规工作，有结果。")

    def _five(system_prompt, user_prompt):
        return {"score": 5, "evidence_quote": "独立完成", "reason": "无论理由"}
    monkeypatch.setattr(scoring, "_mock_score", _five)
    r = scoring.score_question(sid, qid)
    assert r["score_state"] == "INSUFFICIENT_EVIDENCE" and r["score_final"] is None
    assert "上限 3" in r["reason"], f"reason 须指明锚点上限：{r['reason']}"


# ---------- 任务 4：主观 prompt 携带锚点 ----------


def test_score_prompt_carries_anchor():
    """主观 prompt 含测量目标与锚点区间文本（§9.4 契约第 2 条）。"""
    from server.services.prompts.score import score_prompt
    q = {"stem": "讲一次性能优化经历。", "rubric": "场景/方法/结果"}
    p = score_prompt(q, "候选人的回答。", "后端工程师",
                     measurement_target="对 Python 的常规应用测量",
                     level_range=(3, 4))
    assert "对 Python 的常规应用测量" in p
    assert "Lv3 ~ Lv4" in p or "Lv3~Lv4" in p, p
    assert "评分不得高于 Lv4" in p
    # 兼容性：缺省（None）不产段落——既有调用不破
    p_legacy = score_prompt(q, "A", "P")
    assert "测量目标" not in p_legacy and "锚点区间" not in p_legacy


def test_subjective_prompt_defaults_by_difficulty():
    """db 链路：锚点 NULL 行按难度默认查表注入 prompt（easy [2,3]/hard [4,5]）。"""
    from server.services import scoring
    captured = {}

    def capture_llm(call_type, ref_id, system_prompt, user_prompt, **kw):
        captured["user_prompt"] = user_prompt
        return {"score": 3, "evidence_quote": "q", "reason": "r"}

    import server.services.scoring as sc
    orig = sc.call_llm_json
    sc.call_llm_json = capture_llm
    try:
        # easy 行（NULL 锚点）→ [2,3]
        sid, qid = _seed_subjective_question(difficulty="easy", measurement_target=None)
        _add_user_message(sid, qid, "回答文本。")
        sc.score_question(sid, qid)
        assert "Lv2 ~ Lv3" in captured["user_prompt"], captured["user_prompt"]
        assert "评分不得高于 Lv3" in captured["user_prompt"]
        # hard 行（NULL 锚点）→ [4,5]
        sid2, qid2 = _seed_subjective_question(difficulty="hard", measurement_target=None)
        _add_user_message(sid2, qid2, "回答文本。")
        sc.score_question(sid2, qid2)
        assert "Lv4 ~ Lv5" in captured["user_prompt"], captured["user_prompt"]
        # 题库行有 measurement_target 时透传
        sid3, qid3 = _seed_subjective_question(
            difficulty="medium", measurement_target="对分布式系统的复杂问题处理测量")
        _add_user_message(sid3, qid3, "回答文本。")
        sc.score_question(sid3, qid3)
        assert "对分布式系统的复杂问题处理测量" in captured["user_prompt"]
    finally:
        sc.call_llm_json = orig


def test_score_system_prompt_anchor_constraint():
    """SCORE_SYSTEM 含锚点约束三句（评分锚定/理由引用原文/不额外标准扣分）。"""
    from server.services.prompts.score import SCORE_SYSTEM
    assert "锚点区间" in SCORE_SYSTEM
    assert "命中要点与缺失要点" in SCORE_SYSTEM
    assert "不得以题干未要求的标准扣分" in SCORE_SYSTEM
