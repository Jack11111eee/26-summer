"""LLM 客户端封装：JSON 模式 + 失败重试 + llm_trace 落库 + mock 兜底。

LLM_PROVIDER=mock 时用规则模拟输出，离线可跑通全流程；切到 deepseek 需配 LLM_API_KEY。
"""
import json
from typing import Any

from .. import config
from ..db import get_conn
from .pipeline import now_iso, new_id


def _record_trace(call_type: str, ref_id: str, attempt: int,
                  prompt: str, response: str | None, success: bool, error: str | None) -> str:
    """落一条 llm_trace 审计行并返回 trace_id（05-01：供下游 trace_link 关联）。"""
    trace_id = new_id("t")
    conn = get_conn()
    conn.execute(
        "INSERT INTO llm_trace(trace_id, call_type, ref_id, attempt, prompt, response, success, error, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (trace_id, call_type, ref_id, attempt, prompt, response, int(success), error, now_iso()),
    )
    conn.commit()
    return trace_id


def _chat(system_prompt: str, user_prompt: str) -> str:
    """真实 LLM 调用，JSON 模式。DeepSeek 要求 prompt 中含 'json' 字样。"""
    from openai import OpenAI

    client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    resp = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return resp.choices[0].message.content


def call_llm_json(call_type: str, ref_id: str, system_prompt: str, user_prompt: str,
                  mock_fn=None, trace_out: list | None = None) -> dict[str, Any]:
    """调 LLM 并解析 JSON。失败带错误信息重试 LLM_RETRY 次，全败抛异常。

    mock_fn: provider=mock 时替代真实调用的函数，签名 (system_prompt, user_prompt)->dict。
    trace_out: 非 None 时把成功产出 trace 的 trace_id append 进去（失败重试路径不追加——
    仅成功 trace 供下游 trace_link 关联）。
    """
    last_err: str | None = None
    for attempt in range(1, config.LLM_RETRY + 2):  # 首次 + 重试 LLM_RETRY 次
        prompt_for_trace = system_prompt + "\n\n" + user_prompt
        try:
            if config.LLM_PROVIDER == "mock":
                result = mock_fn(system_prompt, user_prompt) if mock_fn else {}
                raw = json.dumps(result, ensure_ascii=False)
            else:
                raw = _chat(system_prompt, user_prompt)
                result = json.loads(raw)
            trace_id = _record_trace(call_type, ref_id, attempt, prompt_for_trace, raw, True, None)
            if trace_out is not None:
                trace_out.append(trace_id)
            return result
        except Exception as e:  # noqa: BLE001 - 网络/解析错误统一重试
            last_err = str(e)
            _record_trace(call_type, ref_id, attempt, prompt_for_trace, None, False, last_err)
    raise RuntimeError(f"LLM 调用 {call_type} 重试 {config.LLM_RETRY + 1} 次仍失败: {last_err}")
