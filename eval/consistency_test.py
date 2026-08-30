"""一致性测试（b）：同一份 transcript 复跑评分，断言 score_final 分差 ≤1。

设计依据：07 文档 §12 —「固定 transcript 复跑断言 score_final 分差≤1（temperature=0）」。
mock 模式确定性输出（同输入必同输出），分差恒为 0，应永远通过。

CLI 用法：
    python eval/consistency_test.py --session-id <sid> --runs 3
"""
import argparse
import os
import sys

# 允许直接 `python eval/consistency_test.py` 跑：把仓库根加进 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import get_conn  # noqa: E402
from server.services.scoring import score_question  # noqa: E402

from eval.assertions import assert_score_consistency  # noqa: E402


def _load_answered_questions(session_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT aq.question_id, b.stem FROM assessment_question aq"
        " JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE aq.session_id=? AND aq.answered_at IS NOT NULL ORDER BY aq.seq",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def test_scoring_consistency(session_id: str, runs: int = 3) -> dict:
    """对同一会话复跑 N 次评分，断言 score_final 分差 ≤1。

    Args:
      session_id: 已完成或至少有已答题的会话
      runs: 复跑次数（默认 3）

    Returns:
      {test_name, session_id, runs, passed, details}
    """
    conn = get_conn()
    s = conn.execute(
        "SELECT status FROM assessment_session WHERE session_id=?", (session_id,)
    ).fetchone()
    if s is None:
        return {
            "test_name": "scoring_consistency",
            "session_id": session_id,
            "runs": runs,
            "passed": False,
            "details": [],
            "error": f"会话不存在: {session_id}",
        }

    questions = _load_answered_questions(session_id)
    if not questions:
        return {
            "test_name": "scoring_consistency",
            "session_id": session_id,
            "runs": runs,
            "passed": False,
            "details": [],
            "error": "无已作答题目",
        }

    # 每题复跑 runs 次，收集 score_final
    per_question_scores: dict[str, list[int]] = {q["question_id"]: [] for q in questions}
    for _ in range(runs):
        for q in questions:
            r = score_question(session_id, q["question_id"])
            per_question_scores[q["question_id"]].append(int(r["score_final"]))

    details: list[dict] = []
    all_passed = True
    for q in questions:
        scores = per_question_scores[q["question_id"]]
        variance = max(scores) - min(scores)
        ok, _msg = assert_score_consistency(scores, max_variance=1)
        details.append({
            "question_id": q["question_id"],
            "stem_preview": q["stem"][:60],
            "scores": scores,
            "variance": variance,
            "passed": ok,
        })
        if not ok:
            all_passed = False

    return {
        "test_name": "scoring_consistency",
        "session_id": session_id,
        "runs": runs,
        "passed": all_passed,
        "details": details,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="评分一致性测试")
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    result = test_scoring_consistency(args.session_id, args.runs)
    print(f"passed={result['passed']}")
    for d in result.get("details", []):
        print(f"  q={d['question_id']} scores={d['scores']} variance={d['variance']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
