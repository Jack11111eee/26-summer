"""测评端 API（P5）：可测评岗位列表 + 测评会话/答题/表单/打分/报告（模块二 M5 + 模块三 M6）。"""
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from ..core.security import load_owned_report, load_owned_session, require_login
from ..db import get_conn
from ..services.difficulty import update_path_state
from ..services.interview import decide_next_action
from ..services.pipeline import new_id, now_iso
from ..services.question_selection import select_next_question
from ..services.readiness import check_session_readiness
from ..services.refine import refine_user_input
from ..services.report import generate_report
from ..services.scoring import score_session
from ..services.state_events import append_event

router = APIRouter(prefix="/api/assessment", tags=["assessment"], dependencies=[Depends(require_login)])


def _latest_confirmed_model(conn, position_id: str):
    """取岗位最新 confirmed 模型行（WR-15：「最新 confirmed 版」唯一口径）。

    相关子查询取每岗位 MAX(version)，列表/会话/预览共用，避免两处实现漂移。
    """
    return conn.execute(
        "SELECT model_id, version, model_json FROM competency_model"
        " WHERE position_id=? AND status='confirmed'"
        " AND version=(SELECT MAX(version) FROM competency_model m2"
        "              WHERE m2.position_id=competency_model.position_id AND m2.status='confirmed')"
        " ORDER BY version DESC LIMIT 1",
        (position_id,),
    ).fetchone()


@router.get("/positions")
def list_assessable_positions() -> list[dict]:
    """可测评岗位：active 且存在 confirmed 模型（附版本号与能力项数）。"""
    conn = get_conn()
    # WR-15：全程取每岗位最新 confirmed 版（相关子查询），岗位排序与版本号无关
    rows = conn.execute(
        "SELECT p.position_id, p.name, m.version, m.model_id,"
        " json_array_length(json_extract(m.model_json,'$.items')) AS item_count"
        " FROM position p"
        " JOIN competency_model m ON m.position_id=p.position_id"
        " WHERE p.status='active' AND m.status='confirmed'"
        " AND m.version=(SELECT MAX(version) FROM competency_model m2"
        "                WHERE m2.position_id=m.position_id AND m2.status='confirmed')"
        " ORDER BY p.created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/positions/{position_id}/model")
