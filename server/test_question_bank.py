"""M5 题库 + 选题 + 提示词测试（mock 模式，离线可跑）。

运行: cd server && python test_question_bank.py
"""
import json
import os
import sys
import tempfile

# 隔离测试库：必须在 import server 模块前设置
_tmpdir = tempfile.mkdtemp(prefix="qb_test_")
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test.db")
os.environ["LLM_PROVIDER"] = "mock"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 仓库根

from server.db import get_conn, init_db  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.question_bank import generate_question_bank  # noqa: E402
from server.services.prompts import question_gen, interviewer, refine, score  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def _seed_model() -> tuple[str, str, dict]:
    """造一个 confirmed 模型：2 hard_skill（rl 5/rl 3 各一）+ 1 soft_skill + 1 experience + 1 qualification。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("m")
    conn.execute("INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
                 (pid, "后端开发工程师", "active", now_iso()))
    items = [
        {"std_name": "Python", "category": "hard_skill", "required_level": 5,
         "importance": "required", "weight": 0.19, "evidence": [{"text": "精通Python"}]},
        {"std_name": "Redis", "category": "hard_skill", "required_level": 3,
         "importance": "preferred", "weight": 0.05, "evidence": [{"text": "熟悉Redis"}]},
        {"std_name": "沟通能力", "category": "soft_skill", "required_level": 3,
         "importance": "required", "weight": 0.12, "evidence": [{"text": "良好的沟通能力"}]},
        {"std_name": "后端开发经验", "category": "experience", "required_level": None,
         "importance": "required", "weight": 0.08, "years": 3, "evidence": [{"text": "3年以上后端经验"}]},
        {"std_name": "本科学历", "category": "qualification", "required_level": None,
         "importance": "required", "weight": 0.01, "gate": 1, "evidence": [{"text": "本科及以上"}]},
    ]
    model = {"items": items}
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, 1, "confirmed", json.dumps(model, ensure_ascii=False), now_iso()),
    )
    for it in items:
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, years, gate, evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (new_id("c"), mid, it["std_name"], it["category"], it.get("required_level"),
             it.get("importance"), it.get("weight"), it.get("years"), int(it.get("gate", 0)),
             json.dumps(it.get("evidence", []), ensure_ascii=False)),
        )
    conn.commit()
    return pid, mid, model


def check_generation(pid: str, mid: str) -> None:
    print("[1] 题库生成（mock）")
    generate_question_bank(pid, mid)
    conn = get_conn()
    rows = conn.execute("SELECT * FROM question_bank").fetchall()
    check("生成题量=7（3+2+2，exp/qual 不生成——SSOT §9.1）", len(rows) == 7, f"实际 {len(rows)}")

    by = {}
    for r in rows:
        by.setdefault((r["std_name"], r["category"]), []).append(dict(r))

    py = by.get(("Python", "hard_skill"), [])
    check("Python(required_level=5) 3 题 easy/medium/hard（§17 修订：weight 解耦）",
          [q["difficulty"] for q in py] == ["easy", "medium", "hard"] and len(py) == 3,
          f"实际 {[(q['difficulty']) for q in py]}")
    check("Python easy 为客观题带 answer_key",
          py and py[0]["qtype"] == "objective" and py[0]["answer_key"] == "Python")
    check("Python 题带 chain_key 且 seq 1..3",
          len(py) == 3 and all(q["chain_key"] for q in py)
          and [q["chain_seq"] for q in py] == [1, 2, 3])

    redis = by.get(("Redis", "hard_skill"), [])
    check("Redis(required_level=3) 2 题 easy/medium",
          [q["difficulty"] for q in redis] == ["easy", "medium"])

    soft = by.get(("沟通能力", "soft_skill"), [])
    check("沟通能力 2 题 easy/hard",
          [q["difficulty"] for q in soft] == ["easy", "hard"])

    exp = by.get(("后端开发经验", "experience"), [])
    check("经验项不生成题（SSOT §9.1 2026-09-07）", len(exp) == 0)

    qual = by.get(("本科学历", "qualification"), [])
    check("门槛项不生成题（SSOT §9.1 2026-09-07）", len(qual) == 0)

    pos_qs = [r for r in rows if r["scope"] == "position"]
    check("岗位题均绑定 position_id", all(r["position_id"] == pid for r in pos_qs))
    check("全部题为岗位题（无 scope=general 新行）", len(pos_qs) == len(rows))
    check("四要素齐全(std_name/category/qtype/scope)",
          all(r["std_name"] and r["category"] and r["qtype"] and r["scope"] for r in rows))

    # §9.4 契约第 1 条（2026-09-09）：新题五测量字段全部写满 + 查表正确
    check("五测量字段全部非空（measurement_target 等 + rubric_version）",
          all(r["measurement_target"] and r["evidence_requirement"]
              and r["observable_level_max"] and r["observable_level_min"]
              and r["rubric_version"] == "v2" for r in rows))
    _lvl = {"easy": (3, 2), "medium": (4, 3), "hard": (5, 4)}
    check("observable_level_max/min 按难度查表（easy 3/2 · medium 4/3 · hard 5/4）",
          all((r["observable_level_max"], r["observable_level_min"])
              == _lvl[r["difficulty"]] for r in rows if r["difficulty"]))

    traces = conn.execute("SELECT COUNT(*) c FROM llm_trace WHERE call_type='question_gen'").fetchone()
    check("question_gen 调用落 llm_trace", traces["c"] == 7, f"实际 {traces['c']}")


def check_idempotent(pid: str, mid: str) -> None:
    print("[2] 幂等：重复触发不重复生成")
    generate_question_bank(pid, mid)
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) c FROM question_bank").fetchone()["c"]
    check("题量不变仍为 7", n == 7, f"实际 {n}")


def check_selection(pid: str, mid: str, model: dict) -> None:
    """[3] 动态选题（02-02：select_next_question 服务级断言，脚本式保持）。"""
    print("[3] 选题算法（动态四层）")
    from server.services.question_selection import (
        largest_remainder_73,
        plan_quotas,
        select_next_question,
    )
    from server import config
    # 测试用 N（沿用 config 常量——Anti-pattern 4：测试值非生产默认语义）
    n = config.ORDINARY_PLAN_N

    # 配额纯函数（§10.2 表 + §10.3 公式）
    check("7:3 最大余数 N=9/10/11/15 四样例",
          [largest_remainder_73(k) for k in (9, 10, 11, 15)]
          == [(6, 3), (7, 3), (8, 3), (11, 4)])
    hard_n, soft_n = largest_remainder_73(n)
    qs_targets = plan_quotas(n, {"hard_skill": {"required": 9, "preferred": 9, "plus": 9},
                                 "soft_skill": {"required": 9, "preferred": 9, "plus": 9}})
    check(f"plan_quotas 类目总量 = 7:3 分配（N={n} → hard {hard_n} / soft {soft_n}）",
          sum(qs_targets["hard_skill"].values()) == hard_n
          and sum(qs_targets["soft_skill"].values()) == soft_n)

    # 直插最小 session 种子后调 select_next_question（服务级，不跑完整 API）
    conn = get_conn()
    sid = new_id("s")
    now = now_iso()
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, created_at) VALUES(?,?,?,?,?)",
        (new_id("u"), "qb_sel_user", "x", "candidate", now_iso()))
    uid = conn.execute("SELECT user_id FROM user WHERE username='qb_sel_user'").fetchone()["user_id"]
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (sid, uid, pid, mid, 1, "in_progress", now, now))
    conn.commit()

    picked = select_next_question(sid)
    check("select_next_question 返回首题实例（非 None）", picked is not None)
    row = conn.execute(
        "SELECT aq.question_id, aq.selection_reason, b.category, b.std_name"
        " FROM assessment_question aq JOIN question_bank b"
        " ON b.question_id=aq.bank_question_id WHERE aq.session_id=? ORDER BY aq.seq DESC LIMIT 1",
        (sid,)).fetchone()
    check("首题实例已落库（question_id 一致）",
          row is not None and row["question_id"] == picked["question_id"])
    reason = json.loads(row["selection_reason"])
    check("selection_reason 七键 + nth 结构（D-18）",
          {"layer", "predicate", "category", "tier", "chain_followed", "weight", "seed", "nth"}
          <= set(reason.keys()))
    check("首题为普通类目（hard/soft，experience/qualification 剔除）",
          row["category"] in ("hard_skill", "soft_skill"))
    check("首题 tier 为模型 item 归属（required 优先）",
          reason["layer"] in ("required_first", "quota"))


def test_prompts() -> None:
    print("[4] 提示词契约")
    p = question_gen.generate_questions_prompt(
        {"std_name": "Python", "category": "hard_skill", "required_level": 4,
         "definition": "", "evidence": [{"text": "精通Python"}]},
        "后端开发工程师", "medium", "subjective")
    check("question_gen prompt 含岗位/能力项/难度",
          "后端开发工程师" in p and "Python" in p and "medium" in p)
    check("question_gen SYSTEM 声明 JSON 输出", "JSON" in question_gen.QUESTION_GEN_SYSTEM)

    mock_out = question_gen.QUESTION_GEN_SYSTEM  # 静态校验即可
    # 02-04 两层化（D-09 只改断言）：prompt 改出观察契约（answer_state 枚举 + 维度），
    # action/followup 键从 LLM 输出移除——代码裁决（REF-1.6/1.7）
    check("interviewer SYSTEM 含观察协议（answer_state/维度/score_live）",
          all(k in interviewer.INTERVIEWER_SYSTEM
              for k in ("answer_state", "observation", "specificity", "score_live"))
          and "followup" not in interviewer.INTERVIEWER_SYSTEM)
    check("refine prompt 包装用户输入", "用户输入" in refine.refine_prompt("abc"))
    check("score prompt 含题目/rubric/回答",
          all(k in score.score_prompt({"stem": "S", "rubric": "R"}, "A", "P")
              for k in ("S", "R", "A", "P")))

    # interviewer 上下文重建
    conn = get_conn()
    sid = new_id("s")
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, created_at) VALUES(?,?,?,?,?)",
        (new_id("u"), "cand1", "x", "candidate", now_iso()))
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        ("pos_x", "占位岗", "active", now_iso()))
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)", ("m_x", "pos_x", 1, "confirmed", '{"items":[]}', now_iso()))
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id, model_version,"
        " status, started_at, created_at)"
        " SELECT ?, user_id, ?, ?, 1, 'in_progress', ?, ? FROM user WHERE username='cand1'",
        (sid, "pos_x", "m_x", now_iso(), now_iso()))
    conn.execute(
        "INSERT INTO assessment_message(message_id, session_id, role, content, created_at)"
        " VALUES(?,?,?,?,?)", (new_id("msg"), sid, "assistant", "你好", now_iso()))
    conn.commit()
    ctx = interviewer.build_interview_context(sid, conn)
    check("build_interview_context 返回 messages 数组",
          ctx == [{"role": "assistant", "content": "你好"}], f"实际 {ctx}")


def _seed_position_and_items() -> tuple[str, str]:
    """归一化回归用种子：active 岗位 + confirmed 模型 + 1 个 hard_skill 项 + QUEUED task 行
    （task 行由 confirm/retry 端点插入，generate_question_bank 只 UPDATE 最新行——与生产一致）。
    required_level=4 → §17 修订下两档（easy/medium，与打桩的 2 次 LLM 调用对齐——旧规则
    weight>0.10 三档时曾致「降级路径任务」隐藏 FAIL）。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("m")
    now = now_iso()
    conn.execute("INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
                 (pid, "SLAM算法工程师", "active", now))
    items = [{"std_name": "地图构建", "category": "hard_skill", "required_level": 4,
              "importance": "required", "weight": 0.19, "evidence": [{"text": "精通SLAM建图"}]}]
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, 1, "confirmed", json.dumps({"items": items}, ensure_ascii=False), now),
    )
    for it in items:
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, evidence_json) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("c"), mid, it["std_name"], it["category"], it.get("required_level"),
             it.get("importance"), it.get("weight"),
             json.dumps(it.get("evidence", []), ensure_ascii=False)),
        )
    conn.execute(
        "INSERT INTO question_bank_task(task_id, position_id, model_id, model_version,"
        " status, created_at) VALUES(?,?,?,?,?,?)",
        (new_id("qbt"), pid, mid, 1, "QUEUED", now),
    )
    conn.commit()
    return pid, mid


