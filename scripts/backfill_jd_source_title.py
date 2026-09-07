"""JD 源标题回填脚本（修理工单 2026-09-07：导入链路丢失源 job_title）。

历史批次（如 2026-09-06 rocxu-ai 1000 条）导入时源标题被丢弃、job_title 已被
LLM#1 覆写成漂移值。本脚本用 raw_text 全文配对源 jsonl 行（jsonl 侧 text_raw
键全唯一已核实；前缀匹配有歧义不猜），把源标题写回 jd_record.job_title，并用
修复后的 assign_position（源标题优先 + COLLATE NOCASE）重算 position_id，最后
清理再无 JD 挂靠的 pending_review 孤儿岗（active 岗一律不动）。

用法（默认 dry-run，只打印计划摘要，不写库）：
    python -m scripts.backfill_jd_source_title
    python -m scripts.backfill_jd_source_title --db /tmp/copy.db   # 在副本上演练
    python -m scripts.backfill_jd_source_title --apply              # 真正写库（须人工审阅后执行）

注意：
- 业务库 data/app.db 的 --apply 由用户本人执行；执行前建议先
  `cp data/app.db data/backups/pre-backfill.db` 留回滚点。
- 仅处理 source_type='file' 的 JD（paste/plugin 导入无源 jsonl）。
- 不重跑 LLM、不重清洗、不改 status（raw_items/std_items/cleaned_text 原样保留）。
- 幂等：重跑输出 0 changed。
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_JSONL = REPO_ROOT / "data" / "jd_corpus" / "normalized" / "rocxu-ai.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 JD 源标题并重算归岗")
    parser.add_argument("--jsonl", default=str(DEFAULT_JSONL), help="源语料 jsonl 路径")
    parser.add_argument("--db", default=None, help="目标库路径（默认 config.DB_PATH 即 data/app.db）")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    args = parser.parse_args()

    import os

    os.environ.setdefault("LLM_PROVIDER", "mock")  # 纯脚本：assign_position 无 LLM 路径

    from server.db import get_conn, init_db, set_db_path

    if args.db:
        set_db_path(args.db)
    init_db()

    # ---------- 1. 读源 jsonl：全文键（text_raw 全唯一，已核实） ----------
    title_map: dict[str, str] = {}
    with open(args.jsonl, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            text_raw = rec.get("text_raw")
            job_title = rec.get("job_title")
            if not isinstance(text_raw, str) or not text_raw:
                print(f"[warn] 第 {lineno} 行缺 text_raw，跳过")
                continue
            if not isinstance(job_title, str) or not job_title.strip():
                continue  # 源行本身无标题：不入映射（DB 行保持现状，不被回填清空）
            if text_raw in title_map:
                print(f"[warn] jsonl 全文键重复（第 {lineno} 行），停止以防错配")
                return 2
            title_map[text_raw] = job_title.strip()

    print(f"[info] 源 jsonl：{len(title_map)} 行带标题")

    # ---------- 2. 逐条配对并计算计划 ----------
    from server.services.pipeline import assign_position

    conn = get_conn()
    rows = conn.execute(
        "SELECT jd_id, raw_text, job_title, position_id FROM jd_record"
        " WHERE source_type='file'"
    ).fetchall()

    plan = []  # (jd_id, new_title, current_title, new_pid, old_pid, status)
    unmatched = 0
    for r in rows:
        src_title = title_map.get(r["raw_text"])
        if src_title is None:
            unmatched += 1
            print(f"[warn] JD {r['jd_id']} raw_text 未匹配源 jsonl 行，保持现状")
            continue
        # 测算重算后的岗位 id（dry-run 不落库：在自身事务里跑，随用随回滚）
        conn.execute("SAVEPOINT backfill_probe")
        try:
            new_pid, why = assign_position(src_title)
        finally:
            conn.execute("ROLLBACK TO backfill_probe")
            conn.execute("RELEASE backfill_probe")
        plan.append((r["jd_id"], src_title, r["job_title"], new_pid, r["position_id"], why))
    conn.close()

    changed_title = sum(1 for p in plan if p[1] != p[2])
    changed_pos = sum(1 for p in plan if p[3] != p[4])
    new_pending = sum(1 for p in plan if p[5] == "new_pending_review")

    if not args.apply:
        print(
            f"[dry-run] 计划：回写标题 {changed_title} 条 / 重算归岗 {changed_pos} 条"
            f"（其中新建 pending_review 岗 {new_pending} 个）/ 未匹配 {unmatched} 条；"
            "加 --apply 执行"
        )
        return 0

    # ---------- 3. --apply：单事务执行 ----------
    conn = get_conn()
    try:
        conn.execute("BEGIN")
        for jd_id, src_title, _, new_pid, old_pid, _why in plan:
            conn.execute(
                "UPDATE jd_record SET job_title=?, position_id=? WHERE jd_id=?",
                (src_title, new_pid, jd_id),
            )
        # 清理再无 JD 挂靠的 pending_review 孤儿岗（active 永不动）；
        # 子表守卫与 admin reject（CR-03）同款：有模型/题库/会话数据的不删。
        orphans = conn.execute(
            "SELECT position_id, name FROM position WHERE status='pending_review'"
            " AND position_id NOT IN (SELECT DISTINCT position_id FROM jd_record"
            "  WHERE position_id IS NOT NULL)"
        ).fetchall()
        deleted = 0
        skipped = 0
        for pos in orphans:
            blocking = conn.execute(
                "SELECT (SELECT COUNT(*) FROM competency_model WHERE position_id=?) m,"
                " (SELECT COUNT(*) FROM question_bank_task WHERE position_id=?) t,"
                " (SELECT COUNT(*) FROM assessment_session WHERE position_id=?) s",
                (pos["position_id"], pos["position_id"], pos["position_id"]),
            ).fetchone()
            if blocking["m"] or blocking["t"] or blocking["s"]:
                print(f"[warn] 孤儿岗 {pos['name']} 有子表数据，跳过删除")
                skipped += 1
                continue
            conn.execute(
                "DELETE FROM position_alias WHERE position_id=?", (pos["position_id"],)
            )
            conn.execute(
                "DELETE FROM position WHERE position_id=?", (pos["position_id"],)
            )
            deleted += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(
        f"[apply] 完成：回写标题 {changed_title} 条 / 重算归岗 {changed_pos} 条"
        f"（新建 pending_review 岗 {new_pending} 个）/ 清理孤儿岗 {deleted} 个"
        f"（因子表占用跳过 {skipped} 个）/ 未匹配 {unmatched} 条"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
