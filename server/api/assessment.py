"""测评端 API（P5）：可测评岗位列表 + 测评会话/答题/表单/打分/报告（模块二 M5 + 模块三 M6）。"""
import json
import math
from typing import Iterator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse

from .. import config as _config
from ..core.security import load_owned_report, load_owned_session, require_login
from ..db import get_conn
from ..schemas import AnswerRequest, FormSubmitRequest
from ..services.difficulty import update_path_state
from ..services.forms import (
    _all_gate_items_collected,
    render_form_instance,
    validate_and_submit,
    whitelist_form,
)
from ..services.interview import decide_next_action
from ..services.idempotency import check_idempotency, finalize_idempotency, request_hash_of
from ..services.pipeline import new_id, now_iso
from ..services.question_selection import exception_granted_items, select_next_question
from ..services.readiness import check_session_readiness
from ..services.refine import refine_user_input
from ..services.report import generate_report
from ..services.scoring import MAX_ANSWER_LEN, score_session
from ..services.state_events import append_event
from ..services.timer import (
    advance_interval,
    close_open_interval,
    maybe_abandon_session,
    open_interval,
    seal_if_question_timed_out,
    session_active_seconds,
    touch_last_activity,
)

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
    # WR-08：模型行改走 _latest_confirmed_model 单源实现（与 create_session 同口径，
    # 相关子查询取每岗位 MAX(version)——原 ORDER BY LIMIT 1 为第二套实现形态）；
    # active 校验单独先行（单源函数不含 position join）
    pos = conn.execute(
        "SELECT status FROM position WHERE position_id=?", (position_id,)
    ).fetchone()
    if pos is None or pos["status"] != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该岗位暂无已确认模型")
    row = _latest_confirmed_model(conn, position_id)
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
    # WR-06：readiness 复用上面已取的 model 行（单源——锚定同一 confirmed 版本）
    result = check_session_readiness(position_id, model=model)
    if result:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": result["error_code"],
                                    "message": result["detail"]})

    session_id = new_id("sess")
    now = now_iso()
    # phase 显式初始化 PENDING_START（03-04 状态机双轨——status 存量语义不动，Anti-pattern 4）
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, created_at, phase) VALUES(?,?,?,?,?,?,?,?,?)",
        (session_id, user["user_id"], position_id, model["model_id"], model["version"],
         "in_progress", now, now, "PENDING_START"),
    )
    # 动态选题（02-02，SC-1）：创建时不预选——每次 action=next 由
    # select_next_question 即时选题实例化；此处只落会话 + SESSION_CREATED 事件
    # 状态迁移留痕：与 INSERT 会话同一事务（SSOT §13.1 快照与事件同事务）
    append_event(conn, session_id=session_id, event_type="SESSION_CREATED",
                 from_state=None, to_state="in_progress",
                 actor_type="candidate", actor_id=user["user_id"])
    conn.commit()
    # estimated_duration_minutes 由 SESSION_TOTAL_MINUTES 派生（IN-06 魔数 20 退役——A5 前端无消费）
    return {"session_id": session_id,
            "estimated_duration_minutes": _config.SESSION_TOTAL_MINUTES}


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
    if cur is None and s["status"] == "in_progress" and s.get("phase") in (None, "ACTIVE"):
        # 动态派发（02-02）：无未答实例且会话进行中 → select_next_question 派发新实例
        # phase 门（03-05 Pitfall 12）：PENDING_START 不派发不计时（入场确认前置）；
        # PAUSED 不派发（暂停窗口不激活新题）。legacy/直插行 phase=NULL 兼容放行
        # （phase in (None, "ACTIVE")——旧行为保持）。data/app.db 存量 in_progress 会话
        # 处置：兼容口径下经 03-04 迁移回填 PENDING_START 会被此门拦截——处置已裁决
        # [03-012] 重跑演示脚本重建会话（本计划不做数据操作）。
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
    # WR-02：例外计数与 selection 层同口径（_exception_granted_items 单源——
    # selection_reason 解析失败时事件兜底，分母与实发题数不漂移）
    if s["status"] == "completed":
        total = answered
    else:
        exceptions = len(exception_granted_items(conn, session_id))
        total = _config.ORDINARY_PLAN_N + exceptions
    # open_form：rendered 实例存在时返回渲染白名单（FormCard 刷新恢复表单），否则 None
    open_form = None
    of = conn.execute(
        "SELECT schema_snapshot FROM form_instance"
        " WHERE session_id=? AND status='rendered' ORDER BY revision DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if of is not None:
        open_form = whitelist_form(json.loads(of["schema_snapshot"]))
    return {
        "session_id": s["session_id"],
        "status": s["status"],
        "phase": s.get("phase"),
        "position_id": s["position_id"],
        "model_version": s["model_version"],
        "current_question": dict(cur) if cur else None,
        "answered_count": answered,
        "total_count": total,
        "open_form": open_form,
    }


@router.post("/sessions/{session_id}/start")
def start_session(session_id: str, user: dict = Depends(require_login)) -> dict:
    """入场确认 start 端点（03-05，REF-2.6/A6/SC-5 起算锚——SSOT §12.1/§15）。

    phase PENDING_START→ACTIVE 三动作同事务（§13.1 快照与事件同事务）：
    UPDATE phase + 开第一个 active 区间（§15「确认开始且首题激活起算」——区间起算
    此处，首题激活在 get_session 派发，两者 <=1 请求间隔设计裁量可接受）+ SESSION_STARTED
    事件。首题不在本端点派发（A6 裁量「前者简单」）——前端 Chat.vue load() → get_session
    由 phase 门自然派发。A6 已裁决（[03-010]）：web 零改动约束下前端「开始测评」按钮
    接线延后 Phase 6 E2E，本端点契约由测试覆盖。无 body 无 Pydantic（D-46 只覆盖有
    body 的端点——GET/start/pause 均无 body）。
    """
    conn = get_conn()
    s = load_owned_session(conn, session_id, user)
    if s["status"] != "in_progress":
        # WR-01：409 detail 统一为 {error_code, message} 结构（与 readiness 三态一致）
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_NOT_IN_PROGRESS",
                                    "message": f"会话已结束（{s['status']}）"})
    if s["phase"] == "ACTIVE":
        # 幂等语义（WR-01 三态）：重复 start 不重复开区间
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_ALREADY_ACTIVE",
                                    "message": "会话已处于进行中"})
    # 三动作同事务（§13.1）
    conn.execute("UPDATE assessment_session SET phase='ACTIVE' WHERE session_id=?", (session_id,))
    open_interval(conn, session_id, "active")
    append_event(conn, session_id=session_id, event_type="SESSION_STARTED",
                 from_state="PENDING_START", to_state="ACTIVE",
                 actor_type="candidate", actor_id=user["user_id"])
    conn.commit()
    return {"session_id": session_id, "phase": "ACTIVE", "started": True}


