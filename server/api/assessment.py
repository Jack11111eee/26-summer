"""测评端 API（P5）：可测评岗位列表 + 测评会话/答题/表单/打分/报告（模块二 M5 + 模块三 M6）。"""
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from ..core.security import require_login
from ..db import get_conn
from ..services.interview import decide_next_action
from ..services.pipeline import new_id, now_iso
from ..services.refine import refine_user_input
from ..services.report import generate_report
from ..services.scoring import score_session

router = APIRouter(prefix="/api/assessment", tags=["assessment"], dependencies=[Depends(require_login)])

# 选题配额（07 文档 §6.2）：hard 6~7 / soft 2~3 / experience 2 / qualification 走表单不占题
_CATEGORY_QUOTA = {"hard_skill": 6, "soft_skill": 2, "experience": 2}
_TOTAL_MAX = 12
_DIFFICULTY_ORDER = {"easy": 0, "medium": 1, "hard": 2, None: 0}


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
    row = conn.execute(
        "SELECT model_id, version, model_json FROM competency_model"
        " WHERE position_id=? AND status='confirmed' ORDER BY version DESC LIMIT 1",
        (position_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该岗位暂无已确认模型")
    d = dict(row)
    d["model"] = json.loads(d.pop("model_json"))
    return d


# ---------- 选题（07 §6.3，代码执行可审计） ----------

def _select_questions(position_id: str, model_id: str) -> list[dict]:
    """从题库选题：岗位题 + 通用题，按类目配额，required 优先，难度递进，沿 chain 排序。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM question_bank WHERE status='active'"
        " AND ((scope='position' AND position_id=?) OR scope='general')",
        (position_id,),
    ).fetchall()
    bank = [dict(r) for r in rows]
    if not bank:
        return []

    # required 项（该模型内 importance='required' 的 std_name 集合）优先
    req_rows = conn.execute(
        "SELECT std_name, importance, weight FROM competency_item WHERE model_id=?",
        (model_id,),
    ).fetchall()
    importance = {r["std_name"]: r["importance"] for r in req_rows}
    weight = {r["std_name"]: r["weight"] or 0 for r in req_rows}

    by_cat: dict[str, list[dict]] = {}
    for q in bank:
        by_cat.setdefault(q["category"], []).append(q)

    def _sort_key(q: dict):
        imp_rank = {"required": 0, "preferred": 1, "plus": 2}.get(importance.get(q["std_name"]), 3)
        return (imp_rank, -weight.get(q["std_name"], 0),
                q.get("chain_key") or "", q.get("chain_seq") or 0,
                _DIFFICULTY_ORDER.get(q.get("difficulty"), 0))

    picked: list[dict] = []
    for cat, quota in _CATEGORY_QUOTA.items():
        candidates = sorted(by_cat.get(cat, []), key=_sort_key)
        picked.extend(candidates[:quota])
    return picked[:_TOTAL_MAX]


# ---------- 会话 ----------

@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(body: dict, user: dict = Depends(require_login)) -> dict:
    """创建测评会话：锚定 confirmed 模型最新版 + 从题库选题落 assessment_question。"""
    position_id = body.get("position_id")
    if not position_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "缺少 position_id")
    conn = get_conn()
    model = conn.execute(
        "SELECT model_id, version FROM competency_model"
        " WHERE position_id=? AND status='confirmed' ORDER BY version DESC LIMIT 1",
        (position_id,),
    ).fetchone()
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该岗位暂无已确认模型，无法开考")

    session_id = new_id("sess")
    now = now_iso()
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (session_id, user["user_id"], position_id, model["model_id"], model["version"],
         "in_progress", now, now),
    )
    questions = _select_questions(position_id, model["model_id"])
    for i, q in enumerate(questions, start=1):
        conn.execute(
            "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq, created_at)"
            " VALUES(?,?,?,?,?)",
            (new_id("aq"), session_id, q["question_id"], i, now),
        )
    conn.commit()
    return {"session_id": session_id, "question_count": len(questions),
            "estimated_duration_minutes": 20}


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    """会话状态：当前题 = 第一个未作答（answered_at IS NULL）的题。"""
    conn = get_conn()
    s = conn.execute(
        "SELECT session_id, status, position_id, model_version FROM assessment_session"
        " WHERE session_id=?",
        (session_id,),
    ).fetchone()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
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
        **dict(s),
        "current_question": dict(cur) if cur else None,
        "answered_count": answered,
        "total_count": total,
    }


@router.post("/sessions/{session_id}/answer")
def submit_answer(session_id: str, body: dict) -> dict:
    """提交回答：精炼落库 → interview 决策 → 落 assistant 消息 → 推进题目/会话状态。"""
    question_id = body.get("question_id")
    answer = body.get("answer", "")
    if not question_id or not answer:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "缺少 question_id 或 answer")

    conn = get_conn()
    s = conn.execute(
        "SELECT status FROM assessment_session WHERE session_id=?", (session_id,)
    ).fetchone()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    if s["status"] != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, f"会话已结束（{s['status']}）")
    q = conn.execute(
        "SELECT question_id, answered_at FROM assessment_question WHERE question_id=? AND session_id=?",
        (question_id, session_id),
    ).fetchone()
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "题目不属于该会话")
    if q["answered_at"] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该题已作答")

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

    # 4. 推进题目/会话状态
    next_question_id = None
    if decision["action"] in ("next", "finish"):
        conn.execute(
            "UPDATE assessment_question SET answered_at=? WHERE question_id=?",
            (now_iso(), question_id),
        )
    if decision["action"] == "finish":
        conn.execute(
            "UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
            (now_iso(), session_id),
        )
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
    s = conn.execute(
        "SELECT 1 FROM assessment_session WHERE session_id=?", (session_id,)
    ).fetchone()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
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
def score_session_endpoint(session_id: str) -> dict:
    """终局打分：会话内所有已答题逐题评分，落 question_score。"""
    conn = get_conn()
    s = conn.execute(
        "SELECT status FROM assessment_session WHERE session_id=?", (session_id,)
    ).fetchone()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    total = conn.execute(
        "SELECT COUNT(*) c FROM assessment_question WHERE session_id=?", (session_id,)
    ).fetchone()["c"]
    result = score_session(session_id)
    return {**result, "total_questions": total}


# ---------- 报告（07 §10.5，异步生成 + 轮询） ----------

def _generate_report_task(session_id: str) -> None:
    """后台任务：生成报告。异常静默（前端轮询 report 表为空即判失败/未完成）。"""
    try:
        generate_report(session_id)
    except Exception:  # noqa: BLE001
        pass


@router.post("/sessions/{session_id}/report", status_code=status.HTTP_202_ACCEPTED)
def request_report(session_id: str, background: BackgroundTasks) -> dict:
    """触发报告生成（异步，前端轮询 GET /reports?session_id= 获取结果）。"""
    conn = get_conn()
    s = conn.execute(
        "SELECT status FROM assessment_session WHERE session_id=?", (session_id,)
    ).fetchone()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    background.add_task(_generate_report_task, session_id)
    return {"session_id": session_id, "status": "generating"}


@router.get("/reports/by-session/{session_id}")
def get_report_by_session(session_id: str) -> dict:
    """按会话取最新报告（前端轮询入口）。未生成 → 404。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT report_json FROM report WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告尚未生成")
    return json.loads(row["report_json"])


@router.get("/reports/{report_id}")
def get_report(report_id: str) -> dict:
    """按 report_id 取报告完整 JSON。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT report_json FROM report WHERE report_id=?", (report_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    return json.loads(row["report_json"])


@router.post("/reports/{report_id}/feedback", status_code=status.HTTP_201_CREATED)
def submit_feedback(report_id: str, body: dict) -> dict:
    """候选人对某能力项评分提异议（07 §11 ② 反馈可回溯）。"""
    item_id = body.get("item_id")
    feedback_text = body.get("feedback_text", "").strip()
    if not item_id or not feedback_text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "缺少 item_id 或 feedback_text")
    conn = get_conn()
    r = conn.execute("SELECT 1 FROM report WHERE report_id=?", (report_id,)).fetchone()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    it = conn.execute("SELECT 1 FROM competency_item WHERE item_id=?", (item_id,)).fetchone()
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
