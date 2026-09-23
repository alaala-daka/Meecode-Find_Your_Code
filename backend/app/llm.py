"""LLM 调用封装:OpenAI 兼容接口 + JSON mode + Pydantic 校验重试。
支持请求级覆盖(设置区自定义模型):空/缺省字段回落 env;客户端按解析后键值缓存。"""
from __future__ import annotations

import json
from typing import Iterator, Type, TypeVar

from openai import OpenAI

from . import config
from .schemas import BaseModel, LLMOverride

T = TypeVar("T", bound=BaseModel)

# 按解析后的 (base_url, api_key) 缓存:{api_key:"x"} 与 {base_url:默认, api_key:"x"} 命中同一客户端
_CLIENTS_MAX = 32
_clients: dict[tuple[str, str], OpenAI] = {}


def _resolve(llm: LLMOverride | None) -> tuple[OpenAI, str]:
    """空串/全空白字段一律 strip 后回落 env;返回 (客户端, 模型名)。"""
    base_url = ((llm.base_url or "").strip() if llm else "") or config.LLM_BASE_URL
    api_key = ((llm.api_key or "").strip() if llm else "") or config.LLM_API_KEY
    model = ((llm.model or "").strip() if llm else "") or config.LLM_MODEL
    if llm and (llm.base_url or "").strip():
        # 防御性复检:schemas 校验过的请求仍在此拦截（如内部直接构造 LLMOverride 的调用方）
        from .urlguard import validate_base_url
        base_url = validate_base_url(base_url)
    key = (base_url, api_key)
    if key not in _clients:
        while len(_clients) >= _CLIENTS_MAX:
            _clients.pop(next(iter(_clients)))   # FIFO 淘汰最旧，保住高频键
        _clients[key] = OpenAI(base_url=base_url, api_key=api_key)
    return _clients[key], model


def _configured(llm: LLMOverride | None) -> bool:
    # env 已配置,或请求级带了 api_key(此时 base_url/model 可回落 env)
    return config.llm_configured() or bool(llm and (llm.api_key or "").strip())


def chat_json(
    system: str,
    user: str,
    model: Type[T],
    *,
    temperature: float | None = None,
    llm: LLMOverride | None = None,
) -> T:
    """请求 LLM 输出 JSON,并用 Pydantic 模型校验;失败时把错误回填重试一次。"""
    if not _configured(llm):
        raise RuntimeError("LLM 未配置:请在 backend/.env 填入 LLM_API_KEY,或在设置区填写自定义模型")

    client, model_name = _resolve(llm)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_error: Exception | None = None

    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=config.LLM_TEMPERATURE if temperature is None else temperature,
                response_format={"type": "json_object"},
            )
            text = resp.choices[0].message.content or ""
            return model.model_validate(json.loads(_strip_code_fence(text)))
        except Exception as exc:  # JSON 解析或 schema 校验失败 → 回填重试
            last_error = exc
            messages.append({"role": "assistant", "content": locals().get("text", "")})
            messages.append(
                {
                    "role": "user",
                    "content": f"上一次输出无法解析或不符合要求:{exc}。请只输出符合要求的 JSON,不要输出任何其他内容。",
                }
            )

    raise RuntimeError(f"LLM 输出连续两次不符合要求:{last_error}")


def _strip_code_fence(text: str) -> str:
    """部分模型会用 ```json ... ``` 包裹输出,剥掉再解析。"""
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


# ---------- 阅读器伴读:流式 + 可选 Tavily 联网搜索 ----------

MAX_TOOL_ROUNDS = 4  # 工具循环上限;之后强制一轮无 tools 的文本作答


def chat_stream_events(
    *,
    system: str,
    messages: list[dict],
    llm: LLMOverride | None = None,
    tavily_key: str | None = None,
    temperature: float | None = None,
) -> Iterator[dict]:
    """流式对话生成器:delta 立即透出;模型请求工具时执行 web_search 并续轮。

    OpenAI 流式 tool_calls 是增量片段:每个片段带 index,id/name 通常只出现在
    该 index 的首个片段,function.arguments 为字符串碎片,必须按 index 归并拼接。
    """
    from .agent.websearch import TAVILY_TOOL, web_search  # 局部导入,避免模块环

    client, model_name = _resolve(llm)
    convo: list[dict] = [{"role": "system", "content": system}, *messages]
    tools = [TAVILY_TOOL] if tavily_key else None

    for round_no in range(MAX_TOOL_ROUNDS + 1):
        use_tools = tools if (tools and round_no < MAX_TOOL_ROUNDS) else None  # 末轮强制纯文本
        kwargs: dict = {
            "model": model_name,
            "messages": convo,
            "stream": True,
            "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
        }
        if use_tools:
            kwargs["tools"] = use_tools
        stream = client.chat.completions.create(**kwargs)

        content_parts: list[str] = []
        tool_calls: dict[int, dict] = {}  # index -> {id, name, arguments}
        finish: str | None = None

        for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta is None:
                continue
            if delta.content:
                content_parts.append(delta.content)
                yield {"type": "delta", "text": delta.content}  # 立即透出(含工具轮前导语)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = tool_calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] += tc.function.name
                        if tc.function.arguments:
                            slot["arguments"] += tc.function.arguments
            if choice.finish_reason:
                finish = choice.finish_reason

        if finish == "tool_calls" and tool_calls and use_tools:
            convo.append(
                {
                    "role": "assistant",
                    "content": "".join(content_parts) or None,
                    "tool_calls": [
                        {
                            "id": tool_calls[i]["id"],
                            "type": "function",
                            "function": {
                                "name": tool_calls[i]["name"],
                                "arguments": tool_calls[i]["arguments"] or "{}",
                            },
                        }
                        for i in sorted(tool_calls)
                    ],
                }
            )
            for i in sorted(tool_calls):
                tc = tool_calls[i]
                try:
                    args = json.loads(tc["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                query = str(args.get("query", "")).strip()
                yield {"type": "status", "stage": "searching", "query": query}
                try:
                    results = web_search(query, tavily_key) if query else []
                except Exception as exc:
                    results = [{"error": f"搜索失败:{exc}"}]
                convo.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(results, ensure_ascii=False),
                    }
                )
            continue

        yield {"type": "done"}
        return
