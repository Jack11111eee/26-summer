"""题库生成（07 文档 §6.2）：模型 confirmed 后异步触发，岗位题 + 通用题双轨。

- hard_skill / soft_skill → 岗位题库（scope=position，带难度链条）
- experience / qualification → 通用题库（scope=general，无难度，跨岗位复用）
幂等：同岗位同能力项已有 active 题则跳过，不重复生成。
"""
import json

from ..db import get_conn
from .llm import call_llm_json
from .pipeline import new_id, now_iso
from .prompts.question_gen import QUESTION_GEN_SYSTEM, generate_questions_prompt


def _question_plan(item: dict) -> list[tuple[str, str]]:
    """按类目与权重规划 (difficulty, qtype) 清单（07 §6.2 + 难度递进 N1）。

    hard_skill：weight>10% → 3 档（easy/medium/hard），否则 2 档（easy/medium）
    soft_skill：2 档（easy/hard）
    experience / qualification：无难度（difficulty=None），各 1 题
    """
    cat = item["category"]
    if cat == "hard_skill":
        if (item.get("weight") or 0) > 0.10:
            return [("easy", "objective"), ("medium", "subjective"), ("hard", "subjective")]
        return [("easy", "objective"), ("medium", "subjective")]
    if cat == "soft_skill":
        return [("easy", "subjective"), ("hard", "subjective")]
    return [(None, "subjective")]


def _mock_question_gen(system_prompt: str, user_prompt: str) -> dict:
    """离线 mock：从 user prompt 中解析能力项/难度/题型，生成模板题。"""
    lines = dict(
        ln.split("：", 1) for ln in user_prompt.splitlines() if "：" in ln
    )
    std_name = lines.get("能力项", "该能力")
    last = user_prompt.strip().splitlines()[-1]
    difficulty = "medium"
    for d in ("easy", "medium", "hard"):
        if f" {d} " in last:
            difficulty = d
            break
    qtype = "objective" if " objective " in last else "subjective"

    if difficulty == "easy":
        stem = f"请谈谈你对{std_name}的理解。"
    else:
        stem = f"请描述一个使用{std_name}解决复杂问题的场景。"
    q = {"stem": stem, "difficulty": difficulty, "qtype": qtype,
         "answer_key": std_name if qtype == "objective" else None,
         "rubric": None if qtype == "objective" else f"能结合实例说明{std_name}的应用；思路清晰；有结果数据"}
    return {"questions": [q]}


def _insert_question(conn, *, scope: str, position_id: str | None, item: dict,
                     difficulty: str | None, qtype: str, stem: str,
                     answer_key: str | None, rubric: str | None,
                     chain_key: str | None, chain_seq: int | None) -> None:
    conn.execute(
        "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
        " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq, source, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("q"), scope, position_id, item["std_name"], item["category"],
         difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq,
         "llm_seed", "active", now_iso()),
    )


def generate_question_bank(position_id: str, model_id: str) -> None:
    """为 confirmed 模型生成题库（异步任务调用）。失败不抛，仅静默（可手动重触发）。"""
    conn = get_conn()
    pos = conn.execute("SELECT name FROM position WHERE position_id=?", (position_id,)).fetchone()
    if pos is None:
        return
    position_name = pos["name"]
    items = conn.execute(
        "SELECT item_id, std_name, category, required_level, weight, evidence_json"
        " FROM competency_item WHERE model_id=?",
        (model_id,),
    ).fetchall()

    for row in items:
        item = dict(row)
        item["evidence"] = json.loads(item.pop("evidence_json") or "[]")
        scope = "position" if item["category"] in ("hard_skill", "soft_skill") else "general"

        # 幂等：同能力项已有 active 题则跳过（岗位题按岗位+项，通用题按项跨岗位）
        if scope == "position":
            exists = conn.execute(
                "SELECT 1 FROM question_bank WHERE scope='position' AND position_id=?"
                " AND std_name=? AND category=? AND status='active' LIMIT 1",
                (position_id, item["std_name"], item["category"]),
            ).fetchone()
        else:
            exists = conn.execute(
                "SELECT 1 FROM question_bank WHERE scope='general'"
                " AND std_name=? AND category=? AND status='active' LIMIT 1",
                (item["std_name"], item["category"]),
            ).fetchone()
        if exists:
            continue

        plan = _question_plan(item)
        chain_key = item["item_id"] if scope == "position" and len(plan) > 1 else None
        for seq, (difficulty, qtype) in enumerate(plan, start=1):
            result = call_llm_json(
                "question_gen", item["item_id"], QUESTION_GEN_SYSTEM,
                generate_questions_prompt(item, position_name, difficulty or "general", qtype),
                mock_fn=_mock_question_gen,
            )
            for q in result.get("questions", []):
                _insert_question(
                    conn, scope=scope,
                    position_id=position_id if scope == "position" else None,
                    item=item, difficulty=difficulty, qtype=q.get("qtype", qtype),
                    stem=q["stem"], answer_key=q.get("answer_key"), rubric=q.get("rubric"),
                    chain_key=chain_key, chain_seq=seq if chain_key else None,
                )
            conn.commit()
