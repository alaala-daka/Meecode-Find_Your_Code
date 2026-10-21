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
from .security import CURRENT_RATE_KEY

T = TypeVar("T", bound=BaseModel)

# 按解析后的 (base_url, api_key) 缓存:{api_key:"x"} 与 {base_url:默认, api_key:"x"} 命中同一客户端
_CLIENTS_MAX = 32
_clients: dict[tuple[str, str], AsyncOpenAI] = {}

# ---------- 并发席位(N4 预留席 + F3 每 key 帽 + 饱和快速失败) ----------
# _llm_sem:全局总帽 LLM_MAX_CONCURRENCY,语义不变 —— 并发在飞的 LLM provider 请求。
# _general_sem:通用池(= 全局 - LLM_RESERVED_SEATS),仅「既有 key」(当前已持有席位的
# rate_key)占用;既有 key 摩不进 _llm_sem 中的预留额度,故新/低活跃 key 恒有
# ≥LLM_RESERVED_SEATS 席可用(预留席模型:通用池 + 预留席 = 全局,既有 key 只可用通用池)。
_llm_sem = asyncio.Semaphore(config.LLM_MAX_CONCURRENCY)
_general_sem = asyncio.Semaphore(
    max(0, config.LLM_MAX_CONCURRENCY - config.LLM_RESERVED_SEATS))

_key_sems: dict[str, asyncio.Semaphore] = {}   # per-key 并发帽(F3);LRU 序,最旧在前
_active_keys: dict[str, int] = {}              # rate_key → 在飞请求计数(含等待全局席者);归零即移除(重新算「新 key」)

_KEY_SEMS_MAX = 4096   # per-key 信号量表上界(F4 纪律):随 epoch 轮换/匿名 IP 无界增长的封口


class SeatBusyError(TimeoutError):
    """席位获取超时(全局/通用池/每 key 任一维度饱和):N4 快速失败,不无限排队。

    继承 TimeoutError 保留超时语义;LLM 路由映射 HTTP 503「服务繁忙，请稍后重试」
    (F6 脱敏),chat_json 不得当作输出失败重试、不落 usage 行(无 provider 往返)。
    """


def _reset_seats_for_test() -> None:
    """重建全部席位信号量(容量取当前 config),清空 per-key/active 状态。测试隔离用。"""
    global _llm_sem, _general_sem
    _llm_sem = asyncio.Semaphore(config.LLM_MAX_CONCURRENCY)
    _general_sem = asyncio.Semaphore(
        max(0, config.LLM_MAX_CONCURRENCY - config.LLM_RESERVED_SEATS))
    _key_sems.clear()
    _active_keys.clear()


def _key_sem_idle(key: str, sem: asyncio.Semaphore) -> bool:
    """零占用(无持有者/无等待者)才算可淘汰:淘汰占用中的信号量会破坏 per-key 记账。"""
    if key in _active_keys:
        return False
    waiters = getattr(sem, "_waiters", None)
    if waiters and any(not w.done() for w in waiters):
        return False
    return sem._value == config.LLM_MAX_CONCURRENCY_PER_KEY


def _key_sem(key: str) -> asyncio.Semaphore:
    """LRU 取/建 per-key 帽:命中挪到最新端;插入前淘汰零占用的最旧项(F4 纪律)。

    全部占用时允许暂时超 _KEY_SEMS_MAX(正确性优先于硬上界);被淘汰的旧持有者
    释放走获取时捕获的旧对象,自洽不串账。
    """
    sem = _key_sems.pop(key, None)
    if sem is not None:
        _key_sems[key] = sem   # LRU:命中即挪到最新端
        return sem
    while len(_key_sems) >= _KEY_SEMS_MAX:
        for k, s in _key_sems.items():   # dict 序即 LRU 序:最旧在前
            if _key_sem_idle(k, s):
                del _key_sems[k]
                break
        else:
            break   # 全部占用:不淘汰
    sem = asyncio.Semaphore(config.LLM_MAX_CONCURRENCY_PER_KEY)
    _key_sems[key] = sem
    return sem


async def _acquire(sem: asyncio.Semaphore) -> None:
    """限时获取一个席位;超时抛 SeatBusyError(N4:饱和快速失败,不无限排队)。"""
    try:
        await asyncio.wait_for(sem.acquire(), timeout=config.LLM_ACQUIRE_TIMEOUT)
    except TimeoutError as exc:   # 3.11+ asyncio.TimeoutError 即内置 TimeoutError
        raise SeatBusyError from exc


@asynccontextmanager
async def _seat():
    """provider 往返期间的并发席位:per-key 帽 → (既有 key)通用池 → 全局帽。

    取键经 security.CURRENT_RATE_KEY(N3,不透传 Request);获取顺序固定(per-key 最先:
    同 key 排队不占全局席),全部限时快速失败(SeatBusyError);任一获取失败即抛,
    已持有席位在对应 finally 全部归还 —— 正常/异常/断开任一退出路径不泄漏席位(F5)。

    预留席分类防垄断(复审 Finding #1):分类与注册在**同一同步段**(无 await)完成,
    并发同 key 请求只有首个计「新 key」可走非通用席,其余一律走通用池 —— 同 key
    ramp-up 冲刺在全局饱和下堆在 _llm_sem 上时,吃不满 LLM_RESERVED_SEATS 预留池,
    真正的新 key 不会被挤成 503。注册先行于 _key_sem 获取,亦保证在飞 key 的
    per-key 信号量不被 LRU 淘汰(Finding #2)。
    """
    key = CURRENT_RATE_KEY.get()
    existing = _active_keys.get(key, 0) > 0    # 分类+注册原子:并发同 key 仅首个算「新 key」
    _active_keys[key] = _active_keys.get(key, 0) + 1
    try:
        ksem = _key_sem(key)
        await _acquire(ksem)
        try:
            if existing:
                await _acquire(_general_sem)   # 既有 key:预留席不向其开放
            try:
                await _acquire(_llm_sem)
                try:
                    yield
                finally:
                    _llm_sem.release()
            finally:
                if existing:
                    _general_sem.release()
        finally:
            ksem.release()
    finally:
        left = _active_keys.get(key, 1) - 1
        if left > 0:
            _active_keys[key] = left
        else:
            _active_keys.pop(key, None)


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
        except SeatBusyError:
            raise   # 席位饱和快速失败:无 provider 往返,不重试、不落 usage 行(N4)
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
        async with _seat():   # 每轮 provider 往返持有席位,流抽干即释放;获取超时→SeatBusyError(无往返,不落 usage)
            t0 = time.monotonic()
            prompt = completion = 0
            ok = 0
            content_parts: list[str] = []
            tool_calls: dict[int, dict] = {}  # index -> {id, name, arguments}
            finish: str | None = None
            try:
                stream = await client.chat.completions.create(**kwargs)

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
        # 席位已释放:web_search 与轮次间隙不占席(§5.1)

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
