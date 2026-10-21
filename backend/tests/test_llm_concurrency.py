"""Task 5 并发细化:每 key 并发帽 + 预留席 + 饱和快速失败 + 断开/泄漏回收(N3/N4/F3/F4/F5)。

席位模型(llm._seat):
- `_llm_sem`:全局总帽 LLM_MAX_CONCURRENCY(语义不变:并发在飞的 provider 请求);
- `_general_sem`:通用池 LLM_MAX_CONCURRENCY - LLM_RESERVED_SEATS,仅「既有 key」
  (当前已持有席位的 rate_key)占用 —— 既有 key 摩不到 _llm_sem 中预留的
  LLM_RESERVED_SEATS 席,新/低活跃 key 恒有预留席可用(N4);
- `_key_sems[rate_key]`:每 rate_key 并发帽 LLM_MAX_CONCURRENCY_PER_KEY(F3);
- 全部限时获取(LLM_ACQUIRE_TIMEOUT),超时抛 llm.SeatBusyError → HTTP 503(N4)。
"""
import asyncio
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app import config, llm, llm_usage, security


# ---------- 每 key 并发帽(N3/F3) ----------


async def test_per_key_cap_limits_same_key(monkeypatch):
    monkeypatch.setattr(config, "LLM_MAX_CONCURRENCY_PER_KEY", 2)
    llm._reset_seats_for_test()
    security.CURRENT_RATE_KEY.set("ip:1.2.3.4")
    got = 0

    async def holder():
        nonlocal got
        async with llm._seat():
            got += 1
            await asyncio.sleep(0.05)

    await asyncio.gather(*[holder() for _ in range(5)])
    assert got == 5  # 最终都能跑完,但并发峰值受 per-key 帽约束(下方断言峰值)


async def test_per_key_peak_concurrency(monkeypatch):
    monkeypatch.setattr(config, "LLM_MAX_CONCURRENCY_PER_KEY", 2)
    monkeypatch.setattr(config, "LLM_ACQUIRE_TIMEOUT", 5)
    llm._reset_seats_for_test()
    security.CURRENT_RATE_KEY.set("ip:1.2.3.4")
    peak = 0
    cur = 0

    async def holder():
        nonlocal peak, cur
        async with llm._seat():
            cur += 1
            peak = max(peak, cur)
            await asyncio.sleep(0.02)
            cur -= 1

    await asyncio.gather(*[holder() for _ in range(6)])
    assert peak <= 2


# ---------- 饱和快速失败(N4) ----------


async def test_acquire_timeout_fast_fails(monkeypatch):
    monkeypatch.setattr(config, "LLM_MAX_CONCURRENCY", 1)
    monkeypatch.setattr(config, "LLM_ACQUIRE_TIMEOUT", 0.05)
    llm._reset_seats_for_test()
    security.CURRENT_RATE_KEY.set("ip:9.9.9.9")

    async def hold():
        async with llm._seat():
            await asyncio.sleep(0.3)

    t = asyncio.create_task(hold())
    await asyncio.sleep(0.01)
    security.CURRENT_RATE_KEY.set("ip:8.8.8.8")
    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        async with llm._seat():
            pass
    await t


async def test_seat_released_on_exception(monkeypatch):
    """任一退出路径(异常/断开)席位必回收:泄漏一个席位 = 慢动作全局故障(F5)。"""
    monkeypatch.setattr(config, "LLM_MAX_CONCURRENCY", 1)
    monkeypatch.setattr(config, "LLM_ACQUIRE_TIMEOUT", 0.05)
    llm._reset_seats_for_test()
    security.CURRENT_RATE_KEY.set("ip:2.2.2.2")
    with pytest.raises(ValueError):
        async with llm._seat():
            raise ValueError("boom")
    assert llm._llm_sem._value == config.LLM_MAX_CONCURRENCY
    assert llm._key_sems["ip:2.2.2.2"]._value == config.LLM_MAX_CONCURRENCY_PER_KEY
    assert llm._active_keys == {}
    # 席位已回收:同一 key 立即可再取席
    async with llm._seat():
        pass


