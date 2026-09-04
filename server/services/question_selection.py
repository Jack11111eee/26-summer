"""四层动态选题（SSOT §10.6，D-17/D-18/D-19——02-02 全量重写）。

每次 action=next 由代码按四层顺序即时选题并实例化（动态实例化，SC-1）：
①合法性过滤：status='active' 且 category IN (hard_skill, soft_skill)（experience/
  qualification 走表单不占普通题）且 scope 匹配且未被本会话使用且版本近似放行
②required 硬约束：模型中未覆盖的 required item 优先
③配额：岗位级 N（config.ORDINARY_PLAN_N）+ 7:3 最大余数（§10.2）+ tier 公式
  （§10.3 required 0.8 / preferred 0.6 / plus 0.3，和 1.7 ceil）——已实例实时扣减
④排序三键：chain 后继（可让位 required）→ item.weight 降序 → 稳定随机种子
  （seed = int(sha256(session_id)[:8], 16)，Q3 决议；「题目质量」分项显式禁用——D-17）。

selection_reason 为结构化 JSON（D-18 最小集，七键 + nth）落
assessment_question.selection_reason；不可复现的中文描述不上此列。

required 刚性例外（§10.5，D-19）：普通计划（N 题实例化完）后仍有未覆盖 required
item → 每 item 最多一次补选（仅 medium；无 medium 才 hard，不走 easy），例外记录
经 REQUIRED_EXCEPTION_GRANTED 事件留痕；无合法候选 → PATH_UNAVAILABLE 不静默。

旧三类硬编码配额（hard 6 / soft 2 / experience 2，experience 占题）已废除
（不留别名）；readiness 第 5 步与本模块共享 plan_quotas 纯函数（防两处公式
漂移，WR-15 教训）。

legacy 会话兜底（Q5）：入口先检测——会话已有实例且 selection_reason 全为 NULL
（旧预选形态）→ 返回 {"legacy": True} 标记，API 层走旧 ORDER BY seq 派发，
本模块不写任何新事件（不污染审计）。新会话（无实例）才走四层。
"""
import hashlib
import json
import random
from math import ceil

from .. import config
from ..db import get_conn
from .pipeline import new_id, now_iso
from .state_events import append_event

# 普通题类目白名单（§9.1：experience/qualification 不进普通对话题库）
ORDINARY_CATEGORIES = ("hard_skill", "soft_skill")

# tier 系数（§10.3：required 0.8 : preferred 0.6 : plus 0.3，和 1.7）
TIER_COEF = {"required": 0.8, "preferred": 0.6, "plus": 0.3}
_TIER_COEF_SUM = sum(TIER_COEF.values())  # 1.7

# selection_policy_version（02-02 起版本串）
_SELECTION_POLICY_VERSION = "p2"


# ---------- 纯函数区（readiness 第 5 步同源复用） ----------

def largest_remainder_73(n: int) -> tuple[int, int]:
    """大类 7:3 整数分配（§10.2 最大余数法）。

    raw_hard = 0.70n、raw_soft = 0.30n；先取整数部分，余下名额按小数部分大小
    分配；小数部分相等时归 hard_skill。
    样例（§10.2 表）：N=9→(6,3)、N=10→(7,3)、N=11→(8,3)、N=15→(11,4)。
    """
    raw_hard, raw_soft = 0.70 * n, 0.30 * n
    hard, soft = int(raw_hard), int(raw_soft)
    rem = n - hard - soft
    if raw_soft - soft > raw_hard - hard:  # soft 小数更大
        soft += rem
    else:  # 含相等：归 hard（§10.2）
        hard += rem
    return hard, soft


