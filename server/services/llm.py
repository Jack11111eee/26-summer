"""LLM 客户端封装：JSON 模式 + 失败重试 + llm_trace 落库 + mock 兜底。

LLM_PROVIDER=mock 时用规则模拟输出，离线可跑通全流程；
LLM_PROVIDER=deepseek 走 OpenAI 兼容 chat.completions（需 LLM_API_KEY）；
LLM_PROVIDER=anthropic 走 Anthropic Messages 协议（urllib 零依赖实现——
2026-09-06 中转上行 glm-5.3-flash 未开 chat 接口，仅 Responses/Messages，
chat 路由长 prompt 100% 503 no_available_providers）。
"""
import json
import urllib.request
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
    """真实 LLM 调用，OpenAI 兼容 chat.completions，JSON 模式。"""
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


def _strip_code_fence(text: str) -> str:
    """剥掉 LLM 偶发包裹的 ```json ...``` 围栏（解析前归一）。"""
    t = text.strip()
    if t.startswith("```"):
        first_newline = t.find("\n")
        if first_newline != -1:
            t = t[first_newline + 1:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _messages(system_prompt: str, user_prompt: str) -> str:
    """Anthropic Messages 协议调用（urllib 实现，无 SDK 依赖）。

    中转类服务常仅暴露 Messages/Responses 接口（chat 不可用），此函数提供
    协议适配：system 独立参数、content 块拼接、code fence 归一。
    """
    body = json.dumps({
        "model": config.LLM_MODEL,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
        "max_tokens": 8192,
        "temperature": 0,
    }).encode()
    url = config.LLM_BASE_URL.rstrip("/") + "/messages"
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "x-api-key": config.LLM_API_KEY,
        "Authorization": f"Bearer {config.LLM_API_KEY}",  # 中转普遍两者都认
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read())
    return _strip_code_fence(
        "".join(c.get("text", "") for c in data.get("content", []) if c.get("type") == "text")
    )


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
            elif config.LLM_PROVIDER == "anthropic":
                raw = _messages(system_prompt, user_prompt)
                result = json.loads(raw)
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