async def test_chat_json_seat_timeout_no_retry_no_usage(monkeypatch):
    """饱和快速失败:SeatBusyError 不重试、不落 usage 行,快速直达调用方。"""
    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(config, "LLM_API_KEY", "k")
    monkeypatch.setattr(config, "LLM_MAX_CONCURRENCY", 0)   # 全局 0 席:一切饱和
    monkeypatch.setattr(config, "LLM_ACQUIRE_TIMEOUT", 0.05)
    llm._reset_seats_for_test()
    security.CURRENT_RATE_KEY.set("ip:7.7.7.7")

    creates: list[int] = []

    async def _create(**_kw):
        creates.append(1)
        raise AssertionError("provider 不应被调用")

    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))

    async def fake_resolve(*_a, **_k):
        return (fake, "m")

    monkeypatch.setattr(llm, "_resolve", fake_resolve)

    entries: list[int] = []
    real_seat = llm._seat

    @asynccontextmanager
    async def counting_seat():
        entries.append(1)
        async with real_seat():
            yield

    monkeypatch.setattr(llm, "_seat", counting_seat)

    from app.schemas import RewriteResult
    t0 = time.monotonic()
    with pytest.raises(llm.SeatBusyError):
        await llm.chat_json("sys", "user", RewriteResult, route=llm_usage.ROUTE_ROOTS)
    assert time.monotonic() - t0 < 1.0      # 快速失败,不排队
    assert entries == [1]                    # 不重试第二次取席
    assert creates == []                     # 无 provider 往返
    assert llm_usage._buf == []              # 无 create 不落 usage 行(计量口径)


# ---------- 预留席(N4:新/低活跃 key 不被既有大户饿死) ----------


async def test_reserved_seats_new_key_gets_in_when_general_full(monkeypatch):
    """通用池被既有 key 占满后,新 key 仍能拿到预留席;既有 key 的后续请求快速失败。"""
    monkeypatch.setattr(config, "LLM_MAX_CONCURRENCY", 5)
    monkeypatch.setattr(config, "LLM_RESERVED_SEATS", 3)      # 通用池=2,预留席=3
    monkeypatch.setattr(config, "LLM_ACQUIRE_TIMEOUT", 0.05)
    llm._reset_seats_for_test()

    started: asyncio.Queue = asyncio.Queue()
    gate = asyncio.Event()

    async def hold(key: str):
        security.CURRENT_RATE_KEY.set(key)
        async with llm._seat():
            started.put_nowait(key)
            await gate.wait()

    # 阶段1:两个 key 各起第一路(新 key 首席,不占通用池)
    tasks = [asyncio.create_task(hold("ip:a")), asyncio.create_task(hold("ip:b"))]
    await started.get()
    await started.get()
    # 阶段2:同 key 第二路(此时已是既有 key,必须走通用池)→ 占满通用池
    tasks += [asyncio.create_task(hold("ip:a")), asyncio.create_task(hold("ip:b"))]
    await started.get()
    await started.get()
    assert llm._general_sem._value == 0                # 通用池被既有 key 占满
    assert llm._llm_sem._value == 1                   # 全局仅剩 1 席(预留席余量)

    # 新 key 仍能拿到席位(预留席,N4)
    security.CURRENT_RATE_KEY.set("ip:new")
    async with llm._seat():
        pass

    # 既有 key 的第三路:通用池已满 → 快速失败,不得动用预留席
    security.CURRENT_RATE_KEY.set("ip:a")
    with pytest.raises(llm.SeatBusyError):
        async with llm._seat():
            pass

    gate.set()
    await asyncio.gather(*tasks)
    assert llm._llm_sem._value == config.LLM_MAX_CONCURRENCY
    assert llm._active_keys == {}

    # --- 复审 Finding #1(ramp-up 竞态):同 key 并发冲刺不得垄断预留席 ---
    llm._reset_seats_for_test()
    rush_outcomes: asyncio.Queue = asyncio.Queue()
    rush_gate = asyncio.Event()

    async def rush(key: str):
        security.CURRENT_RATE_KEY.set(key)
        try:
            async with llm._seat():
                rush_outcomes.put_nowait("held")
                await rush_gate.wait()
        except llm.SeatBusyError:
            rush_outcomes.put_nowait("busy")

    rush_tasks = [asyncio.create_task(rush("ip:rush")) for _ in range(3)]
    got = [await asyncio.wait_for(rush_outcomes.get(), timeout=2) for _ in range(3)]
    assert sorted(got) == ["held", "held", "held"]
    # 冲刺只有 1 路按「新 key」走非通用席,其余必须占通用池(不得 3 路全绕开)
    assert llm._general_sem._value == 0
    assert llm._llm_sem._value == config.LLM_MAX_CONCURRENCY - 3
    # 真正的新 key 仍拿得到席位:预留席没被同 key 冲刺吃满
    security.CURRENT_RATE_KEY.set("ip:other")
    async with llm._seat():
        pass
    rush_gate.set()
    await asyncio.gather(*rush_tasks)
    assert llm._active_keys == {}