@router.post("/sessions/{session_id}/pause")
def pause_session(session_id: str, user: dict = Depends(require_login)) -> dict:
    """候选人显式暂停（03-05，D-40 四源区分——候选人端点本期交付，reason='candidate_request' 固定）。

    技术/无障碍/管理暂停的区间写入能力由 timer.py open_interval(reason=...) 已支持
    （D-40「同一区间类型 reason 区分」），但专属触发端点属人工运维面不在本期交付
    （W6 交付口径——数据面就位，端点面分批）。无 body 无 Pydantic（D-46）。
    """
    conn = get_conn()
    s = load_owned_session(conn, session_id, user)
    if s["status"] != "in_progress":
        # WR-01：409 detail 统一为 {error_code, message} 结构
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_NOT_IN_PROGRESS",
                                    "message": f"会话已结束（{s['status']}）"})
    # 已有 open paused 区间 → 409 SESSION_ALREADY_PAUSED（重复 pause 幂等护栏，T-03-28）
    if conn.execute(
        "SELECT 1 FROM session_time_intervals"
        " WHERE session_id=? AND interval_type='paused' AND ended_at IS NULL",
        (session_id,),
    ).fetchone() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_ALREADY_PAUSED",
                                    "message": "会话已暂停"})
    # phase 门（WR-06）：PENDING_START 会话未经 start 不得暂停——绕过入场确认会
    # 跳过 SESSION_STARTED 事件与 PENDING_START→ACTIVE 迁移
    if s.get("phase") != "ACTIVE":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_NOT_ACTIVE",
                                    "message": "会话尚未开始，不可暂停"})
    # 闭合当前 active → 开 paused 区间 + phase='PAUSED' + 双事件同事务
    close_open_interval(conn, session_id)
    open_interval(conn, session_id, "paused", reason="candidate_request")
    append_event(conn, session_id=session_id, event_type="SESSION_PAUSE_REQUESTED",
                 actor_type="candidate", actor_id=user["user_id"])
    append_event(conn, session_id=session_id, event_type="SESSION_PAUSED",
                 from_state="ACTIVE", to_state="PAUSED",
                 actor_type="candidate", actor_id=user["user_id"])
    conn.execute("UPDATE assessment_session SET phase='PAUSED' WHERE session_id=?", (session_id,))
    conn.commit()
    return {"session_id": session_id, "phase": "PAUSED", "paused": True}


