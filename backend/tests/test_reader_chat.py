"""阅读器聊天:mock 流式 + 会话守卫 + 502 门 + 工具调用循环 + 强制末轮。"""
import json

from fastapi.testclient import TestClient

from app import config, llm, llm_usage
from app.agent import websearch
from app.main import app

client = TestClient(app)


def _make_session() -> str:
    return client.post("/api/sessions").json()["session_id"]


def _read_events(resp) -> list[dict]:
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_chat_mock_streams_delta_and_done(monkeypatch):
    monkeypatch.setattr(config, "LLM_MOCK", True)
    sid = _make_session()
    resp = client.post(
        "/api/reader/chat",
        json={
            "session_id": sid,
            "node_id": "n1",
            "node_title": "历史背景",
            "path": ["相对论的概念", "历史背景"],
            "detail": "详细阐述……",
            "messages": [{"role": "user", "content": "它和以太理论有什么关系?"}],
        },
    )
    assert resp.status_code == 200
    events = _read_events(resp)
    assert events[-1] == {"type": "done"}
    text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert "历史背景" in text  # mock 回答引用节点标题


def test_chat_unknown_session_404():
    resp = client.post(
        "/api/reader/chat",
        json={"session_id": "no-such", "node_id": "n", "node_title": "t",
              "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 404


def test_chat_unconfigured_502(monkeypatch):
    """非 mock 且 env/请求级都没有 key → 流开始前 502。"""
    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    sid = _make_session()
    resp = client.post(
        "/api/reader/chat",
        json={"session_id": sid, "node_id": "n", "node_title": "t",
              "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 502


def test_chat_detail_with_braces_non_mock(monkeypatch):
    """detail 含字面量花括号时,非 mock 路径的 context 格式化不应抛异常,且原样保留花括号。"""
    calls: list[dict] = []

    class _Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return _AsyncIter([_Chunk(_Delta(content="ok"), finish_reason="stop")])

    _install_fake_openai(monkeypatch, _Completions)
    sid = _make_session()
    resp = client.post(
        "/api/reader/chat",
        json={
            "session_id": sid,
            "node_id": "n1",
            "node_title": "测试",
            "detail": "内容含 {foo} 与 {bar[baz]} 花括号",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 200
    events = _read_events(resp)
    assert events[-1] == {"type": "done"}
    context_msg = next(m for m in calls[0]["messages"] if m["role"] == "user")
    assert "内容含 {foo} 与 {bar[baz]} 花括号" in context_msg["content"]


# ---------- chat_stream_events 单测(伪 OpenAI 流) ----------


class _Delta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _Chunk:
    def __init__(self, delta, finish_reason=None):
        self.choices = [_Choice(delta, finish_reason)]


class _Fn:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, index, id=None, name=None, arguments=None):
        self.index = index
        self.id = id
        self.function = _Fn(name, arguments)


class _AsyncIter:
    """伪异步流:把 chunk 列表包成 async for 可迭代对象。"""

    def __init__(self, items):
        self._it = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _install_fake_openai(monkeypatch, completions_cls):
    class _FakeClient:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": completions_cls()})()

    monkeypatch.setattr(llm, "_make_async_client", lambda **kw: _FakeClient())
    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(config, "LLM_API_KEY", "env-key")
    monkeypatch.setattr(config, "LLM_MODEL", "env-model")


async def test_chat_stream_tool_loop(monkeypatch):
    """第一轮分片输出工具调用(id/name 仅首片)→ 搜索回填 → 第二轮文本作答。"""
    calls: list[dict] = []
    searched: list[str] = []

    class _Completions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return _AsyncIter([
                    _Chunk(_Delta(tool_calls=[_ToolCall(0, id="call_0", name="web_search", arguments='{"query": "光速不变')])),
                    _Chunk(_Delta(tool_calls=[_ToolCall(0, arguments=' 实验"}')]), finish_reason="tool_calls"),
                ])
            return _AsyncIter([_Chunk(_Delta(content="迈克耳孙-莫雷实验否定了以太风。"), finish_reason="stop")])

    _install_fake_openai(monkeypatch, _Completions)

    async def fake_web_search(query, api_key, max_results=5):
        searched.append(query)
        return [{"title": "t", "url": "u", "content": "c"}]

    monkeypatch.setattr(websearch, "web_search", fake_web_search)

    events = [e async for e in llm.chat_stream_events(
        system="sys", messages=[{"role": "user", "content": "有什么实验证据?"}],
        route=llm_usage.ROUTE_READER_CHAT,
        llm=None, tavily_key="tvly-test",
    )]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "status" and events[0]["query"] == "光速不变 实验"  # 增量 arguments 正确归并
    assert "delta" in kinds and kinds[-1] == "done"
    assert searched == ["光速不变 实验"]
    assert calls[1]["messages"][-1]["role"] == "tool"  # 搜索结果以 tool 消息回填


async def test_chat_stream_forces_final_text_round(monkeypatch):
    """模型沉迷工具:达到 MAX_TOOL_ROUNDS 后,末轮不带 tools,必须以文本收尾。"""
    calls: list[dict] = []

    class _LoopCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            if "tools" in kwargs:
                return _AsyncIter([_Chunk(
                    _Delta(tool_calls=[_ToolCall(0, id=f"call_{len(calls)}", name="web_search", arguments='{"query":"x"}')]),
                    finish_reason="tool_calls",
                )])
            return _AsyncIter([_Chunk(_Delta(content="最终回答"), finish_reason="stop")])

    _install_fake_openai(monkeypatch, _LoopCompletions)

    async def fake_web_search(q, k, max_results=5):
        return []

    monkeypatch.setattr(websearch, "web_search", fake_web_search)

    events = [e async for e in llm.chat_stream_events(
        system="sys", messages=[{"role": "user", "content": "q"}],
        route=llm_usage.ROUTE_READER_CHAT, llm=None, tavily_key="tvly-test",
    )]
    assert len(calls) == llm.MAX_TOOL_ROUNDS + 1
    assert "tools" not in calls[-1]  # 末轮强制无工具
    text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert "最终回答" in text
    assert events[-1] == {"type": "done"}
