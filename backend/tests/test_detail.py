"""详细阐述端点:mock 确定性输出 + 会话守卫 + 覆盖穿线。"""
import socket

from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


def _make_session() -> str:
    return client.post("/api/sessions").json()["session_id"]


def test_detail_mock_mode_deterministic(monkeypatch):
    monkeypatch.setattr(config, "LLM_MOCK", True)
    sid = _make_session()
    payload = {
        "session_id": sid,
        "node_id": "n1",
        "node_title": "历史背景",
        "path": ["相对论的概念", "历史背景"],
        "brief": "狭义相对论提出的时代背景。",
    }
    r1 = client.post("/api/nodes/detail", json=payload)
    r2 = client.post("/api/nodes/detail", json=payload)
    assert r1.status_code == 200
    body = r1.json()
    assert body["node_id"] == "n1"
    assert "历史背景" in body["detail"]
    assert "##" in body["detail"]  # mock 也输出 markdown 结构
    assert body == r2.json()  # 确定性(e2e 依赖)


def test_detail_unknown_session_404():
    resp = client.post(
        "/api/nodes/detail",
        json={"session_id": "no-such", "node_id": "n1", "node_title": "x", "path": [], "brief": ""},
    )
    assert resp.status_code == 404


def test_detail_threads_llm_override(monkeypatch):
    """非 mock:run_elaborate 必须把 req.llm 传进 chat_json。"""
    from app.agent import graph as agent_graph
    from app.schemas import ElaborateResult

    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", port or 0))])
    seen: dict = {}

    def fake_chat_json(system, user, model, **kwargs):
        seen.update(kwargs)
        return ElaborateResult(detail="详细阐述内容")

    monkeypatch.setattr(agent_graph, "chat_json", fake_chat_json)
    sid = _make_session()
    resp = client.post(
        "/api/nodes/detail",
        json={
            "session_id": sid, "node_id": "n1", "node_title": "历史背景",
            "path": [], "brief": "",
            "llm": {"base_url": "https://x.example.com", "api_key": "sk-x", "model": "m1"},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["detail"] == "详细阐述内容"
    assert seen["llm"].model == "m1"
