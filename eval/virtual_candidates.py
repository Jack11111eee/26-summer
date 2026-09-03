"""虚拟考生端到端测试（c）：3 档考生（强/中/弱），断言报告档位正确区分。

设计依据：07 文档 §12 —「虚拟考生端到端：强/中/弱三档，断言 strong>medium>weak」。

策略（mock 模式纯 fixture 驱动，零服务修改）：
- 选用客观题（_score_objective：answer_key 正则命中→5 分，否则 1 分）保证确定性；
- 档位分差由答案命中率拉开：strong 全中、medium 中一半、weak 全不中；
- 主观题 mock 恒为 3 分，不影响档位排序（三档均分抬高相同常数）。

真实 LLM 模式下，三档 fixture 的答案质量（详细/一般/敷衍）由模型自然区分。

CLI 用法：
    python eval/virtual_candidates.py --position-id <pid>
"""
import argparse
import os
import sys

# 允许直接 `python eval/virtual_candidates.py` 跑：把仓库根加进 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import get_conn  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.scoring import score_session  # noqa: E402
from server.services.aggregation import aggregate_session_scores  # noqa: E402

from eval.assertions import assert_tier_ordering  # noqa: E402

# ---------- 三档答案 fixture（答案长度 >20 字符，避免 followup 干扰流程）----------
_KEYWORDS = ["索引", "事务", "缓存"]  # 客观题 answer_key 用


def _answers_for_tier(tier: str, questions: list[dict]) -> list[str]:
    """按档位给每道题造答案。strong 全命中、medium 命中一半、weak 全不命中。"""
    answers: list[str] = []
    for i, q in enumerate(questions):
        key = q["answer_key"] or _KEYWORDS[i % len(_KEYWORDS)]
        if tier == "strong":
            answers.append(f"这道题我会从 {key} 入手，结合生产环境的实际经验详细展开说明整个方案和取舍。")
        elif tier == "medium":
            if i % 2 == 0:
                answers.append(f"主要思路是围绕 {key} 来设计，基本的原理我了解，可以简单说一说。")
            else:
                answers.append("这个问题我了解得不够深入，只能凭印象说一说大概的概念和常见的做法。")
        else:
            answers.append("这个问题我不太清楚，之前没有接触过，只能随便说说我的猜测和理解。")
    return answers


def _get_or_seed_bank(position_id: str) -> str:
    """确保该岗位存在可测的客观题；没有则按 fixture 造 3 道（idempotent）。返回 model_id。"""
    conn = get_conn()
    model = conn.execute(
        "SELECT model_id FROM competency_model WHERE position_id=? AND status='confirmed'"
        " ORDER BY version DESC LIMIT 1",
        (position_id,),
    ).fetchone()
    if model is None:
        raise ValueError(f"岗位 {position_id} 无 confirmed 模型，无法跑虚拟考生")
    model_id = model["model_id"]

    items = conn.execute(
        "SELECT item_id, std_name FROM competency_item WHERE model_id=? AND category='hard_skill'"
        " ORDER BY weight DESC LIMIT 3",
        (model_id,),
    ).fetchall()
    if not items:
        raise ValueError(f"模型 {model_id} 无 hard_skill 能力项，无法造题")

    existing = conn.execute(
        "SELECT COUNT(*) AS c FROM question_bank WHERE position_id=? AND qtype='objective'"
        " AND status IN ('active','eval_seed')",
        (position_id,),
    ).fetchone()["c"]
    if existing >= 3:
        return model_id

    # 造 3 道客观题（answer_key = fixture 关键词）。
    # WR-13：占位题写 status='eval_seed' 隔离态（表无 status CHECK，无需迁移）——
    # 选题（question_selection）与 readiness 计数口径均为 status='active'，
    # 占位题不进真实候选人选题池、不计配额；仅本工具自身会话可见。
    for i, item in enumerate(items[:3]):
        conn.execute(
            "INSERT OR IGNORE INTO question_bank(question_id, scope, position_id, std_name, category,"
            " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq,"
            " source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"qb_eval_{item['item_id'][:8]}_{i}",
                "position", position_id, item["std_name"], "hard_skill",
                "easy", "objective",
                f"（虚拟考生造题）请简述 {item['std_name']} 的核心概念。",
                _KEYWORDS[i % len(_KEYWORDS)], None,
                f"eval_{item['item_id'][:8]}", 1,
                "human", "eval_seed", now_iso(),
            ),
        )
    conn.commit()
    return model_id


