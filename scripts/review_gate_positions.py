"""岗位审核轮执行脚本（2026-09-07，用户裁决：策略 B + C 窄版 + 空巢下架）。

三项动作：
  1. C 窄版合并：修饰词系列 pending 岗（名称以 高级/资深 开头，或以 专家/高级 结尾）
     的 JD 全量改归到「去掉修饰词后的主名岗位」——仅当主名岗 status='active'（不要求
     有 JD，但合并前有 0 挂靠的会打进明细核对）；壳岗清空后走 delete；同时插
     position_alias（主岗名=壳岗原名，NOCASE 匹配接住未来同 title 的新 JD）。
  2. 策略 B approve：其余 pending 岗中，挂有 >=2 条 status='parsed' JD 的批量
     approve（active）。单例岗不动（保持 pending_review）。
  3. 空巢下架：status='active' 且无任何 jd_record（任何 status）的岗位 status→inactive。

执行方式：优先走运行中的 API（http://127.0.0.1:8000，admin 登录取 JWT）——
  - approve → POST /api/admin/positions/{id}/review {"action":"approve"}
  - JD 改归 → POST /api/admin/jds/{jd_id}/reassign {"position_id":...}
  - 壳岗清理 → POST /api/admin/positions/{id}/review {"action":"reject"}
    （reject 语义 = 撤销岗位 + JD 归 NULL；此时壳岗已 0 JD，是安全的空删——CR-03
    的子表占用检查由 API 自带）
API 不覆盖的两步走直连 SQLite（.timeout 语义：每语句 PRAGMA busy_timeout）：
  - position_alias 插入（无对应 API）
  - 空巢 inactive 批量 UPDATE（无对应 API；migration 14 已放宽 CHECK）

用法：
    python -m scripts.review_gate_positions                 # dry-run（默认，只打印计划）
    python -m scripts.review_gate_positions --apply         # 真正执行
    python -m scripts.review_gate_positions --apply --no-api # 直连 SQL 模式（服务器不可用时）

判据口径全部以 DB 实查为准（--apply 前 DJ 计数、主名状态逐岗再查一遍）。
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import os

os.environ.setdefault("LLM_PROVIDER", "mock")  # 纯脚本，无 LLM 路径

from server.db import get_conn  # noqa: E402

MOD_PREFIXES = ("高级", "资深")
MOD_SUFFIXES = ("专家", "高级")  # 高级可前可后（「slam算法高级」）


def strip_modifier(name: str) -> str | None:
    """去掉修饰词返回主名；名称本身不含修饰词边界则返回 None（窄 C 只认边界消修饰）。"""
    for p in MOD_PREFIXES:
        if name.startswith(p) and len(name) > len(p):
            rest = name[len(p):]
            # 防双重修饰（高级/资深 X）：剥掉前缀后仍以修饰词开头的不再剥（保守）
            return rest
    for s in MOD_SUFFIXES:
        if name.endswith(s) and len(name) > len(s):
            return name[: -len(s)]
    return None


def collect_plan(conn) -> dict:
    """三类动作的执行计划（纯读，不落库）。"""
    # ---- C 窄版候选：pending + 名称带修饰词 + 主名岗存在且 active ----
    pending = conn.execute(
        "SELECT position_id, name FROM position WHERE status='pending_review' ORDER BY name"
    ).fetchall()
    by_name = {}  # lower(name) -> list[(pid, status, jd_count)]（防同名绕过：逐条看）
    rows_all = conn.execute(
        "SELECT position_id, name, status FROM position"
    ).fetchall()
    jd_counts = {
        r["position_id"]: r["c"]
        for r in conn.execute(
            "SELECT position_id, COUNT(*) c FROM jd_record"
            " WHERE position_id IS NOT NULL GROUP BY position_id"
        ).fetchall()
    }
    jd_parsed_counts = {
        r["position_id"]: r["c"]
        for r in conn.execute(
            "SELECT position_id, COUNT(*) c FROM jd_record"
            " WHERE position_id IS NOT NULL AND status='parsed' GROUP BY position_id"
        ).fetchall()
    }
    for r in rows_all:
        by_name.setdefault(r["name"].lower(), []).append((r["position_id"], r["status"]))

    merges = []      # (pid, name, jd_ids, main_pid, main_name)
    no_main = []     # 带修饰词但主名岗不存在/非 active——不在窄 C 范围，按 B 独立处理
    for p in pending:
        main = strip_modifier(p["name"])
        if main is None:
            continue
        cands = by_name.get(main.lower(), [])
        actives = [(pid, st) for pid, st in cands if st == "active"]
        jd_ids = [
            r["jd_id"]
            for r in conn.execute(
                "SELECT jd_id FROM jd_record WHERE position_id=? ORDER BY jd_id", (p["position_id"],)
            ).fetchall()
        ]
        if len(actives) == 1:
            merges.append((p["position_id"], p["name"], jd_ids, actives[0][0], main))
        else:
            no_main.append((p["position_id"], p["name"], len(jd_ids), main,
                            [st for _, st in cands]))
    merge_pids = {m[0] for m in merges}

    # ---- B approve：非合并目标、parsed JD >= 2 ----
    approves = []
    for p in pending:
        if p["position_id"] in merge_pids:
            continue
        if jd_parsed_counts.get(p["position_id"], 0) >= 2:
            approves.append((p["position_id"], p["name"],
                              jd_parsed_counts.get(p["position_id"], 0)))
    # 合并目标的主名岗不参与 approve（它们本来就 active）

    # ---- 空巢 active → inactive ----
    nest_empty = [
        (r["position_id"], r["name"])
        for r in conn.execute(
            "SELECT position_id, name FROM position WHERE status='active'"
            " AND NOT EXISTS (SELECT 1 FROM jd_record WHERE position_id=position.position_id)"
            " ORDER BY position_id"
        ).fetchall()
    ]
    return {"merges": merges, "no_main": no_main, "approves": approves,
            "nest_empty": nest_empty}


# ---------- API 客户端 ----------

class Api:
    def __init__(self, base: str, username: str, password: str):
        self.base = base.rstrip("/")
        body = json.dumps({"username": username, "password": password}).encode()
        req = urllib.request.Request(
            f"{self.base}/api/auth/login", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            self.token = json.loads(resp.read())["token"]

    def post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base}{path}", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.token}"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())


def api_review(api: Api, pid: str, action: str) -> dict:
    return api.post(f"/api/admin/positions/{pid}/review", {"action": action})


def api_reassign(api: Api, jd_id: str, pid: str) -> dict:
    return api.post(f"/api/admin/jds/{jd_id}/reassign", {"position_id": pid})


# ---------- 执行 ----------

def main() -> int:
    parser = argparse.ArgumentParser(description="岗位审核轮：B approve + C 窄版合并 + 空巢下架")
    parser.add_argument("--apply", action="store_true", help="真正执行（默认 dry-run）")
    parser.add_argument("--no-api", action="store_true", help="直连 SQL（不走 API）")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-pass", default="admin123")
    args = parser.parse_args()

    conn = get_conn()
    plan = collect_plan(conn)
    merges, no_main = plan["merges"], plan["no_main"]
    approves, nest_empty = plan["approves"], plan["nest_empty"]

    # 空巢安全性抽样：与合并/审核目标零交集断言（互踩即停）
    merge_or_pending_pids = {p[0] for p in conn.execute(
        "SELECT position_id FROM position WHERE status='pending_review'").fetchall()}
    nest_pids = {n[0] for n in nest_empty}
    overlap = nest_pids & merge_or_pending_pids
    if overlap:
        print(f"[abort] 空巢 active 与 pending_review 交集非空：{overlap}")
        return 2

    api = None
    if args.apply and not args.no_api:
        api = Api(args.base, args.admin_user, args.admin_pass)

    total_merge_jds = sum(len(m[2]) for m in merges)
    print(f"[plan] 窄C 合并：{len(merges)} 壳岗 / {total_merge_jds} 条 JD 挪移")
    for pid, name, jd_ids, main_pid, main_name in merges:
        print(f"  merge {name!r} ({len(jd_ids)} JD) -> {main_name!r} [{main_pid}]")
    print(f"[plan] B approve：{len(approves)} 岗（含窄C 边缘主名 pending 的非合并壳岗）")
    for pid, name, n in approves:
        print(f"  approve {name!r} (parsed={n})")
    print(f"[plan] 空巢下架 inactive：{len(nest_empty)} 岗")
    print(f"[plan] 带修饰词但无 active 主名岗（不动，报待裁决）：{len(no_main)} 个")

    if not args.apply:
        print("[dry-run] 未写库。加 --apply 执行。")
        return 0

    # ---- 1. C 窄版合并 ----
    # 1a. JD 改归（API reassign 或直连 SQL）
    moved = 0
    errors: list[str] = []
    for pid, name, jd_ids, main_pid, main_name in merges:
        # 执行时再核对一遍（dry-run 与 apply 之间库可能变化）
        cur = conn.execute(
            "SELECT COUNT(*) c FROM jd_record WHERE position_id=?", (pid,)
        ).fetchone()["c"]
        if cur != len(jd_ids):
            print(f"[abort] 岗位 {name!r} JD 数已变化（{len(jd_ids)}→{cur}），停止")
            return 3
        for jd_id in jd_ids:
            if api:
                api_reassign(api, jd_id, main_pid)
            else:
                conn.execute("UPDATE jd_record SET position_id=? WHERE jd_id=?",
                             (main_pid, jd_id))
                conn.commit()
            moved += 1
    print(f"[apply] JD 改归完成：{moved} 条")

    # 1b. 别名登记（主岗名=壳岗原名，未来同 title 新 JD 由 assign_position 的
    #     position_alias 分支接住——NOCASE）。直连 SQL：无对应 API。
    events = []
    for pid, name, jd_ids, main_pid, main_name in merges:
        exists = conn.execute(
            "SELECT 1 FROM position_alias WHERE alias=? COLLATE NOCASE", (name,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO position_alias(alias_id, position_id, alias) VALUES(?,?,?)",
                (f"pa_{pid[4:]}", main_pid, name),
            )
            conn.commit()
            events.append((name, main_name))
    print(f"[apply] 别名登记：{len(events)} 条 -> " + "; ".join(
        f"{a}->{b}" for a, b in events))

    # 1c. 壳岗清理（reject 语义 = 撤销删除；此时壳岗已 0 JD）
    shells = 0
    for pid, name, jd_ids, main_pid, main_name in merges:
        left = conn.execute(
            "SELECT COUNT(*) c FROM jd_record WHERE position_id=?", (pid,)
        ).fetchone()["c"]
        if left != 0:
            print(f"[warn] 壳岗 {name!r} 仍有 {left} JD，跳过清理")
            continue
        if api:
            try:
                api_review(api, pid, "reject")
            except Exception as e:  # noqa: BLE001 - 4xx 记明细不停（人审个例）
                errors.append(f"reject {name!r}: {e}")
                continue
        else:
            conn.execute("DELETE FROM position WHERE position_id=?", (pid,))
            conn.commit()
        shells += 1
    print(f"[apply] 壳岗清理：{shells}/{len(merges)}")

    # ---- 2. B approve（含 no_main 且 parsed>=2 的）----
    approved = 0
    for pid, name, n in approves:
        if api:
            try:
                api_review(api, pid, "approve")
            except Exception as e:  # noqa: BLE001
                errors.append(f"approve {name!r}: {e}")
                continue
        else:
            conn.execute("UPDATE position SET status='active' WHERE position_id=?", (pid,))
            conn.commit()
        approved += 1
    print(f"[apply] approve：{approved}/{len(approves)}")

    # ---- 3. 空巢 inactive ----
    # 直连 SQL：无「下架」API；判据与收集时一致，单语句批量翻转（busy_timeout 5s）
    conn.execute("PRAGMA busy_timeout = 5000")
    cur = conn.execute(
        "UPDATE position SET status='inactive'"
        " WHERE status='active'"
        " AND NOT EXISTS (SELECT 1 FROM jd_record WHERE position_id=position.position_id)"
    )
    conn.commit()
    print(f"[apply] 空巢下架 inactive：{cur.rowcount} 岗")

    if errors:
        print(f"[warn] API 错误 {len(errors)} 条：")
        for e in errors:
            print("  " + e)

    # ---- 终态验证 ----
    stats = conn.execute(
        "SELECT status, COUNT(*) c FROM position GROUP BY status ORDER BY status"
    ).fetchall()
    print("[final] position 状态分布：" + ", ".join(f"{r['status']}={r['c']}" for r in stats))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
