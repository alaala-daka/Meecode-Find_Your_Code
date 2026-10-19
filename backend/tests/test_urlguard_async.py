"""urlguard 异步非阻塞校验 + schemas 纯语法校验（F1/N1/N2）：DNS 移出 body 校验路径。"""
import asyncio
import socket

import pytest

from app import config, urlguard
from app.schemas import LLMOverride


async def test_validate_base_url_async_accepts_public(monkeypatch):
    async def fake_getaddrinfo(host, port):
        return [(2, 1, 6, "", ("93.184.216.34", port))]  # 公网 IP
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    out = await urlguard.validate_base_url_async("https://api.example.com/v1")
    assert out.startswith("https://")


async def test_validate_base_url_async_blocks_private(monkeypatch):
    async def fake_getaddrinfo(host, port):
        return [(2, 1, 6, "", ("127.0.0.1", port))]  # 内网
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError):
        await urlguard.validate_base_url_async("http://127.0.0.1:8000")


def test_check_base_url_is_syntax_only():
    # 纯语法：不触碰 DNS，语法错即拒
    with pytest.raises(ValueError):
        LLMOverride._check_base_url("ftp://bad.example.com")  # 非法协议
    # 合法语法直接放行（即便域名不可解析，也只在 _resolve 连接前才解析）
    assert LLMOverride._check_base_url("https://api.example.com/v1") == "https://api.example.com/v1"


def test_check_base_url_never_touches_dns(monkeypatch):
    # 语法校验路径若触碰 DNS，此桩会立刻暴露
    def _boom(*a, **k):
        raise AssertionError("syntax-only 校验不允许触碰 DNS")
    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    assert LLMOverride._check_base_url("https://never-resolves.example.invalid/v1") == "https://never-resolves.example.invalid/v1"


async def test_validate_base_url_async_timeout(monkeypatch):
    monkeypatch.setattr(config, "URL_RESOLVE_TIMEOUT", 0.01)

    async def slow_getaddrinfo(host, port):
        await asyncio.sleep(1)
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", slow_getaddrinfo)
    with pytest.raises(ValueError):
        await urlguard.validate_base_url_async("https://slow.example.com/v1")


async def test_validate_base_url_async_unresolvable(monkeypatch):
    async def boom(host, port):
        raise socket.gaierror("no such host")

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", boom)
    with pytest.raises(ValueError):
        await urlguard.validate_base_url_async("http://nope.invalid/v1")
