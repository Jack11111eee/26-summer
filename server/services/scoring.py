"""终局逐题评分（SSOT §12.4 / §17 / §18——02-05 契约修正 + 2026-09-09 评分契约改造 U5b）。

客观题：结构化答案规则判分 `_score_objective_v2`（SSOT §17 2026-09-09——作废
「整串说明文本 + | 连接 + _looks_like_regex 猜正则」旧口径）：答案键三形态识别
（`[any_of] ` 前缀显式语义 / 旧 `|` 存量键 / 整段说明文本要点包含计数），命中=5 /
部分命中=3 / 未命中=1；answer_key 缺失 → score_state=INVALIDATED（题库无效，
不进正常分母）。正确性与能力等级分离（§17 / §9.4 契约第 2 条）：客观题命中 5 >
observable_level_max → 结构化截断（reason 注明，非静默 min()）。

主观题：P-score（LLM，temperature≈0），按 raw_hash 回捞原文输入（评分不受精炼影响，
§8）；prompt 携带 measurement_target 与锚点区间（§9.4 契约第 2 条替代通用脱靶评分）；
评分输出 `_validate_score` 严格校验类型/范围/锚点上限（§9.4 契约第 3 条——非法结果
进 INSUFFICIENT_EVIDENCE 排除态，不 int() 截断不越界静默接受，不生成正常低分记录）。

证据定位（SSOT §12.5 跨消息禁令）：quote 在各消息原文内分别定位，偏移相对该消息
原文；跨消息引文拆段各归各消息；找不到原文显式标记 located=false 全 NULL——绝不把
joined 拼接文本的偏移挂到最后一条用户消息（已确认旧缺陷形态）。

score_state 生产态（02-05 + U5b）：SCORED（正常评分）/ REFUSED（拒答封存，
§18 特殊状态值 score_value=0）/ INVALIDATED（answer_key 空的客观题）/
INSUFFICIENT_EVIDENCE（主观评分输出非法——D-28 枚举位自 U5b 起生产）。
score_live 仅导航参考值（D-26——不参与任何 final 计算，无 50/50 合成）。
"""
import hashlib
import json
import math
import re

from ..config import OBJECTIVE_KEYPOINT_HIT_RATIO
from ..db import get_conn
from .llm import call_llm_json
from .pipeline import new_id, now_iso
from .prompts.score import SCORE_SYSTEM, score_prompt
from .trace_link import link_entity

# score_state 六态（D-28；N11 代码校验惯例——生产四态，枚举位供校验）
SCORE_STATES = (
    "SCORED",
    "REFUSED",
    "INSUFFICIENT_EVIDENCE",
    "NOT_ADMINISTERED",
    "INVALIDATED",
    "INCOMPLETE",
)


# ---------- 客观题代码判分（SSOT §17 结构化答案规则，U5b 2026-09-09）----------

# WR-14：answer_key 长度上限与候选人回答截断长度（防病态输入灾难性匹配）
_MAX_KEY_LEN = 512
MAX_ANSWER_LEN = 64 * 1024  # WR-07：输入侧（assessment）与评分侧同口径公开设定的上限
_MAX_ANSWER_LEN = MAX_ANSWER_LEN  # 旧私有名（模块内既有引用保持）
# 客观题 evidence_quote 展示截断长度（SSOT §17 登记口径：固定展示规则非开放参数；
# 主观题引文由 LLM 摘引，客观题回答可长文，前缀截断仅为引文列展示约定）
_OBJECTIVE_QUOTE_LEN = 60
# any_of 答案键前缀（U5a question_bank._mark_any_of 落库形态，§17 过渡标记）
_ANY_OF_PREFIX = "[any_of] "
# 难度 → 锚点区间（SSOT §9.4 表；题库行 NULL 时主观评分 prompt 的回退查表）
_LEVEL_RANGE_BY_DIFFICULTY = {"easy": (2, 3), "medium": (3, 4), "hard": (4, 5)}
# 符号串判定的字母/数字/希腊字母字符集（§17——数学符号串整体保留，不看拆词）
_SYMBOL_LETTERS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                      "0123456789γβαλμσ±×÷-—~")
# 否定词（首版从简：命中位置附近含否定词 → 该要点不计命中）
_NEGATION_WORDS = ("不是", "没有", "并非", "不包含", "不属于", "不含", "无",
                   "错误", "并不是", "不包括")
_NEGATION_WINDOW = 12  # 否定词判定的前向字符窗口（命中起点前 + 要点后 2 字）