def get_confirmed_model(position_id: str) -> dict:
    """confirmed 模型快照（模块二出题的输入契约，本期用于占位页展示）。"""
    conn = get_conn()
    # WR-10：join position 校验 status='active'——与列表接口的 active 过滤一致，
    # 不向任意登录用户泄露未上架岗位的胜任力模型配置
    row = conn.execute(
        "SELECT m.model_id, m.version, m.model_json FROM competency_model m"
        " JOIN position p ON p.position_id=m.position_id"
        " WHERE m.position_id=? AND m.status='confirmed' AND p.status='active'"
        " ORDER BY m.version DESC LIMIT 1",
        (position_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该岗位暂无已确认模型")
    d = dict(row)
    d["model"] = json.loads(d.pop("model_json"))
    return d


# ---------- 会话 ----------

@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(body: dict, user: dict = Depends(require_login)) -> dict:
    """创建测评会话：锚定 confirmed 模型最新版（动态选题——SC-1 零预选）。

    首题在首次 GET /answer 时由 select_next_question 派发（02-02，SSOT §10.6）。
    """
    position_id = body.get("position_id")
    if not position_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "缺少 position_id")
    conn = get_conn()
    model = _latest_confirmed_model(conn, position_id)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该岗位暂无已确认模型，无法开考")

    # 开考前可测量性检查（§10.4）：不通过拒绝创建会话（杜绝 0 题会话静默开考，REF-3.5/8.5）
    result = check_session_readiness(position_id)
    if result:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": result["error_code"],
                                    "message": result["detail"]})

    session_id = new_id("sess")
    now = now_iso()
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (session_id, user["user_id"], position_id, model["model_id"], model["version"],
         "in_progress", now, now),
    )
    # 动态选题（02-02，SC-1）：创建时不预选——每次 action=next 由
    # select_next_question 即时选题实例化；此处只落会话 + SESSION_CREATED 事件
    # 状态迁移留痕：与 INSERT 会话同一事务（SSOT §13.1 快照与事件同事务）
    append_event(conn, session_id=session_id, event_type="SESSION_CREATED",
                 from_state=None, to_state="in_progress",
                 actor_type="candidate", actor_id=user["user_id"])
    conn.commit()
    return {"session_id": session_id,
            "estimated_duration_minutes": 20}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, user: dict = Depends(require_login)) -> dict:
    """会话状态：当前题 = 未封存最新实例（动态派发 / legacy 旧 seq 兜底）。"""
    conn = get_conn()
    s = load_owned_session(conn, session_id, user, allow_admin_read=True)
    answered = conn.execute(
        "SELECT COUNT(*) c FROM assessment_question WHERE session_id=? AND answered_at IS NOT NULL",
        (session_id,),
    ).fetchone()["c"]
    cur = conn.execute(
        "SELECT aq.question_id, aq.seq, b.stem, b.category, b.qtype, b.difficulty"
        " FROM assessment_question aq JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE aq.session_id=? AND aq.answered_at IS NULL ORDER BY aq.seq LIMIT 1",
        (session_id,),
    ).fetchone()
    if cur is None and s["status"] == "in_progress":
        # 动态派发（02-02）：无未答实例且会话进行中 → select_next_question 派发新实例
        picked = select_next_question(session_id)
        if picked is not None and not picked.get("legacy"):
            conn2 = get_conn()
            try:
                cur = conn2.execute(
                    "SELECT aq.question_id, aq.seq, b.stem, b.category, b.qtype, b.difficulty"
                    " FROM assessment_question aq JOIN question_bank b ON b.question_id=aq.bank_question_id"
                    " WHERE aq.question_id=?",
                    (picked["question_id"],),
                ).fetchone()
            finally:
                conn2.close()
        # legacy 兜底（Q5）：{'legacy': True} 或旧未答行形态 → 走上面旧 ORDER BY seq
        # 查询结果（cur 已取——legacy 会话已被该查询覆盖；无行则保持 None 不 500）
    # total_count 口径（02-02）：计划数 N + 已发生例外数 E（answer 行数不再作分母）
    from .. import config as _config
    if s["status"] == "completed":
        total = answered
    else:
        exceptions = conn.execute(
            "SELECT COUNT(*) c FROM assessment_question WHERE session_id=?"
            " AND selection_reason IS NOT NULL AND json_extract(selection_reason,'$.layer')='exception'",
            (session_id,),
        ).fetchone()["c"]
        total = _config.ORDINARY_PLAN_N + exceptions
    return {
        "session_id": s["session_id"],
        "status": s["status"],
        "position_id": s["position_id"],
        "model_version": s["model_version"],
        "current_question": dict(cur) if cur else None,
        "answered_count": answered,
        "total_count": total,
    }


