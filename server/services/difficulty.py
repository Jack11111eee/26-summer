"""难度路径状态机（SSOT §11.2 v2.0 确认，D-20/D-21——Phase 2 02-03）。

判据逐条出处《design/final-design/总设计文档.md》§11.2：
  - easy→medium：一次充分证据（sufficient_in_row ≥ 1）
  - medium→hard：充分且稳定的证据；hard 仅对 required_level > 4 的 item 开放
  - 降级触发（仅统计有效候选人证据失败）：同 item 同难度连续两道有效题未达最低
    锚点（fail_same_difficulty ≥ 2）或 followup 后仍模糊（followup_ambiguous）；
    当前非最低难度才可降级（easy 不降）
  - 降级后恢复（滞回原则）：连续两次充分证据（sufficient_in_row ≥ 2）或一次
    稳定证据（stable_ever 出现即算）
  - 一次实例内不升降级：本模块只在实例封存后由调用方触发，返回的 new_difficulty
    由【下一实例】承载（D-20：current_difficulty 写进 snapshot，选题层读取）
  - 跳级默认禁止：easy→hard 直接迁移不可产生。仅当模型/rubric 明确配置允许时
    才可跳级（§11.2「跳级」原文）——本期直接不实现跳级（无该分支）；无合法
    迁移返回 (None, None)。PATH_UNAVAILABLE 事件类型映射保留给 §10.5 例外
    无候选场景（question_selection.py 已实现），本模块不重复触发。

「不计入普通失败」七类（§11.2 原文：技术故障/无障碍问题/题目无效/模型不确定/
合理流程质疑/明确拒答/攻击性事件）——排除逻辑不写入本文件：调用方（assessment.py
封存点）从 02-04 answer_state 分类计算 is_valid_failure 传入，本文件只认布尔
（T-02-14：七类一概 False 不触发降级计数）。

path_state_snapshot 七键 JSON（D-20，Claude's Discretion 建议形态）：
  {item_id, current_difficulty, sufficient_in_row, stable_ever,
   fail_same_difficulty, followup_ambiguous, exception_used}

事务边界（D-06/T-02-13）：update_path_state 接 conn 但不 commit——snapshot UPDATE
与 DIFFICULTY_* 事件在调用者持有的同一事务内落库（§13.1 快照与事件同事务）。
"""
import json

from .state_events import append_event

# 降级判据摘要常量（事件 payload 的 criterion 值——Pitfall 5 审计可解释）
CRITERION_TWO_BELOW = "two_consecutive_below_anchor"
CRITERION_FOLLOWUP = "followup_still_ambiguous"
CRITERION_ONE_SUFFICIENT = "one_sufficient_observation"
CRITERION_SUFFICIENT_STABLE = "sufficient_and_stable"
CRITERION_HYSTERESIS_TWO = "hysteresis_two_sufficient"
CRITERION_HYSTERESIS_STABLE = "hysteresis_one_stable"