def _patch_llm(questions_per_call: list[list[dict]]):
    """monkeypatch server.services.question_bank.call_llm_json：按调用序依次返回给定题目。

    LLM_PROVIDER=mock 时 call_llm_json 本走 _mock_question_gen——为造「rubric 是 list」
    等真 LLM 形态，把整个 call_llm_json 打桩直接返回指定 dict（同时落 trace 保口径）。
    返回打桩函数；questions_per_call 每元素是一次 call_llm_json 调用的 questions 列表。
    """
    import server.services.question_bank as qb

    calls = iter(questions_per_call)

    def fake_call_llm_json(call_type, ref_id, system_prompt, user_prompt,
                           mock_fn=None, trace_out=None):
        from server.db import get_conn as _gc
        result = {"questions": next(calls)}
        conn = _gc()
        try:
            conn.execute(
                "INSERT INTO llm_trace(trace_id, call_type, ref_id, attempt, prompt, response,"
                " success, error, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (new_id("t"), call_type, ref_id, 1, system_prompt + "\n\n" + user_prompt,
                 json.dumps(result, ensure_ascii=False), 1, None, now_iso()),
            )
            conn.commit()
        finally:
            conn.close()
        return result

    return fake_call_llm_json, qb


def test_generate_question_bank_rubric_list_normalized(monkeypatch):
    """主用例（qbt_74fedfff3a23 故障直击）：LLM 返回 rubric=list[str] → 任务 SUCCEEDED、
    入库 rubric 为换行连接的 str（sqlite3 参数绑定不支持 list）。"""
    pid, mid = _seed_position_and_items()
    fake, qb = _patch_llm([
        # Python 计划 easy(objective)：answer_key 仍为 list（实测 t_1e12628bf54f 也有此风险形态）→ 归一为 |
        [{"stem": "请谈谈你对地图构建的理解。",
          "difficulty": "easy", "qtype": "objective",
          "answer_key": ["栅格地图", "拓扑地图"], "rubric": None}],
        # 计划 medium(subjective)：rubric 为 4 元素 JSON 数组——本次故障形态
        [{"stem": "请描述一个使用地图构建解决复杂问题的场景。",
          "difficulty": "medium", "qtype": "subjective",
          "answer_key": None, "rubric": ["要点一。", "要点二。", "", "要点三。"]}],
    ])
    monkeypatch.setattr(qb, "call_llm_json", fake)
    qb.generate_question_bank(pid, mid)

    conn = get_conn()
    task = conn.execute(
        "SELECT status, error_msg FROM question_bank_task WHERE position_id=? AND model_id=?"
        " ORDER BY created_at DESC LIMIT 1", (pid, mid)).fetchone()
    check("任务 SUCCEEDED（rubric list 不再炸 INSERT）", task["status"] == "SUCCEEDED",
          f"实际 {task['status']} {task['error_msg']}")
    rows = conn.execute(
        "SELECT difficulty, qtype, answer_key, rubric FROM question_bank"
        " WHERE model_id=? ORDER BY difficulty", (mid,)).fetchall()
    check("插入 2 题（easy/medium）", len(rows) == 2, f"实际 {len(rows)}")
    subj = [r for r in rows if r["qtype"] == "subjective"][0]
    check("subjective rubric 为 str（换行连接）",
          isinstance(subj["rubric"], str) and subj["rubric"] == "要点一。\n要点二。\n要点三。"
          and subj["rubric"].count("\n") == 2, f"实际 {subj['rubric']!r}")
    obj = [r for r in rows if r["qtype"] == "objective"][0]
    check("objective answer_key list 多元素 → [any_of] 前缀 + 换行 join（§17 过渡标记）",
          obj["answer_key"] == "[any_of] 栅格地图\n拓扑地图", f"实际 {obj['answer_key']!r}")
    check("objective 行 rubric 仍为 NULL", obj["rubric"] is None)


