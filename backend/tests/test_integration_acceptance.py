"""§12 集成验收可自动化部分(LLM_MOCK=1 离线联调 + 并发就绪自检)。

§12 七项中可自动化的三项在此落地:
④ LLM_MOCK=true 离线联调:图谱展开(POST /api/expand 出 children/edges)+
  伴读流式(POST /api/reader/chat 出 NDJSON,以 done 事件收尾)。
⑤ 并发压测 ≥100 路事件循环不卡:自动化弱化版 = ≥150 并发 llm._seat() 占有者
  不挂起事件循环(心跳任务持续被调度、席位全数归还)。真网络 100 路压测见
  任务报告手工项(避免写脆的性能断言)。
其余四项(①全测试 ②端点契约 ③红线自检 ⑥计量口径 ⑦脱敏/无泄漏)的可执行
形态在 test_redline_static.py / test_redline_runtime.py 与既有套件,手工项见报告。
"""
from __future__ import annotations

import asyncio
import json

from app import config, llm, security


def test_expand_end_to_end_offline_mock(client, monkeypatch):
    """离线联调:图谱展开端点出 children/edges,契约字段齐全。"""
    monkeypatch.setattr(config, "LLM_MOCK", True)
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post("/api/expand", json={"session_id": sid, "node_id": "n",
                                         "node_title": "相对论", "path": ["相对论"], "depth": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is None
    assert len(body["children"]) >= 1
    assert len(body["edges"]) == len(body["children"])
    for child in body["children"]:
        assert child["id"] and child["title"]
    for edge in body["edges"]:
        assert edge["parent_id"] == "n" and edge["child_id"]


def test_reader_chat_ndjson_end_to_end_offline_mock(client, monkeypatch):
    """离线联调:伴读流式 NDJSON,以 done 事件收尾,主体是 delta 流。"""
    monkeypatch.setattr(config, "LLM_MOCK", True)
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post("/api/reader/chat", json={"session_id": sid, "node_id": "n",
                                              "node_title": "历史背景", "path": ["相对论", "历史背景"],
                                              "detail": "详述", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
    assert events[-1] == {"type": "done"}
    assert any(e["type"] == "delta" for e in events)


async def test_150_concurrent_seat_holders_keep_event_loop_live(monkeypatch):
    """§12⑤ 自动化弱化版:≥150 路并发占席不冻结事件循环、席位不泄漏。

    非脆的性能测试:不断言时延,只断言(a)全部持有者在宽限期内拿到并放回席位、
    (b)占席期间心跳任务持续被调度(循环未被同步 I/O 钉死)、(c)席位计数归零。
    """
    monkeypatch.setattr(config, "LLM_MAX_CONCURRENCY", 200)
    monkeypatch.setattr(config, "LLM_MAX_CONCURRENCY_PER_KEY", 20)
    monkeypatch.setattr(config, "LLM_RESERVED_SEATS", 20)
    monkeypatch.setattr(config, "LLM_ACQUIRE_TIMEOUT", 10.0)
    llm._reset_seats_for_test()

    holders = 150
    ticks = 0
    stop = asyncio.Event()

    async def heartbeat():
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0)   # 让出但不停顿:被冻结的循环会停在某次占席上

    async def holder(i: int):
        security.CURRENT_RATE_KEY.set(f"seat-key-{i}")   # per-key 帽 20:各持独立键
        async with llm._seat():
            await asyncio.sleep(0.01)   # 持席挂起:占席期间循环必须持续调度心跳

    hb = asyncio.create_task(heartbeat())
    try:
        await asyncio.wait_for(
            asyncio.gather(*(holder(i) for i in range(holders))), timeout=15)
    finally:
        stop.set()
        await hb

    assert ticks >= 10, "占席期间事件循环未保持调度(疑似同步阻塞)"
    assert llm._llm_sem._value == config.LLM_MAX_CONCURRENCY   # 全数归还,无泄漏
    assert llm._general_sem._value == max(
        0, config.LLM_MAX_CONCURRENCY - config.LLM_RESERVED_SEATS)
    assert llm._active_keys == {}
