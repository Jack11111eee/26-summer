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
from server.services.question_selection import select_questions_for_session  # noqa: E402
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
    """造一个 confirmed 模型：2 hard_skill(一重一轻) + 1 soft_skill + 1 experience + 1 qualification。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("m")
    conn.execute("INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
                 (pid, "后端开发工程师", "active", now_iso()))
    items = [
        {"std_name": "Python", "category": "hard_skill", "required_level": 4,
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


def test_generation(pid: str, mid: str) -> None:
    print("[1] 题库生成（mock）")
    generate_question_bank(pid, mid)
    conn = get_conn()
    rows = conn.execute("SELECT * FROM question_bank").fetchall()
    check("生成题量=9（3+2+2+1+1）", len(rows) == 9, f"实际 {len(rows)}")

    by = {}
    for r in rows:
        by.setdefault((r["std_name"], r["category"]), []).append(dict(r))

    py = by.get(("Python", "hard_skill"), [])
    check("Python(weight>10%) 3 题 easy/medium/hard",
          [q["difficulty"] for q in py] == ["easy", "medium", "hard"] and len(py) == 3,
          f"实际 {[(q['difficulty']) for q in py]}")
    check("Python easy 为客观题带 answer_key",
          py and py[0]["qtype"] == "objective" and py[0]["answer_key"] == "Python")
    check("Python 题带 chain_key 且 seq 1..3",
          len(py) == 3 and all(q["chain_key"] for q in py)
          and [q["chain_seq"] for q in py] == [1, 2, 3])

    redis = by.get(("Redis", "hard_skill"), [])
    check("Redis(weight<=10%) 2 题 easy/medium",
          [q["difficulty"] for q in redis] == ["easy", "medium"])

    soft = by.get(("沟通能力", "soft_skill"), [])
    check("沟通能力 2 题 easy/hard",
          [q["difficulty"] for q in soft] == ["easy", "hard"])

    exp = by.get(("后端开发经验", "experience"), [])
    check("经验题为通用题库(scope=general)且无难度",
          len(exp) == 1 and exp[0]["scope"] == "general"
          and exp[0]["difficulty"] is None and exp[0]["position_id"] is None)

    qual = by.get(("本科学历", "qualification"), [])
    check("门槛题为通用题库(scope=general)", len(qual) == 1 and qual[0]["scope"] == "general")

    pos_qs = [r for r in rows if r["scope"] == "position"]
    check("岗位题均绑定 position_id", all(r["position_id"] == pid for r in pos_qs))
    check("四要素齐全(std_name/category/qtype/scope)",
          all(r["std_name"] and r["category"] and r["qtype"] and r["scope"] for r in rows))

    traces = conn.execute("SELECT COUNT(*) c FROM llm_trace WHERE call_type='question_gen'").fetchone()
    check("question_gen 调用落 llm_trace", traces["c"] == 9, f"实际 {traces['c']}")


def test_idempotent(pid: str, mid: str) -> None:
    print("[2] 幂等：重复触发不重复生成")
    generate_question_bank(pid, mid)
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) c FROM question_bank").fetchone()["c"]
    check("题量不变仍为 9", n == 9, f"实际 {n}")


def test_selection(pid: str, model: dict) -> None:
    print("[3] 选题算法")
    qs = select_questions_for_session(pid, model)
    by_cat = {}
    for q in qs:
        by_cat.setdefault(q["category"], []).append(q)
    check("硬技能 5 题（Python 链 3 + Redis 链 2）", len(by_cat.get("hard_skill", [])) == 5,
          f"实际 {len(by_cat.get('hard_skill', []))}")
    check("软技能 2 题（整链入选）", len(by_cat.get("soft_skill", [])) == 2)
    check("经验 1 题（题库仅 1 道，配额 2 取不满）", len(by_cat.get("experience", [])) == 1)
    check("门槛不占题", "qualification" not in by_cat)
    check("总量 8 题 = 硬 5 + 软 2 + 经验 1", len(qs) == 8, f"实际 {len(qs)}")
    py_chain = [q for q in qs if q["std_name"] == "Python"]
    check("Python 链按难度递进 easy→medium→hard",
          [q["difficulty"] for q in py_chain] == ["easy", "medium", "hard"])
    hard = by_cat.get("hard_skill", [])
    check("硬技能 required(Python) 先于 preferred(Redis)",
          hard and hard[0]["std_name"] == "Python")


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
    check("interviewer SYSTEM 含 action 协议",
          all(k in interviewer.INTERVIEWER_SYSTEM for k in ("followup", "next", "finish", "score_live")))
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


if __name__ == "__main__":
    init_db()
    pid, mid, model = _seed_model()
    test_generation(pid, mid)
    test_idempotent(pid, mid)
    test_selection(pid, model)
    test_prompts()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)
