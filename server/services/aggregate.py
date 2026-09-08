"""工序⑤ 聚合：同岗位多 JD 的 std_items 融合成岗位模型草稿。

四步（04 §2.3）：
  Step1 代码频次统计（r 总出现率、req 必备率，JD 级）
  Step2 importance 双比率阈值映射（配置项）
  Step3 required_level 冲突裁决（LLM#3，无自动取众数后门；失败→stalled）
  Step4 权重纯代码计算（类间配比 × 类内 importance 系数归一，Σ=100%）

产出 competency_model(status=draft/stalled) + competency_item 明细。
"""
import json
from collections import Counter, defaultdict

from .. import config
from ..db import get_conn
from ..schemas import AggregateLevelResult
from .llm import call_llm_json
from .pipeline import new_id, now_iso
from .prompts.aggregate_level import AGGREGATE_LEVEL_SYSTEM, build_aggregate_level_user


def _mock_aggregate_level(system_prompt: str, user_prompt: str) -> dict:
    """离线 mock：取各证据等级的众数，理由标注 mock。"""
    levels = [int(w) for w in __import__("re").findall(r"Lv(\d)", user_prompt)]
    level = Counter(levels).most_common(1)[0][0] if levels else 3
    return {"level": level, "reason": "mock 取众数等级"}


def _collect_items(position_id: str) -> dict[tuple[str, str], dict]:
    """按 (std_name, category) 分组收集该岗位所有 parsed JD 的能力项与证据。

    §8.5 证据排除（单点收口，下游全继承）：evidences 已滤除 evidence_exclusion 的
    active 行，`_resolve_level`/`_needs_llm` 收到的即滤后集合——禁止在任何下游二次
    过滤（防口径漂移）。频次级规则：某 JD 对某项的当期证据**非空且全部被排除** →
    该 JD 整项跳过（不计 jds/req_jds 分子、无证据、无 years 贡献）；原有证据为空
    的项无可排除对象，行为不变（仍计入出现）。
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT jd_id, std_items_json FROM jd_record"
        " WHERE position_id=? AND status='parsed' AND std_items_json IS NOT NULL",
        (position_id,),
    ).fetchall()
    excluded = {
        (r["jd_id"], r["std_name"], r["category"], r["text"])
        for r in conn.execute(
            "SELECT jd_id, std_name, category, text FROM evidence_exclusion"
            " WHERE position_id=? AND status='active'", (position_id,))
    }

    groups: dict[tuple[str, str], dict] = defaultdict(lambda: {"jds": set(), "req_jds": set(), "evidences": []})
    for row in rows:
        jd_id = row["jd_id"]
        for it in json.loads(row["std_items_json"]):
            ev_texts = it.get("evidence") or []
            kept = [t for t in ev_texts if (jd_id, it["name"], it["category"], t) not in excluded]
            if ev_texts and not kept:
                continue  # §8.5 全排除：该 JD 对该项的支持整体撤回
            key = (it["name"], it["category"])
            g = groups[key]
            g["jds"].add(jd_id)
            if it["importance"] == "required":
                g["req_jds"].add(jd_id)
            for ev_text in kept:
                g["evidences"].append({"jd_id": jd_id, "level": it["required_level"], "text": ev_text})
            # 保留 years（experience 类）
            if it.get("years") is not None:
                g.setdefault("years_list", []).append(it["years"])
    return groups


def collect_excluded_entries(position_id: str) -> dict[tuple[str, str], list[dict]]:
    """§8.5 读侧合并：active 排除 → {(std_name, category): [entry]}，供模型读取端点
    将被排除证据条目合并回当期 draft/stalled 模型的 evidence 列表。

    entry = {jd_id, level, text, excluded: True, reason, excluded_by, excluded_at}；
    level 取该 JD std_item 的 required_level（与快照 evidence 同口径）。表内存 text，
    但 level/所在项上下文以源头 std_items_json 为准重建（避免双写漂移）。
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT jd_id, std_items_json FROM jd_record"
        " WHERE position_id=? AND status='parsed' AND std_items_json IS NOT NULL",
        (position_id,),
    ).fetchall()
    # (jd_id, std_name, category, text) → level 索引（排除行的 level 从源头取）
    level_index: dict[tuple[str, str, str, str], int | None] = {}
    for row in rows:
        jd_id = row["jd_id"]
        for it in json.loads(row["std_items_json"]):
            for t in it.get("evidence") or []:
                level_index[(jd_id, it["name"], it["category"], t)] = it.get("required_level")

    out: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in conn.execute(
        "SELECT jd_id, std_name, category, text, reason, excluded_by, excluded_at"
        " FROM evidence_exclusion WHERE position_id=? AND status='active'",
        (position_id,),
    ):
        key = (r["std_name"], r["category"])
        out[key].append({
            "jd_id": r["jd_id"],
            "level": level_index.get((r["jd_id"], r["std_name"], r["category"], r["text"])),
            "text": r["text"],
            "excluded": True,
            "reason": r["reason"],
            "excluded_by": r["excluded_by"],
            "excluded_at": r["excluded_at"],
        })
    return dict(out)