async def test_same_key_burst_cannot_monopolize_reserved(monkeypatch):
    """复审 Finding #1(核心保证):全局饱和下的同 key ramp-up 冲刺吃不满预留池 ——
    冲刺里只有 1 路计「新 key」,其余走通用池;真正的新 key 仍拿得到席位。
    (旧实现必须先有全局饱和:冲刺全部堆积在 _llm_sem 取席点且尚未注册时,才会
    全部误计「新 key」全绕开通用池,吃光含预留在内的全部席位。)"""
    monkeypatch.setattr(config, "LLM_MAX_CONCURRENCY", 4)
    monkeypatch.setattr(config, "LLM_RESERVED_SEATS", 2)      # 通用池=2,预留额度=2
    monkeypatch.setattr(config, "LLM_ACQUIRE_TIMEOUT", 1.0)
    llm._reset_seats_for_test()

    outcomes: asyncio.Queue = asyncio.Queue()

    async def hold(key: str, tag: str, gate: asyncio.Event):
        security.CURRENT_RATE_KEY.set(key)
        try:
            async with llm._seat():
                outcomes.put_nowait(("held", tag))
                await gate.wait()
        except llm.SeatBusyError:
            outcomes.put_nowait(("busy", tag))

    # 阶段1:4 个互异 key 各占 1 席,占满全局 —— 制造 ramp-up 堆积窗口
    blocker_gate = asyncio.Event()
    blockers = [asyncio.create_task(hold(f"ip:s{i}", f"s{i}", blocker_gate)) for i in range(4)]
    for _ in range(4):
        assert (await asyncio.wait_for(outcomes.get(), timeout=2))[0] == "held"
    assert llm._llm_sem._value == 0

    # 阶段2:同 key 并发冲刺(此刻全局饱和,必然堆积在取席点)
    burst_gate = asyncio.Event()
    burst = [asyncio.create_task(hold("ip:big", f"b{i}", burst_gate)) for i in range(4)]
    await asyncio.sleep(0.05)   # 让 4 路全部进入取席等待(远小于 ACQUIRE_TIMEOUT)

    # 阶段3:释放阻塞者,冲刺占席:只有 1 路非通用席,其余争 2 个通用席
    blocker_gate.set()
    await asyncio.gather(*blockers)
    got = [await asyncio.wait_for(outcomes.get(), timeout=3) for _ in range(4)]
    assert sorted(g for g, _ in got) == ["busy", "held", "held", "held"]  # 旧实现:4 held 全绕开通用池
    assert llm._general_sem._value == 0                       # 通用池满:2 席都被冲刺的既有请求拿走
    assert llm._llm_sem._value == 1                           # 冲刺共占 3 席(1 非通用 + 2 通用),预留额度未被吃满

    # 核心断言:真正的新 key 仍拿得到席位(旧实现此处 503)
    security.CURRENT_RATE_KEY.set("ip:fresh")
    async with llm._seat():
        pass

    burst_gate.set()
    await asyncio.gather(*burst)
    assert llm._llm_sem._value == config.LLM_MAX_CONCURRENCY
    assert llm._general_sem._value == config.LLM_MAX_CONCURRENCY - config.LLM_RESERVED_SEATS
    assert llm._active_keys == {}


