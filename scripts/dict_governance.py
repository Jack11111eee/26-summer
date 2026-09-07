#!/usr/bin/env python3
"""词典治理落地脚本（第 1+2 层已授权；第 3 层身份迁移组默认不动）。

动作：
  1) 同义合并（138 组）：变体词条从 competency_dict 删除（仅删与 canonical
     同类目的行），canonical 词条 aliases_json 记录变体名，created_by 置
     human（对齐 P6 merge API 语义）。合并只改 name、保留每条 item 自己的
     category——任何 (name,category) 元组的类目都不因合并而变。
  2) 类目内归一（intra 档，hard↔soft / qual↔exp，不动 gate 身份）：少数派
     类目改写为主类目。
  3) 重算 std_items_json（parsed JD 全量）：按「合并映射 + 类目归一映射」查表
     替换；同名去重保留单条，importance 取高档、required_level 取高值、
     years 取最大、evidence 拼接去重（对齐 _collect_items 的 req 上位语义，
     且 evidence 是下游 LLM#3 的输入不可丢）。

冻结规则（第 3 层身份迁移组 = to_gate 48 + to_scored 78，用户逐条审）：
  - 冻结名作为「变体」出现在合并组里 → 跳过该变体（不做改名，避免把待裁决
    项转移到别的名字下；其 cross-side 元组原样保留）。
  - 冻结名作为「canonical」→ 组照常执行：canonical 自己的少数派类目元组
    不受波及（合并不改类目），待用户逐条裁决。
  - 冻结名不进类目内归一映射。

用法：
  GS_DRYRUN=1 python3 scripts/dict_governance.py   # 干跑，只打印统计
  python3 scripts/dict_governance.py              # 实跑（单事务，出错回滚）
"""
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "app.db")
PROPOSAL = "/tmp/gsd_dict_governance_proposal.json"

DRY = os.environ.get("GS_DRYRUN") == "1"
IMP_RANK = {"required": 3, "preferred": 2, "plus": 1}


def main() -> int:
    with open(PROPOSAL) as f:
        prop = json.load(f)
    syn_groups: dict[str, list[str]] = prop["syn_groups"]
    to_gate: list = prop["to_gate"]
    to_scored: list = prop["to_scored"]
    frozen = {n for n, _ in to_gate} | {n for n, _ in to_scored}

    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row

    # ---- 1) 同义合并：canonical 的 alias 追加 + 变体行删除 ----
    alias_updates: list[tuple[str, str, list[str]]] = []
    drop_rows: list[tuple[str, str]] = []
    skipped_variants = []
    for canonical, variants in syn_groups.items():
        row = conn.execute(
            "SELECT category, aliases_json FROM competency_dict WHERE std_name=?",
            (canonical,)).fetchone()
        if row is None:
            print(f"WARN canonical 词条缺失（跳过组）: {canonical}")
            continue
        cat, aliases = row["category"], json.loads(row["aliases_json"] or "[]")
        add = [v for v in variants if v not in aliases and v != canonical]
        frozen_variants = [v for v in add if v in frozen]
        add = [v for v in add if v not in frozen]
        skipped_variants += frozen_variants
        if add:
            alias_updates.append((canonical, cat, aliases + add))
        for v in add:  # 仅删与 canonical 同类目的变体行（跨类目行归第 3 层管辖）
            vrows = conn.execute(
                "SELECT category FROM competency_dict WHERE std_name=?", (v,)).fetchall()
            drop_rows += [(v, vr["category"]) for vr in vrows if vr["category"] == cat]

    # ---- 2) 类目内归一映射（排除冻结名） ----
    cat_fix: dict[tuple[str, str], str] = {}
    for name, cat_counts in prop["intra"]:
        if name in frozen:
            continue
        dom = Counter(cat_counts).most_common(1)[0][0]
        for c in cat_counts:
            if c != dom:
                cat_fix[(name, c)] = dom

    # ---- 3) 名字映射（变体 → canonical；冻结变体不映射） ----
    name_map: dict[str, str] = {}
    for canonical, variants in syn_groups.items():
        if not conn.execute("SELECT 1 FROM competency_dict WHERE std_name=?",
                             (canonical,)).fetchone():
            continue
        for v in variants:
            if v not in frozen and v != canonical:
                name_map[v] = canonical

    def remap(name: str, cat: str) -> tuple[str, str]:
        n2 = name_map.get(name, name)
        c2 = cat_fix.get((n2, cat), cat_fix.get((name, cat), cat))
        return n2, c2

    def merge_item(a: dict, b: dict) -> dict:
        """同名 (name,category) 碰撞时合并为一条：importance/level 取高，years 取大，evidence 拼接。"""
        hi, lo = (a, b) if IMP_RANK.get(a["importance"], 0) >= IMP_RANK.get(b["importance"], 0) else (b, a)
        out = dict(hi)
        out["required_level"] = max(a.get("required_level") or 0, b.get("required_level") or 0) or None
        ya, yb = a.get("years"), b.get("years")
        if ya is not None or yb is not None:
            out["years"] = max((y for y in (ya, yb) if y is not None), default=None)
        ev = list(dict.fromkeys((a.get("evidence") or []) + (b.get("evidence") or [])))
        if ev:
            out["evidence"] = ev
        return out

    jd_rows = conn.execute(
        "SELECT jd_id, std_items_json FROM jd_record"
        " WHERE status='parsed' AND std_items_json IS NOT NULL").fetchall()
    new_rows: list[tuple[str, str]] = []
    changed = removed_dup = 0
    for r in jd_rows:
        items = json.loads(r["std_items_json"])
        out: list[dict] = []
        seen: dict[tuple[str, str], int] = {}   # (name,category) -> out 下标
        changed_this = False
        for it in items:
            n2, c2 = remap(it["name"], it["category"])
            if (n2, c2) != (it["name"], it["category"]):
                changed_this = True
            merged_item = {**it, "name": n2, "category": c2}
            if (n2, c2) in seen:
                i = seen[(n2, c2)]
                out[i] = merge_item(out[i], merged_item)
                removed_dup += 1
                changed_this = True
                continue
            seen[(n2, c2)] = len(out)
            out.append(merged_item)
        if changed_this:
            changed += 1
            new_rows.append((r["jd_id"], json.dumps(out, ensure_ascii=False)))

    print(f"[{'DRY' if DRY else 'RUN'}] 同义组 {len(syn_groups)}：alias 更新 {len(alias_updates)} 行；"
          f"删变体行 {len(set(drop_rows))}；冻结变体跳过 {len(skipped_variants)}")
    print(f"[{'DRY' if DRY else 'RUN'}] 类目内归一 {len(cat_fix)} 个 (name,cat)")
    print(f"[{'DRY' if DRY else 'RUN'}] JD 重映射：{changed}/{len(jd_rows)} 条变化，去重吸收 {removed_dup} 项")

    if DRY:
        conn.close()
        return 0

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute("BEGIN")
    try:
        for std, cat, aliases in alias_updates:
            conn.execute(
                "UPDATE competency_dict SET aliases_json=?, created_by='human', updated_at=?"
                " WHERE std_name=? AND category=?",
                (json.dumps(aliases, ensure_ascii=False), now, std, cat))
        for std, cat in set(drop_rows):
            conn.execute("DELETE FROM competency_dict WHERE std_name=? AND category=?",
                         (std, cat))
        for jd_id, payload in new_rows:
            conn.execute("UPDATE jd_record SET std_items_json=? WHERE jd_id=?",
                         (payload, jd_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print("DONE: committed")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