@router.post("/sessions/{session_id}/answer")
def submit_answer(session_id: str, body: dict, user: dict = Depends(require_login)) -> dict:
    """提交回答：精炼落库 → interview 决策 → 落 assistant 消息 → 推进题目/会话状态。"""
    question_id = body.get("question_id")
    # WR-02：与 submit_feedback 的 .strip() 语义对齐——纯空格串 422，不落入精炼/评分
    raw_answer = body.get("answer")
    answer = raw_answer.strip() if isinstance(raw_answer, str) else ""
    if not question_id or not answer:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "缺少 question_id 或 answer")

    conn = get_conn()
    s = load_owned_session(conn, session_id, user)
    if s["status"] != "in_progress":
        # WR-01：409 detail 统一为 {error_code, message} 结构（与 readiness 三态一致）
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_NOT_IN_PROGRESS",
                                    "message": f"会话已结束（{s['status']}）"})
    q = conn.execute(
        "SELECT question_id, answered_at FROM assessment_question WHERE question_id=? AND session_id=?",
        (question_id, session_id),
    ).fetchone()
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "题目不属于该会话")
    if q["answered_at"] is not None:
        # WR-01：409 detail 统一为 {error_code, message} 结构（与 readiness 三态一致）
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "QUESTION_ALREADY_ANSWERED",
                                    "message": "该题已作答"})

    now = now_iso()
    # 1. 用户消息（长输入走精炼，原文哈希归档）
    refined, raw_hash = refine_user_input(answer)
    conn.execute(
        "INSERT INTO assessment_message(message_id, session_id, question_id, role, content, raw_hash, created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (new_id("msg"), session_id, question_id, "user", refined, raw_hash, now),
    )
    # 首条用户消息视为开问标记
    conn.execute(
        "UPDATE assessment_question SET asked_at=COALESCE(asked_at, ?) WHERE question_id=?",
        (now, question_id),
    )
    # 先提交用户消息再调 LLM：llm_trace 用新连接写库，本连接持写事务会 database is locked
    conn.commit()

    # 2. 面试决策（观察层 + 裁决层，02-04 两层化：LLM 只出观察，代码裁决 action）
    decision = decide_next_action(session_id, question_id, refined)

    # 拒答封存路径（D-24/裁决规则 2）：内部值 seal_refused 对前端仍透出 next，
    # refused 标记键驱动封存分支（5 键契约只加不减，Pitfall 8）
    _refused = bool(decision.get("refused"))
    _out_action = "next" if _refused else decision["action"]

    # 3. assistant 消息落库（action/reason/score_live 先于展示，可审计）
    conn.execute(
        "INSERT INTO assessment_message(message_id, session_id, question_id, role, content,"
        " action, reason, score_live, score_live_reason, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (new_id("msg"), session_id, question_id, "assistant", decision["reply"],
         _out_action, decision["reason"], decision["score_live"],
         decision["score_live_reason"], now_iso()),
    )

    # 观察留痕（§13.2 最小集——T-02-18）：每次决策后落 OBSERVATION_CLASSIFIED
    append_event(conn, session_id=session_id, event_type="OBSERVATION_CLASSIFIED",
                 actor_type="system", assessment_question_id=question_id,
                 payload={"answer_state": decision["answer_state"],
                          "evidence_sufficient": decision["evidence_sufficient"],
                          "action": _out_action})

    # followup 计数（D-25 迁列）：与 assistant 消息 INSERT 同事务段自增
    if _out_action == "followup":
        conn.execute(
            "UPDATE assessment_question SET followup_count=followup_count+1 WHERE question_id=?",
            (question_id,),
        )

    # 4. 推进题目/会话状态（事件行与快照 UPDATE 同事务，随下述最终 commit 落库）
    next_question_id = None
    _is_legacy_session = False
    if _refused:
        # 拒答二次确认 → 封存 refused（D-24）：不写 question_score（评分写入属 02-05，
        # REFUSED 的 score_state 行不在此产生），照 next 路径派发下一题
        now_seal = now_iso()
        conn.execute(
            "UPDATE assessment_question SET answered_at=?, closed_at=?, seal_reason='refused'"
            " WHERE question_id=?",
            (now_seal, now_seal, question_id),
        )
        append_event(conn, session_id=session_id, event_type="QUESTION_SEALED",
                     from_state="active", to_state="sealed",
                     actor_type="candidate", actor_id=user["user_id"],
                     assessment_question_id=question_id,
                     payload={"seal_reason": "refused"})
        append_event(conn, session_id=session_id, event_type="EVIDENCE_EVALUATED",
                     actor_type="system", assessment_question_id=question_id,
                     payload={"evidence_sufficient": decision["evidence_sufficient"],
                              "stable_evidence": False})
        # 封存点推进难度状态机（02-03：refused 是七类排除之一——is_valid_failure=False，
        # 计数器不动，但 snapshot 推进保持审计链完整）
        _advance_difficulty_state(conn, session_id, question_id, decision, stable=False,
                                  followup_ambiguous=False)
    elif _out_action in ("next", "finish"):
        now_seal = now_iso()
        # answered 封存语义补全（D-25 三路统一：closed_at + seal_reason='answered'）
        conn.execute(
            "UPDATE assessment_question SET answered_at=?, closed_at=?, seal_reason='answered'"
            " WHERE question_id=?",
            (now_seal, now_seal, question_id),
        )
        append_event(conn, session_id=session_id, event_type="QUESTION_ANSWERED",
                     from_state="active", to_state="answered",
                     actor_type="candidate", actor_id=user["user_id"],
                     assessment_question_id=question_id)
        append_event(conn, session_id=session_id, event_type="QUESTION_SEALED",
                     from_state="active", to_state="sealed",
                     actor_type="system", assessment_question_id=question_id,
                     payload={"seal_reason": "answered"})
        # 裁决发生在封存时机（§13.2 EVIDENCE_EVALUATED）：轻量 stable 判据
        # sufficient_in_row ≥ 2（A2 决议——本会话该 item 充分观察计数，Phase 2 轻量版）
        stable = _stable_evidence_light(conn, session_id, question_id,
                                        decision["evidence_sufficient"])
        append_event(conn, session_id=session_id, event_type="EVIDENCE_EVALUATED",
                     actor_type="system", assessment_question_id=question_id,
                     payload={"evidence_sufficient": decision["evidence_sufficient"],
                              "stable_evidence": stable})
        # 封存点推进难度状态机（02-03：§11.2 降级判据 2——followup 后仍不充分
        # 即 followup_ambiguous；实例发生过 followup 才可能满足，首答即 next 不算）
        followup_happened = _instance_followup_count(conn, question_id) > 0
        _advance_difficulty_state(
            conn, session_id, question_id, decision, stable=stable,
            followup_ambiguous=bool(followup_happened
                                    and not decision["evidence_sufficient"]))
    if _out_action == "followup" or decision["action"] == "confirm":
        # followup：实例内子轮次，不推进实例状态（followup_count 已自增）
        # confirm：拒答首次确认（D-24 控制类一次性确认话术），同样不推进实例状态
        conn.commit()
    else:
        # 先提交本事务再选题（Anti-pattern 1 / 单写者纪律：select_next_question
        # 自取连接自持事务，llm_trace 已在 :192 commit 后写库，此处 commit 保证
        # 决策与选出实例分属两个事务，无锁冲突）
        conn.commit()
        # 02-02 动态选题：finish 不再由决策 is_last 直接判定（migration 期决策的
        # is_last 基于静态预选——动态实例化下第 N-1 题作答时第 N 题尚未实例化），
        # 改以「选题返回 None（可选池耗尽）」为 finish 唯一触发源（02-04 裁决层
        # 再统一移入调用点）
        picked = select_next_question(session_id)
        _is_legacy_session = bool(picked and picked.get("legacy"))
        if picked is None:
            # 可选池耗尽（普通计划 + required 例外全完成）→ finish 收尾
            conn.execute(
                "UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
                (now_iso(), session_id),
            )
            append_event(conn, session_id=session_id, event_type="SESSION_COMPLETED",
                         from_state="in_progress", to_state="completed", actor_type="system")
            conn.commit()
            return {"action": "finish", "reply": decision["reply"],
                    "question_id": question_id, "next_question_id": None,
                    "score_live": decision["score_live"]}
        if picked.get("legacy"):
            # legacy 会话（Q5）：旧预选行按 seq 继续派发——走旧查询，不进四层；
            # 旧行为语义保持：决策 next/finish 按原样透出（旧行耗尽时如上提前 return）
            nxt = conn.execute(
                "SELECT question_id FROM assessment_question"
                " WHERE session_id=? AND answered_at IS NULL ORDER BY seq LIMIT 1",
                (session_id,),
            ).fetchone()
            if nxt is None:
                conn.execute(
                    "UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
                    (now_iso(), session_id),
                )
                append_event(conn, session_id=session_id, event_type="SESSION_COMPLETED",
                             from_state="in_progress", to_state="completed", actor_type="system")
                conn.commit()
                return {"action": "finish", "reply": decision["reply"],
                        "question_id": question_id, "next_question_id": None,
                        "score_live": decision["score_live"]}
            next_question_id = nxt["question_id"]
        else:
            next_question_id = picked["question_id"]
    conn.commit()

    # 02-02 动态选题：决策的 finish（is_last 旧口径）在池未耗尽时降级为
    # next——finish 唯一触发源是选题返回 None（见上分支）；legacy 会话按旧
    # 语义透出决策 action
    action = _out_action
    if action == "finish" and next_question_id is not None and not _is_legacy_session:
        action = "next"
    return {"action": action, "reply": decision["reply"],
            "question_id": question_id, "next_question_id": next_question_id,
            "score_live": decision["score_live"]}


