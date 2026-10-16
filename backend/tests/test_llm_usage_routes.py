"""route 常量与调用点一致（spec §4.2）：每个 LLM 入口的记账 route 归属。"""
from unittest.mock import MagicMock

import pytest

from app import config, llm_usage
from app.agent import graph as agent_graph
from app.schemas import Settings


@pytest.fixture()
def graph_calls(monkeypatch):
    """替换 agent.graph 的 chat_json，捕获 route 实参。"""
    calls: list[dict] = []

    def fake_chat_json(*args, **kwargs):
        calls.append(kwargs)
        return MagicMock(topic="t", children=[MagicMock(title="c")], edges=[])

    monkeypatch.setattr(agent_graph, "chat_json", fake_chat_json)
    monkeypatch.setattr(config, "LLM_MOCK", False)
    return calls


def test_graph五调用点route归属(graph_calls):
    base = len(graph_calls)
    agent_graph.run_rewrite("输入")
    assert len(graph_calls) == base + 1  # rewrite_node 一次
    assert graph_calls[-1]["route"] == llm_usage.ROUTE_ROOTS

    base = len(graph_calls)
    agent_graph.run_expand("父", ["父"], 0, Settings())
    assert len(graph_calls) == base + 2  # decompose + relate 各触发一次
    assert all(c["route"] == llm_usage.ROUTE_EXPAND for c in graph_calls[base:])
    assert graph_calls[-1]["route"] == llm_usage.ROUTE_EXPAND

    base = len(graph_calls)
    agent_graph.run_expand("父", ["父"], 0, Settings(),
                           route=llm_usage.ROUTE_REPO_ROOT)
    assert len(graph_calls) == base + 2  # decompose + relate 各触发一次
    assert all(c["route"] == llm_usage.ROUTE_REPO_ROOT for c in graph_calls[base:])
    assert graph_calls[-1]["route"] == llm_usage.ROUTE_REPO_ROOT

    base = len(graph_calls)
    agent_graph.run_elaborate("n", ["n"], "b")
    assert len(graph_calls) == base + 1  # run_elaborate 一次
    assert graph_calls[-1]["route"] == llm_usage.ROUTE_NODES_DETAIL

    base = len(graph_calls)
    agent_graph.run_repo_topic("a/b", "d", "r")
    assert len(graph_calls) == base + 1  # run_repo_topic 一次
    assert graph_calls[-1]["route"] == llm_usage.ROUTE_REPO_ROOT


def test_main三路由的route接线(client, monkeypatch):
    """HTTP 入口 → run_*：expand/repo-root 分流与 reader-chat 归属。"""
    import app.main as main_mod

    monkeypatch.setattr(config, "LLM_MOCK", False)  # mock 模式 reader_chat 走 mock_chat_events，绕开 chat_stream_events
    monkeypatch.setattr(config, "LLM_API_KEY", "k")  # reader_chat 的 llm_configured() 检查
    sid = client.post("/api/sessions").json()["session_id"]

    expand_spy = MagicMock(return_value=([], [], None))
    monkeypatch.setattr(main_mod, "run_expand", expand_spy)
    monkeypatch.setattr(main_mod, "run_repo_topic", MagicMock(return_value="主题"))
    monkeypatch.setattr(main_mod.gh, "fetch_repo_context",
                        MagicMock(return_value={"full_name": "a/b", "description": "", "readme": ""}))

    client.post("/api/expand", json={"session_id": sid, "node_id": "n",
                                     "node_title": "t", "depth": 1})
    assert expand_spy.call_args.kwargs["route"] == llm_usage.ROUTE_EXPAND

    client.post("/api/repos/root", json={"session_id": sid, "full_name": "a/b"})
    assert expand_spy.call_args.kwargs["route"] == llm_usage.ROUTE_REPO_ROOT

    chat_spy = MagicMock(return_value=iter([]))
    monkeypatch.setattr(main_mod, "chat_stream_events", chat_spy)
    client.post("/api/reader/chat",
                json={"session_id": sid, "node_id": "n", "node_title": "t"})
    assert chat_spy.call_args.kwargs["route"] == llm_usage.ROUTE_READER_CHAT
