"""LLM 调用封装:OpenAI 兼容接口 + JSON mode + Pydantic 校验重试。
支持请求级覆盖(设置区自定义模型):空/缺省字段回落 env;客户端按解析后键值缓存。

全链路异步(Task 4):AsyncOpenAI + 全局并发信号量;provider 往返期间持有席位,
解析/校验/联网搜索不占位,事件循环不再被 20-60s 的 LLM 调用钉住。"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Type, TypeVar

import httpx
from openai import AsyncOpenAI

from . import config, llm_usage
from .schemas import BaseModel, LLMOverride

T = TypeVar("T", bound=BaseModel)

# 按解析后的 (base_url, api_key) 缓存:{api_key:"x"} 与 {base_url:默认, api_key:"x"} 命中同一客户端
_CLIENTS_MAX = 32
_clients: dict[tuple[str, str], AsyncOpenAI] = {}

# 全进程 LLM provider 并发上限(每 rate_key 细分额度在 Task 5 接入,此处仅全局)
_llm_sem = asyncio.Semaphore(config.LLM_MAX_CONCURRENCY)


def _make_async_client(*, base_url: str, api_key: str) -> AsyncOpenAI:
    """构建 AsyncOpenAI 客户端(N6:自持 httpx.AsyncClient,显式超时、不跟随重定向)。"""
    return AsyncOpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=config.LLM_TIMEOUT,
        max_retries=1,
        http_client=httpx.AsyncClient(follow_redirects=False),
    )


async def _resolve(llm: LLMOverride | None) -> tuple[AsyncOpenAI, str]:
    """空串/全空白字段一律 strip 后回落 env;返回 (客户端, 模型名)。"""
    base_url = ((llm.base_url or "").strip() if llm else "") or config.LLM_BASE_URL
    api_key = ((llm.api_key or "").strip() if llm else "") or config.LLM_API_KEY
    model = ((llm.model or "").strip() if llm else "") or config.LLM_MODEL
    if llm and (llm.base_url or "").strip():
        # 防御性复检:schemas 校验过的请求仍在此拦截（如内部直接构造 LLMOverride 的调用方）
        from .urlguard import validate_base_url_async
        base_url = await validate_base_url_async(base_url)   # 非阻塞 DNS 校验(F1)
    key = (base_url, api_key)
    if key not in _clients:
        while len(_clients) >= _CLIENTS_MAX:
            evicted = _clients.pop(next(iter(_clients)))   # FIFO 淘汰最旧，保住高频键
            try:
                await evicted.close()   # F4:淘汰即关闭,不裸丢底层连接
            except Exception:
                pass
        _clients[key] = _make_async_client(base_url=base_url, api_key=api_key)
    return _clients[key], model


def _configured(llm: LLMOverride | None) -> bool:
    # env 已配置,或请求级带了 api_key(此时 base_url/model 可回落 env)
    return config.llm_configured() or bool(llm and (llm.api_key or "").strip())


@asynccontextmanager
async def _seat():
    """全局并发席位:N4 限时获取,超限快速失败,不无限排队。"""
    await asyncio.wait_for(_llm_sem.acquire(), timeout=config.LLM_ACQUIRE_TIMEOUT)
    try:
        yield
    finally:
        _llm_sem.release()


async def chat_json(
    system: str,
    user: str,
    model: Type[T],
    *,
    route: str,
    repo_id: int | None = None,
    temperature: float | None = None,
    llm: LLMOverride | None = None,
) -> T:
    """请求 LLM 输出 JSON,并用 Pydantic 模型校验;失败时把错误回填重试一次。

    每次 create 落一行 llm_usage:成功 ok=1;解析/校验失败 attempt ok=0 且 tokens
    记 resp.usage 实得值(成本已发生);HTTP/网络异常 ok=0、tokens 0。
    """
    if not _configured(llm):
        raise RuntimeError("LLM 未配置:请在 backend/.env 填入 LLM_API_KEY,或在设置区填写自定义模型")

    client, model_name = await _resolve(llm)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_error: Exception | None = None

    for attempt in range(2):
        t0 = time.monotonic()
        prompt = completion = 0
        try:
            async with _seat():   # provider 往返全程占席;解析/校验不占
                resp = await client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=config.LLM_TEMPERATURE if temperature is None else temperature,
                    response_format={"type": "json_object"},
                )
            usage = getattr(resp, "usage", None)
            prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion = int(getattr(usage, "completion_tokens", 0) or 0)
            text = resp.choices[0].message.content or ""
            result = model.model_validate(json.loads(_strip_code_fence(text)))
        except Exception as exc:  # JSON 解析或 schema 校验失败 → 回填重试
            llm_usage.record_usage(
                route=route, repo_id=repo_id, model=model_name,
                prompt_tokens=prompt, completion_tokens=completion,
                ok=0, latency_ms=int((time.monotonic() - t0) * 1000))
            last_error = exc
            messages.append({"role": "assistant", "content": locals().get("text", "")})
            messages.append(
                {
                    "role": "user",
                    "content": f"上一次输出无法解析或不符合要求:{exc}。请只输出符合要求的 JSON,不要输出任何其他内容。",
                }
            )
        else:
            llm_usage.record_usage(
                route=route, repo_id=repo_id, model=model_name,
                prompt_tokens=prompt, completion_tokens=completion,
                ok=1, latency_ms=int((time.monotonic() - t0) * 1000))
            return result

    # F6:不把原始异常文本(可能含 URL/主机/密钥片段)带出到用户可见错误
    raise RuntimeError("LLM 输出连续两次不符合要求")


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


async def chat_stream_events(
    *,
    system: str,
    messages: list[dict],
    route: str,
    repo_id: int | None = None,
    llm: LLMOverride | None = None,
    tavily_key: str | None = None,
    temperature: float | None = None,
) -> AsyncIterator[dict]:
    """流式对话生成器:delta 立即透出;模型请求工具时执行 web_search 并续轮。

    OpenAI 流式 tool_calls 是增量片段:每个片段带 index,id/name 通常只出现在
    该 index 的首个片段,function.arguments 为字符串碎片,必须按 index 归并拼接。
    """
    from .agent.websearch import TAVILY_TOOL, web_search  # 局部导入,避免模块环

    client, model_name = await _resolve(llm)
    convo: list[dict] = [{"role": "system", "content": system}, *messages]
    tools = [TAVILY_TOOL] if tavily_key else None
    deadline = time.monotonic() + config.LLM_STREAM_TOTAL_TIMEOUT  # 墙钟总超时(N5)

    for round_no in range(MAX_TOOL_ROUNDS + 1):
        if time.monotonic() > deadline:
            yield {"type": "error", "message": "生成超时"}
            return
        use_tools = tools if (tools and round_no < MAX_TOOL_ROUNDS) else None  # 末轮强制纯文本
        kwargs: dict = {
            "model": model_name,
            "messages": convo,
            "stream": True,
            "stream_options": {"include_usage": True},  # 流式 usage 仅随末 chunk 上报（§4.2）
            "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
        }
        if use_tools:
            kwargs["tools"] = use_tools
        t0 = time.monotonic()
        prompt = completion = 0
        ok = 0
        try:
            async with _seat():   # 每轮 provider 往返持有席位,流抽干即释放
                stream = await client.chat.completions.create(**kwargs)

                content_parts: list[str] = []
                tool_calls: dict[int, dict] = {}  # index -> {id, name, arguments}
                finish: str | None = None

                async for chunk in stream:
                    usage = getattr(chunk, "usage", None)  # usage chunk choices 为空,先于过滤捕获
                    if usage is not None:
                        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
                        completion = int(getattr(usage, "completion_tokens", 0) or 0)
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
            ok = 1  # 流正常走完
        except GeneratorExit:
            ok = 1  # 客户端断流:调用已成功返流、成本已发生,计 ok(§4.2)
            raise
        finally:
            llm_usage.record_usage(
                route=route, repo_id=repo_id, model=model_name,
                prompt_tokens=prompt, completion_tokens=completion,
                ok=ok, latency_ms=int((time.monotonic() - t0) * 1000))

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
                    results = await web_search(query, tavily_key) if query else []
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
