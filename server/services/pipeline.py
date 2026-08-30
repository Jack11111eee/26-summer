"""单 JD 解析链：②清洗 → ③LLM#1抽取 → 归岗 → ④LLM#2消歧，产物落库。"""
import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from .. import config
from ..db import get_conn

NOISE_HEADERS = ["公司介绍", "关于我们", "福利待遇", "薪资福利", "我们提供", "加入我们", "团队介绍"]
REQ_HEADERS = ["任职要求", "岗位要求", "任职资格", "我们需要", "希望你", "职位要求"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


# ---------- 工序② 清洗（纯规则，无 LLM 兜底） ----------

def clean_jd(raw_text: str) -> tuple[str, bool]:
    """删噪音段，留要求相关内容。要求块为空或过短 → low_confidence=True 但继续流程。"""
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    kept: list[str] = []
    in_noise = False
    for ln in lines:
        # 噪音段 header：进入噪音态；header 之前若同行有要求内容则保留
        noise_hit = next((h for h in NOISE_HEADERS if h in ln), None)
        if noise_hit:
            before = ln.split(noise_hit, 1)[0].strip(" ：:，,")
            if before and not in_noise:
                kept.append(before)
            in_noise = True
            continue
        # 要求段 header：退出噪音态；header 之后同行的内容必须保留（header 与内容常同行）
        req_hit = next((h for h in REQ_HEADERS if h in ln), None)
        if req_hit:
            in_noise = False
            after = ln.split(req_hit, 1)[1].strip(" ：:，,")
            if after:
                kept.append(after)
            continue
        if not in_noise:
            kept.append(ln)
    cleaned = "\n".join(kept)
    low_confidence = len(cleaned) < config.CLEAN_MIN_REQ_LEN
    return cleaned, low_confidence


# ---------- 工序③ LLM#1 抽取 ----------

def _mock_extract(system_prompt: str, user_prompt: str) -> dict:
    """离线 mock：按关键词规则模拟 LLM#1 输出，保证全流程无网可演示。"""
    text = user_prompt
    items = []
    skills = re.findall(r"(Python|Java|Go|MySQL|Redis|Docker|Kubernetes|微服务|沟通能力|团队协作)", text)
    for s in dict.fromkeys(skills):  # 去重保序
        category = "soft_skill" if s in ("沟通能力", "团队协作") else "hard_skill"
        level = 4 if "精通" in text and s in text else 3
        items.append({
            "name": s, "category": category, "required_level": level,
            "importance": "required", "evidence": [s],
        })
    years_m = re.search(r"(\d+)\s*年", text)
    if years_m:
        items.append({
            "name": "相关工作经验", "category": "experience", "required_level": 3,
            "importance": "required", "evidence": [years_m.group(0)], "years": float(years_m.group(1)),
        })
    title = "软件工程师"
    m = re.search(r"岗位[:：]\s*(\S+)", text)
    if m:
        title = m.group(1)
    return {"job_title": title, "items": items}


def extract_items(jd_id: str, cleaned_text: str) -> dict:
    from .llm import call_llm_json
    from .prompts.extract import EXTRACT_SYSTEM, build_extract_user
    from ..schemas import ExtractResult

    result = call_llm_json(
        "extract", jd_id, EXTRACT_SYSTEM, build_extract_user(cleaned_text),
        mock_fn=_mock_extract,
    )
    return ExtractResult(**result).model_dump()


# ---------- 归岗 ----------

def assign_position(job_title: str) -> tuple[str | None, str]:
    """返回 (position_id, 状态说明)。未命中则创建 pending_review 岗位。"""
    from .assign import normalize_title

    conn = get_conn()
    norm = normalize_title(job_title)
    row = conn.execute("SELECT position_id, status FROM position WHERE name=?", (norm,)).fetchone()
    if row:
        return row["position_id"], "matched"
    row = conn.execute(
        "SELECT position_id FROM position_alias WHERE alias=?", (norm,)
    ).fetchone()
    if row:
        return row["position_id"], "alias"
    pid = new_id("pos")
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, norm, "pending_review", now_iso()),
    )
    conn.commit()
    return pid, "new_pending_review"


