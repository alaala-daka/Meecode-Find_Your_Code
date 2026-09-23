"""请求级 LLM 覆盖:按解析后 (base_url, api_key) 缓存客户端,model 逐请求覆盖。"""
from __future__ import annotations

from typing import Any

import pytest

from app import llm
from app.schemas import LLMOverride, RewriteResult


class _FakeCompletions:
    def __init__(self, sink: dict[str, Any]):
        self._sink = sink

    def create(self, **kwargs):
        self._sink["create_kwargs"] = kwargs

        class _Msg:
            content = '{"topic": "测试主题"}'

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        return _Resp()


class _FakeOpenAI:
    instances: list["_FakeOpenAI"] = []

    def __init__(self, base_url=None, api_key=None, sink=None):
        self.base_url = base_url
        self.api_key = api_key
        self.chat = type("Chat", (), {"completions": _FakeCompletions(sink if sink is not None else {})})()
        _FakeOpenAI.instances.append(self)


@pytest.fixture
def env(monkeypatch):
    """固定 env 配置 + 伪 OpenAI + 伪 DNS，返回创建记录。"""
    import socket
    sink: dict[str, Any] = {}
    _FakeOpenAI.instances = []
    monkeypatch.setattr(llm, "OpenAI", lambda base_url=None, api_key=None: _FakeOpenAI(base_url, api_key, sink))
    monkeypatch.setattr(llm.config, "LLM_MOCK", False)
    monkeypatch.setattr(llm.config, "LLM_API_KEY", "env-key")
    monkeypatch.setattr(llm.config, "LLM_BASE_URL", "https://env.example.com")
    monkeypatch.setattr(llm.config, "LLM_MODEL", "env-model")
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", port or 0))])
    return sink


def test_default_uses_env(env):
    out = llm.chat_json("sys", "user", RewriteResult)
    assert out.topic == "测试主题"
    assert _FakeOpenAI.instances[0].base_url == "https://env.example.com"
    assert _FakeOpenAI.instances[0].api_key == "env-key"
    assert env["create_kwargs"]["model"] == "env-model"


def test_full_override_per_request(env):
    ov = LLMOverride(base_url="https://custom.example.com", api_key="sk-custom", model="custom-llm")
    llm.chat_json("sys", "user", RewriteResult, llm=ov)
    assert _FakeOpenAI.instances[0].base_url == "https://custom.example.com"
    assert _FakeOpenAI.instances[0].api_key == "sk-custom"
    assert env["create_kwargs"]["model"] == "custom-llm"

    llm.chat_json("sys", "user", RewriteResult, llm=ov)
    assert len(_FakeOpenAI.instances) == 1  # 同参数命中缓存


def test_blank_fields_fall_back_to_env(env):
    """空白字段(设置区没填)必须回落 env,不能拿去建客户端。"""
    ov = LLMOverride(base_url="  ", api_key="", model="  custom-llm ")
    llm.chat_json("sys", "user", RewriteResult, llm=ov)
    assert _FakeOpenAI.instances[0].base_url == "https://env.example.com"
    assert _FakeOpenAI.instances[0].api_key == "env-key"
    assert env["create_kwargs"]["model"] == "custom-llm"


def test_unconfigured_raises(monkeypatch):
    monkeypatch.setattr(llm.config, "LLM_MOCK", False)
    monkeypatch.setattr(llm.config, "LLM_API_KEY", "")
    with pytest.raises(RuntimeError, match="LLM 未配置"):
        llm.chat_json("sys", "user", RewriteResult)
    # 请求级 api_key 可脱离 env 解锁
    monkeypatch.setattr(llm, "OpenAI", lambda base_url=None, api_key=None: _FakeOpenAI(base_url, api_key, {}))
    monkeypatch.setattr(llm.config, "LLM_BASE_URL", "https://env.example.com")
    llm.chat_json("sys", "user", RewriteResult, llm=LLMOverride(api_key="sk-only"))


def test_client_cache_is_capped(env, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", port or 0))])
    assert llm._CLIENTS_MAX == 32
    for i in range(llm._CLIENTS_MAX + 5):
        llm._resolve(LLMOverride(base_url=f"https://h{i}.example.com", api_key=f"k{i}"))
    assert len(llm._clients) <= llm._CLIENTS_MAX
    assert ("https://h0.example.com", "k0") not in llm._clients
    newest = (f"https://h{llm._CLIENTS_MAX + 4}.example.com", f"k{llm._CLIENTS_MAX + 4}")
    assert newest in llm._clients