def tier_targets(category_quota: int, available_counts: dict[str, int]) -> dict[str, int]:
    """类内 tier 配额（§10.3 用户公式）。

    required_target = ceil(q×0.8/1.7)、preferred_target = ceil(q×0.6/1.7)、
    plus = q − req − pref。
    边界 clamp（§10.3 优先级原文）：实际分配遵守 required > preferred > plus——
    题量不足时先保 required 再保 preferred，plus 用剩余名额；向上取整不得使目标
    超过该大类总量（如 soft 仅 2 题：required=1、preferred=1、plus=0）。
    available_counts: {tier: 该类目下各 tier 可用题量}（缺 tier 视作 0）。
    """
    quota = max(int(category_quota), 0)
    req = min(ceil(quota * TIER_COEF["required"] / _TIER_COEF_SUM), quota)
    pref = min(ceil(quota * TIER_COEF["preferred"] / _TIER_COEF_SUM), quota - req)
    plus = quota - req - pref
    # 题量不足时先保 required 再保 preferred（§10.3 优先级）
    req = min(req, available_counts.get("required", 0))
    pref = min(pref, available_counts.get("preferred", 0))
    # 保不住的名额按优先级回落：先给 preferred 余量，再给 plus，最后给 required 余量
    shortfall = quota - req - pref - plus
    if shortfall > 0:
        for tier in ("preferred", "plus", "required"):
            avail = available_counts.get(tier, 0) - (pref if tier == "preferred" else
                                                    plus if tier == "plus" else req)
            refill = min(shortfall, max(avail, 0))
            if tier == "preferred":
                pref += refill
            elif tier == "plus":
                plus += refill
            else:
                req += refill
            shortfall -= refill
            if shortfall <= 0:
                break
    return {"required": req, "preferred": pref, "plus": plus}


