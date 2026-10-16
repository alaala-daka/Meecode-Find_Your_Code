"""LLM 调用封装：OpenAI 兼容接口 + JSON mode + Pydantic 校验重试。

复用 Concept_Simplify 的做法：JSON 解析或 schema 校验失败时把错误回填重试一次。
"""
from __future__ import annotations

import json
import time
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from .. import config, llm_usage

T = TypeVar("T", bound=BaseModel)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY,
                         timeout=30.0, max_retries=1)
    return _client


def _strip_code_fence(text: str) -> str:
    """部分模型用 ```json ... ``` 包裹输出，剥掉再解析。"""
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def chat_json(*, system: str, user: str, model: Type[T], route: str,
              repo_id: int | None = None) -> T:
    """请求 LLM 输出 JSON 并用 Pydantic 校验；失败回填错误重试一次。

    每次 create 落一行 llm_usage（口径同 app/llm.chat_json）。
    """
    if not config.llm_configured():
        raise RuntimeError("LLM 未配置：请在 backend/.env 填入 LLM_API_KEY")

    client = _get_client()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_error: Exception | None = None
    text = ""

    for _attempt in range(2):
        t0 = time.monotonic()
        prompt = completion = 0
        try:
            resp = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=messages,
                temperature=config.LLM_TEMPERATURE,
                response_format={"type": "json_object"},
            )
            usage = getattr(resp, "usage", None)
            prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion = int(getattr(usage, "completion_tokens", 0) or 0)
            text = resp.choices[0].message.content or ""
            result = model.model_validate(json.loads(_strip_code_fence(text)))
        except Exception as exc:
            llm_usage.record_usage(
                route=route, repo_id=repo_id, model=config.LLM_MODEL,
                prompt_tokens=prompt, completion_tokens=completion,
                ok=0, latency_ms=int((time.monotonic() - t0) * 1000))
            last_error = exc
            messages.append({"role": "assistant", "content": text})
            messages.append({
                "role": "user",
                "content": f"上一次输出无法解析或不符合要求：{exc}。请只输出符合要求的 JSON。",
            })
        else:
            llm_usage.record_usage(
                route=route, repo_id=repo_id, model=config.LLM_MODEL,
                prompt_tokens=prompt, completion_tokens=completion,
                ok=1, latency_ms=int((time.monotonic() - t0) * 1000))
            return result

    raise RuntimeError(f"LLM 输出连续两次不符合要求：{last_error}")
