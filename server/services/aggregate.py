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
    """按 (std_name, category) 分组收集该岗位所有 parsed JD 的能力项与证据。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT jd_id, std_items_json FROM jd_record"
        " WHERE position_id=? AND status='parsed' AND std_items_json IS NOT NULL",
        (position_id,),
    ).fetchall()

    groups: dict[tuple[str, str], dict] = defaultdict(lambda: {"jds": set(), "req_jds": set(), "evidences": []})
    for row in rows:
        jd_id = row["jd_id"]
        for it in json.loads(row["std_items_json"]):
            key = (it["name"], it["category"])
            g = groups[key]
            g["jds"].add(jd_id)
            if it["importance"] == "required":
                g["req_jds"].add(jd_id)
            for ev_text in it.get("evidence", []):
                g["evidences"].append({"jd_id": jd_id, "level": it["required_level"], "text": ev_text})
            # 保留 years（experience 类）
            if it.get("years") is not None:
                g.setdefault("years_list", []).append(it["years"])
    return groups


def _map_importance(r: float, req: float) -> str:
    """双比率阈值映射（04 §2.3 Step2，阈值为配置项）。"""
    if req >= config.REQ_THRESHOLD:
        return "required"
    if r >= config.R_THRESHOLD:
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


def run_aggregate(position_id: str) -> str:
    """聚合成模型草稿。返回 model_id；LLM#3 失败时模型 status=stalled。

    已有 confirmed 模型时不覆盖（diff 审阅流属 M3），仅生成新 draft。
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

    items: list[dict] = []
    stalled = False
    stall_reason = None
    for (std_name, category), g in groups.items():
        n_jds = len(g["jds"])
        r = n_jds / total_jds
        req = len(g["req_jds"]) / total_jds
        importance = _map_importance(r, req)

        is_gate = category == "qualification" or (category == "experience" and bool(g.get("years_list")))
        if is_gate:
            level, reason = None, "门槛项，二值判定（模块三评分）"
        else:
            try:
                level, reason = _resolve_level(model_id, std_name, g["evidences"])
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
            "occurrence": {"r": round(r, 4), "req": round(req, 4)},
            "evidence": g["evidences"],
        })

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
        conn.commit()
    return model_id
