"""虚拟考生端到端测试（c）：3 档考生（强/中/弱），断言报告档位正确区分。

设计依据：SSOT §23(c)——「强/中/弱三档端到端，断言总分排序（强>中>弱）+ 短板定位
符合预设 + required 覆盖 + 拒答/缺失状态 + 证据引用 + 报告状态」。

策略（SSOT §20.3 完整性门控对齐，2026-09-09 U4 后修订）：
- 客观题铺满全部分母——为每个正式范围能力项（scope item）造一道 eval_seed 客观题
  （answer_key=std_name，任意岗位可跑），未测量比例=0，总分链路真实走通；
  旧「每岗只造 3 题」形态在 §20.3 下必然 total_score=None（未测量比例>0.2），
  round(None) 即崩溃；
- 档位分差由答案命中率拉开：strong 全命中、medium 命中一半（偶序条目）、
  weak 全不命中——命中=5、未命中=1（§17 客观题规则判分）；
- 全客观题零 LLM 依赖（规则判分），三档任何provider下均确定可复跑。

题库隔离（WR-13 沿用）：占位题 status='eval_seed'，不进真实候选人选题池
（选题与 readiness 口径均为 status='active'）；且本工具评测全程跑在隔离
临时库（_run_isolated，REF-8.8/D-074），题随库丢弃，业务库零写入。

CLI 用法：
    python eval/virtual_candidates.py --position-id <pid>
"""
import argparse
import os
import sqlite3
import sys
import tempfile

# 允许直接 `python eval/virtual_candidates.py` 跑：把仓库根加进 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import get_conn, set_db_path  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.scoring import score_session  # noqa: E402
from server.services.aggregation import aggregate_session_scores  # noqa: E402
from server.services.report import generate_report  # noqa: E402

from eval.assertions import (  # noqa: E402
    assert_tier_ordering,
    assert_weaknesses_within_tested,
)


def _run_isolated(fn, *args):
    """在隔离临时库上运行评测（REF-8.8/D-074）。

    业务库 data/app.db 永不用于测试：把业务库只读快照到临时库（eval.db），
    评测写入全部落在临时库；结束 set_db_path(None) 复位，业务库零写入。
    """
    src = get_conn()  # 业务库（此刻无 override）
    tmp = os.path.join(tempfile.mkdtemp(prefix="gsd-eval-"), "eval.db")
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    set_db_path(tmp)
    try:
        return fn(*args)
    finally:
        set_db_path(None)


def _answer_for_tier(tier: str, seq: int, std_name: str) -> str:
    """按档位生成答案（答案长度 >20 字符，避免 followup 干扰流程）。
    strong 全命中、medium 偶序条目命中、weak 全不命中。"""
    if tier == "strong":
        return f"这道题我会从 {std_name} 入手，结合生产环境的实际经验详细展开说明整个方案和取舍。"
    if tier == "medium" and seq % 2 == 0:
        return f"主要思路是围绕 {std_name} 来设计，基本的原理我了解，可以简单说一说。"
    return "这个问题我了解得不够深入，只能凭印象说一说大概的概念和常见的做法。"


def _scope_items(conn, model_id: str) -> list[dict]:
    """该模型全部正式范围能力项（§20.1.A：非 gate 且 in_scope≠0，NULL 视为 1）。

    铺满口径 = 聚合分母口径（aggregation.scope_items 同谓词）——未测量比例可归零，
    §20.3 门控不触发，总分链路真实走通。
    """
    return conn.execute(
        "SELECT item_id, std_name, required_level FROM competency_item"
        " WHERE model_id=? AND gate=0 AND (in_scope IS NULL OR in_scope<>0)"
        " ORDER BY item_id",
        (model_id,),
    ).fetchall()