@router.post("/sessions/{session_id}/resume")
def resume_session(session_id: str, user: dict = Depends(require_login)) -> dict:
    """候选人恢复会话（03-05，D-40 恢复计时——闭合 paused 区间 + 开 active 区间 reason='resumed'）。

    无 open paused 区间 → 409 SESSION_NOT_PAUSED（T-03-28 幂等护栏：无条件 resume 拒）。
    无 body 无 Pydantic（D-46）。
    """
    conn = get_conn()
    s = load_owned_session(conn, session_id, user)
    if s["status"] != "in_progress":
        # WR-01：409 detail 统一为 {error_code, message} 结构
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_NOT_IN_PROGRESS",
                                    "message": f"会话已结束（{s['status']}）"})
    # phase 门（WR-06）：仅在 PAUSED 态允许 resume——防止 PENDING_START 会话被
    # pause-resume 直接升到 ACTIVE 而绕过 SESSION_STARTED 事件
    if s.get("phase") != "PAUSED":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_NOT_PAUSED",
                                    "message": "会话未暂停"})
    # 无 open paused 区间 → 409 SESSION_NOT_PAUSED
    if conn.execute(
        "SELECT 1 FROM session_time_intervals"
        " WHERE session_id=? AND interval_type='paused' AND ended_at IS NULL",
        (session_id,),
    ).fetchone() is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_NOT_PAUSED",
                                    "message": "会话未暂停"})
    # 闭合 paused → 开 active（恢复计时）+ phase='ACTIVE' + SESSION_RESUMED 事件同事务
    close_open_interval(conn, session_id)
    open_interval(conn, session_id, "active", reason="resumed")
    append_event(conn, session_id=session_id, event_type="SESSION_RESUMED",
                 from_state="PAUSED", to_state="ACTIVE",
                 actor_type="candidate", actor_id=user["user_id"])
    conn.execute("UPDATE assessment_session SET phase='ACTIVE' WHERE session_id=?", (session_id,))
    conn.commit()
    return {"session_id": session_id, "phase": "ACTIVE", "resumed": True}