def next_difficulty(snap: dict, *, evidence_sufficient: bool, stable_evidence: bool,
                    is_valid_failure: bool, required_level: int | None
                    ) -> tuple[str | None, str | None]:
    """§11.2 判据裁决（纯函数，不持 conn）。返回 (new_difficulty, event_type)。

    None = 无迁移（下一实例沿用 snap["current_difficulty"]）。
    输入封装：is_valid_failure=False 的一律不累计 fail（七类排除——§11.2
    「不计入普通失败」；fail_same_difficulty 计数由 advance_snapshot 推进，
    本函数只读判定，未达锚点的无效失败在计数层已被排除）。

    判据顺序：降级优先于升级（避免同一次封存同时满足升降两判据漂移）；
    跨档非法迁移防御（跳级禁止）：easy 档位的任何充分/稳定组合只可能升到
    medium——函数内部永不返回 easy→hard 组合。
    """
    current = snap["current_difficulty"]
    sufficient_in_row = snap.get("sufficient_in_row", 0)
    stable_ever = snap.get("stable_ever", False)
    fail_same_difficulty = snap.get("fail_same_difficulty", 0)
    followup_ambiguous = snap.get("followup_ambiguous", False)

    # ---- 降级（§11.2：仅统计有效候选人证据失败；当前非最低难度才可降） ----
    if current != "easy" and (fail_same_difficulty >= 2 or followup_ambiguous):
        target = "easy" if current == "medium" else "medium"
        return target, "DIFFICULTY_LOWERED"

    # ---- easy 档升级 / 降级后恢复（滞回） ----
    if current == "easy":
        # 恢复判据（§11.2 滞回原则）：连续两次充分或一次稳定（stable_ever 出现即算）
        if sufficient_in_row >= 2 or (sufficient_in_row >= 1 and stable_ever):
            return "medium", "DIFFICULTY_RESTORED"
        # 首次升级判据：一次充分证据
        if sufficient_in_row >= 1:
            return "medium", "DIFFICULTY_RAISED"

    # ---- medium 档升级 ----
    elif current == "medium":
        # hard 门槛（§11.2 原文）：充分且稳定 + 仅 required_level > 4 的 item
        if sufficient_in_row >= 1 and stable_ever and required_level is not None \
                and required_level > 4:
            return "hard", "DIFFICULTY_RAISED"

    return None, None


def _criterion_for(snap: dict, event_type: str) -> str:
    """事件 payload 的 criterion 摘要（Pitfall 5——判据可解释，非仅 event_type）。"""
    if event_type == "DIFFICULTY_LOWERED":
        return (CRITERION_TWO_BELOW if snap.get("fail_same_difficulty", 0) >= 2
                else CRITERION_FOLLOWUP)
    if event_type == "DIFFICULTY_RAISED" and snap.get("current_difficulty") == "easy":
        return CRITERION_ONE_SUFFICIENT
    if event_type == "DIFFICULTY_RAISED":
        return CRITERION_SUFFICIENT_STABLE
    if event_type == "DIFFICULTY_RESTORED" and snap.get("stable_ever"):
        return CRITERION_HYSTERESIS_STABLE
    if event_type == "DIFFICULTY_RESTORED":
        return CRITERION_HYSTERESIS_TWO
    return "no_transition"


def advance_snapshot(snap: dict, *, evidence_sufficient: bool, stable_evidence: bool,
                     is_valid_failure: bool, followup_ambiguous: bool = False) -> dict:
    """计数器推进（§11.2 状态载体的递增/重置逻辑）。返回推进后的新 dict。

    - 充分证据 → sufficient_in_row +1 且 fail_same_difficulty 清零（连续充分
      打断连续失败）；stable_evidence=True 时 stable_ever 置位（出现一次即算）
    - 有效失败（is_valid_failure=True）且未达锚点 → fail_same_difficulty +1 且
      sufficient_in_row 清零（连续失败打断连续充分）
    - is_valid_failure=False（七类排除）→ 两个计数器都不动（§11.2 原文——
      非候选人源性失败不得触发降级）
    - followup_ambiguous 由调用方在封存时传入（followup 后仍模糊 → 触发降级判据 2）；
      充分证据时清回 False
    - 跨难度迁移（update_path_state 判定 new_level 后）fail_same_difficulty /
      followup_ambiguous 清零（换档即换「同难度」分母——判据不跨档携带）；
      降到 easy 时 sufficient_in_row 一并清零（滞回按新档重新累计）
    """
    out = dict(snap)
    if evidence_sufficient:
        out["sufficient_in_row"] = out.get("sufficient_in_row", 0) + 1
        out["fail_same_difficulty"] = 0
        out["followup_ambiguous"] = False
        if stable_evidence:
            out["stable_ever"] = True
    elif is_valid_failure:
        out["fail_same_difficulty"] = out.get("fail_same_difficulty", 0) + 1
        out["sufficient_in_row"] = 0
        if followup_ambiguous:
            out["followup_ambiguous"] = True
    return out