def plan_quotas(n: int, categories_present: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """总配额（§10.1-10.3）：N + 7:3 大类 + tier 公式 → {category: {tier: target}}。

    categories_present: {category: {tier: 该类目该 tier 可用题量}}——只含模型实际
    出现的类目（CR-04：模型不含的类目不要求配额）。选层③每轮实时调用，
    已实例计数由调用方在外部扣减（readiness 第 5 步同源复用做开考预检）。
    """
    hard_n, soft_n = largest_remainder_73(n)
    cat_quota = {"hard_skill": hard_n, "soft_skill": soft_n}
    quotas: dict[str, dict[str, int]] = {}
    for category, tiers_available in categories_present.items():
        if category not in ORDINARY_CATEGORIES:
            continue
        # 大类退化：单类目岗位未能消费的大类名额归本类（纯 hard 岗 soft 配额回落 hard）
        quota = cat_quota.get(category, 0)
        quotas[category] = tier_targets(quota, tiers_available)
    # 大类退化兜底：只出现一个普通类目时，另一类名额并入该类
    present = [c for c in ORDINARY_CATEGORIES if c in quotas]
    if len(present) == 1:
        only = present[0]
        other = "soft_skill" if only == "hard_skill" else "hard_skill"
        total = sum(quotas[only].values()) + cat_quota.get(other, 0)
        tiers_available = categories_present.get(only, {})
        quotas[only] = tier_targets(total, tiers_available)
    return quotas


# ---------- 查询 helpers ----------

# 难度档序（snapshot 承接的候选难度口径比较基准——02-03）
_DIFF_ORDER = {"easy": 0, "medium": 1, "hard": 2}


def _snapshot_target_difficulty(conn, session_id: str) -> dict[str, tuple[str, str]]:
    """层①难度承接（02-03）：各 item 最新封存 snapshot 指示的候选难度口径。

    返回 {item_id: (current_difficulty, predicate_note)}——一 item 一份，
    以该 item 最后一个封存实例行上的 JSON 为准（closed_at/created_at 最新）。
    无 snapshot 的 item 不在返回值内（首实例起始 easy 照旧——§11 无
    alternative 起始难度规定，沿现有题库起始 + chain 惯例）。
    """
    rows = conn.execute(
        "SELECT item_id, path_state_snapshot FROM assessment_question"
        " WHERE session_id=? AND item_id IS NOT NULL AND closed_at IS NOT NULL"
        " ORDER BY seq", (session_id,)
    ).fetchall()
    targets: dict[str, tuple[str, str]] = {}
    for r in rows:  # 后行覆盖前行 → 留最新封存行
        if not r["path_state_snapshot"]:
            continue
        try:
            snap = json.loads(r["path_state_snapshot"])
        except (json.JSONDecodeError, TypeError):
            continue
        current = snap.get("current_difficulty")
        if current in ("easy", "medium", "hard"):
            targets[r["item_id"]] = (current, "snapshot_difficulty")
    return targets


def _apply_snapshot_difficulty(pool: list[dict],
                               snapshot_targets: dict[str, tuple[str, str]]) -> list[dict]:
    """按 item 的 snapshot 目标难度过滤候选池（02-03 难度承接）。

    - 题库有目标档行 → 该 item 只留目标档（其余难度行出池）
    - 无目标档行 → 落回该 item 可得最高档（不高于目标档——跳级禁止，
      plan <interfaces>：无则落回题库已有最高可得档）
    - 候选行按 model_item_id 优先归属 item，回退 (std_name, category) 键匹配
    """
    # item_id → 该 item 的候选行（双口径归属，model_item_id 优先）
    by_item: dict[str, list[dict]] = {}
    for c in pool:
        key = c.get("model_item_id") or f"kc:{_item_key(c)[0]}|{_item_key(c)[1]}"
        if key in snapshot_targets:
            by_item.setdefault(key, []).append(c)
    for key, (target, _note) in snapshot_targets.items():
        item_pool = by_item.get(key)
        if not item_pool:
            continue
        target_rows = [c for c in item_pool if c["difficulty"] == target]
        if target_rows:
            keep_ids = {c["question_id"] for c in target_rows}
        else:
            ceiling = _DIFF_ORDER[target]
            ranked = sorted(
                (c for c in item_pool
                 if c["difficulty"] and _DIFF_ORDER.get(c["difficulty"], -1) <= ceiling),
                key=lambda c: _DIFF_ORDER[c["difficulty"]], reverse=True)
            if not ranked:
                continue  # 无不高于目标的行 → 不动（保持未过滤原池，不静默断路径）
            keep_ids = {c["question_id"] for c in ranked
                        if c["difficulty"] == ranked[0]["difficulty"]}
        drop_ids = {c["question_id"] for c in item_pool} - keep_ids
        if drop_ids:
            pool = [c for c in pool if c["question_id"] not in drop_ids]
    return pool

def _load_model_items(conn, model_id: str) -> list[dict]:
    """模型非 gate items（tier=importance；item_id 优先绑定口径）。"""
    rows = conn.execute(
        "SELECT item_id, std_name, category, importance, weight, gate"
        " FROM competency_item WHERE model_id=? AND gate=0", (model_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _load_candidate_rows(conn, position_id: str, model_id: str | None) -> list[dict]:
    """层①合法性过滤的候选池（沿用旧 :23-28 WHERE 口径 + 版本近似）。

    版本归属近似（Phase 4 前过渡）：题库行 model_id IS NULL 或等于会话 model_id
    → 放行（存量/m5 种子全 NULL 统一放行；Phase 4 REF-3.4 收紧为强制绑定）。
    """
    rows = conn.execute(
        "SELECT b.*, ci.weight AS item_weight, ci.importance AS item_importance,"
        " ci.item_id AS model_item_id"
        " FROM question_bank b"
        " LEFT JOIN competency_item ci ON ci.std_name=b.std_name AND ci.category=b.category"
        " AND ci.model_id=?"
        " WHERE b.status='active' AND b.category IN ('hard_skill','soft_skill')"
        " AND (b.scope='general' OR (b.scope='position' AND b.position_id=?))"
        " AND (b.model_id IS NULL OR ? IS NULL OR b.model_id=?)",
        (model_id, position_id, model_id, model_id),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        # tier 优先取题库行 item 绑定（v2.0 item_id 绑定），回退 competency_item importance
        if d.get("item_importance"):
            d["tier"] = d["item_importance"]
        d["weight"] = d.get("item_weight") or 0.0  # NULL 视作 0（§10.6 第四层）
        out.append(d)
    return out


def _session_instance_state(conn, session_id: str) -> tuple[list[dict], bool]:
    """返回 (已建实例行列表, is_legacy)。

    is_legacy：会话已有实例且 selection_reason 全为 NULL（旧预选形态）→ True。
    新会话（无实例）与已走新选题的会话（有 selection_reason）都为 False。
    """
    rows = conn.execute(
        "SELECT question_id, bank_question_id, seq, answered_at, selection_reason, question_type"
        " FROM assessment_question WHERE session_id=? ORDER BY seq", (session_id,)
    ).fetchall()
    instances = [dict(r) for r in rows]
    if not instances:
        return instances, False
    is_legacy = all(r["selection_reason"] is None for r in instances)
    return instances, is_legacy


# ---------- 主函数 ----------

def select_next_question(session_id: str) -> dict | None:
    """四层选题并实例化下一题（§10.6）。返回新实例 dict；选题完成返回 None。

    分工：本函数自取连接、自持事务（决策 commit 之后调用，Anti-pattern 1 次序
    天然合规；服务层惯例）；选中后同事务 INSERT 实例 + QUESTION_SELECTED /
    QUESTION_ACTIVATED 事件。legacy 会话（全 NULL selection_reason 存量实例）→
    返回 {"legacy": True}，由 API 层走旧 ORDER BY seq 派发（不写新事件）。
    全程零 LLM 调用（纯代码选题，T-02-08）。
    """
    conn = get_conn()
    try:
        return _select_next_question_locked(conn, session_id)
    finally:
        conn.close()


def _select_next_question_locked(conn, session_id: str) -> dict | None:
    session = conn.execute(
        "SELECT session_id, position_id, model_id, model_version, status"
        " FROM assessment_session WHERE session_id=?", (session_id,)
    ).fetchone()
    if session is None:
        return None
    if session["status"] != "in_progress":
        return None

    instances, is_legacy = _session_instance_state(conn, session_id)
    if is_legacy:
        # legacy 兜底（Q5）：旧预选行按 seq 顺序继续派发——API 层走旧查询，不进四层
        return {"legacy": True}

    model_id = session["model_id"]
    items = _load_model_items(conn, model_id)
    candidates = _load_candidate_rows(conn, session["position_id"], model_id)
    # 难度承接（02-03）：各 item 最新封存 snapshot 的目标难度口径
    snapshot_targets = _snapshot_target_difficulty(conn, session_id)

    used_bank_ids = {r["bank_question_id"] for r in instances}
    answered_cnt = sum(1 for r in instances if r["answered_at"] is not None)
    total_instances = len(instances)

    n = config.ORDINARY_PLAN_N

    # ---------- required 例外分支（§10.5：普通计划耗尽后） ----------
    if total_instances >= n:
        uncovered_required = _uncovered_required_items(items, candidates, used_bank_ids)
        granted = _exception_granted_items(conn, session_id)
        pending = [it for it in uncovered_required if it["item_id"] not in granted]
        if not pending:
            return None  # 普通计划 + 例外全耗尽 → API 层据此触发 finish
        item = pending[0]
        picked = _pick_exception_question(candidates, item, used_bank_ids)
        if picked is None:
            # 无合法候选 → 不静默：PATH_UNAVAILABLE 留痕（D-21 既有枚举）
            append_event(conn, session_id=session_id, event_type="PATH_UNAVAILABLE",
                         actor_type="system",
                         payload={"item_id": item["item_id"], "scope": "required_exception",
                                 "note": "required 例外无 medium/hard 候选（§10.5）"})
            conn.commit()
            return None
        return _instantiate(conn, session, picked, layer="exception", used_bank_ids=used_bank_ids,
                            nth=total_instances + 1, exception_item=item,
                            seed=_stable_seed(session_id))

    # ---------- 普通选题（四层依序） ----------
    uncovered_required = _uncovered_required_items(items, candidates, used_bank_ids)
    seed = _stable_seed(session_id)
    picked, layer, tier = _pick_ordinary(candidates, items, instances, used_bank_ids, n,
                                         uncovered_required, seed,
                                         snapshot_targets=snapshot_targets)
    if picked is None:
        # 可选池耗尽且未达计划（题库量不足）→ 返回 None 由 API 层判断收尾
        return None
    return _instantiate(conn, session, picked, layer=layer, used_bank_ids=used_bank_ids,
                         nth=total_instances + 1, tier=tier, seed=seed)


def _uncovered_required_items(items: list[dict], candidates: list[dict],
                              used_bank_ids: set[str]) -> list[dict]:
    """层②硬约束：模型 required + gate=0 且本会话未用其任何题的项。

    覆盖判定按已实例题的 item 归属（bank_question_id → (std_name, category) 匹配
    competency_item）——不依赖 assessment_question.item_id 列（暂未回填）。
    """
    covered_keys: set[tuple[str, str]] = {
        (c["std_name"], c["category"]) for c in candidates if c["question_id"] in used_bank_ids
    }
    return [it for it in items
            if it["importance"] == "required" and _item_key(it) not in covered_keys]


def exception_granted_items(conn, session_id: str) -> set[str]:
    """已获例外 item 集合（公开入口——WR-02：assessment.get_session 同口径复用）。"""
    return _exception_granted_items(conn, session_id)


def _exception_granted_items(conn, session_id: str) -> set[str]:
    """已获例外的 item_id 集合（每 item 最多一次——事件留痕处查询，不建新表）。

    判定上界收紧到「题型实例段」：本会话 selection_reason JSON 的 exception
    layer 记录（第 n 题后追加），事件行作冗余审计。结构性最小实现（§10.5）。
    WR-02：get_session 的 total_count 例外计数同口径复用本函数（事件兜底含
    selection_reason 解析失败的实例，进度分母与实发题数不漂移）。
    """
    rows = conn.execute(
        "SELECT selection_reason FROM assessment_question"
        " WHERE session_id=? AND selection_reason IS NOT NULL", (session_id,)
    ).fetchall()
    granted: set[str] = set()
    for r in rows:
        try:
            reason = json.loads(r["selection_reason"])
        except (json.JSONDecodeError, TypeError):
            continue
        if reason.get("layer") == "exception" and reason.get("item_id"):
            granted.add(reason["item_id"])
    # 兜底：REQUIRED_EXCEPTION_GRANTED 事件 payload 也是例外记录载体
    evs = conn.execute(
        "SELECT payload_json FROM assessment_state_event"
        " WHERE session_id=? AND event_type='REQUIRED_EXCEPTION_GRANTED'", (session_id,)
    ).fetchall()
    for e in evs:
        try:
            payload = json.loads(e["payload_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if payload.get("item_id"):
            granted.add(payload["item_id"])
    return granted


def _pick_exception_question(candidates: list[dict], item: dict,
                             used_bank_ids: set[str]) -> dict | None:
    """例外补选（§10.5）：仅 medium；无 medium 才 hard；不走 easy；未用。"""
    pool = [c for c in candidates
            if _item_key(c) == _item_key(item) and c["question_id"] not in used_bank_ids]
    mediums = [c for c in pool if c["difficulty"] == "medium"]
    if mediums:
        return max(mediums, key=lambda c: (c.get("weight") or 0.0))
    hards = [c for c in pool if c["difficulty"] == "hard"]
    if hards:
        return max(hards, key=lambda c: (c.get("weight") or 0.0))
    return None


def _item_key(item: dict) -> tuple[str, str]:
    return (item["std_name"], item["category"])


def _pick_ordinary(candidates: list[dict], items: list[dict], instances: list[dict],
                   used_bank_ids: set[str], n: int,
                   uncovered_required: list[dict],
                   seed: int, snapshot_targets: dict[str, tuple[str, str]] | None = None
                   ) -> tuple[dict | None, str, str | None]:
    """四层普通选题：返回 (picked, layer, tier)。

    层①过滤在候选池加载时完成（_load_candidate_rows）；层②③④在此执行：
    ② required 硬约束——uncovered required 的题在配额（category/tier）剩余
      槽位内优先（chain 后继可让位 required——本实现以权重序近似，先保证覆盖）；
    ③ 配额——plan_quotas 目标按已实例 (category, tier) 实时扣减；
    ④ 排序三键——chain 后继 → item.weight 降序 → 稳定随机种子（Q3 决议；
      「题目质量」分项显式禁用——D-17）。
    snapshot_targets（02-03 难度承接）：{item_id: (current_difficulty, note)}——
    item 有 snapshot 时以其 current_difficulty 为该 item 候选难度口径（题库需
    有该难度题行；无则落回可得最高档，不高于目标档——跳级禁止）。
    """
    pool = [c for c in candidates if c["question_id"] not in used_bank_ids]
    if not pool:
        return None, "fallback", None

    # 层①难度承接（02-03）：按 item 过滤候选难度
    if snapshot_targets:
        pool = _apply_snapshot_difficulty(pool, snapshot_targets)

    quotas = plan_quotas(n, _available_counts(candidates))
    # 已建实例的 (category, tier) 计数（配额实时扣减）
    used_by_cat_tier: dict[tuple[str, str], int] = {}
    for inst in instances:
        row = next((c for c in candidates if c["question_id"] == inst["bank_question_id"]), None)
        if row:
            key = (row["category"], row.get("tier") or "plus")
            used_by_cat_tier[key] = used_by_cat_tier.get(key, 0) + 1

    # 组内层③+层④统一实现：过滤配额剩余 → 层④排序取首
    def _quota_remaining(c: dict) -> bool:
        cat, tier = c["category"], c.get("tier") or "plus"
        target = quotas.get(cat, {}).get(tier, 0)
        used = used_by_cat_tier.get((cat, tier), 0)
        # 大类级剩余：ORdinary 类目总实例 < n（未超总计划——类目退化已并入 quotas）
        return used < target

    # 层②：uncovered required 优先——但其选择仍须在配额剩余槽位内（否则 §10.5
    # 的例外永不触发——required 覆盖让位于配额边界，正是例外分支的语义入口）
    required_keys = {_item_key(it) for it in uncovered_required}
    req_pool = [c for c in pool if _item_key(c) in required_keys and _quota_remaining(c)]
    if req_pool:
        picked = _sort_pool(req_pool, seed)[0]
        return picked, "required_first", picked.get("tier") or "plus"

    # 层③+层④：配额剩余池 → 排序三键取首
    quota_pool = [c for c in pool if _quota_remaining(c)]
    if quota_pool:
        picked = _sort_pool(quota_pool, seed)[0]
        return picked, "quota", picked.get("tier") or "plus"

    # 配额槽位全满：大类总量达标即计划完成（readiness 保证题库足量时必达 N；
    # 未达 N 即题库量不足口径——由 API 层触发 finish，不越配额补位）
    return None, "quota", None


def _available_counts(candidates: list[dict]) -> dict[str, dict[str, int]]:
    """层③ quota 公式的 categories_present 输入：{category: {tier: 可用量}}。"""
    counts: dict[str, dict[str, int]] = {}
    for c in candidates:
        cat = c["category"]
        tier = c.get("tier") or "plus"
        counts.setdefault(cat, {"required": 0, "preferred": 0, "plus": 0})
        counts[cat][tier] = counts[cat].get(tier, 0) + 1
    return counts


def _sort_pool(pool: list[dict], seed: int) -> list[dict]:
    """层④排序三键（题目质量显式禁用——D-17）：

    chain 后继（当前实例 chain_key 相同且 chain_seq=当前+1 的题优先，可让位
    required——本实现在各调用池上算后继标志）→ item.weight 降序 → 稳定随机
    种子（同 seed 的随机序作 weight 并列时的 tie-break，Q3 决议）。
    """
    rng = random.Random(seed)

    def sort_key(c: dict):
        chain = 1 if c.get("chain_followed") else 0
        return (-chain, -(c.get("weight") or 0.0), rng.random())

    return sorted(pool, key=sort_key)


def _instantiate(conn, session: dict, picked: dict, *, layer: str,
                 used_bank_ids: set[str], nth: int, seed: int, tier: str | None = None,
                 exception_item: dict | None = None) -> dict:
    """选中后同事务：INSERT 实例 + QUESTION_SELECTED/QUESTION_ACTIVATED 事件 → commit。"""
    session_id = session["session_id"]
    now = now_iso()

    # chain 后继判定（层④第一键）：当前会话最新实例 chain_key 相同且 chain_seq
    # =当前+1 的候选优先（可让位 required——此处只记录命中标志，排序键在 _sort_pool）
    chain_followed = False
    if picked.get("chain_key"):
        rows = conn.execute(
            "SELECT b.chain_key, b.chain_seq FROM assessment_question aq"
            " JOIN question_bank b ON b.question_id=aq.bank_question_id"
            " WHERE aq.session_id=? ORDER BY aq.seq DESC LIMIT 1", (session_id,),
        ).fetchall()
        for row in reversed(rows):
            if row["chain_key"] and row["chain_key"] == picked["chain_key"] \
                    and (row["chain_seq"] or 0) + 1 == (picked["chain_seq"] or 0):
                chain_followed = True
                break

    reason = {
        "layer": layer,
        "predicate": "tier_quota_remaining",
        "category": picked["category"],
        "tier": tier or picked.get("tier") or "plus",
        "chain_followed": chain_followed,
        "weight": picked.get("weight") or 0.0,
        "seed": seed,
        "nth": nth,
    }
    if exception_item is not None:
        reason["item_id"] = exception_item["item_id"]

    seq = nth
    aq_id = new_id("aq")
    item_id = exception_item["item_id"] if exception_item is not None \
        else picked.get("model_item_id")
    conn.execute(
        "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq,"
        " question_type, item_id, difficulty, status, activated_at, selection_reason,"
        " selection_policy_version, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (aq_id, session_id, picked["question_id"], seq,
         "ordinary", item_id, picked["difficulty"], "active", now,
         json.dumps(reason, ensure_ascii=False), _SELECTION_POLICY_VERSION, now),
    )
    # QUESTION_SELECTED：与实例 INSERT 同事务（Pattern 3），payload 全量镜像（T-02-07）
    append_event(conn, session_id=session_id, event_type="QUESTION_SELECTED",
                 actor_type="system", assessment_question_id=aq_id,
                 payload={"selection_reason": reason})
    append_event(conn, session_id=session_id, event_type="QUESTION_ACTIVATED",
                 from_state=None, to_state="active",
                 actor_type="system", assessment_question_id=aq_id)
    if exception_item is not None:
        # 例外留痕（A6 决议：事件 payload 记 item_id 与候选难度）
        append_event(conn, session_id=session_id, event_type="REQUIRED_EXCEPTION_GRANTED",
                     actor_type="system", assessment_question_id=aq_id,
                     payload={"item_id": exception_item["item_id"],
                              "std_name": exception_item["std_name"],
                              "difficulty": picked["difficulty"]})
    conn.commit()
    return {
        "question_id": aq_id,
        "bank_question_id": picked["question_id"],
        "seq": seq,
        "stem": picked.get("stem"),
        "category": picked["category"],
        "difficulty": picked.get("difficulty"),
    }


def _stable_seed(session_id: str) -> int:
    """稳定随机种子（Q3 决议）：int(sha256(session_id).hexdigest()[:8], 16)。"""
    return int(hashlib.sha256(session_id.encode()).hexdigest()[:8], 16)
