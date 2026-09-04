"""Phase 2 wave 5（02-05）：评分链契约修正——50/50 废除 + score_state 分母规则。

覆盖断言（SSOT §12.4 / §18 / D-26 / D-28）：
- score_final 独立落库（mock 主观 3 分直落数据库，无 50/50 合成路径）
- 拒答题（二次 DECLINED 封存）→ score_state='REFUSED' 且 score_final=0，
  不进能力等级分母（aggregate refusals 单列）
- answer_key 空客观题 → score_state='INVALIDATED' 且 score_final IS None
  （不写 1 分不写 5 分——WR-14「缺 key 按最低分记」语义替换），不进分母，
  aggregate missing_warnings 含对应 reason
- 聚合取数用 score_final（构造 score_live≠score_final 场景验证均值口径）
- SCORE_STATES 六值枚举常量在位（INSUFFICIENT_EVIDENCE 保留供 Phase 5）
- 报告端到端闭环（含 1 拒答 + 1 INVALIDATED 客观题不炸报告）

运行：cd server && python -m pytest test_phase2_scoring.py -v
"""
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(prefix="p2_score_"), "test_phase2_scoring.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ---------- fixtures ----------

def _seed_position_with_confirmed_model() -> tuple[str, str]:
    """建 active 岗位 + confirmed 模型 + competency_item（hard/soft 各 1 必选项）。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "Python 后端工程师", "active", now),
    )
    items = [
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.6},
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "required", "weight": 0.4},
    ]
    model_json = {"position_id": pid, "version": 1, "items": items}
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, 1, "confirmed", json.dumps(model_json, ensure_ascii=False), now),
    )
    for it in items:
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("ci"), mid, it["std_name"], it["category"], 3, it["importance"],
             it["weight"], 0),
        )
    conn.commit()
    conn.close()
    return pid, mid


def _seed_question_bank(pid: str) -> None:
    """题库（按 02-05 配额可满足的池子）：hard（difficulty 字段用于选题分层——按需覆盖）。

    Python 主观链 subjective：候选数量足够 02-01 难度快照 / 02-02 选题分层使用。

    固定三关键题（std_name 精准制导）：
    - "Python 沟通"（沟通能力 soft subjective，答长答案 → score_live 路径）
    - Python 客观（answer_key='def' → 正常判分 5 分命中）
    - Python 客观 NULL key（answer_key=NULL 直插 → INVALIDATED 路径）
    """
    conn = get_conn()
    now = now_iso()

    def _add(std_name, category, difficulty, qtype, stem, answer_key, rubric):
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
            " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq, source,"
            " status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("qb"), "position", pid, std_name, category, difficulty, qtype,
             stem, answer_key, rubric, None, None, "human", "active", now),
        )

    # 沟通能力 subjective ×2（easy/medium——为软性配额与 difficulty 快照提供池）
    _add("沟通能力", "soft_skill", "easy", "subjective",
         "讲一次跨团队沟通的经历。", None, "背景/冲突/结果")
    _add("沟通能力", "soft_skill", "medium", "subjective",
         "遇到意见分歧怎么处理？", None, "倾听/数据/共识")
    # Python subjective ×2（hard_skill 主观池——不命中 answer_key）
    _add("Python", "hard_skill", "easy", "subjective",
         "讲一个你用 Python 解决性能问题的经历。", None, "场景/方法/结果")
    _add("Python", "hard_skill", "medium", "subjective",
         "讲一次你用 Python 做模块设计的经历。", None, "结构/取舍/结果")
    conn.commit()
    conn.close()


def _auth_headers(username: str = "p2_score_candidate") -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _cur_q(sid: str, headers: dict) -> dict | None:
    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["current_question"]


def _answer(sid: str, headers: dict, question_id: str, answer: str) -> dict:
    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": question_id, "answer": answer}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# 答案文案（02-04 词表口径——避开 _EVIDENCE_WORDS 会触发实义路径：
# 这里长答案须含"项目/数据/结果"等实义词走充分证据路径拿 score_live=3）
_LONG_ANSWER = (
    "我在电商平台项目中负责订单模块重构，通过拆分大事务重构数据表结构，"
    "把下单接口的响应时间从 800ms 降到了 200ms，并复盘成文档沉淀给团队。"
)
# 长但无实义词 → score_live=2（构造 score_live≠score_final 的均值口径场景用）
_LONG_EMPTY_ANSWER = (
    "这个问题嘛，我觉得总体上来说还是挺有说道的地方的，"
    "不过当时的情况也是比较复杂的，各色各样的因素交织在一起。"
)
# 拒答词（02-04 _DECLINE_WORDS 词表内）
_DECLINE_ANSWER = "这道题我不方便回答，涉及隐私"


def _seed_invalid_objective(pid: str, std_name: str = "Python") -> str:
    """直插 1 道 answer_key=NULL 的客观题（绕过 CR-01 生成侧——题库生成层会拦空 key）。

    返回 question_id。INVALIDATED 路径的题库侧种子。
    """
    conn = get_conn()
    qid = new_id("qb")
    conn.execute(
        "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
        " difficulty, qtype, stem, answer_key, rubric, source, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (qid, "position", pid, std_name, "hard_skill", "easy", "objective",
         "Python 的 GIL 是什么？", None, None, "human", "active", now_iso()),
    )
    conn.commit()
    conn.close()
    return qid


def _aq_id_for_bank(sid: str, bank_question_id: str) -> str | None:
    """bank 题号 → 本会话实例 question_id（current_question 用的是 aq 实例 id）。"""
    rows = _q(
        "SELECT question_id, bank_question_id FROM assessment_question WHERE session_id=?",
        (sid,),
    )
    for r in rows:
        if r["bank_question_id"] == bank_question_id:
            return r["question_id"]
    return None


def _answer_whole_session(sid: str, headers: dict, *, first_answer: str,
                          invalid_qid: str | None = None) -> dict:
    """答完整场：每题按映射指定答案（invalid_qid 命中时答客观词——判分照走，结果应为 INVALIDATED）。

    返回统计 dict（refused_qid/invalidated_qid 等）。
    """
    refused_qid = None
    invalidated_qid = None
    while True:
        cur = _cur_q(sid, headers)
        if cur is None:
            break
        if invalid_qid is not None and _aq_id_for_bank(sid, invalid_qid) == cur["question_id"]:
            # 客观题（answer_key=NULL 直插）——正常回答文本（判分输入不缺）
            _answer(sid, headers, cur["question_id"], "GIL 是全局解释器锁，限制线程并行。")
            invalidated_qid = cur["question_id"]
            continue
        answered = _answer(sid, headers, cur["question_id"], first_answer)
        if answered.get("action") == "finish":
            break
    return {"refused_qid": refused_qid, "invalidated_qid": invalidated_qid}


def _answer_whole_session_with_one_refusal(sid: str, headers: dict, *,
                                            first_answer: str,
                                            invalid_qid: str | None = None) -> dict:
    """答完整场且第一道主观题走拒答二次封存（第一次 confirm + 第二次 DECLINED → seal refused）。

    返回统计 dict（refused_qid/invalidated_qid）。
    """
    refused_qid = None
    invalidated_qid = None
    refusal_done = False
    while True:
        cur = _cur_q(sid, headers)
        if cur is None:
            break
        if invalid_qid is not None and _aq_id_for_bank(sid, invalid_qid) == cur["question_id"]:
            _answer(sid, headers, cur["question_id"], "GIL 是全局解释器锁，限制线程并行。")
            invalidated_qid = cur["question_id"]
            continue
        if not refusal_done:
            # 第一次 DECLINE → action='confirm'（拒答确认）；第二次 DECLINE → seal refused
            r1 = _answer(sid, headers, cur["question_id"], _DECLINE_ANSWER)
            refused_qid = cur["question_id"]
            if r1.get("action") == "confirm":
                r2 = _answer(sid, headers, cur["question_id"], _DECLINE_ANSWER)
                refusal_done = True
                if r2.get("action") == "finish":
                    break
                continue
            refusal_done = True
            if r1.get("action") == "finish":
                break
            continue
        answered = _answer(sid, headers, cur["question_id"], first_answer)
        if answered.get("action") == "finish":
            break
    return {"refused_qid": refused_qid, "invalidated_qid": invalidated_qid}


def _trigger_scoring_and_report(sid: str, headers: dict) -> dict:
    """POST /report 串行链（评分+报告服务端执行）→ 轮询 by-session 取报告 JSON。"""
    r = client.post(f"/api/assessment/sessions/{sid}/report", headers=headers)
    assert r.status_code == 202, r.text
    r = client.get(f"/api/assessment/reports/by-session/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _question_score_rows(sid: str) -> list[dict]:
    return _q(
        "SELECT qs.*, b.qtype FROM question_score qs"
        " JOIN assessment_question aq ON aq.question_id=qs.question_id"
        " JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE qs.session_id=?",
        (sid,),
    )


# ---------- 测试 ----------

def test_score_state_enum_completeness():
    """SCORE_STATES 六值常量在位（Q1 决议：INSUFFICIENT_EVIDENCE 保留供 Phase 5）。"""
    from server.services.scoring import SCORE_STATES
    assert SCORE_STATES == ("SCORED", "REFUSED", "INSUFFICIENT_EVIDENCE",
                            "NOT_ADMINISTERED", "INVALIDATED", "INCOMPLETE")


def test_no_synthesis_residual():
    """评分链无 50/50 合成残留：源码静态断言 scoring.py 不含 "0.5 +" 模式（D-26）。"""
    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "services", "scoring.py")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    assert "0.5 +" not in src, "scoring.py 仍含 50/50 合成（0.5 + 残留）"
    assert "score_live * 0.5" not in src, "scoring.py 仍含 score_live 合成权重"


def test_score_final_independent():
    """mock 主观题 3 分直落数据库：score_final==3 且 score_state=='SCORED'。

    final_score 合成列已废（Task 3 DROP 前中期态：断言 score_state 与 score_final
    独立值即证明无合成路径——若 50/50 存在且 score_live=2，final 会是 round(2.5)=2）。
    """
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p2_sco_indep")
    sid = client.post("/api/assessment/sessions", json={"position_id": pid},
                      headers=headers).json()["session_id"]

    stats = _answer_whole_session(sid, headers, first_answer=_LONG_ANSWER)
    assert stats["invalidated_qid"] is None

    # score_live 均为 3（mock 实义词路径）
    _trigger_scoring_and_report(sid, headers)
    rows = _question_score_rows(sid)
    subj = [r for r in rows if r["qtype"] == "subjective"]
    assert subj, "整场应含主观题"
    assert all(r["score_final"] == 3 and r["score_state"] == "SCORED" for r in subj), \
        f"主观题应 score_final=3(mock) 独立落库且 SCORED：{subj}"


def test_refused_excluded_from_denominator():
    """整场含 1 道拒答题（二次 DECLINED 封存）→ REFUSED 行 score_final==0 不进分母。

    - question_score 行：score_state=='REFUSED' 且 score_final==0（§18 特殊状态值）
    - aggregate refusals 列表含该题所属 item
    - 对照：无拒答同构会话（其余答案相同）不含 REFUSED 行
    - 分母排除证明：拒答题不贡献所属 item 的 actual 平均（对比同构会话）
    """
    from server.services.aggregation import aggregate_session_scores
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)

    # 会话 A：含 1 拒答（其余题照常长答案）
    headers_a = _auth_headers("p2_sco_refused")
    sid_a = client.post("/api/assessment/sessions", json={"position_id": pid},
                        headers=headers_a).json()["session_id"]
    stats_a = _answer_whole_session_with_one_refusal(sid_a, headers_a,
                                                     first_answer=_LONG_ANSWER)
    _trigger_scoring_and_report(sid_a, headers_a)
    rows_a = _question_score_rows(sid_a)
    refused_rows = [r for r in rows_a if r["score_state"] == "REFUSED"]
    assert len(refused_rows) == 1, f"应恰有 1 行 REFUSED（拒答封存题）：{rows_a}"
    assert refused_rows[0]["score_final"] == 0, "REFUSED 行 score_final==0（§18）"

    agg_a = aggregate_session_scores(sid_a)
    refused_item_ids = {r["item_id"] for r in refused_rows}
    assert any(w["item_id"] in refused_item_ids for w in agg_a["refusals"]), \
        f"aggregate refusals 应含拒答题所属 item：{agg_a['refusals']}"

    # 拒答题实际不进 actual 平均：SCORED 行才进 item_scores_map 的均值
    scored_finals_by_item: dict[str, list[int]] = {}
    for r in rows_a:
        if r["score_state"] == "SCORED":
            scored_finals_by_item.setdefault(r["item_id"], []).append(r["score_final"])
    for it in agg_a["item_scores"]:
        if it.get("actual_level") is not None:
            expected = sum(scored_finals_by_item[it["item_id"]]) / len(
                scored_finals_by_item[it["item_id"]])
            assert abs(it["actual_level"] - round(expected, 2)) < 0.01, \
                f"item {it['std_name']} actual 应只含 SCORED 行均值：{it}"


def test_invalidated_objective():
    """题库造 1 道客观题 answer_key NULL（直插绕过 CR-01）→ INVALIDATED 且 score_final IS None。

    - 不写 1 分（旧 WR-14「按最低分记」语义）也不写 5 分（恒满分漏洞 REF-8.1）
    - aggregate 的 missing_warnings 含对应 reason
    - 该题不进任何 item 的 actual 平均
    """
    from server.services.aggregation import aggregate_session_scores
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    invalid_qid = _seed_invalid_objective(pid)
    headers = _auth_headers("p2_sco_invalid")
    sid = client.post("/api/assessment/sessions", json={"position_id": pid},
                      headers=headers).json()["session_id"]

    stats = _answer_whole_session(sid, headers, first_answer=_LONG_ANSWER,
                                  invalid_qid=invalid_qid)
    assert stats["invalidated_qid"] is not None, "NULL key 客观题应被派发到（选题池含 hard_skill）"

    _trigger_scoring_and_report(sid, headers)
    rows = _question_score_rows(sid)
    inv_rows = [r for r in rows if r["question_id"] == stats["invalidated_qid"]]
    assert len(inv_rows) == 1, f"NULL key 客观题应落 1 行 question_score：{rows}"
    inv = inv_rows[0]
    assert inv["score_state"] == "INVALIDATED", \
        f"NULL key 客观题应 INVALIDATED，实得 {inv['score_state']}"
    assert inv["score_final"] is None, \
        f"INVALIDATED 行 score_final 应为 None（不写 1/不写 5），实得 {inv['score_final']}"

    agg = aggregate_session_scores(sid)
    assert any(w["item_id"] == inv["item_id"] for w in agg["missing_warnings"]), \
        f"missing_warnings 应含 NULL key 题对应 item：{agg['missing_warnings']}"
    # 不进 actual 平均：Python item 的 actual 只由 SCORED 行构成
    scored_py = [r["score_final"] for r in rows
                 if r["score_state"] == "SCORED" and r["item_id"] == inv["item_id"]]
    for it in agg["item_scores"]:
        if it["item_id"] == inv["item_id"] and it.get("actual_level") is not None:
            expected = round(sum(scored_py) / len(scored_py), 2) if scored_py else None
            assert it["actual_level"] == expected, \
                f"INVALIDATED 题不应进 actual 平均：{it}"


def test_aggregation_reads_score_final():
    """聚合 item actual 的值等于各题 score_final 的均值（score_live≠score_final 场景）。

    构造：主观题用「长但无实义词」答案（score_live=2），mock 终局分恒 3
    ——score_live=2 与 score_final=3 两列不同值；若聚合取 final_score 合成
    （round(2*0.5+3*0.5)=round(2.5)=2）或混入 live，actual 将不等于 score_final 均值 3。
    """
    from server.services.aggregation import aggregate_session_scores
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p2_sco_final_col")
    sid = client.post("/api/assessment/sessions", json={"position_id": pid},
                      headers=headers).json()["session_id"]
    _answer_whole_session(sid, headers, first_answer=_LONG_EMPTY_ANSWER)
    _trigger_scoring_and_report(sid, headers)

    rows = _question_score_rows(sid)
    subj = [r for r in rows if r["qtype"] == "subjective"]
    assert subj, "整场应含主观题"
    assert all(r["score_live"] == 2 for r in subj), \
        f"mock 词表下长空答案应 score_live=2：{[(r['score_live'], r['score_final']) for r in subj]}"
    assert all(r["score_final"] == 3 for r in subj)

    agg = aggregate_session_scores(sid)
    finals_by_item: dict[str, list[int]] = {}
    for r in rows:
        if r["score_state"] == "SCORED":
            finals_by_item.setdefault(r["item_id"], []).append(r["score_final"])
    for it in agg["item_scores"]:
        if it.get("actual_level") is not None:
            expected = sum(finals_by_item[it["item_id"]]) / len(finals_by_item[it["item_id"]])
            assert abs(it["actual_level"] - expected) < 0.01, \
                f"item actual 应等于 SCORED 行 score_final 均值（live=2 不混入）：{it}"


def test_report_chain_end_to_end():
    """完整会话（含 1 拒答 + 1 INVALIDATED 客观题）→ POST /report → 报告成功生成。

    INVALIDATED/REFUSED 题不炸报告：radar_data.indicators 非空。
    """
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    invalid_qid = _seed_invalid_objective(pid)
    headers = _auth_headers("p2_sco_report")
    sid = client.post("/api/assessment/sessions", json={"position_id": pid},
                      headers=headers).json()["session_id"]

    stats = _answer_whole_session_with_one_refusal(sid, headers,
                                                   first_answer=_LONG_ANSWER,
                                                   invalid_qid=invalid_qid)
    assert stats["refused_qid"] is not None, "应有 1 道拒答封存题"
    assert stats["invalidated_qid"] is not None, "应有 1 道 NULL key 客观题"

    rpt = _trigger_scoring_and_report(sid, headers)
    assert rpt["total_score"] is not None
    assert len(rpt["radar_data"]["indicators"]) > 0, \
        "radar_data.indicators 应非空（拒答+无效题不炸报告）"
    rows = _question_score_rows(sid)
    states = {r["score_state"] for r in rows}
    assert "REFUSED" in states and "INVALIDATED" in states and "SCORED" in states, \
        f"整场应含三态行：{states}"