def _sse_event(payload: dict) -> str:
    """单条 SSE 帧：`data: {json}\n\n`（sse.js:69-71 逐字段对齐——
    只解析 'data: ' 前缀行 + JSON.parse；ensure_ascii=False 保中文原样）。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _event_stream(decision: dict, action: str, question_id: str,
                  next_question_id: str | None) -> Iterator[str]:
    """SSE 事件序列（SSOT §11.5/D-33/D-34）：decision → reply×N → done。

    generator 内零 DB 连接（Pitfall 1——threadpool worker 持连接至流结束会
    database is locked）；「先落库再推流」：本函数只消费局部变量，全部持久化
    动作在调用方返回 StreamingResponse 前完成。decision dict 一律 .get 防
    MODEL_UNCERTAIN 降级 dict 缺键面。question_id 仅为调用方快照完整性的
    形参（帧内不出题号——前端按会话流上下文定位）。
    """
    # ① decision（sse.js onDecision 消费 action/reason/score_live + 扩展键透传 D-34）
    yield _sse_event({"type": "decision",
                      "action": action, "reason": decision.get("reason"),
                      "score_live": decision.get("score_live"),
                      "answer_state": decision.get("answer_state"),
                      "evidence_sufficient": decision.get("evidence_sufficient"),
                      "reply": decision.get("reply")})
    # ② reply 逐块（sse.js onReply 消费 data.content 逐块拼接；mock 4 块假流）
    reply = decision.get("reply") or ""
    if _config.LLM_PROVIDER == "mock":
        size = max(1, math.ceil(len(reply) / 4))
        chunks = [reply[i:i + size] for i in range(0, len(reply), size)]
    else:
        chunks = [reply]  # 真实模式：决策已含完整话术（02-04 reply_suggestion）——单块推送
    for chunk in chunks:
        yield _sse_event({"type": "reply", "content": chunk})
    # ③ done（sse.js onDone 消费 next_question_id + action——finish/form 时 None）
    yield _sse_event({"type": "done", "action": action,
                      "next_question_id": next_question_id})


def _answer_snapshot(action: str, decision: dict, question_id: str,
                     next_question_id: str | None) -> dict:
    """幂等响应快照 = 决策结果 dict（SSOT §13.4/Pitfall 5——白名单键，不含候选人输入原文——A1）。

    键集合 ⊆ {action, reply, question_id, next_question_id, score_live, answer_state,
    evidence_sufficient}——重复请求 200 application/json 直返（sse.js 形态 B 消费）。
    reply 取 .get or "" 与 _event_stream 重装语义对齐（防 MODEL_UNCERTAIN 降级缺键面）。
    """
    return {"action": action, "reply": decision.get("reply") or "",
            "question_id": question_id, "next_question_id": next_question_id,
            "score_live": decision.get("score_live"),
            "answer_state": decision.get("answer_state"),
            "evidence_sufficient": decision.get("evidence_sufficient")}


def _render_form_branch(conn, session_id: str, question_id: str, decision: dict) -> StreamingResponse:
    """池耗尽且 gate 未采集（D-30）→ 渲染表单 + assistant 消息（📎[form:id] 标记）+ commit。

    Chat.vue:159-160 extractFormId 正则 `/📎\[form:([^\]]+)\]/` 逐字对齐；表单无决策推进，
    next_question_id=None（前端据 action='form' 渲染表单，不再 GET current_question）。
    """
    fi = render_form_instance(conn, session_id)
    # reply 与 assistant 消息 content 同串：前端 Chat.vue extractFormId 从消息/响应 reply
    # 提取 📎[form:id] 标记（决策 reply + 表单提示，逐字对齐正则 /📎\[form:([^\]]+)\]/）
    reply = decision["reply"] + f" 请先填写资格核验表单 📎[form:{fi['form_instance_id']}]"
    conn.execute(
        "INSERT INTO assessment_message(message_id, session_id, question_id, role, content,"
        " action, created_at) VALUES(?,?,?,?,?,?,?)",
        (new_id("msg"), session_id, question_id, "assistant", reply, "form", now_iso()),
    )
    conn.commit()
    # decision 帧 action='form'（sse.js 对 action 无白名单直通）；reply 含 📎[form:id] 标记
    stream_decision = {**decision, "reply": reply}
    return StreamingResponse(
        _event_stream(stream_decision, "form", question_id, None),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/answer")
def submit_answer(session_id: str, body: AnswerRequest, user: dict = Depends(require_login)) -> StreamingResponse:
    """提交回答：精炼落库 → interview 决策 → 落 assistant 消息 → 推进题目/会话状态。

    响应为 SSE 流（decision → reply×N → done——先落库再推流，SSOT §11.5/D-33）。
    """
    question_id = body.question_id
    answer = body.answer  # 已 strip（AnswerRequest validator——WR-02 strip 后判空语义）
    # WR-07：输入长度上限对齐评分侧 MAX_ANSWER_LEN=64*1024（同口径单源）——
    # 超大 payload 直达精炼/LLM 会撑爆上下文且撞 CR-01 降级面，输入侧统一 422
    if len(answer) > MAX_ANSWER_LEN:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"回答过长（>{MAX_ANSWER_LEN} 字符），请精简后提交")

    conn = get_conn()
    s = load_owned_session(conn, session_id, user)
    # (1) 6h 惰性 ABANDONED 判定（03-04 A4 时序——load 后、判 status 前；D-42 无后台线程）
    maybe_abandon_session(conn, s)
    # 幂等前置（D-36 可选——无 key 零路径；A4 时序：幂等最先，先于单题超时点检 03-04 后插）：
    # 命中 COMMITTED 且 hash 一致 → 200 JSON 快照直返（不进 SSE 链）；异 hash/PENDING 由
    # check_idempotency 内 409 抛出（endpoint 层不重复判）
    if body.idempotency_key:
        snap = check_idempotency(
            conn, session_id=session_id, endpoint="answer", key=body.idempotency_key,
            request_hash=request_hash_of(body.model_dump(), {
                "question_instance_id": question_id,
                "expected_question_revision": body.expected_revision,
                "client_attempt_id": body.client_attempt_id}))
        if snap is not None:
            return JSONResponse(content=snap, status_code=200)
    if s["status"] != "in_progress":
        # write-then-raise（maybe_abandon 的 UPDATE 未 commit——先落再抛持久化 abandoned）
        conn.commit()
        # WR-01：409 detail 统一为 {error_code, message} 结构（与 readiness 三态一致）
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_NOT_IN_PROGRESS",
                                    "message": f"会话已结束（{s['status']}）"})
    # (2) 暂停护栏（03-04 A4 时序——暂停窗口内所有写操作被拒）：open paused 区间存在 → 409
    if conn.execute(
        "SELECT 1 FROM session_time_intervals"
        " WHERE session_id=? AND interval_type='paused' AND ended_at IS NULL",
        (session_id,),
    ).fetchone() is not None:
        conn.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_PAUSED",
                                    "message": "会话已暂停，请先恢复"})
    q = conn.execute(
        "SELECT question_id, answered_at FROM assessment_question WHERE question_id=? AND session_id=?",
        (question_id, session_id),
    ).fetchone()
    if q is None:
        conn.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "题目不属于该会话")
    if q["answered_at"] is not None:
        # WR-01：409 detail 统一为 {error_code, message} 结构（与 readiness 三态一致）
        conn.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "QUESTION_ALREADY_ANSWERED",
                                    "message": "该题已作答"})

    # (3)/(5) 单题超时点检 → 全场超时点检（03-04 A4 时序——消息 INSERT 前）
    if seal_if_question_timed_out(conn, session_id, question_id, user["user_id"]):
        # 本请求不决策不写消息，转「选下一题」路径（timer 内已落 QUESTION_SEALED + QUESTION_TIMEOUT）
        conn.commit()  # 持久化 timeout 封存（closed_at+seal_reason，answered_at 保持 NULL）
        timeout_decision = {
            "action": "next",
            "reason": "本题超时封存",
            "reply": "本题已超时，进入下一题",
            "score_live": None,
            "answer_state": "QUESTION_TIMEOUT",
            "evidence_sufficient": False,
        }
        picked = select_next_question(session_id)
        if picked is None:
            # 池耗尽 → 先判 gate（03-01 gate 分支不动）→ form 或 finish
            if not _all_gate_items_collected(conn, session_id):
                if body.idempotency_key:
                    finalize_idempotency(session_id=session_id, endpoint="answer",
                                         key=body.idempotency_key,
                                         snapshot=_answer_snapshot("form", timeout_decision, question_id, None))
                return _render_form_branch(conn, session_id, question_id, timeout_decision)
            conn.execute(
                "UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
                (now_iso(), session_id),
            )
            append_event(conn, session_id=session_id, event_type="SESSION_COMPLETED",
                         from_state="in_progress", to_state="completed", actor_type="system")
            conn.commit()
            if body.idempotency_key:
                finalize_idempotency(session_id=session_id, endpoint="answer",
                                     key=body.idempotency_key,
                                     snapshot=_answer_snapshot("finish", timeout_decision, question_id, None))
            return StreamingResponse(
                _event_stream(timeout_decision, "finish", question_id, None),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        next_qid = picked["question_id"]
        if body.idempotency_key:
            finalize_idempotency(session_id=session_id, endpoint="answer",
                                 key=body.idempotency_key,
                                 snapshot=_answer_snapshot("next", timeout_decision, question_id, next_qid))
        return StreamingResponse(
            _event_stream(timeout_decision, "next", question_id, next_qid),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    # (5) 全场超时点检（Σactive > SESSION_TOTAL_MINUTES → 收尾；Pitfall 11 先因后果）
    if session_active_seconds(conn, session_id) > _config.SESSION_TOTAL_MINUTES * 60:
        # GLOBAL_TIMEOUT 独立小事务先落（Pitfall 11——sequence_no 顺序断言 GLOBAL_TIMEOUT 最先）
        append_event(conn, session_id=session_id, event_type="SESSION_GLOBAL_TIMEOUT",
                     from_state="ACTIVE", to_state="SCORING", actor_type="system")
        conn.execute("UPDATE assessment_session SET phase='SCORING' WHERE session_id=?", (session_id,))
        conn.commit()
        # 串行链（同步——D-005 单进程演示；_generate_report_task 纯函数入口，其内部
        # ENTERED_SCORING 事件自然靠后）
        _generate_report_task(session_id)
        # 正常收尾口径（phase 承载 SCORING 态，status 枚举无 SCORING——Anti-pattern 4）
        conn.execute(
            "UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
            (now_iso(), session_id),
        )
        append_event(conn, session_id=session_id, event_type="SESSION_COMPLETED",
                     from_state="in_progress", to_state="completed", actor_type="system")
        conn.commit()
        finish_decision = {
            "action": "finish",
            "reason": "全场超时收尾",
            "reply": "全场时间已到，测评收尾",
            "score_live": None,
            "answer_state": "QUESTION_TIMEOUT",
            "evidence_sufficient": False,
        }
        if body.idempotency_key:
            finalize_idempotency(session_id=session_id, endpoint="answer",
                                 key=body.idempotency_key,
                                 snapshot=_answer_snapshot("finish", finish_decision, question_id, None))
        return StreamingResponse(
            _event_stream(finish_decision, "finish", question_id, None),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    now = now_iso()
    # 乐观锁（D-37 可选——带 expected_revision 才走，无 key 零行为变化 A/B 兼容）：
    # UPDATE WHERE revision=? 原子判（rowcount==0 → 409——先 SELECT 后比对有 TOCTOU 窗口）
    if body.expected_revision is not None:
        cur = conn.execute(
            "UPDATE assessment_question SET revision=revision+1"
            " WHERE question_id=? AND revision=?",
            (question_id, body.expected_revision),
        )
        if cur.rowcount == 0:
            # UPDATE 已起写事务（RESERVED 锁）——write-then-raise 须先 rollback 释放锁，
            # 否则连接泄漏持锁 >5s，阻塞后续测试/请求的写库（SQLite 单写者）
            conn.rollback()
            # WR-01：409 detail 统一为 {error_code, message} 结构
            raise HTTPException(status.HTTP_409_CONFLICT,
                                detail={"error_code": "QUESTION_REVISION_CONFLICT",
                                        "message": f"题目版本冲突（expected={body.expected_revision}）"})
    # 1. 用户消息（长输入走精炼，原文哈希归档；分列三列 D-43：refined=content 同值、
    # client_request_id=body 键、sequence_no=本会话消息序）
    refined, raw_hash = refine_user_input(answer)
    user_seq = conn.execute(
        "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM assessment_message WHERE session_id=?",
        (session_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO assessment_message(message_id, session_id, question_id, role, content, raw_hash,"
        " refined_content, client_request_id, sequence_no, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (new_id("msg"), session_id, question_id, "user", refined, raw_hash,
         refined, body.client_attempt_id, user_seq, now),
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

    # 3. assistant 消息落库（action/reason/score_live 先于展示，可审计；sequence_no 同步补——D-43）
    assistant_seq = conn.execute(
        "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM assessment_message WHERE session_id=?",
        (session_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO assessment_message(message_id, session_id, question_id, role, content,"
        " action, reason, score_live, score_live_reason, sequence_no, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("msg"), session_id, question_id, "assistant", decision["reply"],
         _out_action, decision["reason"], decision["score_live"],
         decision["score_live_reason"], assistant_seq, now_iso()),
    )

    # 观察留痕（§13.2 最小集——T-02-18）：每次决策后落 OBSERVATION_CLASSIFIED
    append_event(conn, session_id=session_id, event_type="OBSERVATION_CLASSIFIED",
                 actor_type="system", assessment_question_id=question_id,
                 payload={"answer_state": decision["answer_state"],
                          "evidence_sufficient": decision["evidence_sufficient"],
                          "action": _out_action})

    # 注入留痕（03-05，D-45/REF-6.4）：answer_state 分类驱动，与 OBSERVATION_CLASSIFIED
    # 同事务同 commit 锚。payload 白名单恰两键 {answer_state, stability}——不含输入原文
    # （T-03-25：注入面证据不变成泄露面）。
    if decision.get("answer_state") == "PROMPT_INJECTION":
        append_event(conn, session_id=session_id, event_type="INJECTION_DETECTED",
                     actor_type="system", assessment_question_id=question_id,
                     payload={"answer_state": "PROMPT_INJECTION",
                              "stability": bool(decision.get("evidence_sufficient"))})

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
        # (4) 计时采样（D-39/D-42）：闭旧开新 + 刷新 last_activity（主事务内）
        advance_interval(conn, session_id, "active")
        touch_last_activity(conn, session_id)
        conn.commit()
    else:
        # (4) 计时采样（D-39/D-42）：闭旧开新 + 刷新 last_activity（主事务内）
        advance_interval(conn, session_id, "active")
        touch_last_activity(conn, session_id)
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
            # 可选池耗尽（普通计划 + required 例外全完成）→ 先判 gate 全采集（D-30）：
            # 未采集走表单 render（📎[form:id] 标记），已采集才 finish 收尾
            if not _all_gate_items_collected(conn, session_id):
                if body.idempotency_key:
                    finalize_idempotency(session_id=session_id, endpoint="answer",
                                         key=body.idempotency_key,
                                         snapshot=_answer_snapshot("form", decision, question_id, None))
                return _render_form_branch(conn, session_id, question_id, decision)
            conn.execute(
                "UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
                (now_iso(), session_id),
            )
            append_event(conn, session_id=session_id, event_type="SESSION_COMPLETED",
                         from_state="in_progress", to_state="completed", actor_type="system")
            conn.commit()
            if body.idempotency_key:
                finalize_idempotency(session_id=session_id, endpoint="answer",
                                     key=body.idempotency_key,
                                     snapshot=_answer_snapshot("finish", decision, question_id, None))
            return StreamingResponse(
                _event_stream(decision, "finish", question_id, None),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        if picked.get("legacy"):
            # legacy 会话（Q5）：旧预选行按 seq 继续派发——走旧查询，不进四层；
            # 旧行为语义保持：决策 next/finish 按原样透出（旧行耗尽时如上提前 return）
            nxt = conn.execute(
                "SELECT question_id FROM assessment_question"
                " WHERE session_id=? AND answered_at IS NULL ORDER BY seq LIMIT 1",
                (session_id,),
            ).fetchone()
            if nxt is None:
                # legacy 会话同样先判 gate 全采集（D-30 两处对称插入）
                if not _all_gate_items_collected(conn, session_id):
                    if body.idempotency_key:
                        finalize_idempotency(session_id=session_id, endpoint="answer",
                                             key=body.idempotency_key,
                                             snapshot=_answer_snapshot("form", decision, question_id, None))
                    return _render_form_branch(conn, session_id, question_id, decision)
                conn.execute(
                    "UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
                    (now_iso(), session_id),
                )
                append_event(conn, session_id=session_id, event_type="SESSION_COMPLETED",
                             from_state="in_progress", to_state="completed", actor_type="system")
                conn.commit()
                if body.idempotency_key:
                    finalize_idempotency(session_id=session_id, endpoint="answer",
                                         key=body.idempotency_key,
                                         snapshot=_answer_snapshot("finish", decision, question_id, None))
                return StreamingResponse(
                    _event_stream(decision, "finish", question_id, None),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
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
    # 幂等收尾（尾段——终态 commit 后、return 前）：全部持久化完成 → UPDATE COMMITTED + 快照
    if body.idempotency_key:
        finalize_idempotency(session_id=session_id, endpoint="answer",
                             key=body.idempotency_key,
                             snapshot=_answer_snapshot(action, decision, question_id, next_question_id))
    return StreamingResponse(
        _event_stream(decision, action, question_id, next_question_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


@router.get("/forms/{form_instance_id}")
def get_form(form_instance_id: str, user: dict = Depends(require_login)) -> dict:
    """GET 表单渲染白名单（只读：form_type/title/fields——years 门槛值/required_level 不出）。

    双 404：instance 不存在 / 非 owner（session 归属经 form_instance.session_id 反查
    load_owned_session——D-01 统一不存在语义）。URL 不带 /sessions 前缀（api/index.js:46）。
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT session_id, schema_snapshot FROM form_instance WHERE form_instance_id=?",
        (form_instance_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "表单不存在")
    load_owned_session(conn, row["session_id"], user)
    return whitelist_form(json.loads(row["schema_snapshot"]))


