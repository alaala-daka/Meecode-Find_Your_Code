"""错误码不变量:resolve 期 base_url 校验 ValueError → 422,不裸落 500。

Task 3 把 SSRF/不可解析/超时校验移到 urlguard.validate_base_url_async
(llm._resolve 连接前调用);ValueError 若不在路由层映射,该输入类会从分支前的
422 退化成 500。消息是 urlguard 固定脱敏文案,直出安全(F6)。

ASGITransport 让应用跑在测试事件循环内,loop.getaddrinfo 打桩与
test_urlguard_async.py 同款,把域名解析到内网 IP 触发 SSRF 拦截。
"""
import asyncio
import socket

import httpx

from app import config
from app.main import app

SSRF_MSG = "模型接口地址不允许指向内网或本机，请填写公网 API 地址"
_OV = {"base_url": "http://internal.example.com/v1", "api_key": "sk-test"}


def _patch_private_dns(monkeypatch) -> None:
    async def fake_getaddrinfo(host, port):
        return [(2, 1, 6, "", ("127.0.0.1", port))]  # 内网
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)


def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


async def test_expand_base_url_ssrf_returns_422(monkeypatch):
    """JSON 路由:/api/expand 携带解析到内网的 llm.base_url → 422 + 脱敏文案,非 500。"""
    _patch_private_dns(monkeypatch)
    monkeypatch.setattr(config, "LLM_MOCK", False)  # mock 分支不走 _resolve,须关掉才测得到
    async with _client() as client:
        sid = (await client.post("/api/sessions")).json()["session_id"]
        resp = await client.post("/api/expand", json={
            "session_id": sid, "node_id": "n", "node_title": "t",
            "path": ["t"], "depth": 0, "llm": _OV,
        })
    assert resp.status_code == 422
    assert resp.status_code != 500
    assert resp.json()["detail"] == SSRF_MSG
    assert "127.0.0.1" not in resp.text   # F6:解析落点细节不出网


async def test_reader_chat_base_url_ssrf_returns_422(monkeypatch):
    """预取首事件路径:reader_chat 的 _resolve ValueError 显形为 422,而非流前 500。"""
    _patch_private_dns(monkeypatch)
    monkeypatch.setattr(config, "LLM_MOCK", False)
    async with _client() as client:
        sid = (await client.post("/api/sessions")).json()["session_id"]
        resp = await client.post("/api/reader/chat", json={
            "session_id": sid, "node_id": "n", "node_title": "t",
            "path": ["t"], "detail": "d",
            "messages": [{"role": "user", "content": "hi"}], "llm": _OV,
        })
    assert resp.status_code == 422
    assert resp.status_code != 500
    assert resp.json()["detail"] == SSRF_MSG


async def test_roots_base_url_unresolvable_returns_422(monkeypatch):
    """不可解析域名同为 resolve 期 ValueError:同样 422,消息为固定脱敏文案。"""
    async def boom(host, port):
        raise socket.gaierror("no such host")
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", boom)
    monkeypatch.setattr(config, "LLM_MOCK", False)
    async with _client() as client:
        sid = (await client.post("/api/sessions")).json()["session_id"]
        resp = await client.post("/api/roots", json={
            "session_id": sid, "raw_input": "AI 编程", "llm": _OV,
        })
    assert resp.status_code == 422
    assert resp.status_code != 500
    assert resp.json()["detail"] == "模型接口地址无法解析：internal.example.com"
