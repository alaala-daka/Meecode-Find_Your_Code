"""Task 4 流式契约:reader/chat 的 NDJSON 形态经异步链路保持不变。"""
import json

from app import config


def test_reader_chat_ndjson_shape(client, monkeypatch):
    monkeypatch.setattr(config, "LLM_MOCK", True)  # mock 流，不触真实 LLM
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post("/api/reader/chat", json={
        "session_id": sid, "node_id": "n", "node_title": "N", "path": ["N"], "detail": "d",
        "messages": [{"role": "user", "content": "你好"}],
    })
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(x) for x in r.text.strip().splitlines()]
    assert lines[-1]["type"] == "done"
    assert any(x["type"] == "delta" for x in lines)