@router.post("/sessions/{session_id}/forms/submit-v2")
def submit_form_v2(session_id: str, body: FormSubmitRequest,
                   user: dict = Depends(require_login)) -> dict:
    """表单提交（六维校验 + gate 行 + finish/next 触发器——gate 采集链终局闭合）。

    提交成功即 gate 全采集；触发器 B1：池未空 → action='next'（带下一题 id），
    池耗尽 → 复用主链 finish 三步（无 assistant 消息——表单提交无决策 reply）。
    幂等（D-36 可选）：命中 COMMITTED 且 hash 一致 → 200 快照直返（不进六维——状态维
    FORM_ALREADY_SUBMITTED 不触发）。
    """
    conn = get_conn()
    load_owned_session(conn, session_id, user)
    # 幂等前置（endpoint='form_submit'——与 answer 三键隔离）：命中且 hash 一致 → 快照 200 直返
    if body.idempotency_key:
        snap = check_idempotency(conn, session_id=session_id, endpoint="form_submit",
                                 key=body.idempotency_key,
                                 request_hash=request_hash_of(body.model_dump()))
        if snap is not None:
            return JSONResponse(content=snap, status_code=200)
    result = validate_and_submit(
        conn, session_id=session_id, form_instance_id=body.form_instance_id,
        payload=body.payload, expected_revision=body.expected_revision, user=user,
    )
    if not result["ok"]:
        conn.rollback()
        code = result["error_code"]
        if code == "FORM_NOT_FOUND":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "表单不存在")
        if code in ("FORM_ALREADY_SUBMITTED", "FORM_INSTANCE_REVISION_CONFLICT"):
            detail = {"error_code": code, "message": code}
            if code == "FORM_ALREADY_SUBMITTED":
                # 重复提交幂等语义：首次结果行 payload_json 原样带回
                detail["payload"] = result["payload"]
            raise HTTPException(status.HTTP_409_CONFLICT, detail=detail)
        # ④⑤⑥ 422 三态 error_code
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"error_code": code, "field": result["field"]})
    # (8) 计时采样：表单提交也是写操作（D-39/D-42——闭旧开新 + 刷新 last_activity）
    advance_interval(conn, session_id, "active")
    touch_last_activity(conn, session_id)
    conn.commit()

    base = {"form_instance_id": body.form_instance_id, "status": result["status"],
            "gate_results": result["gate_results"]}
    if _all_gate_items_collected(conn, session_id):
        nxt = select_next_question(session_id)
        # legacy 标记 dict 无 question_id → 视作无下一题（legacy 会话渲染表单时旧题已答完）
        next_id = (nxt or {}).get("question_id")
        if next_id is None:
            # 复用主链 finish 段语义（UPDATE status + SESSION_COMPLETED + commit）
            conn.execute(
                "UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
                (now_iso(), session_id),
            )
            append_event(conn, session_id=session_id, event_type="SESSION_COMPLETED",
                         from_state="in_progress", to_state="completed", actor_type="system")
            conn.commit()
            out = {**base, "action": "finish", "next_question_id": None}
        else:
            out = {**base, "action": "next", "next_question_id": next_id}
    else:
        # 提交成功即 gate 全采集，理论上不达此分支；防御性回 form（状态维由 validate 兜底）
        out = {**base, "action": "form", "next_question_id": None}
    # 幂等收尾：validate_and_submit 的 commit 后 → COMMITTED 快照（= 首次返回体）
    if body.idempotency_key:
        finalize_idempotency(session_id=session_id, endpoint="form_submit",
                             key=body.idempotency_key, snapshot=out)
    return out


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