def _map_importance(r: float, cond_req: float, occ: int, category: str) -> str:
    """importance 三档混合口径映射（SSOT §8.1 工序⑤，required 2026-09-07 / preferred 2026-09-08 裁决）。

    required 三重判据：条件 req（req_jds/出现 jds）≥ REQ_THRESHOLD、
    r ≥ REQ_MIN_OCCURRENCE_RATIO、出现 JD 数 ≥ REQ_MIN_OCCURRENCE，
    且仅 hard_skill 可判 required（soft_skill 上限 preferred）；
    preferred ⇔ 未达 required 且 出现 JD 数 ≥ PREFERRED_MIN_OCCURRENCE；否则 plus。
    gate 类（experience/qualification）在调用侧不参与本分档。
    """
    if (category == "hard_skill"
            and cond_req >= config.REQ_THRESHOLD
            and r >= config.REQ_MIN_OCCURRENCE_RATIO
            and occ >= config.REQ_MIN_OCCURRENCE):
        return "required"
    if occ >= config.PREFERRED_MIN_OCCURRENCE:
        return "preferred"
    return "plus"


def _resolve_level(model_id: str, std_name: str, evidences: list[dict]) -> tuple[int, str]:
    """Step3：level 冲突交 LLM#3。等级一致时直接用，不调用 LLM（省一次调用）。

    LLM#3 失败由上层捕获 → 模型 stalled。
    """
    levels = {ev["level"] for ev in evidences}
    if len(levels) == 1:
        return levels.pop(), "各 JD 等级一致"
    result = call_llm_json(
        "aggregate_level", model_id, AGGREGATE_LEVEL_SYSTEM,
        build_aggregate_level_user(std_name, evidences),
        mock_fn=_mock_aggregate_level,
    )
    parsed = AggregateLevelResult(**result)
    return parsed.level, parsed.reason


def _compute_weights(items: list[dict]) -> None:
    """Step4：类间配比 × 类内 importance 系数，归一到 Σ=1。就地写 item['weight']。"""
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_cat[it["category"]].append(it)

    total_ratio = sum(config.CATEGORY_RATIO[c] for c in by_cat)  # 仅出现的类目参与配比
    if total_ratio == 0:
        # REF-5.7/§8.2：gate 类（experience/qualification）7:3 下系数为 0，走事实核验不占权重池；
        # 纯 gate 模型 total_ratio==0 会除零，且尾差吸收块会把 drift=1.0 压给单个 gate item
        # 使其 weight=1.0（达标即 +100 分，语义错误）——全部置 0 且跳过尾差吸收。
        for it in items:
            it["weight"] = 0.0
        return
    for cat, cat_items in by_cat.items():
        cat_share = config.CATEGORY_RATIO[cat] / total_ratio
        coef_sum = sum(config.IMPORTANCE_COEF[it["importance"]] for it in cat_items)
        for it in cat_items:
            it["weight"] = round(cat_share * config.IMPORTANCE_COEF[it["importance"]] / coef_sum, 4)
    # 四舍五入尾差由权重最大项吸收，保证 Σ 严格 = 1
    if items:
        drift = round(1.0 - sum(it["weight"] for it in items), 4)
        if drift:
            max(items, key=lambda x: x["weight"])["weight"] = round(
                max(items, key=lambda x: x["weight"])["weight"] + drift, 4)