def _get_or_seed_bank(position_id: str, model_id: str) -> list[dict]:
    """为每个 scope item 确保一道 eval_seed 客观题（幂等），返回 items（含题目关联）。"""
    conn = get_conn()
    try:
        items = _scope_items(conn, model_id)
        if not items:
            raise ValueError(f"模型 {model_id} 无正式范围能力项，无法跑虚拟考生")
        # 幂等补题：每 item 一道（answer_key=std_name）。WR-13：占位题
        # status='eval_seed' 隔离态，不进真实候选人选题池（选题/ready 口径皆
        # status='active'）；本工具全程跑隔离临时库（_run_isolated），业务库零写入。
        for i, item in enumerate(items):
            conn.execute(
                "INSERT OR IGNORE INTO question_bank(question_id, scope, position_id, std_name,"
                " category, difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq,"
                " source, status, created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"qb_eval_{item['item_id'][:8]}_{i}", "position", position_id,
                    item["std_name"], "hard_skill", "easy", "objective",
                    f"（虚拟考生造题）请简述 {item['std_name']} 的核心概念。",
                    item["std_name"], None,
                    f"eval_{item['item_id'][:8]}", 1,
                    "human", "eval_seed", now_iso(),
                ),
            )
        conn.commit()
        return [dict(r) for r in items]
    finally:
        conn.close()


def _run_one_tier(position_id: str, user_id: str, tier: str, model_id: str,
                  items: list[dict]) -> dict:
    """跑一档：会话→逐 scope item 作答→打分→聚合，返回 {session_id, total_score}。"""
    conn = get_conn()
    try:
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
        for seq, item in enumerate(items, 1):
            qid = f"qb_eval_{item['item_id'][:8]}_{seq - 1}"
            answer = _answer_for_tier(tier, seq, item["std_name"])
            aq_id = new_id("aq")
            conn.execute(
                "INSERT INTO assessment_question(question_id, session_id, bank_question_id,"
                " seq, asked_at, answered_at, created_at, item_id) VALUES(?,?,?,?,?,?,?,?)",
                (aq_id, session_id, qid, seq, now_iso(), now_iso(), now_iso(),
                 item["item_id"]),
            )
            conn.execute(
                "INSERT INTO assessment_message(message_id, session_id, question_id,"
                " role, content, created_at) VALUES(?,?,?,?,?,?)",
                (new_id("am"), session_id, aq_id, "user", answer, now_iso()),
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
        return {
            "session_id": session_id,
            # §20.3 完整性门控：铺满分母后不应 None；仍 None（模型无 scope item 等
            # 边界）不崩溃——ordering 断言会如实失败，结果透传 None 供人工判读。
            "total_score": agg["total_score"],
            "unmeasured_ratio": agg.get("unmeasured_ratio"),
        }
    finally:
        conn.close()


def run_virtual_candidate(position_id: str, tier: str, user_id: str = "eval_user") -> dict:
    """跑单档虚拟考生（对外入口）。返回 {session_id, total_score}。"""
    _ensure_eval_user(user_id)
    model_id = _latest_confirmed_model(position_id)
    items = _get_or_seed_bank(position_id, model_id)
    return _run_one_tier(position_id, user_id, tier, model_id, items)


def _latest_confirmed_model(position_id: str) -> str:
    conn = get_conn()
    try:
        model = conn.execute(
            "SELECT model_id FROM competency_model WHERE position_id=? AND status='confirmed'"
            " ORDER BY version DESC LIMIT 1",
            (position_id,),
        ).fetchone()
        if model is None:
            raise ValueError(f"岗位 {position_id} 无 confirmed 模型，无法跑虚拟考生")
        return model["model_id"]
    finally:
        conn.close()


def _ensure_eval_user(user_id: str) -> None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT user_id FROM user WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
                " VALUES(?,?,?,?,1,?)",
                (user_id, user_id, "eval_placeholder", "candidate", now_iso()),
            )
            conn.commit()
    finally:
        conn.close()


