"""面试决策两层化（SSOT §11.3/§11.4，D-22——Phase 2 02-04 重构）。

观察层：call_llm_json 输出经 InterviewObservation（Pydantic 11 态白名单）校验；
  非法输出降级 answer_state=MODEL_UNCERTAIN 不卡死会话（§11.5）。
裁决层：classify_observation 纯函数计算证据充分性布尔，decide_action 纯函数
  按 §11.4 处理原则决定 action——LLM 不输出 action/难度/结束（REF-1.6/1.7）。

decide_next_action：基于会话历史 + 当前题 + 最新回答，返回
  {action: confirm|followup|next, reason, reply, score_live?, score_live_reason?,
   answer_state, evidence_sufficient[, refused]}
5 基础键契约保持（Pitfall 8——前端 sse.js 消费面零破坏，只加不减）。
finish 不再由本层触发（is_last 旧口径废除——02-02 起动态实例化下
「选题返回 None（池耗尽）」是 finish 唯一触发源，由 assessment.py 消费）。
"""
from pydantic import ValidationError

from .. import config
from ..db import get_conn
from ..schemas import InterviewObservation, ObservationDims
from .llm import call_llm_json
from .prompts.interviewer import INTERVIEWER_SYSTEM

MIN_ANSWER_CHARS = 20  # mock 规则：低于此长度视为需澄清

# mock 分类器词表（D-23——模块级元组惯例照 _VALID_ACTOR_TYPES）
_DECLINE_WORDS = ("不方便回答", "不想说", "隐私", "无可奉告", "拒绝回答")
_EVIDENCE_WORDS = ("项目", "举例", "具体", "结果", "数据", "负责")

# 拒答确认话术（§11.4 拒答处理原则——SUPPORT 控制类一次性确认，D-24）
_CONFIRM_REPLY = "可以不回答这道题吗？跳过后将不再回到该题。"


def _load_session_question(session_id: str, question_id: str) -> tuple[dict, dict, bool]:
    """返回 (session_row, question_row(join bank), is_last_question)。"""
    conn = get_conn()
    session = conn.execute(
        "SELECT s.*, p.name AS position_name FROM assessment_session s"
        " JOIN position p ON p.position_id=s.position_id WHERE s.session_id=?",
        (session_id,),
    ).fetchone()
    question = conn.execute(
        "SELECT aq.question_id, b.stem, b.category, b.qtype, b.difficulty, b.rubric"
        " FROM assessment_question aq JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE aq.question_id=?",
        (question_id,),
    ).fetchone()
    last = conn.execute(
        "SELECT COUNT(*) c FROM assessment_question"
        " WHERE session_id=? AND answered_at IS NULL AND question_id<>?",
        (session_id, question_id),
    ).fetchone()["c"] == 0
    return dict(session), dict(question), last


def _count_followups(session_id: str, question_id: str) -> int:
    """实例内追问计数（D-25 迁列：读 assessment_question.followup_count，单行）。"""
    conn = get_conn()
    return conn.execute(
        "SELECT followup_count FROM assessment_question WHERE question_id=?",
        (question_id,),
    ).fetchone()["followup_count"]