# ---------- 工序④ LLM#2 消歧 ----------

def _dict_candidates(categories: set[str]) -> list[str]:
    conn = get_conn()
    if not categories:
        return []
    placeholders = ",".join("?" * len(categories))
    rows = conn.execute(
        f"SELECT std_name FROM competency_dict WHERE status='active' AND category IN ({placeholders})",
        tuple(categories),
    ).fetchall()
    return [r["std_name"] for r in rows]


def _mock_disambiguate(system_prompt: str, user_prompt: str) -> dict:
    return {"merges": []}


def disambiguate_items(jd_id: str, items: list[dict]) -> list[dict]:
    """对抽取项做同义合并 + 标准名归一；新标准名被动写词典 llm_pending。"""
    from .llm import call_llm_json
    from .prompts.disambiguate import DISAMBIGUATE_SYSTEM, build_disambiguate_user
    from ..schemas import DisambiguateResult

    if not items:
        return items
    names = [it["name"] for it in items]
    candidates = _dict_candidates({it["category"] for it in items})

    merge_map: dict[str, str] = {}
    if candidates:  # 词典为空时跳过 LLM#2，仅代码级处理
        result = call_llm_json(
            "disambiguate", jd_id, DISAMBIGUATE_SYSTEM,
            build_disambiguate_user(names, candidates), mock_fn=_mock_disambiguate,
        )
        merges = DisambiguateResult(**result).merges
        merge_map = {m["from"]: m["to"] for m in merges}

    conn = get_conn()
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for it in items:
        std = merge_map.get(it["name"], it["name"])
        it = {**it, "name": std}
        key = (std, it["category"])
        if key in seen:  # 代码级精确去重兜底
            continue
        seen.add(key)
        out.append(it)
        # 被动回写词典（已有则跳过）
        exists = conn.execute(
            "SELECT 1 FROM competency_dict WHERE std_name=? AND category=?",
            (std, it["category"]),
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO competency_dict(std_name, category, definition, aliases_json,"
                " exclusions_json, created_by, status, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (std, it["category"], None, "[]", "[]", "llm_pending", "active", now_iso(), now_iso()),
            )
    conn.commit()
    return out


# ---------- 编排：单 JD 全流程 ----------

def run_parse_pipeline(jd_id: str) -> None:
    """imported → parsing → parsed / failed。产物逐工序落库。"""
    conn = get_conn()
    row = conn.execute("SELECT raw_text FROM jd_record WHERE jd_id=?", (jd_id,)).fetchone()
    if row is None:
        return
    conn.execute("UPDATE jd_record SET status='parsing' WHERE jd_id=?", (jd_id,))
    conn.commit()
    try:
        cleaned, low_conf = clean_jd(row["raw_text"])
        conn.execute(
            "UPDATE jd_record SET cleaned_text=?, low_confidence=? WHERE jd_id=?",
            (cleaned, int(low_conf), jd_id),
        )
        conn.commit()

        extracted = extract_items(jd_id, cleaned)
        conn.execute(
            "UPDATE jd_record SET raw_items_json=?, job_title=? WHERE jd_id=?",
            (json.dumps(extracted["items"], ensure_ascii=False), extracted["job_title"], jd_id),
        )
        conn.commit()

        position_id, _ = assign_position(extracted["job_title"])
        conn.execute("UPDATE jd_record SET position_id=? WHERE jd_id=?", (position_id, jd_id))
        conn.commit()

        std_items = disambiguate_items(jd_id, extracted["items"])
        conn.execute(
            "UPDATE jd_record SET std_items_json=?, status='parsed', error_msg=NULL WHERE jd_id=?",
            (json.dumps(std_items, ensure_ascii=False), jd_id),
        )
        conn.commit()
    except Exception as e:  # noqa: BLE001 - 单 JD 失败不阻塞其他
        conn.execute(
            "UPDATE jd_record SET status='failed', error_msg=? WHERE jd_id=?",
            (str(e), jd_id),
        )
        conn.commit()
