"""红线运行时探针(§12③/⑦ 可执行形态):驱动真实 async 路径,证明事件循环上无同步阻塞 I/O。

静态扫描(test_redline_static.py)管词法/可达调用;本文件用「探针」在真实执行路径上
实证两条非阻塞承诺:
- URL 校验走 loop.getaddrinfo(线程池),不直调同步 socket.getaddrinfo;
- LLM 计量走内存缓冲(守护线程落库),async 路径不直开 sqlite3.connect、不写游标。
探针实现:把同步入口换成「被调即记录并 raise」的函数 —— fail-swallow 的封装可能吞掉
异常,但记录的调用序列抓不到漏网(assert hits == [])。
(CPython 3.14 的 sqlite3.Connection/Cursor 是不可变 C 类型,类型级打补丁不可行,
故连接级探针经 sqlite3.connect 捕获一切同步建连/游标写,详见各用例注释。)

外加 F6 错误脱敏断言:502/流中断只出通用文案,原始异常(主机/URL/细节)不外泄。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import socket

import pytest

from app import config, llm, llm_usage, main, urlguard
from app.schemas import LLMOverride, RewriteResult


# ---------- 运行时探针:同步 DNS ----------


async def test_async_url_validation_never_calls_sync_dns(monkeypatch):
    """validate_base_url_async 走 loop.getaddrinfo;同步 socket.getaddrinfo 零触发。"""
    dns_hits: list = []

    def probe(*a, **k):
        dns_hits.append(a)
        raise AssertionError(f"同步 socket.getaddrinfo 在 async 路径被调用: {a}")

    monkeypatch.setattr(socket, "getaddrinfo", probe)
    loop = asyncio.get_running_loop()

    async def fake_gai(host, port):
        return [(2, 1, 6, "", ("1.2.3.4", port))]

    monkeypatch.setattr(loop, "getaddrinfo", fake_gai)

    out = await urlguard.validate_base_url_async("https://api.example.com/v1")
    assert out == "https://api.example.com/v1"
    assert dns_hits == [], "同步 socket.getaddrinfo 不应在 async 路径被调用"
    with pytest.raises(AssertionError):   # 探针自证在位(不是没生效的空断言)
        socket.getaddrinfo("x", 1)


# ---------- 运行时探针:同步 sqlite ----------


class _ProbeFactory:
    """连接工厂探针:任何同步建连/游标写先记录再 raise;记录兜住 fail-swallow 的吞异常路径。"""

    def __init__(self) -> None:
        self.hits: list[str] = []

    def __call__(self, *a, **k):
        self.hits.append("factory()")
        raise AssertionError("同步 sqlite 连接获取在 async 路径被调用")

    def touch(self, name: str):
        self.hits.append(name)
        raise AssertionError(f"同步 sqlite {name} 在 async 路径被调用")


class _FakeCompletions:
    async def create(self, **kwargs):
        message = type("M", (), {"content": '{"topic": "T"}'})()
        usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()
        choice = type("C", (), {"message": message})()
        return type("R", (), {"usage": usage, "choices": [choice]})()


class _FakeClient:
    def __init__(self) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions()})()


async def test_async_llm_path_buffers_usage_without_sync_sqlite(monkeypatch):
    """chat_json 全链路(DNS 校验 + 计量落账):同步 sqlite 零触发,计量入内存缓冲。"""
    probe = _ProbeFactory()
    dns_hits: list = []
    sqlite_hits: list = []

    def dns_probe(*a, **k):
        dns_hits.append(a)
        raise AssertionError(f"同步 socket.getaddrinfo 在 async 路径被调用: {a}")

    def sqlite_probe(*a, **k):
        sqlite_hits.append(a)
        raise AssertionError(f"sqlite3.connect 在 async 路径被调用: {a}")

    monkeypatch.setattr(socket, "getaddrinfo", dns_probe)
    monkeypatch.setattr(sqlite3, "connect", sqlite_probe)   # 一切同步建连/游标写的唯一入口
    loop = asyncio.get_running_loop()

    async def fake_gai(host, port):
        return [(2, 1, 6, "", ("1.2.3.4", port))]

    monkeypatch.setattr(loop, "getaddrinfo", fake_gai)
    monkeypatch.setattr(llm, "_make_async_client", lambda **k: _FakeClient())
    monkeypatch.setattr(config, "LLM_MOCK", False)   # LLM_MOCK=1 时不落账,须关掉才测得到计量路径
    monkeypatch.setattr(config, "LLM_API_KEY", "k")
    llm_usage.bind(probe)   # 连接工厂=探针:同步获取即暴露

    result = await llm.chat_json(
        "system", "user", RewriteResult,
        route=llm_usage.ROUTE_ROOTS,
        llm=LLMOverride(base_url="https://api.example.com/v1", api_key="k"),
    )
    assert result.topic == "T"
    assert dns_hits == [] and sqlite_hits == []
    assert probe.hits == [], "计量应入内存缓冲,不触同步 sqlite"
    assert len(llm_usage._buf) == 1   # 计量确实落了行,只是缓冲而非直写
    with pytest.raises(AssertionError):   # 探针自证在位
        sqlite3.connect(":memory:")


# ---------- F6 错误脱敏 ----------


def test_error_response_sanitized(client, monkeypatch):
    """502 只出通用文案:原始异常文本(主机/URL/细节)不出网,仅落日志。"""
    async def boom(*a, **k):
        raise RuntimeError("secret-host.internal leaked detail")

    monkeypatch.setattr(main, "run_expand", boom)   # main 已 from-import,须补 main 引用
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post("/api/expand", json={"session_id": sid, "node_id": "n",
                                         "node_title": "t", "path": ["t"], "depth": 0})
    assert r.status_code == 502
    assert "secret-host.internal" not in r.text
    assert "leaked detail" not in r.text
    assert "生成失败，请稍后重试" in r.text   # 通用文案照常出,不是裸 502


def test_ndjson_stream_error_event_sanitized(client, monkeypatch):
    """流中途异常(状态码已 200):error 事件只带通用文案,原始异常不出网。"""
    async def boom_events(*a, **k):
        yield {"type": "delta", "text": "hi"}
        raise RuntimeError("secret-host.internal leaked detail")

    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(config, "LLM_API_KEY", "k")
    monkeypatch.setattr(main, "chat_stream_events", boom_events)
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post("/api/reader/chat", json={"session_id": sid, "node_id": "n",
                                              "node_title": "t", "path": ["t"],
                                              "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
    assert events[-1] == {"type": "error", "message": "生成中断"}
    assert "secret-host.internal" not in r.text
    assert "leaked detail" not in r.text