def _stable_evidence_light(conn, session_id: str, question_id: str,
                           current_sufficient: bool) -> bool:
    """stable_evidence 轻量版（A2 决议——Phase 2 难度导航用，Phase 5 完整裁决留白）。

    判据 = 本会话同 item 的充分观察计数 sufficient_in_row ≥ 2（两个不同实例
    的独立有效观察）。当前结论按「含本次」计数：本次充分且同 item 既有充分
    观察达 1 次 → stable。事件表 OBSERVATION_CLASSIFIED payload 的布尔聚合。
    WR-01：接调用方主 conn（决策事务内自读自写——不另开连接读到陈旧状态）。
    """
    if not current_sufficient:
        return False
    item_id = _question_item_id(conn, question_id)
    if item_id is None:
        return False
    rows = conn.execute(
        "SELECT e.payload_json FROM assessment_state_event e"
        " JOIN assessment_question aq ON aq.question_id=e.assessment_question_id"
        " WHERE e.session_id=? AND e.event_type='OBSERVATION_CLASSIFIED'"
        " AND aq.item_id=?",
        (session_id, item_id),
    ).fetchall()
    sufficient_cnt = 0
    for r in rows:
        try:
            p = json.loads(r["payload_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if p.get("evidence_sufficient"):
            sufficient_cnt += 1
    # 含本次（本次 OBSERVATION_CLASSIFIED 已落）：≥2 即两个不同实例充分观察
    return sufficient_cnt >= 2


def _instance_followup_count(conn, question_id: str) -> int:
    """实例内 followup 次数（D-25 迁列后的单行读——难度状态机降级判据 2 用）。

    WR-01：接调用方主 conn（同事务自读自写，消除双连接交错窗口）。
    """
    row = conn.execute(
        "SELECT followup_count FROM assessment_question WHERE question_id=?",
        (question_id,),
    ).fetchone()
    return row["followup_count"] if row else 0


def _question_item_id(conn, question_id: str) -> str | None:
    """取实例的 item_id（02-01 列回填后可用；NULL（legacy/未回填）返回 None）。

    WR-01：接调用方主 conn（同事务自读自写，消除双连接交错窗口）。
    """
    row = conn.execute(
        "SELECT item_id FROM assessment_question WHERE question_id=?", (question_id,)
    ).fetchone()
    return row["item_id"] if row else None


# §11.2「不计入普通失败」七类（技术/无障碍/题目无效/模型不确定/合理质疑/
# 明确拒答/攻击性事件）——answer_state 分类驱动排除，非候选人源性失败
# 不触发降级计数（is_valid_failure=False → advance_snapshot 计数器不动）
_EXCLUDED_FAILURE_STATES = (
    "TECHNICAL_OR_ACCESS_BARRIER",  # 技术故障 + 无障碍（§11.2 同前一条）
    "ITEM_INVALID",                 # 题目无效
    "MODEL_UNCERTAIN",              # 模型不确定
    "PROCESS_CHALLENGE",            # 合理流程质疑
    "DECLINED",                     # 明确拒答
    "CONDUCT_EVENT",                # 攻击性事件
    "PROMPT_INJECTION",             # 攻击性事件（注入归攻击类——§11.4 处理原则同路）
)


def _advance_difficulty_state(conn, session_id: str, question_id: str,
                               decision: dict, stable: bool,
                               followup_ambiguous: bool) -> None:
    """封存点推进难度状态机（§11.2——一次实例内不升降级，封存后才算一次观察）。

    update_path_state 不 commit（同事务由调用者最终 commit）；item_id NULL
    （legacy/未回填实例）跳过——无 item 归属即无难度路径。followup_ambiguous：
    本实例发生过 followup 且证据仍不充分（长但空路径）→ 降级判据 2。
    """
    row = conn.execute(
        "SELECT aq.item_id, ci.required_level FROM assessment_question aq"
        " LEFT JOIN competency_item ci ON ci.item_id=aq.item_id"
        " WHERE aq.question_id=?", (question_id,),
    ).fetchone()
    if row is None or not row["item_id"]:
        return
    answer_state = decision.get("answer_state", "")
    observation = {
        "answer_state": answer_state,
        "evidence_sufficient": bool(decision.get("evidence_sufficient")),
        "stable_evidence": stable,
        "is_valid_failure": answer_state not in _EXCLUDED_FAILURE_STATES,
        "followup_ambiguous": followup_ambiguous,
    }
    update_path_state(conn, session_id=session_id, item_id=row["item_id"],
                       sealed_question_id=question_id, observation=observation,
                       required_level=row["required_level"])


@router.post("/sessions/{session_id}/forms/submit", status_code=status.HTTP_201_CREATED)
def submit_form(session_id: str, body: dict, user: dict = Depends(require_login)) -> dict:
    """表单提交（简历/门槛项）：原始 payload 落 form_submission。"""
    form_type = body.get("form_type")
    payload = body.get("payload")
    if not form_type or payload is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "缺少 form_type 或 payload")
    conn = get_conn()
    load_owned_session(conn, session_id, user)
    form_id = new_id("form")
    conn.execute(
        "INSERT INTO form_submission(form_id, session_id, user_id, form_type, payload_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (form_id, session_id, user["user_id"], form_type,
         json.dumps(payload, ensure_ascii=False), now_iso()),
    )
    conn.commit()
    return {"form_id": form_id, "status": "submitted"}