def _normalize_answer_text(text: str) -> str:
    """评分侧归一化（SSOT §17）：全半角统一、空白折叠、Markdown 强调符剥除、小写。

    数学符号不删除（§17「归一化不得改变语义」——(S, A, P, R, γ) 的括号统一为
    半角是形态差异非语义差异；删符号会破坏五元组判分）。行结构保留（any_of
    候选拆行在归一化后进行——候选内空白也折叠）。
    """
    if not text:
        return ""
    t = text
    # 全角 → 半角（常见括号/逗号/空格/冒号/分号）
    for src, dst in (("（", "("), ("）", ")"), ("，", ","), ("　", " "),
                     ("：", ":"), ("；", ";"), ("？", "?"), ("！", "!")):
        t = t.replace(src, dst)
    # Markdown 强调符剥除（**bold**、*italic*、`code`、# heading）——出现在词间时剥离
    t = t.replace("**", "").replace("`", "").replace("#", "").replace("*", "")
    # 空白折叠：连续空白（含全角空格已转）压成单空格；符号串内空白删除（形近归一：
    # (S, A, P, R, γ) 与 (S,A,P,R,γ) 同要点——括号内是符号列表，空格仅排版差异）
    t = re.sub(r"(?<=[\(,\[]) *(?=[,a-zA-Z0-9γβαλμσ\)\]])", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def _extract_keypoints(key: str) -> list[str]:
    """从答案键（整段说明文本）提取关键实体要点（SSOT §17 要点包含计数）。

    规则：中文词串按标点/空白切分，取长度 ≥2 的非虚词片段；数学符号串
    （如 (S, A, P, R, γ)——括号/逗号/字母数字/希腊字母构成）整体保留为一个要点；
    纯单字、纯虚词、纯数字符号片段丢弃。归一化先行（全半角统一后切分稳定）。
    """
    norm = _normalize_answer_text(key)
    if not norm:
        return []
    keypoints: list[str] = []
    # 先抽取括号/方括号内的符号串（含括号整体），这些片段不可拆词
    consumed: list[tuple[int, int]] = []
    symbol_pattern = re.compile(
        r"[\(\[][^\(\)\[\]]*[\)\]]"  # (...) / [...] 形态（含空内容则跳过）
    )
    for m in symbol_pattern.finditer(norm):
        inner = m.group(0)
        # 只保留含字母/数字/希腊字母的符号串（(S, A, P, R, γ)；纯中文括号内容按普通切分）
        if any(c in _SYMBOL_LETTERS for c in inner) and re.search(
                r"[a-z0-9γβαλμσ]", inner.lower()):
            keypoints.append(inner)
            consumed.append((m.start(), m.end()))
    # 掩掉已消费区间后按切分符分词
    masked = norm
    for s, e in consumed:
        masked = masked[:s] + (" " * (e - s)) + masked[e:]
    # 切分：ASCII/全角标点（归一化后全角已转半角，剩 ASCII 标点 + 中文顿号等已被转）
    parts = re.split(r"[,;:(){}\[\]<>!?。\s、·/|—–\-\"'“”‘’]+", masked)
    for p in parts:
        p = p.strip()
        if len(p) >= 2 and re.search(r"[一-鿿 a-z0-9γβαλμσ]", p.lower()):
            keypoints.append(p)
    return keypoints


def _has_negation_near(text: str, idx: int, end: int) -> bool:
    """要点命中位置附近是否含否定词（首版从简，SSOT §17 否定检测）。

    窗口：命中起点前 _NEGATION_WINDOW 字符 + 要点末尾后 2 字（「没有X」「并非X」
    前置否定 +「不是X」紧邻形态）。中文否定常作用于整个顿号枚举段
    （「并不包含A、B、C」），故窗口命中后再向两侧扩到最近句读边界（逗号/句号/
    顿号链视为同段），同段含否定词 → 该要点不计命中。首版从简：否定段内直接判
    否定，不做肯定/否定并存细粒度消歧。
    """
    window_start = max(0, idx - _NEGATION_WINDOW)
    window_end = min(len(text), end + 2)
    if any(w in text[window_start:window_end] for w in _NEGATION_WORDS):
        return True
    # 顿号枚举段内否定（「不包含A、B、C」）：向两侧扩到最近非枚举句读边界
    seg_start = text.rfind("，", 0, idx)
    seg_start = text.rfind("。", 0, seg_start if seg_start != -1 else idx)
    seg_start = 0 if seg_start == -1 else seg_start + 1
    seg_end_candidates = [p for p in (text.find("，", end), text.find("。", end)) if p != -1]
    seg_end = min(seg_end_candidates) if seg_end_candidates else len(text)
    # 段内不允许只有顿号（顿号本身是枚举连接符不算边界）——用逗号/句号切出的段
    # 若与相邻段以顿号相连则并入（枚举链跨逗号极罕见，首版不处理）
    return any(w in text[seg_start:seg_end] for w in _NEGATION_WORDS)


def _hit_ratio_with_negation(keypoints: list[str], answer_norm: str) -> tuple[float, list[str]]:
    """逐要点查包含（否定窗口过滤），返回 (命中率, 命中要点列表)。"""
    if not keypoints:
        return 0.0, []
    hits: list[str] = []
    for kp in keypoints:
        idx = answer_norm.find(kp)
        if idx != -1 and not _has_negation_near(answer_norm, idx, idx + len(kp)):
            hits.append(kp)
    return len(hits) / len(keypoints), hits


def _score_objective_v2(answer_key: str, answer: str) -> tuple[int, str]:
    """结构化答案规则判分器（SSOT §17 核心，U5b 2026-09-09）。

    答案键形态判序（三形态并存）：
    a) `[any_of] ` 前缀（U5a 新契约形态）→ any_of 语义：拆行得候选集合，任一候选
       规范化后「包含匹配」命中即 5 分——纯文本包含不执行正则（re.escape 精神）；
    b) 旧 `|` 连接存量键（无前缀且含 |）→ 拆 | 为候选集合同 any_of 处理（SSOT 作废
       「| 猜正则」——不 re.search；旧键「栅格地图|拓扑地图」答「栅格地图」命中）；
    c) 其余（整段说明文本 / 单串）→ 要点包含计数：关键实体提取 → 规范化回答逐要点
       查包含（否定窗口过滤）→ 命中率 ≥ OBJECTIVE_KEYPOINT_HIT_RATIO 判 5、
       ≥0.3 判 3（部分命中，首版保守两档）、<0.3 判 1。要点为空（如单符号键 'def'）
       退化为单要点整串包含——键本身就是唯一要点。

    answer_key 缺失/空白不在本函数处理——score_question 客观分支先判空 key 升
    INVALIDATED（02-05 语义替换沿用）。
    """
    key = answer_key[:_MAX_KEY_LEN]
    text = (answer or "")[:_MAX_ANSWER_LEN]
    answer_norm = _normalize_answer_text(text)

    # a) any_of 显式语义（U5a 契约形态）
    if key.startswith(_ANY_OF_PREFIX):
        candidates = [_normalize_answer_text(c) for c in
                      key[len(_ANY_OF_PREFIX):].split("\n") if c.strip()]
        for cand in candidates:
            if not cand:
                continue
            idx = answer_norm.find(cand)
            if idx != -1 and not _has_negation_near(answer_norm, idx, idx + len(cand)):
                return 5, f"命中答案要点（any_of）: {cand}"
            # 裸符号串候选（去外层括号后命中也认可：`(S, A, P, R、γ)` 反引号形态）——
            # 括号是排版差异非语义差异（§17 归一化不变语义）
            stripped = cand.lstrip("(").rstrip(")")
            if stripped != cand:
                idx2 = answer_norm.find(stripped)
                if idx2 != -1 and not _has_negation_near(answer_norm, idx2, idx2 + len(stripped)):
                    return 5, f"命中答案要点（any_of 符号串）: {cand}"
            # 多要点候选（如中文要素列举行）：按要点包含计数——任一候选达标即命中
            cand_kps = _extract_keypoints(cand)
            if cand_kps:
                ratio, hits = _hit_ratio_with_negation(cand_kps, answer_norm)
                if ratio >= OBJECTIVE_KEYPOINT_HIT_RATIO:
                    return 5, f"命中答案要点（any_of 要点数）：{len(hits)}/{len(cand_kps)}"
        return 1, "未命中任一等价答案（any_of）"

    # b) 旧 | 连接存量键——同 any_of 处理（不再 re.search，SSOT 作废 | 猜正则）
    if "|" in key:
        candidates = [_normalize_answer_text(c) for c in key.split("|") if c.strip()]
        for cand in candidates:
            if not cand:
                continue
            idx = answer_norm.find(cand)
            if idx != -1 and not _has_negation_near(answer_norm, idx, idx + len(cand)):
                return 5, f"命中答案要点（存量 | 键 any_of 兼容）: {cand}"
        return 1, "未命中任一候选答案（存量 | 键）"

    # c) 整段说明文本 → 要点包含计数
    keypoints = _extract_keypoints(key)
    if not keypoints:
        # 单要点退化：键本身就是要点（如 'def'、'GET'——归一化后整体包含判定）
        kp = _normalize_answer_text(key)
        if kp and kp in answer_norm:
            return 5, f"命中答案要点（单要点包含）: {kp}"
        return 1, "未命中答案要点（单要点包含）"
    ratio, hits = _hit_ratio_with_negation(keypoints, answer_norm)
    total = len(keypoints)
    if ratio >= OBJECTIVE_KEYPOINT_HIT_RATIO:
        return 5, f"命中全部要点（{len(hits)}/{total}）: {'、'.join(hits)}"
    if ratio >= 0.3:
        return 3, f"部分命中要点（{len(hits)}/{total}）: {'、'.join(hits)}"
    return 1, f"未命中答案要点（{len(hits)}/{total}）"


def _mock_score(system_prompt: str, user_prompt: str) -> dict:
    return {"score": 3, "evidence_quote": "mock quote", "reason": "mock reason"}


def _fetch_answer_messages(session_id: str, question_id: str) -> list[tuple[str, str]]:
    """取该题各轮候选人回答消息（SSOT §12.5 各消息独立定位的输入）。

    返回 [(message_id, 原文文本), ...] 按消息顺序；有 raw_hash 的按 hash 回捞原文
    （P-score 用原文，评分不受精炼影响 §8）——原文即各消息定位基准。
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT message_id, content, raw_hash FROM assessment_message"
        " WHERE session_id=? AND question_id=? AND role='user' ORDER BY created_at, rowid",
        (session_id, question_id),
    ).fetchall()
    messages: list[tuple[str, str]] = []
    for r in rows:
        if r["raw_hash"]:
            raw = conn.execute(
                "SELECT full_text FROM context_raw WHERE hash=?", (r["raw_hash"],)
            ).fetchone()
            text = raw["full_text"] if raw else r["content"]
        else:
            text = r["content"]
        messages.append((r["message_id"], text))
    return messages


def _fetch_answer_text(session_id: str, question_id: str) -> tuple[list[tuple[str, str]], str]:
    """该题全部候选人回答消息 + 拼接全文。

    返回 (messages, joined)：messages 供证据定位（§12.5 各消息分别定位）；joined
    供 LLM 评分 prompt（行为与旧版一致——prompt 仍吃全文）。joined 仅用于 prompt
    与客观题展示截断，**绝不**用于证据定位偏移（跨消息禁令）。
    """
    messages = _fetch_answer_messages(session_id, question_id)
    joined = "\n".join(text for _, text in messages)
    return messages, joined


def _locate_span(answer_text: str, quote: str, source_message_id: str | None) -> dict | None:
    """在单条消息原文内定位 quote，返回结构化 span。定位失败返回 None（调用方降级）。

    offset 按 Python str.find/len（code point 语义，§12.5）；多命中取最早；
    quote_hash = sha256(quote.encode('utf-8'))（D-003「LLM 不碰数字」——offset/hash
    全代码计算）。遗留纯函数（test_phase5_evidence 直测保留）；生产定位走
    _build_evidence_spans（逐消息定位，§12.5）。
    """
    if not quote:
        return None
    idx = answer_text.find(quote)
    if idx == -1:
        return None  # mock "mock quote" / LLM 改写非原文 → 降级
    return {
        "source_message_id": source_message_id,
        "source_content_type": "raw",
        "start_offset": idx,
        "end_offset": idx + len(quote),
        "quote_hash": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
    }


def _quote_hash(quote: str) -> str:
    return hashlib.sha256(quote.encode("utf-8")).hexdigest()


def _span_for(message_id: str, text: str, quote: str, idx: int) -> dict:
    return {
        "source_message_id": message_id,
        "source_content_type": "raw",
        "start_offset": idx,
        "end_offset": idx + len(quote),
        "quote_hash": _quote_hash(quote),
    }


def _unlocated_span(quote: str) -> dict:
    """定位失败显式标记（SSOT §12.5/§18）：offset 与来源全 NULL + located: false。

    不以仅有 quote_hash 的记录冒充已定位证据——located 键让消费方可机器判别。
    """
    return {
        "quote_hash": _quote_hash(quote),
        "source_message_id": None,
        "source_content_type": None,
        "start_offset": None,
        "end_offset": None,
        "located": False,
    }


def _split_quote_in_message(remainder: str, text: str) -> tuple[int, int] | None:
    """跨消息引文拆段：返回 (段在 quote 前缀中的长度, 段在该消息内的偏移)。

    找 quote 前缀中能在该消息原文内命中的最长段（贪婪前缀对齐）；拼接分隔符
    （\n）只存在于 joined 文本、不属任何消息原文——剥离后再对齐。
    """
    probe = remainder.lstrip("\n")
    if not probe:
        return None
    for cut in range(len(probe), 0, -1):
        seg_idx = text.find(probe[:cut])
        if seg_idx != -1:
            return cut, seg_idx
    return None


def _build_evidence_spans(messages: list[tuple[str, str]], evidence_quote: str | None,
                          source_message_id: str | None = None) -> str | None:
    """定位 evidence_quote → evidence_spans_json（SSOT §12.5 跨消息禁令，U5b）。

    - quote 在**各消息原文内分别 find**：第一条命中消息的 span 绑定该消息
      source_message_id，偏移相对该消息原文；
    - 单消息找不到完整 quote（跨消息引文）：在消息边界处拆段，每段绑定各自消息
      （贪婪前缀对齐；joined 的 \n 分隔符非消息原文，跳过后对齐下一段）；
    - 拆段也无法全部命中 → 定位失败显式标记（located=false 全 NULL），不以
      joined 偏移挂最后一条消息（旧缺陷形态绝对禁止）。

    source_message_id 参数为遗留签名兼容（调用方可传 None）；忽略该值——
    定位来源由 messages 逐条命中决定（§12.5 禁止统一填最后一条）。
    """
    if not evidence_quote:
        return None
    spans: list[dict] = []
    remainder = evidence_quote
    for message_id, text in messages:
        if not remainder:
            break
        idx = text.find(remainder)
        if idx != -1:
            # 剩余引文整段在本消息内 → 完整定位（单消息命中是主路径）
            spans.append(_span_for(message_id, text, remainder, idx))
            remainder = ""
            break
        # 跨消息引文拆段：本消息内对齐最长前缀
        seg = _split_quote_in_message(remainder, text)
        if seg is not None:
            cut, seg_idx = seg
            spans.append(_span_for(message_id, text, remainder.lstrip("\n")[:cut], seg_idx))
            # 消费已对齐段（含其前的 \n 分隔符——分隔符不属消息原文）
            skip = len(remainder) - len(remainder.lstrip("\n")) + cut
            remainder = remainder[skip:]
    if not remainder and spans:
        for span in spans:
            span["located"] = True
        return json.dumps(spans)
    # 定位失败：显式标记（不以 quote_hash-only 冒充已定位；保留 hash 供对账）
    return json.dumps([_unlocated_span(evidence_quote)])


def _validate_score(result: dict, observable_level_max: int | None) -> tuple[int | None, str | None]:
    """主观评分输出严格校验（SSOT §9.4 契约第 3 条，U5b）。

    返回 (score, error)：合法 → (int score, None)；非法 → (None, 原因描述)。
    校验：非 int/float（bool 排除）、非有限数学值（NaN/inf）、<1 或 >5、
    > observable_level_max（题库行有值时）——不截断小数、不静默接受越界值
    （int(result["score"]) 旧口径作废）。非法结果由调用方走 INSUFFICIENT_EVIDENCE
    排除态（§17「非法结果进明确失败或复核路径，不生成正常低分记录」）。
    """
    try:
        raw = result["score"]
    except (KeyError, TypeError):
        return None, "缺 score 键"
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None, f"score 非数值类型: {type(raw).__name__}"
    if not math.isfinite(raw):
        return None, "score 非有限数值（NaN/inf）"
    if raw != int(raw):
        return None, f"score 含小数（不得截断）: {raw}"
    score = int(raw)
    if score < 1 or score > 5:
        return None, f"score 越界量表（1-5）: {score}"
    if observable_level_max is not None and score > observable_level_max:
        return None, f"score 超题目观测上限 {observable_level_max}: {score}"
    return score, None


def score_question(session_id: str, question_id: str) -> dict:
    """对单题终局判分。返回 {score_final, evidence_quote, reason, score_state,
    evidence_spans_json, trace_id}。

    客观题 answer_key 空 → score_state=INVALIDATED + score_final=None（题库无效，
    不落 1/不落 5——脱离普通评分通道，REF-5.2/8.1）；命中=5 口径不变，但 5 >
    observable_level_max（题库行有值）时结构化截断——截断值写进 reason
    「客观题命中，依题目测量上限 {max} 调整为 {capped}」（§17 正确性与等级分离）。
    未命中=1 不受 observable_level_min 约束（锚点起点非判分下限）。

    主观题评分输出非法（类型/范围/上限）→ score_state=INSUFFICIENT_EVIDENCE +
    score_final=None（§9.4 契约第 3 条——不生成正常低分记录）；prompt 携带
    measurement_target 与锚点区间（§9.4 契约第 2 条）。

    evidence_spans_json 结构化权威（source_message_id/offset 相对各消息原文/quote_hash/
    located，§12.5）；主观题 trace_id 为成功 LLM trace 的 trace_id（供 trace_link
    关联），客观/INVALIDATED 分支为 None。
    """
    conn = get_conn()
    q = conn.execute(
        "SELECT aq.question_id, aq.session_id, b.stem, b.qtype, b.answer_key, b.rubric,"
        " b.difficulty, b.rubric_version, b.measurement_target,"
        " b.observable_level_max, b.observable_level_min,"
        " s.position_id, p.name AS position_name"
        " FROM assessment_question aq"
        " JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " JOIN assessment_session s ON s.session_id=aq.session_id"
        " JOIN position p ON p.position_id=s.position_id"
        " WHERE aq.question_id=?",
        (question_id,),
    ).fetchone()
    if q is None:
        raise ValueError(f"题目不存在: {question_id}")
    q = dict(q)
    messages, answer_text = _fetch_answer_text(session_id, question_id)

    if q["qtype"] == "objective":
        if not (q["answer_key"] or "").strip():
            # 02-05：题库无效（客观题缺 answer_key）→ INVALIDATED（REF-5.2/8.1），
            # 不再按最低分记
            return {
                "score_final": None,
                "evidence_quote": None,
                "reason": "题库无效：客观题缺 answer_key（REF-5.2/8.1）",
                "score_state": "INVALIDATED",
                "evidence_spans_json": None,
                "trace_id": None,
            }
        score, reason = _score_objective_v2(q["answer_key"], answer_text)
        # §17 正确性与等级分离：客观题命中 5 > observable_level_max → 结构化截断
        # （题库行 NULL 不约束——存量旧行；截断值写进 reason 非静默 min()）
        level_max = q["observable_level_max"]
        if score == 5 and level_max is not None and score > level_max:
            capped = level_max
            reason = (f"{reason}；客观题命中，依题目测量上限 {level_max} 调整为 {capped}")
            score = capped
        evidence_quote = answer_text[:_OBJECTIVE_QUOTE_LEN]
        return {"score_final": score, "evidence_quote": evidence_quote,
                "reason": reason, "score_state": "SCORED",
                "evidence_spans_json": _build_evidence_spans(
                    messages, evidence_quote),
                "trace_id": None}

    # 主观题：锚点区间（题库行 NULL 时按难度默认查表，§9.4 表）
    level_min, level_max = q["observable_level_min"], q["observable_level_max"]
    if level_min is None or level_max is None:
        level_min, level_max = _LEVEL_RANGE_BY_DIFFICULTY.get(q["difficulty"] or "medium", (3, 4))
    trace_out: list[str] = []
    result = call_llm_json(
        "score", question_id, SCORE_SYSTEM,
        score_prompt(q, answer_text, q["position_name"],
                     measurement_target=q["measurement_target"],
                     level_range=(level_min, level_max)),
        mock_fn=_mock_score,
        trace_out=trace_out,
    )
    evidence_quote = result.get("evidence_quote") or ""
    score, err = _validate_score(result, level_max)
    if err is not None:
        # §9.4 契约第 3 条 / §17：非法结果进明确失败或复核路径，不生成正常低分记录
        return {
            "score_final": None,
            "evidence_quote": evidence_quote or None,
            "reason": f"评分输出非法：{err}",
            "score_state": "INSUFFICIENT_EVIDENCE",
            "evidence_spans_json": None,
            "trace_id": trace_out[0] if trace_out else None,
        }
    return {
        "score_final": score,
        "evidence_quote": evidence_quote,
        "reason": result.get("reason", ""),
        "score_state": "SCORED",
        "evidence_spans_json": _build_evidence_spans(messages, evidence_quote),
        "trace_id": trace_out[0] if trace_out else None,
    }


# ---------- 会话级打分 ----------

def _find_item_id(model_id: str, std_name: str, category: str) -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT item_id FROM competency_item WHERE model_id=? AND std_name=? AND category=?",
        (model_id, std_name, category),
    ).fetchone()
    return row["item_id"] if row else None


def _latest_score_live(session_id: str, question_id: str) -> int | None:
    """score_live 参考值读取（D-26：仅供导航/审计参考，不参与任何 final 计算）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT score_live FROM assessment_message"
        " WHERE session_id=? AND question_id=? AND score_live IS NOT NULL"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (session_id, question_id),
    ).fetchone()
    return row["score_live"] if row else None