def _run_one_tier(position_id: str, user_id: str, tier: str, model_id: str) -> dict:
    """跑一档：会话→作答→打分→聚合，返回 {session_id, total_score}。"""
    conn = get_conn()
    session_id = new_id("as")
    model = conn.execute(
        "SELECT version FROM competency_model WHERE model_id=?", (model_id,)
    ).fetchone()
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id, model_version,"
        " status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (session_id, user_id, position_id, model_id, model["version"],
         "in_progress", now_iso(), now_iso()),
    )
    questions = conn.execute(
        "SELECT question_id, answer_key FROM question_bank"
        " WHERE position_id=? AND qtype='objective' AND status IN ('active','eval_seed')"
        " ORDER BY question_id LIMIT 3",
        (position_id,),
    ).fetchall()
    answers = _answers_for_tier(tier, [dict(q) for q in questions])

    for seq, (q, ans) in enumerate(zip(questions, answers), 1):
        aq_id = new_id("aq")
        conn.execute(
            "INSERT INTO assessment_question(question_id, session_id, bank_question_id,"
            " seq, asked_at, answered_at, created_at) VALUES(?,?,?,?,?,?,?)",
            (aq_id, session_id, q["question_id"], seq, now_iso(), now_iso(), now_iso()),
        )
        conn.execute(
            "INSERT INTO assessment_message(message_id, session_id, question_id,"
            " role, content, created_at) VALUES(?,?,?,?,?,?)",
            (new_id("am"), session_id, aq_id, "user", ans, now_iso()),
        )
    # 先落库再评分（score_session 用独立连接）；评分须在置 completed 之前（01-03 护栏）
    conn.commit()

    score_session(session_id)
    conn.execute(
        "UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
        (now_iso(), session_id),
    )
    conn.commit()
    agg = aggregate_session_scores(session_id)
    return {"session_id": session_id, "total_score": agg["total_score"]}


def run_virtual_candidate(position_id: str, tier: str, user_id: str = "eval_user") -> dict:
    """跑单档虚拟考生（对外入口）。返回 {session_id, total_score}。"""
    _ensure_eval_user(user_id)
    model_id = _get_or_seed_bank(position_id)
    return _run_one_tier(position_id, user_id, tier, model_id)


def _ensure_eval_user(user_id: str) -> None:
    conn = get_conn()
    row = conn.execute("SELECT user_id FROM user WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (user_id, user_id, "eval_placeholder", "candidate", now_iso()),
        )
        conn.commit()


def test_virtual_candidates(position_id: str) -> dict:
    """跑三档并断言 strong>medium>weak。"""
    model_id = _get_or_seed_bank(position_id)
    _ensure_eval_user("eval_user")
    scores: dict[str, float] = {}
    for tier in ("strong", "medium", "weak"):
        r = _run_one_tier(position_id, "eval_user", tier, model_id)
        scores[tier] = round(r["total_score"], 1)

    ok, msg = assert_tier_ordering(scores["strong"], scores["medium"], scores["weak"])
    return {
        "test_name": "virtual_candidates",
        "position_id": position_id,
        "passed": ok,
        "scores": scores,
        "ordering_correct": ok,
        "message": msg,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="虚拟考生三档端到端测试")
    ap.add_argument("--position-id", required=True)
    args = ap.parse_args()
    result = test_virtual_candidates(args.position_id)
    print(f"passed={result['passed']} scores={result['scores']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