@router.post("/sessions/{session_id}/score")
def score_session_endpoint(session_id: str, user: dict = Depends(require_login)) -> dict:
    """终局打分：会话内所有已答题逐题评分，落 question_score。

    completed 会话被服务层护栏拒绝（ValueError → 409，REF-8.2）；正常 UI 主链的
    评分已由 request_report 串行链在服务端承接（D-08），本端点保留为显式入口。
    """
    conn = get_conn()
    load_owned_session(conn, session_id, user)
    total = conn.execute(
        "SELECT COUNT(*) c FROM assessment_question WHERE session_id=?", (session_id,)
    ).fetchone()["c"]
    try:
        result = score_session(session_id)
    except ValueError as e:
        # WR-01：409 detail 统一为 {error_code, message} 结构（与 readiness 三态一致）
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_NOT_COMPLETED",
                                    "message": str(e)})
    return {**result, "total_questions": total}


# ---------- 报告（07 §10.5，异步生成 + 轮询） ----------

def _append_task_event(session_id: str, event_type: str, *, payload: dict | None = None,
                       from_state: str | None = None, to_state: str | None = None) -> None:
    """独立小事务写串行链事件（后台任务无外层事务；不持事务跨 LLM 调用）。"""
    conn = get_conn()
    try:
        append_event(conn, session_id=session_id, event_type=event_type,
                     from_state=from_state, to_state=to_state,
                     actor_type="system", payload=payload)
        conn.commit()
    finally:
        conn.close()