def _needs_llm(category: str, g: dict) -> bool:
    """循环项与任务行 llm_total 共用的「该项实际走 LLM#3」判定（SSOT §8.4）——
    与循环内 if/else 分支完全同一谓词，杜绝预计算口径漂移：非 gate 且组内要求等级
    不一致（_resolve_level 的 len(levels)==1 早退路径不计入）。"""
    is_gate = category == "qualification" or (category == "experience" and bool(g.get("years_list")))
    if is_gate:
        return False
    return len({ev["level"] for ev in g["evidences"]}) > 1


def run_aggregate(position_id: str, trigger_source: str = "manual") -> str:
    """聚合成模型草稿。返回 model_id；LLM#3 失败时模型 status=stalled。

    已有 confirmed 模型时不覆盖（diff 审阅流属 M3），仅生成新 draft。

    trigger_source：任务行溯源用（manual / retry / auto:jd-parse，SSOT §8.4）；
    聚合业务行为不受影响——每次触发落一行 aggregate_task（RUNNING→SUCCEEDED/FAILED）。

    未捕获异常：任务行落 FAILED + error 后 re-raise（BackgroundTasks 会吞、
    pipeline 外层有 try/except——防线是给「死了留下尸体」，不改现有抛出语义）。
    """
    conn = get_conn()
    pos = conn.execute("SELECT name FROM position WHERE position_id=?", (position_id,)).fetchone()
    if pos is None:
        raise ValueError(f"岗位不存在: {position_id}")

    groups = _collect_items(position_id)
    total_jds = conn.execute(
        "SELECT COUNT(*) c FROM jd_record WHERE position_id=? AND status='parsed'",
        (position_id,),
    ).fetchone()["c"]
    if total_jds == 0:
        raise ValueError("该岗位无已解析 JD，无法聚合")

    model_id = new_id("cm")
    version = conn.execute(
        "SELECT COALESCE(MAX(version),0)+1 v FROM competency_model WHERE position_id=?",
        (position_id,),
    ).fetchone()["v"]

    # 任务行起跑（SSOT §8.4）：total/llm_total 起跑可算（llm_total 与循环判定共用
    # _needs_llm 谓词，纯代码预计算），循环内逐项更新 done/llm_done/current_item
    task_id = new_id("agg_task")
    ts = now_iso()
    conn.execute(
        "INSERT INTO aggregate_task(task_id, position_id, status, trigger_source,"
        " total, llm_total, created_at, started_at) VALUES(?,?,?,?,?,?,?,?)",
        (task_id, position_id, "RUNNING", trigger_source, len(groups),
         sum(1 for (sn, cat), g in groups.items() if _needs_llm(cat, g)), ts, ts),
    )
    conn.commit()

    def _finish(task_status: str, error: str | None = None) -> None:
        """任务终态（写序敏感：先落模型行，再落任务终态——调用点须在模型 INSERT/commit 之后）。

        done/llm_done 只前进（取 max 防回拨）；model_id 回填（stalled 产物也存在，
        保溯源链第三跳 llm_trace 查得到）；current_item 保留最后一项不清理。
        """
        conn.execute(
            "UPDATE aggregate_task SET status=?, error=?, model_id=?, finished_at=?,"
            " done=MAX(COALESCE(done,0), ?), llm_done=MAX(COALESCE(llm_done,0), ?)"
            " WHERE task_id=?",
            (task_status, error, model_id, now_iso(), done, llm_done, task_id),
        )

    def _advance(done: int, llm_done: int, current_item: str) -> None:
        """循环内逐项推进（done/llm_done/current_item 一次 UPDATE 写齐）。

        逐项 commit 而非攒批：progress 端点另一连接轮询本行，且 LLM#3 落
        llm_trace 用独立连接——本连接不持未决写事务，否则交叉持锁 5s 超时
        （sqlite 默认 busy_timeout）把 LLM 写 trace 顶成 database is locked。
        """
        conn.execute(
            "UPDATE aggregate_task SET done=?, llm_done=?, current_item=? WHERE task_id=?",
            (done, llm_done, current_item, task_id),
        )
        conn.commit()

    items: list[dict] = []
    stalled = False
    stall_reason = None
    done = 0
    llm_done = 0
    try:
        for (std_name, category), g in groups.items():
            _advance(done, llm_done, f"{std_name} ({category})")
            n_jds = len(g["jds"])  # 出现 JD 数（occ，非岗位 JD 总数）
            r = n_jds / total_jds
            # 条件口径（2026-09-07 裁决）：标 required 的 JD 数 ÷ 该能力出现的 JD 数；
            # 绝对口径（÷ total_jds）废弃。occ=0 时 n_jds=0，组不存在，不会进循环。
            req = len(g["req_jds"]) / n_jds
            importance = _map_importance(r, req, n_jds, category)

            is_gate = category == "qualification" or (category == "experience" and bool(g.get("years_list")))
            if is_gate:
                level, reason = None, "门槛项，二值判定（模块三评分）"
            else:
                try:
                    level, reason = _resolve_level(model_id, std_name, g["evidences"])
                    if _needs_llm(category, g):  # 该且仅该项实际走 LLM#3 才计 llm_done
                        llm_done += 1
                except Exception as e:  # noqa: BLE001 - LLM#3 失效 → stalled
                    stalled = True
                    stall_reason = f"{std_name}: {e}"
                    level, reason = None, f"等级裁决失败：{e}"

            years = max(g["years_list"]) if g.get("years_list") else None  # 年限取最高要求
            items.append({
                "std_name": std_name,
                "category": category,
                "required_level": level,
                "importance": importance,
                "years": years,
                "gate": int(is_gate),
                "level_reason": reason,
                # req 存条件口径值（语义 2026-09-07 变更）；occ=出现 JD 数（新增键，
                # 存量模型无此键不受影响）
                "occurrence": {"r": round(r, 4), "req": round(req, 4), "occ": n_jds},
                "evidence": g["evidences"],
            })
            done += 1

        _compute_weights(items)

        model_json = {
            "position_id": position_id,
            "position_name": pos["name"],
            "version": version,
            "jd_count": total_jds,
            "category_weights": {c: round(config.CATEGORY_RATIO[c] / sum(config.CATEGORY_RATIO.values()), 4)
                                  for c in {i["category"] for i in items}},
            "items": items,
        }

        status = "stalled" if stalled else "draft"
        conn.execute(
            "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (model_id, position_id, version, status, json.dumps(model_json, ensure_ascii=False), now_iso()),
        )
        for it in items:
            conn.execute(
                "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
                " importance, weight, years, gate, level_reason, occurrence_json, evidence_json)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id("c"), model_id, it["std_name"], it["category"], it["required_level"],
                 it["importance"], it["weight"], it["years"], it["gate"], it["level_reason"],
                 json.dumps(it["occurrence"]), json.dumps(it["evidence"], ensure_ascii=False)),
            )
        conn.commit()
        if stalled:
            # stalled 原因写进 model_json 便于 P1 待办展示
            model_json["stall_reason"] = stall_reason
            conn.execute("UPDATE competency_model SET model_json=? WHERE model_id=?",
                         (json.dumps(model_json, ensure_ascii=False), model_id))
        # 任务终态：模型行已落库（含 stalled 产物——model_id 照样回填保溯源链第三跳）
        if stalled:
            _finish("FAILED", error=stall_reason)
        else:
            _finish("SUCCEEDED")
        conn.commit()
    except Exception as e:  # noqa: BLE001 - 任务行落 FAILED 留尸体后维持原抛出语义
        try:
            conn.execute(
                "UPDATE aggregate_task SET status='FAILED', error=?, finished_at=? WHERE task_id=?",
                (str(e), now_iso(), task_id),
            )
            conn.commit()
        except Exception:  # noqa: BLE001 - 收尸失败不吞业务异常
            pass
        raise
    return model_id