async def test_key_sems_bounded_lru_evicts_only_unoccupied(monkeypatch):
    """复审 Finding #2:_key_sems 有界(LRU),只淘汰零占用的信号量;
    有持有者/等待者的一律保留(per-key 记账不被破坏)。"""
    monkeypatch.setattr(llm, "_KEY_SEMS_MAX", 4)
    llm._reset_seats_for_test()
    started: asyncio.Queue = asyncio.Queue()
    gate = asyncio.Event()

    async def hold(key: str):
        security.CURRENT_RATE_KEY.set(key)
        async with llm._seat():
            started.put_nowait(key)
            await gate.wait()

    tasks = [asyncio.create_task(hold(k)) for k in ("ip:a", "ip:b")]
    for _ in range(2):
        await asyncio.wait_for(started.get(), timeout=2)

    for i in range(10):   # churn 10 个不同 key(每个入席即出,留下零占用信号量)
        security.CURRENT_RATE_KEY.set(f"ip:{i}")
        async with llm._seat():
            pass

    assert len(llm._key_sems) <= 4                            # 有界(F4 纪律)
    assert "ip:a" in llm._key_sems and "ip:b" in llm._key_sems  # 占用中的不被淘汰
    assert "ip:0" not in llm._key_sems                        # 零占用最旧项被淘汰(LRU)
    assert "ip:9" in llm._key_sems                            # 最新项保留

    gate.set()
    await asyncio.gather(*tasks)
    assert llm._active_keys == {}


# ---------- ContextVar 传播(N3:named risk —— BaseHTTPMiddleware 下游传播) ----------


def test_rate_key_contextvar_reaches_seat(client, monkeypatch):
    """SecurityMiddleware 写入的 rate_key 必须传到 llm._seat 的读取点。"""
    from app import llm as llm_mod
    from app import main as main_mod

    seen: list[str] = []

    async def fake_run_rewrite(raw, llm=None):
        async with llm_mod._seat():                    # 即 llm._seat 读取点
            seen.append(security.CURRENT_RATE_KEY.get())
        return "主题"

    monkeypatch.setattr(main_mod, "run_rewrite", fake_run_rewrite)
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post("/api/roots", json={"session_id": sid, "raw_input": "AI 编程"})
    assert r.status_code == 200
    assert seen == ["ip:testclient"]   # 非默认 "anon":中间件取键已传播到 _seat


# ---------- 饱和 → HTTP 503(F6 保持脱敏,不 500 不挂起) ----------


def test_seat_timeout_maps_to_503(client, monkeypatch):
    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(config, "LLM_API_KEY", "k")
    monkeypatch.setattr(config, "LLM_MAX_CONCURRENCY", 0)
    monkeypatch.setattr(config, "LLM_ACQUIRE_TIMEOUT", 0.05)
    llm._reset_seats_for_test()
    sid = client.post("/api/sessions").json()["session_id"]
    t0 = time.monotonic()
    r = client.post("/api/roots", json={"session_id": sid, "raw_input": "AI 编程"})
    assert time.monotonic() - t0 < 3.0          # 不挂起
    assert r.status_code == 503                 # 不是 500/502
    assert r.json()["detail"] == "服务繁忙，请稍后重试"


def test_reader_chat_seat_timeout_maps_to_503(client, monkeypatch):
    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(config, "LLM_API_KEY", "k")
    monkeypatch.setattr(config, "LLM_MAX_CONCURRENCY", 0)
    monkeypatch.setattr(config, "LLM_ACQUIRE_TIMEOUT", 0.05)
    llm._reset_seats_for_test()
    sid = client.post("/api/sessions").json()["session_id"]
    t0 = time.monotonic()
    r = client.post("/api/reader/chat", json={
        "session_id": sid, "node_id": "n", "node_title": "N", "path": ["N"],
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert time.monotonic() - t0 < 3.0          # 不挂起
    assert r.status_code == 503
    assert r.json()["detail"] == "服务繁忙，请稍后重试"


# ---------- 断开席位回收(F5) ----------


class _HangingStream:
    """先给定 chunks,之后永挂起的假流:模拟长流,直到生成器被关闭/取消。"""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._chunks:
            return self._chunks.pop(0)
        await asyncio.Event().wait()   # 永不返回
        raise StopAsyncIteration       # pragma: no cover


def _fake_stream_client(chunks):
    async def _create(**_kw):
        return _HangingStream(chunks)

    async def _close():
        pass

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create)),
        close=_close)


def _delta_chunk(text):
    return SimpleNamespace(
        usage=None,
        choices=[SimpleNamespace(
            delta=SimpleNamespace(content=text, tool_calls=None),
            finish_reason=None)])