def _is_confirmed_refusal(session_id: str, question_id: str) -> bool:
    """该实例是否已发过拒答确认（消息表查 action='confirm'——现成口径，D-24）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) c FROM assessment_message"
        " WHERE session_id=? AND question_id=? AND role='assistant' AND action='confirm'",
        (session_id, question_id),
    ).fetchone()
    return row["c"] > 0


def _build_user_prompt(session: dict, question: dict, history: list[dict],
                       user_message: str, is_last: bool) -> str:
    lines = [
        f"岗位：{session['position_name']}",
        f"当前题目（{question['category']}/{question['qtype']}，难度 {question.get('difficulty') or '无'}）：",
        question["stem"],
        "",
        "对话历史：",
    ]
    for m in history:
        role = {"user": "候选人", "assistant": "面试官", "system": "系统"}[m["role"]]
        lines.append(f"{role}：{m['content']}")
    lines.append(f"候选人：{user_message}")
    lines.append("")
    lines.append("系统提示：" + ("这是最后一题。" if is_last else "后面还有题目。"))
    return "\n".join(lines)


def _mock_interview(system_prompt: str, user_prompt: str) -> dict:
    """mock 规则分类器（D-23）：模拟「观察输出」而非「绕过裁决」。

    输出与真实模式同构（InterviewObservation dict）：拒答词 → DECLINED；
    短答 → NEED_CLARIFICATION；实义词 → VALID_EVIDENCE（spec=2/attr=True）；
    其余长答 → VALID_EVIDENCE 粗判（spec=1/attr=False——长但空路径交裁决层判不足）。
    """
    last_user = ""
    for line in reversed(user_prompt.splitlines()):
        if line.startswith("候选人："):
            last_user = line[len("候选人："):]
            break
    is_objective = "/objective" in user_prompt
    if any(w in last_user for w in _DECLINE_WORDS):
        state = "DECLINED"
        dims = {"relevance": False, "specificity": 0, "attribution": False}
        return {"answer_state": state, "observation": dims,
                "reply_suggestion": "", "reason": "mock: 拒答关键词",
                "score_live": None, "score_live_reason": None}
    if len(last_user) < MIN_ANSWER_CHARS:
        state = "NEED_CLARIFICATION"
        dims = {"relevance": True, "specificity": 0, "attribution": False}
        return {"answer_state": state, "observation": dims,
                "reply_suggestion": "能再具体展开一下吗？", "reason": "mock: 回答过于简短",
                "score_live": None if is_objective else 2,
                "score_live_reason": None if is_objective else "信息不足"}
    if any(w in last_user for w in _EVIDENCE_WORDS):
        state = "VALID_EVIDENCE"
        dims = {"relevance": True, "specificity": 2, "attribution": True}
        return {"answer_state": state, "observation": dims,
                "reply_suggestion": "好的，感谢你的回答。", "reason": "mock: 实义词充分",
                "score_live": None if is_objective else 3,
                "score_live_reason": None if is_objective else "mock 中档"}
    # 长但空：VALID_EVIDENCE 粗判——specificity=1/attribution=False 由裁决层判不足
    state = "VALID_EVIDENCE"
    dims = {"relevance": True, "specificity": 1, "attribution": False}
    return {"answer_state": state, "observation": dims,
            "reply_suggestion": "能补充一个具体的例子或结果吗？", "reason": "mock: 长答无实义词",
            "score_live": None if is_objective else 2,
            "score_live_reason": None if is_objective else "粗判 2 分"}


# ---------- 裁决层纯函数（不持 conn——Simplicity 边界） ----------

def classify_observation(obs: InterviewObservation) -> tuple[bool, dict]:
    """§11.3 排除清单代码化：单次观察是否构成充分证据。

    返回 (evidence_sufficient, detail)。required_points_covered/source_span_available
    属 Phase 5 证据链强化维度——schema 保留，裁决不消费。
    """
    d = obs.observation
    evidence_sufficient = (
        obs.answer_state == "VALID_EVIDENCE"
        and d.relevance is True
        and d.attribution is True
        and d.specificity >= 1
        and d.contradiction_detected is not True
        and d.uncertainty is not True
    )
    detail = {
        "relevance": d.relevance,
        "specificity": d.specificity,
        "attribution": d.attribution,
        "contradiction_detected": d.contradiction_detected,
        "uncertainty": d.uncertainty,
    }
    return evidence_sufficient, detail


def decide_action(answer_state: str, evidence_sufficient: bool, followups: int,
                  is_confirmed: bool, is_exhausted: bool) -> tuple[str, dict]:
    """裁决规则（§11.4 处理原则代码化——代码唯一权威，LLM 不输出 action）。

    返回 (action, extra)：confirm/seal_refused 为内部值，followup/next 为
    既有语义；refused 标记键由 extra 携带（assessment.py 消费封存）。
    """
    # 规则 1/2：拒答——首次确认（一次性），二次封存推进（D-24）
    if answer_state == "DECLINED":
        if not is_confirmed:
            return "confirm", {"refused": False}
        # 内部值 seal_refused：API 层置 action='next' + refused 标记键封存当前题
        return "seal_refused", {"refused": True}
    # 规则 3：模型不确定——不猜测，按证据不足处理但不 followup，直接 next（§11.5 不卡死）
    if answer_state == "MODEL_UNCERTAIN":
        return "next", {}
    # 规则 7：过程挑战/行为事件/技术与访问障碍/注入/题目无效——不扣分不猜疑，next 推进
    #（INJECTION_DETECTED 事件留 Phase 3；answer_state 已落 OBSERVATION_CLASSIFIED 即审计足够）
    if answer_state in ("PROCESS_CHALLENGE", "CONDUCT_EVENT",
                        "TECHNICAL_OR_ACCESS_BARRIER", "PROMPT_INJECTION", "ITEM_INVALID"):
        return "next", {}
    # 规则 5：充分证据 → next（finish 由 02-02 池耗尽在 API 层触发，本层不出 finish）
    if evidence_sufficient:
        return "next", {}
    # 规则 4：NEED_CLARIFICATION 且不足 → followup（受 ≤2 上限）
    # 规则 6：OFF_TOPIC/NO_RECALL → followup（重定向/脚手架，受 ≤2 限制后转 next）
    # 不充分且无特殊状态的其余路径（长但空 VALID_EVIDENCE）同走 followup
    return "followup", {}


def decide_next_action(session_id: str, question_id: str, user_message: str) -> dict:
    """决策下一步动作：观察层（LLM/Pydantic）→ 裁决层（纯函数）→ 5 键 + 扩展键组装。

    追问达上限强制 next；拒答一次确认、二次封存（refused 标记键）；
    is_last 语义已废除——finish 由 select_next_question 池耗尽在 API 层触发（02-02）。
    """
    conn = get_conn()
    session, question, _is_last = _load_session_question(session_id, question_id)
    history_rows = conn.execute(
        "SELECT role, content FROM assessment_message WHERE session_id=?"
        " ORDER BY created_at, rowid",
        (session_id,),
    ).fetchall()
    history = [dict(r) for r in history_rows]

    # 1) 观察层：LLM 结构化观察 → InterviewObservation（aggregate.py:77 同款消费先例）
    # CR-01：call_llm_json 重试全败 raise RuntimeError——观察层捕获降级 MODEL_UNCERTAIN
    # （与 ValidationError 降级同语义：§11.5 不卡死，答题主链不 500、审计链完整）
    try:
        result = call_llm_json(
            "interviewer", session_id, INTERVIEWER_SYSTEM,
            _build_user_prompt(session, question, history, user_message, _is_last),
            mock_fn=_mock_interview,
        )
    except RuntimeError:
        result = {
            "answer_state": "MODEL_UNCERTAIN",
            "observation": {"relevance": False, "specificity": 0, "attribution": False},
            "reason": "LLM 调用失败（重试全败），降级 MODEL_UNCERTAIN（§11.5 不卡死会话）",
        }
    try:
        parsed = InterviewObservation(**result)
    except ValidationError:
        # 非法输出降级 MODEL_UNCERTAIN（§11.5 不卡死）：dims 全默认，不采纳不猜测
        parsed = InterviewObservation(
            answer_state="MODEL_UNCERTAIN",
            observation=ObservationDims(relevance=False, specificity=0, attribution=False),
            reason="LLM 输出未通过 InterviewObservation 校验，降级 MODEL_UNCERTAIN",
        )

    # 2) 裁决层：纯函数布尔 + action（规则唯一权威）
    evidence_sufficient, obs_detail = classify_observation(parsed)
    followups = _count_followups(session_id, question_id)
    is_confirmed = _is_confirmed_refusal(session_id, question_id)
    action, extra = decide_action(parsed.answer_state, evidence_sufficient,
                                  followups, is_confirmed, is_exhausted=False)

    # 3) 护栏（07 §7.2）：followup 达上限强制 next（迁移到 followup_count 列——上限逻辑不变）
    if action == "followup" and followups >= config.FOLLOWUP_MAX:
        action = "next"
        extra["reason_override"] = f"追问达上限({config.FOLLOWUP_MAX})，强制 next"

    # 4) 话术：confirm 固定文案；其余取观察层建议或默认
    answer_state = parsed.answer_state
    reason = extra.pop("reason_override", None) or parsed.reason or ""
    if action == "confirm":
        reply = _CONFIRM_REPLY
    elif action == "seal_refused":
        reply = "好的，已跳过该题。"
    else:
        reply = parsed.reply_suggestion or ("好的，感谢你的回答。" if action == "next" else "")

    # 5) 组装：5 基础键（契约不变）+ 扩展键（只加不减，Pitfall 8）
    decision = {
        "action": action,
        "reason": reason,
        "reply": reply,
        "score_live": parsed.score_live if question["qtype"] == "subjective" else None,
        "score_live_reason": parsed.score_live_reason if question["qtype"] == "subjective" else None,
        "answer_state": answer_state,
        "evidence_sufficient": evidence_sufficient,
    }
    if extra.get("refused"):
        decision["refused"] = True
    return decision