def _generate_report_task(session_id: str) -> None:
    """后台任务：评分→报告串行链（D-08 方案 B，SSOT §21.1 前端完成后由服务端执行）。

    异常静默（前端轮询 report 表为空即判失败/未完成），TASK_FAILED 事件留痕；
    FAILED 可见性属 Phase 5（REF-8.3）。completed 会话评分经 allow_completed 内部
    链豁免（D-03：串行链语义，不经候选人端点）。
    """
    try:
        # 链入口事件（事实类，D-10 无 SCORING 快照态）
        _append_task_event(session_id, "TASK_STARTED",
                           payload={"note": "串行链启动（评分→报告）"})
        _append_task_event(session_id, "SESSION_ENTERED_SCORING",
                           from_state="in_progress", to_state="in_progress",
                           payload={"note": "无 SCORING 快照态（D-10），事实类事件"})
        # 评分子步：内存算完单事务落库（scoring 模式），事件紧随其后独立小事务
        score_session(session_id, allow_completed=True)
        _append_task_event(session_id, "TASK_SUCCEEDED", payload={"step": "score"})
        # 报告子步
        generate_report(session_id)
        _append_task_event(session_id, "TASK_SUCCEEDED", payload={"step": "report"})
    except Exception as e:  # noqa: BLE001
        try:
            _append_task_event(session_id, "TASK_FAILED", payload={"error": str(e)[:200]})
        except Exception:  # noqa: BLE001
            pass  # 事件写入失败不改变静默现状