def _existing_score_rows(conn, session_id: str) -> int:
    """该会话已存在的非 gate 评分行数（gate_result IS NOT NULL 的 gate 行不算）。"""
    return conn.execute(
        "SELECT COUNT(*) c FROM question_score WHERE session_id=? AND gate_result IS NULL",
        (session_id,),
    ).fetchone()["c"]


def score_session(session_id: str, *, allow_completed: bool = False,
                  progress_cb=None) -> dict:
    """对会话内所有已回答题目打分并落 question_score（score_state 生产态）。

    评分批次（SSOT §20.2.A，U6 2026-09-09）：每次成功落库生成 batch_id = new_id("sb")，
    全部 INSERT 行携带——报告经 report_json.scoring_batch_id 绑定批次（归属一致）。

    progress_cb（§21.1 生成进度透传，2026-09-09）：可选回调 (done, total)——
    循环前先报告 (0, len(answered))，之后每题顶部报告 (i, total)（i = 正在评的
    第几题，含拒答/无 item 映射的快行；total 单源于本函数的 answered 计数）。
    约束承诺：cb 调用期间本函数不持写事务（循环期 conn 只读、写库统一在末尾
    单事务），cb 实现方负责吞掉自身异常（不得写 question_score）——异常吞噬
    职责在 cb 实现方，本层不另包裹。默认 None 零影响。

    completed 护栏（REF-8.2 + §20.2.A 历史证据链保护，U6 2026-09-09）：
    - 会话 completed 且已有非 gate 评分行 → **一律拒绝重评分**（ValueError），即使
      allow_completed=True——DELETE+重插会替换已终态化的评分证据链（审计断裂形态，
      §20.2.A 作废）；修订须走管理员修订流程（先只读预演，不在本函数）。
      调用方分析（改后语义不堵死正常链路）：
      ① 串行链 _run_report_task（allow_completed=True）：只对「尚无评分行」的
        completed 会话评分——request_report 三分支裁决中，终态成功报告
        （PROVISIONAL/READY/PUBLISHED）本就 409 不重触发，FAILED/无行才允许重入；
        超龄 GENERATING 接管重写新 version 行同理。故已评分会话重新入队时本次
        直接跳过评分子步（幂等——不删不重算），报告子步照常以既有评分行生成；
        未评分 completed 会话（后台链失败于评分前/接管前死亡）照常首次评分。
      ② 显式评分端点 POST /score：completed 一律 409（既有语义不变，护栏更严）。
      ③ 测试直调 allow_completed=True 的路径均为「先评分后生成」首次链，不受影响。
    - 会话 in_progress 且已有评分行（评分尚未终态化，不算历史证据）→ 维持现行
      幂等语义：删旧重打（DELETE 只清评分行，gate 行幸存——03-01）。

    分母契约（02-05 + U5b）：
    - seal_reason='refused'（02-04 二次 DECLINED 封存）→ score_state='REFUSED'、
      score_final=0（§18 特殊状态值），不调 score_question（拒答不产生能力证据）；
    - 客观题缺 answer_key（INVALIDATED）/ 主观评分输出非法（INSUFFICIENT_EVIDENCE，
      §9.4 契约第 3 条）→ score_final=None 透传（不进正常分母）；
    - 其余 → score_state='SCORED'，score_final 独立落库（无 50/50 合成——D-26）。

    版本快照（§20.2.A「保存真正使用的 rubric/scorer/测量目标版本」）：
    rubric_version 从题库行读真实值（b.rubric_version，'v1' 兜底——存量行无版本时）；
    measurement_target 从题库行读（b.measurement_target，可为 NULL）——本函数不再
    硬编码 'v1' 与空置目标（REF-5.x 编号见表 docstring；硬编码形态作废）。

    实现注意：先在内存里算完全部行（含 LLM 调用），最后一次写库——避免外层
    conn 持写事务时 LLM trace 用新连接写库导致 database is locked。
    """
    conn = get_conn()
    session = conn.execute(
        "SELECT model_id, status FROM assessment_session WHERE session_id=?", (session_id,)
    ).fetchone()
    if session is None:
        raise ValueError(f"会话不存在: {session_id}")
    has_existing = _existing_score_rows(conn, session_id) > 0
    if session["status"] == "completed":
        if has_existing:
            # §20.2.A 历史证据链保护：completed 会话的已终态化评分不覆盖不重算
            # （allow_completed 只豁免「未评分即 completed」的首次链，不豁免重打）
            raise ValueError(
                "会话已评分，修订须走管理员修订流程（评分批次不可变，SSOT §20.2.A）")
        if not allow_completed:
            raise ValueError("会话已结束，不允许重复评分")
    # in_progress 放行（重复调用删旧重打）

    answered = conn.execute(
        "SELECT aq.question_id, aq.seal_reason, aq.item_id,"
        " b.std_name, b.category, b.qtype, b.rubric_version, b.measurement_target"
        " FROM assessment_question aq JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE aq.session_id=? AND aq.answered_at IS NOT NULL",
        (session_id,),
    ).fetchall()

    # 0) 评分批次（§20.2.A）：本函数成功落库即一个不可变批次
    batch_id = new_id("sb")

    # 1) 内存计算（含 LLM 调用，此时本 conn 未持写事务）
    pending_rows: list[tuple] = []
    trace_links: list[tuple[str, str, str]] = []  # (trace_id, score_id, question_id)
    # 进度开评一报（total 在此单源定死——调用方不另行 COUNT，防谓词漂移）
    if progress_cb is not None:
        progress_cb(0, len(answered))
    for i, q in enumerate(answered, 1):
        if progress_cb is not None:
            progress_cb(i, len(answered))
        # item_id 取值：优先实例列（02-02 v2.0 item 绑定），NULL 回退 competency_item 查询（过渡）
        item_id = q["item_id"] or _find_item_id(session["model_id"], q["std_name"], q["category"])
        if item_id is None:
            # 题库 std_name 在模型中无对应项（通用题）——跳过不入分表
            continue

        if q["seal_reason"] == "refused":
            # 拒答封存（02-04 二次 DECLINED）：score_value=0 特殊状态值（§18），
            # 不调 score_question（拒答不产生能力证据，REFUSED 行不经 LLM 评分）
            pending_rows.append(
                (new_id("qs"), session_id, q["question_id"], item_id,
                 None, 0, "REFUSED", None, "拒答（§18 score_value=0 特殊状态值）",
                 None, q["rubric_version"] or "v1", "p-score-1", q["measurement_target"],
                 now_iso(), batch_id)
            )
            continue

        r = score_question(session_id, q["question_id"])
        # score_live 参考值（D-26——不参与 final 计算，仅落库供导航/审计）
        score_live = _latest_score_live(session_id, q["question_id"]) \
            if q["qtype"] == "subjective" else None
        if r["score_state"] in ("INVALIDATED", "INSUFFICIENT_EVIDENCE"):
            # 客观题缺 answer_key / 主观评分输出非法（§9.4 契约第 3 条）：
            # score_final=None（脱离普通评分通道，不冒充正常低分）。
            # INSUFFICIENT_EVIDENCE 行保留 LLM trace 关联（评分输出复核路径——
            # 被拒的原始输出可供人工复核，§17「非法结果进复核路径」）
            invalid_score_id = new_id("qs")
            pending_rows.append(
                (invalid_score_id, session_id, q["question_id"], item_id,
                 None, None, r["score_state"], r["evidence_quote"], r["reason"],
                 None, q["rubric_version"] or "v1", "p-score-1", q["measurement_target"],
                 now_iso(), batch_id)
            )
            if r.get("trace_id"):
                trace_links.append((r["trace_id"], invalid_score_id, q["question_id"]))
            continue
        score_id = new_id("qs")
        pending_rows.append(
            (score_id, session_id, q["question_id"], item_id,
             score_live, r["score_final"], r["score_state"],
             r["evidence_quote"], r["reason"], r["evidence_spans_json"],
             q["rubric_version"] or "v1", "p-score-1", q["measurement_target"],
             now_iso(), batch_id)
        )
        # 运行时 score→trace 写点（D-020）：仅主观题产 LLM trace（客观/INVALIDATED trace_id=None）
        if q["qtype"] == "subjective" and r.get("trace_id"):
            trace_links.append((r["trace_id"], score_id, q["question_id"]))

    # 2) 单事务写库
    # gate 行非评分重算面（03-01）：DELETE 只清评分行（gate_result IS NULL），
    # 表单链 gate 结构化结果必须幸存——顺序链 _generate_report_task 与 UI request_report
    # 都走 score_session，吞掉 gate 行会导致表单链死循环（gate 永不采集→finish 不可达）。
    # （§20.2.A 后本 DELETE 只对 in_progress 会话可达——completed 已在护栏上方拒绝）
    conn.execute("DELETE FROM question_score WHERE session_id=? AND gate_result IS NULL", (session_id,))
    conn.executemany(
        "INSERT INTO question_score(score_id, session_id, question_id, item_id,"
        " score_live, score_final, score_state, evidence_quote, reason,"
        " evidence_spans_json, rubric_version, scorer_version, measurement_target,"
        " created_at, scoring_batch_id)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        pending_rows,
    )
    for trace_id, score_id, question_id in trace_links:
        link_entity(conn, trace_id=trace_id, entity_type="question_score",
                    entity_id=score_id, link_role="scored")
        link_entity(conn, trace_id=trace_id, entity_type="assessment_question",
                    entity_id=question_id, link_role="source")
    conn.commit()
    return {"session_id": session_id, "scored_count": len(answered),
            "scoring_batch_id": batch_id}
