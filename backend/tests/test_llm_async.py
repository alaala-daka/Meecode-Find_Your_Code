"""Task 4 异步核心:chat_json 协程化 + AsyncOpenAI 客户端 FIFO 淘汰即 close(F4)。"""
from types import SimpleNamespace

from app import config, llm, llm_usage


class _FakeCompletions:
    def __init__(self, payload):
        self._payload = payload

    async def create(self, **kwargs):
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4),
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._payload))],
        )


class _FakeAsyncOpenAI:
    def __init__(self, payload):
        self.chat = SimpleNamespace(completions=_FakeCompletions(payload))
        self.closed = False

    async def close(self):
        self.closed = True


async def test_chat_json_async_returns_model(monkeypatch, conn):
    llm_usage.bind(lambda: conn)
    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(config, "LLM_API_KEY", "k")

    async def fake_resolve(*_a, **_k):
        return (_FakeAsyncOpenAI('{"topic": "异步主题"}'), "m")
    monkeypatch.setattr(llm, "_resolve", fake_resolve)
    from app.schemas import RewriteResult
    out = await llm.chat_json("sys", "user", RewriteResult, route=llm_usage.ROUTE_ROOTS)
    assert out.topic == "异步主题"


async def test_client_eviction_closes(monkeypatch):
    llm._clients.clear()
    created = []
    monkeypatch.setattr(llm, "_make_async_client",
                        lambda **kw: created.append(_FakeAsyncOpenAI("{}")) or created[-1])
    from app.schemas import LLMOverride
    for i in range(llm._CLIENTS_MAX + 3):
        await llm._resolve(LLMOverride(api_key=f"sk-{i}"))
    assert len(llm._clients) <= llm._CLIENTS_MAX
    assert all(getattr(c, "closed", False) for c in created[:3])  # 被淘汰者已 close
