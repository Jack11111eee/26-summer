"""测评端 API（P5）：可测评岗位列表 + 测评会话/答题/表单/打分/报告（模块二 M5 + 模块三 M6）。"""
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from ..core.security import load_owned_report, load_owned_session, require_login
from ..db import get_conn
from ..services.interview import decide_next_action
from ..services.pipeline import new_id, now_iso
from ..services.question_selection import select_questions_for_session
from ..services.readiness import check_session_readiness
from ..services.refine import refine_user_input
from ..services.report import generate_report
from ..services.scoring import score_session
from ..services.state_events import append_event

router = APIRouter(prefix="/api/assessment", tags=["assessment"], dependencies=[Depends(require_login)])


@router.get("/positions")
def list_assessable_positions() -> list[dict]:
    """可测评岗位：active 且存在 confirmed 模型（附版本号与能力项数）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT p.position_id, p.name, m.version, m.model_id,"
        " json_array_length(json_extract(m.model_json,'$.items')) AS item_count"
        " FROM position p"
        " JOIN competency_model m ON m.position_id=p.position_id"
        " WHERE p.status='active' AND m.status='confirmed'"
        " ORDER BY m.version DESC"
    ).fetchall()
    # 同一岗位只展示最新 confirmed 版
    seen = set()
    out = []
    for r in rows:
        if r["position_id"] in seen:
            continue
        seen.add(r["position_id"])
        out.append(dict(r))
    return out


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
    """创建测评会话：锚定 confirmed 模型最新版 + 从题库选题落 assessment_question。

    选题走 services.question_selection（07 §6.3 代码执行可审计）。
    """
    position_id = body.get("position_id")
    if not position_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "缺少 position_id")
    conn = get_conn()
    model = conn.execute(
        "SELECT model_id, version, model_json FROM competency_model"
        " WHERE position_id=? AND status='confirmed' ORDER BY version DESC LIMIT 1",
        (position_id,),
    ).fetchone()
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
    questions = select_questions_for_session(position_id, json.loads(model["model_json"]))
    for i, q in enumerate(questions, start=1):
        conn.execute(
            "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq, created_at)"
            " VALUES(?,?,?,?,?)",
            (new_id("aq"), session_id, q["question_id"], i, now),
        )
    # 状态迁移留痕：与 INSERT 会话同一事务（SSOT §13.1 快照与事件同事务）
    append_event(conn, session_id=session_id, event_type="SESSION_CREATED",
                 from_state=None, to_state="in_progress",
                 actor_type="candidate", actor_id=user["user_id"])
    conn.commit()
    return {"session_id": session_id, "question_count": len(questions),
            "estimated_duration_minutes": 20}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, user: dict = Depends(require_login)) -> dict:
    """会话状态：当前题 = 第一个未作答（answered_at IS NULL）的题。"""
    conn = get_conn()
    s = load_owned_session(conn, session_id, user, allow_admin_read=True)
    total = conn.execute(
        "SELECT COUNT(*) c FROM assessment_question WHERE session_id=?", (session_id,)
    ).fetchone()["c"]
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

    # 2. 面试决策
    decision = decide_next_action(session_id, question_id, refined)

    # 3. assistant 消息落库（action/reason/score_live 先于展示，可审计）
    conn.execute(
        "INSERT INTO assessment_message(message_id, session_id, question_id, role, content,"
        " action, reason, score_live, score_live_reason, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (new_id("msg"), session_id, question_id, "assistant", decision["reply"],
         decision["action"], decision["reason"], decision["score_live"],
         decision["score_live_reason"], now_iso()),
    )

    # 4. 推进题目/会话状态（事件行与快照 UPDATE 同事务，随下述最终 commit 落库）
    next_question_id = None
    if decision["action"] in ("next", "finish"):
        conn.execute(
            "UPDATE assessment_question SET answered_at=? WHERE question_id=?",
            (now_iso(), question_id),
        )
        append_event(conn, session_id=session_id, event_type="QUESTION_ANSWERED",
                     from_state="active", to_state="answered",
                     actor_type="candidate", actor_id=user["user_id"],
                     assessment_question_id=question_id)
    if decision["action"] == "finish":
        conn.execute(
            "UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
            (now_iso(), session_id),
        )
        append_event(conn, session_id=session_id, event_type="SESSION_COMPLETED",
                     from_state="in_progress", to_state="completed", actor_type="system")
    else:
        nxt = conn.execute(
            "SELECT question_id FROM assessment_question"
            " WHERE session_id=? AND answered_at IS NULL ORDER BY seq LIMIT 1",
            (session_id,),
        ).fetchone()
        next_question_id = nxt["question_id"] if nxt else None
    conn.commit()

    return {"action": decision["action"], "reply": decision["reply"],
            "question_id": question_id, "next_question_id": next_question_id,
            "score_live": decision["score_live"]}


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