def update_path_state(conn, *, session_id: str, item_id: str, sealed_question_id: str,
                      observation: dict, required_level: int | None) -> None:
    """实例封存后推进 item 难度状态（§11.2——不 commit，事务归调用者）。

    流程：读该 item 最新封存实例的 snapshot（无则按首实例难度初始化）→
    advance_snapshot 计数 → next_difficulty 判定 → 迁移则把新 snapshot
    （current_difficulty=new）UPDATE 到【本次封存实例行】+ append_event
    DIFFICULTY_RAISED/LOWERED/RESTORED（from_state=旧难度 to_state=新难度，
    payload 判据摘要四键：criterion/evidence_counts/from_difficulty/to_difficulty）；
    无迁移也持久化推进后的 snapshot（计数器状态留给下一判据）但不写事件。

    observation: {answer_state, evidence_sufficient, followup_ambiguous}——
    02-04 observation 层的布尔输出（is_valid_failure 已由调用方按七类排除算好）。
    一次实例内不升降级：本函数只在封存点被调用（assessment.py next/finish/
    refused 三路封存之后）；followup 路径（实例未封存）不触发。
    """
    row = conn.execute(
        "SELECT path_state_snapshot FROM assessment_question"
        " WHERE session_id=? AND item_id=? AND closed_at IS NOT NULL"
        " AND question_id<>?"
        " ORDER BY seq DESC LIMIT 1",
        (session_id, item_id, sealed_question_id),
    ).fetchone()
    if row is not None and row["path_state_snapshot"]:
        try:
            snap = json.loads(row["path_state_snapshot"])
        except (json.JSONDecodeError, TypeError):
            snap = None
    else:
        snap = None
    if snap is None:
        # 初始 snapshot：起始 easy（§11 无 alternative 起始难度规定——plan
        # <interfaces> Simplicity：沿题库 easy 起始 + chain 惯例；不取实例
        # 行 difficulty——那是选题层第④层排序的结果，不是路径状态）
        snap = {
            "item_id": item_id,
            "current_difficulty": "easy",
            "sufficient_in_row": 0,
            "stable_ever": False,
            "fail_same_difficulty": 0,
            "followup_ambiguous": False,
            "exception_used": False,
        }

    old_level = snap["current_difficulty"]
    advanced = advance_snapshot(
        snap,
        evidence_sufficient=bool(observation.get("evidence_sufficient")),
        stable_evidence=bool(observation.get("stable_evidence")),
        is_valid_failure=bool(observation.get("is_valid_failure", True)),
        followup_ambiguous=bool(observation.get("followup_ambiguous")),
    )

    new_level, event_type = next_difficulty(
        advanced,
        evidence_sufficient=bool(observation.get("evidence_sufficient")),
        stable_evidence=bool(observation.get("stable_evidence")),
        is_valid_failure=bool(observation.get("is_valid_failure", True)),
        required_level=required_level,
    )
    if new_level is not None:
        advanced["current_difficulty"] = new_level
        # CR-02：跨难度迁移即换「同难度」分母——降级判据只描述本档内最近的
        # 封存观察，档内计数与 followup_ambiguous 不跨档携带（否则上个难度档
        # 的残留计数会在下一档错误触发降级/虚假 criterion）
        advanced["fail_same_difficulty"] = 0
        advanced["followup_ambiguous"] = False
        if new_level == "easy":
            # 降级到 easy 后恢复滞回按新档重新累计（不沿用降级前的升档进度）
            advanced["sufficient_in_row"] = 0
        payload = {
            "criterion": _criterion_for(advanced, event_type),
            "evidence_counts": {
                "sufficient": advanced.get("sufficient_in_row", 0),
                "insufficient": advanced.get("fail_same_difficulty", 0),
            },
            "from_difficulty": old_level,
            "to_difficulty": new_level,
        }
        append_event(conn, session_id=session_id, event_type=event_type,
                     from_state=old_level, to_state=new_level, actor_type="system",
                     assessment_question_id=sealed_question_id, payload=payload)

    conn.execute(
        "UPDATE assessment_question SET path_state_snapshot=? WHERE question_id=?",
        (json.dumps(advanced, ensure_ascii=False), sealed_question_id),
    )
