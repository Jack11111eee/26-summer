"""长输入精炼（07 文档 §8，N5/N6）。

token 数近似 len(text)/2（中文一字≈一 token 偏多，取保守近似）。
超过 REFINE_MIN_TOKENS 才走 P-refine；原文 SHA256 归档 context_raw，可回溯。
"""
import hashlib

from .. import config
from ..db import get_conn
from .llm import call_llm_json
from .pipeline import new_id, now_iso
from .prompts.refine import REFINE_SYSTEM, refine_prompt


def _approx_tokens(text: str) -> int:
    return len(text) // 2


def _mock_refine(system_prompt: str, user_prompt: str) -> dict:
    """离线 mock：截取前 200 字作为精炼结果。"""
    text = user_prompt.split("\n", 1)[-1]
    return {"refined": text[:200]}


def refine_user_input(text: str) -> tuple[str, str | None]:
    """长输入精炼。返回 (refined_text, raw_hash|None)；未触发阈值时原样返回 (text, None)。"""
    if _approx_tokens(text) <= config.REFINE_MIN_TOKENS:
        return text, None

    raw_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    conn = get_conn()
    exists = conn.execute("SELECT 1 FROM context_raw WHERE hash=?", (raw_hash,)).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO context_raw(raw_id, hash, full_text, created_at) VALUES(?,?,?,?)",
            (new_id("raw"), raw_hash, text, now_iso()),
        )
        conn.commit()

    result = call_llm_json(
        "refine", raw_hash, REFINE_SYSTEM, refine_prompt(text),
        mock_fn=_mock_refine,
    )
    return result["refined"], raw_hash