@router.post("/sessions/{session_id}/report", status_code=status.HTTP_202_ACCEPTED)
def request_report(session_id: str, background: BackgroundTasks, user: dict = Depends(require_login)) -> dict:
    """触发报告生成（异步，前端轮询 GET /reports?session_id= 获取结果）。

    三分支裁决（B-1）：(a) 会话非 completed → 409 非法前置（报告必须在完成后请求）；
    (b) completed 且已存在 report 行 → 409 拒绝重复触发（不重复评分/报告）；
    (c) completed 且尚无 report 行 → 202 入队（含后台链失败后的重试入口）。
    评分→报告由服务端串行链执行（D-08 方案 B），前端无需再显式调 POST /score。
    """
    conn = get_conn()
    session = load_owned_session(conn, session_id, user)
    if session["status"] != "completed":
        # WR-01：409 detail 统一为 {error_code, message} 结构（与 readiness 三态一致）
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_NOT_COMPLETED",
                                    "message": "会话未完成，不能请求报告"})
    report_row = conn.execute(
        "SELECT 1 FROM report WHERE session_id=?", (session_id,)
    ).fetchone()
    if report_row is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "REPORT_ALREADY_EXISTS",
                                    "message": "报告已生成，不允许重复报告"})
    # 仅 (c) 分支入队；TASK_QUEUED 事件独立小事务，务必在 add_task 前落库
    # （TASK_QUEUED 为事实类事件，无快照态迁移：from/to 留空）
    append_event(conn, session_id=session_id, event_type="TASK_QUEUED",
                 actor_type="system")
    conn.commit()
    background.add_task(_generate_report_task, session_id)
    return {"session_id": session_id, "status": "generating"}


@router.get("/reports/by-session/{session_id}")
def get_report_by_session(session_id: str, user: dict = Depends(require_login)) -> dict:
    """按会话取最新报告（前端轮询入口）。未生成 → 404。"""
    conn = get_conn()
    rid = conn.execute(
        "SELECT report_id FROM report WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if rid is None:
        # WR-05：与 load_owned_report 的 404 文案统一——"未生成"与"已生成但属他人"
        # 只差在文案即构成存在性 oracle（D-01：统一不存在语义）
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    r = load_owned_report(conn, rid["report_id"], user, allow_admin_read=True)
    return json.loads(r["report_json"])


@router.get("/reports/{report_id}")
def get_report(report_id: str, user: dict = Depends(require_login)) -> dict:
    """按 report_id 取报告完整 JSON。"""
    conn = get_conn()
    r = load_owned_report(conn, report_id, user, allow_admin_read=True)
    return json.loads(r["report_json"])


@router.post("/reports/{report_id}/feedback", status_code=status.HTTP_201_CREATED)
def submit_feedback(report_id: str, body: dict, user: dict = Depends(require_login)) -> dict:
    """候选人对某能力项评分提异议（07 §11 ② 反馈可回溯）。"""
    item_id = body.get("item_id")
    feedback_text = body.get("feedback_text", "").strip()
    if not item_id or not feedback_text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "缺少 item_id 或 feedback_text")
    conn = get_conn()
    load_owned_report(conn, report_id, user)
    # WR-06：item_id 须属于本报告会话锚定的模型（非全表存在性校验——
    # 挂入无关模型的能力项会破坏反馈回溯链 report→item 的数据完整性）
    it = conn.execute(
        "SELECT 1 FROM competency_item ci"
        " JOIN assessment_session s ON s.model_id=ci.model_id"
        " JOIN report r ON r.session_id=s.session_id"
        " WHERE r.report_id=? AND ci.item_id=?",
        (report_id, item_id),
    ).fetchone()
    if it is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "能力项不存在")
    feedback_id = new_id("fb")
    conn.execute(
        "INSERT INTO feedback(feedback_id, report_id, item_id, feedback_text, status, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (feedback_id, report_id, item_id, feedback_text, "pending", now_iso()),
    )
    conn.commit()
    return {"feedback_id": feedback_id, "status": "pending"}