async def test_stream_close_releases_seats(monkeypatch):
    """F5:流生成器被关闭(GeneratorExit,模拟客户端断流)后席位立即回归基线。"""
    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(config, "LLM_API_KEY", "k")
    llm._reset_seats_for_test()
    security.CURRENT_RATE_KEY.set("ip:10.0.0.1")
    fake = _fake_stream_client([_delta_chunk("你好")])

    async def fake_resolve(*_a, **_k):
        return (fake, "m")

    monkeypatch.setattr(llm, "_resolve", fake_resolve)

    agen = llm.chat_stream_events(
        system="s", messages=[{"role": "user", "content": "hi"}],
        route=llm_usage.ROUTE_READER_CHAT)
    ev = await anext(agen)                        # 流已开始:席位在手
    assert ev == {"type": "delta", "text": "你好"}
    assert llm._llm_sem._value == config.LLM_MAX_CONCURRENCY - 1
    assert llm._key_sems["ip:10.0.0.1"]._value == config.LLM_MAX_CONCURRENCY_PER_KEY - 1
    assert llm._active_keys == {"ip:10.0.0.1": 1}

    await agen.aclose()                           # 断流:GeneratorExit 在 yield 处展开
    assert llm._llm_sem._value == config.LLM_MAX_CONCURRENCY            # 全局席位回归基线
    assert llm._general_sem._value == config.LLM_MAX_CONCURRENCY - config.LLM_RESERVED_SEATS
    assert llm._key_sems["ip:10.0.0.1"]._value == config.LLM_MAX_CONCURRENCY_PER_KEY
    assert llm._active_keys == {}                 # key 重新变为「新 key」


async def test_disconnect_releases_seats(monkeypatch):
    """F5:真实中间件栈(BaseHTTPMiddleware+StreamingResponse)下中途断流(http.disconnect),
    席位在短 bounded 时间内回归基线。TestClient 的 transport 整 body 缓冲(实测首行 ≈ 全流
    结束才返回),无法中途断流,故直接驱动 ASGI app 并在首块出栈后注入 http.disconnect。"""
    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(config, "LLM_API_KEY", "k")
    llm._reset_seats_for_test()
    fake = _fake_stream_client([_delta_chunk("第一块")])

    async def fake_resolve(*_a, **_k):
        return (fake, "m")

    monkeypatch.setattr(llm, "_resolve", fake_resolve)

    from app import main as main_mod
    from app.main import app

    session_id = main_mod._sessions.create()
    body = json.dumps({
        "session_id": session_id, "node_id": "n", "node_title": "N", "path": ["N"],
        "messages": [{"role": "user", "content": "hi"}],
    }).encode()

    body_read = False
    first_body = asyncio.Event()
    sent: list[dict] = []

    async def receive():
        nonlocal body_read
        if not body_read:
            body_read = True
            return {"type": "http.request", "body": body, "more_body": False}
        await first_body.wait()      # 首块出栈 = 流已开始,此刻起视为客户端断流
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)
        if (message["type"] == "http.response.body"
                and message.get("body") and not first_body.is_set()):
            # 首块出栈时席位仍在手:证明确实是「流中途」断开,而非流前/流后
            assert llm._llm_sem._value == config.LLM_MAX_CONCURRENCY - 1
            assert llm._active_keys == {"ip:1.2.3.4": 1}
            first_body.set()

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/api/reader/chat", "raw_path": b"/api/reader/chat",
        "query_string": b"", "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("1.2.3.4", 12345), "server": ("testserver", 80),
    }
    # 断流后 app 必须尽快返回,不挂起(挂起即 F5 失败面)
    await asyncio.wait_for(app(scope, receive, send), timeout=10)

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and llm._llm_sem._value != config.LLM_MAX_CONCURRENCY:
        await asyncio.sleep(0.02)   # 给事件循环收尾(取消/GC 关闭生成器)的轮次
    assert llm._llm_sem._value == config.LLM_MAX_CONCURRENCY, "断流后全局席位未回归(F5 泄漏)"
    assert llm._general_sem._value == config.LLM_MAX_CONCURRENCY - config.LLM_RESERVED_SEATS
    assert llm._key_sems["ip:1.2.3.4"]._value == config.LLM_MAX_CONCURRENCY_PER_KEY
    assert llm._active_keys == {}, "断流后 _active_keys 未回归(F5 泄漏)"