def test_virtual_candidates(position_id: str) -> dict:
    """跑三档并断言六子项（§23(c)：排序/短板/required 覆盖/缺失/证据/报告状态）。

    checks 语义（对齐聚合现行输出契约）：
    - ordering：三档 total_score 强>中>弱（铺满分母后总分即 0-100 综合分）；
    - weakness：weak 档全不命中 → 各已测项 gap=required−1>0 → 短板含被测 std_name；
    - report_status：READY/PROVISIONAL（产生即通过；FAILED 才失败）；
    - evidence：weak 档 question_reviews.evidence_quote 全非空（§9.4 契约）；
    - required_coverage：§20.4 coverage——铺满后 observed=scope 全量、
      weight_coverage=1.0、required_covered=required_total；
    - missing_state：coverage.missing_reasons 列表 + item_details 明细在位
      （weak 档无缺失 → 空列表合法，断言结构在位而非非空）。
    """
    model_id = _latest_confirmed_model(position_id)
    _ensure_eval_user("eval_user")
    items = _get_or_seed_bank(position_id, model_id)
    scores: dict[str, float | None] = {}
    sessions: dict[str, str] = {}
    for tier in ("strong", "medium", "weak"):
        r = _run_one_tier(position_id, "eval_user", tier, model_id, items)
        scores[tier] = round(r["total_score"], 1) if r["total_score"] is not None else None
        sessions[tier] = r["session_id"]

    ok, msg = assert_tier_ordering(scores["strong"], scores["medium"], scores["weak"])

    # 报告下游五子项：weak 档全 miss → 各已测项 gap=required−1>0 → 短板取 gap×weight
    # 最大前 3（内部排序细节）；E2E 断言短板整体落在被测条目集合内（非空 + 无幻影）。
    # 客观题 evidence_quote=answer[:60]（scoring.py）→ 证据引用非空。
    report = generate_report(sessions["weak"])
    tested_names = [it["std_name"] for it in items]
    weakness_ok, weakness_msg = (
        assert_weaknesses_within_tested(report, tested_names) if tested_names
        else (False, "无被测能力项，无法断言短板")
    )
    report_ok = report.get("report_status") in ("READY", "PROVISIONAL")
    evidence_ok = bool(report.get("question_reviews")) and all(
        qr.get("evidence_quote") for qr in report["question_reviews"]
    )
    # §20.4 覆盖率五指标：分母 0 → 比率字段 null（前端显「不适用」）；铺满后
    # observed=scope 全量、weight_coverage=1.0、required 全覆盖
    coverage = report.get("coverage") or {}
    coverage_ok = (
        isinstance(coverage.get("observed_items"), int)
        and isinstance(coverage.get("scope_items"), int)
        and coverage.get("observed_items") == coverage.get("scope_items")
        and coverage.get("scope_items") > 0
        and coverage.get("weight_coverage") in (1.0, 1)
        and coverage.get("required_covered") == coverage.get("required_total")
    )
    # 缺失/拒答状态：coverage.missing_reasons 列表与 item_details 明细在位
    # （weak 档铺满无缺失 → 空列表合法；结构在位即过）
    missing_ok = ("missing_reasons" in coverage
                  and isinstance(coverage.get("missing_reasons"), list)
                  and isinstance(report.get("item_details"), list)
                  and bool(report["item_details"]))

    checks = {
        "ordering": (ok, msg),
        "weakness": (weakness_ok, weakness_msg),
        "report_status": (report_ok, f"report_status={report.get('report_status')}"),
        "evidence": (evidence_ok, "question_reviews evidence_quote 非空"),
        "required_coverage": (
            coverage_ok,
            f"observed={coverage.get('observed_items')}/{coverage.get('scope_items')}"
            f" weight_coverage={coverage.get('weight_coverage')}"
            f" required={coverage.get('required_covered')}/{coverage.get('required_total')}",
        ),
        "missing_state": (missing_ok, "coverage.missing_reasons / item_details 在位"),
    }
    all_ok = all(v[0] for v in checks.values())

    return {
        "test_name": "virtual_candidates",
        "position_id": position_id,
        "passed": all_ok,
        "scores": scores,
        "ordering_correct": ok,
        "message": msg,
        "checks": {k: {"passed": v[0], "message": v[1]} for k, v in checks.items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="虚拟考生三档端到端测试")
    ap.add_argument("--position-id", required=True)
    args = ap.parse_args()
    result = _run_isolated(test_virtual_candidates, args.position_id)
    print(f"passed={result['passed']} scores={result['scores']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