def test_generate_question_bank_wr06_list_rubric_no_crash(monkeypatch):
    """WR-06 伴生雷：objective 缺 answer_key 降级 subjective 且 rubric 为非空 list——
    旧代码 `(q.get("rubric") or "").strip()` 对 list 抛 AttributeError；归一化后安全入库。"""
    pid, mid = _seed_position_and_items()
    fake, qb = _patch_llm([
        [{"stem": "请谈谈你对地图构建的理解。",
          "difficulty": "easy", "qtype": "objective",
          "answer_key": None, "rubric": ["能说明建图流程。", "能举例传感器。"]}],
    ])
    monkeypatch.setattr(qb, "call_llm_json", fake)
    qb.generate_question_bank(pid, mid)  # 不抛 AttributeError 即过

    conn = get_conn()
    task = conn.execute(
        "SELECT status, error_msg FROM question_bank_task WHERE position_id=? AND model_id=?"
        " ORDER BY created_at DESC LIMIT 1", (pid, mid)).fetchone()
    check("降级路径任务 SUCCEEDED", task["status"] == "SUCCEEDED",
          f"实际 {task['status']} {task['error_msg']}")
    row = conn.execute(
        "SELECT qtype, answer_key, rubric FROM question_bank WHERE model_id=?", (mid,)).fetchone()
    check("CR-01 降级：objective → subjective", row["qtype"] == "subjective", f"实际 {row['qtype']}")
    check("降级后 answer_key 置 None", row["answer_key"] is None)
    check("非空 list rubric 归一入库（非默认文案）",
          row["rubric"] == "能说明建图流程。\n能举例传感器。", f"实际 {row['rubric']!r}")


if __name__ == "__main__":
    init_db()
    pid, mid, model = _seed_model()
    check_generation(pid, mid)
    check_idempotent(pid, mid)
    check_selection(pid, mid, model)
    test_prompts()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)
