"""LLM 用量记账（spec 2026-10-10 三期 §4）。"""
import pytest

from app import config, llm_usage
from app.feed import db


@pytest.fixture()
def usage_db(tmp_path, monkeypatch, _reset_llm_usage):
    """文件库绑定（照 test_admin_policies 先例）：recorder 自开连接，与断言连接同库。

    显式依赖 autouse 的 _reset_llm_usage，保证绑定发生在 reset 之后（顺序确定性）。
    """
    path = str(tmp_path / "u.db")
    boot = db.connect(path)
    db.init_db(boot)
    boot.close()
    # 本地 .env 可置 LLM_MOCK=true（CI 无 .env）：显式钉住 False，用例不依赖环境默值
    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(llm_usage, "_factory", lambda: db.connect(path))
    yield path
    llm_usage.reset()


def _rows(path):
    conn = db.connect(path)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM llm_usage ORDER BY id")]
    finally:
        conn.close()


def _seed_kw(**kw):
    base = dict(route=llm_usage.ROUTE_ROOTS, repo_id=None, model="m",
                prompt_tokens=1, completion_tokens=2, ok=1, latency_ms=10)
    base.update(kw)
    llm_usage.record_usage(**base)


def test_枚举锁_九值():
    assert llm_usage.ROUTES == {
        "roots", "repo-root", "expand", "nodes-detail", "reader-chat",
        "ai-draft", "submit-screen", "comment-moderate", "crawl-screen"}


def test_record落行字段(usage_db):
    _seed_kw(route=llm_usage.ROUTE_EXPAND, repo_id=3, model="gpt-x",
             prompt_tokens=7, completion_tokens=5, ok=0, latency_ms=250)
    (row,) = _rows(usage_db)
    assert row["route"] == "expand" and row["repo_id"] == 3
    assert row["model"] == "gpt-x"
    assert (row["prompt_tokens"], row["completion_tokens"]) == (7, 5)
    assert row["ok"] == 0 and row["latency_ms"] == 250
    assert row["ts"] > 0


def test_model截断100字符(usage_db):
    _seed_kw(model="x" * 300)
    (row,) = _rows(usage_db)
    assert row["model"] == "x" * 100


def test_写库异常吞掉并计failures(usage_db, monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(llm_usage, "_factory", boom)
    before = llm_usage.failures
    _seed_kw()  # 不得抛出
    assert llm_usage.failures == before + 1


def test_未绑定连接工厂丢弃不抛():
    llm_usage.reset()
    _seed_kw()  # 不得抛出、不落行（无库可写）


def test_LLM_MOCK不落行(usage_db, monkeypatch):
    monkeypatch.setattr(config, "LLM_MOCK", True)
    _seed_kw()
    assert _rows(usage_db) == []


# ---------- Task 3：app/llm.py 埋点 ----------
from app import llm
from app.schemas import RewriteResult


class _Usage:
    prompt_tokens = 7
    completion_tokens = 5


def _resp(content='{"topic": "t"}', usage=True):
    msg = type("Msg", (), {"content": content})()
    choice = type("Choice", (), {"message": msg})()
    attrs = {"choices": [choice]}
    if usage:
        attrs["usage"] = _Usage()
    return type("Resp", (), attrs)()


class _FakeCompletions:
    def __init__(self, *, resp=None, exc=None, stream=None):
        self._resp, self._exc, self._stream = resp, exc, stream

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self._exc is not None:
            raise self._exc
        if self._stream is not None:
            return iter(self._stream)
        return self._resp


def _install(monkeypatch, completions):
    fake = type("Fake", (), {"chat": type("Chat", (), {"completions": completions})()})()
    monkeypatch.setattr(llm, "OpenAI", lambda base_url=None, api_key=None: fake)
    monkeypatch.setattr(llm.config, "LLM_MOCK", False)
    monkeypatch.setattr(llm.config, "LLM_API_KEY", "k")
    monkeypatch.setattr(llm.config, "LLM_MODEL", "m1")
    monkeypatch.setattr(llm.config, "LLM_BASE_URL", "https://api.example.com/v1")


def _delta_chunk(content):
    delta = type("Delta", (), {"content": content, "tool_calls": None})()
    choice = type("Choice", (), {"delta": delta, "finish_reason": None})()
    return type("Chunk", (), {"choices": [choice], "usage": None})()


def _usage_chunk():
    u = type("Usage", (), {"prompt_tokens": 3, "completion_tokens": 4})()
    return type("Chunk", (), {"choices": [], "usage": u})()


def test_chat_json成功落行ok1(usage_db, monkeypatch):
    _install(monkeypatch, _FakeCompletions(resp=_resp()))
    llm.chat_json("s", "u", RewriteResult,
                  route=llm_usage.ROUTE_ROOTS, repo_id=9)
    (row,) = _rows(usage_db)
    assert (row["route"], row["repo_id"], row["model"], row["ok"]) == ("roots", 9, "m1", 1)
    assert (row["prompt_tokens"], row["completion_tokens"]) == (7, 5)
    assert row["latency_ms"] >= 0


def test_chat_json解析失败记ok0与usage实得值(usage_db, monkeypatch):
    _install(monkeypatch, _FakeCompletions(resp=_resp(content="不是 JSON")))
    with pytest.raises(RuntimeError):
        llm.chat_json("s", "u", RewriteResult,
                      route=llm_usage.ROUTE_NODES_DETAIL)
    rows = _rows(usage_db)
    assert len(rows) == 2  # 两次 attempt 各一行
    assert [r["ok"] for r in rows] == [0, 0]
    assert all((r["prompt_tokens"], r["completion_tokens"]) == (7, 5) for r in rows)


def test_chat_json网络异常记ok0与0tokens(usage_db, monkeypatch):
    _install(monkeypatch, _FakeCompletions(exc=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        llm.chat_json("s", "u", RewriteResult, route=llm_usage.ROUTE_ROOTS)
    rows = _rows(usage_db)
    assert len(rows) == 2 and all(r["ok"] == 0 for r in rows)
    assert all((r["prompt_tokens"], r["completion_tokens"]) == (0, 0) for r in rows)


def test_流式usage末chunk空choices也被采到(usage_db, monkeypatch):
    _install(monkeypatch,
             _FakeCompletions(stream=[_delta_chunk("hi"), _usage_chunk()]))
    events = list(llm.chat_stream_events(
        system="s", messages=[{"role": "user", "content": "x"}],
        route=llm_usage.ROUTE_READER_CHAT))
    assert events == [{"type": "delta", "text": "hi"}, {"type": "done"}]  # done 收尾为既有事件协议
    (row,) = _rows(usage_db)
    assert (row["route"], row["ok"]) == ("reader-chat", 1)
    assert (row["prompt_tokens"], row["completion_tokens"]) == (3, 4)


def test_流式断流记ok1且latency到中断时刻(usage_db, monkeypatch):
    _install(monkeypatch,
             _FakeCompletions(stream=[_delta_chunk("a"), _delta_chunk("b"), _usage_chunk()]))
    gen = llm.chat_stream_events(
        system="s", messages=[{"role": "user", "content": "x"}],
        route=llm_usage.ROUTE_READER_CHAT)
    next(gen)
    gen.close()  # 模拟客户端断流（GeneratorExit）
    (row,) = _rows(usage_db)
    assert row["ok"] == 1 and row["latency_ms"] >= 0
    assert (row["prompt_tokens"], row["completion_tokens"]) == (0, 0)  # 未到 usage chunk


def test_流式断言stream_options开启usage(usage_db, monkeypatch):
    comp = _FakeCompletions(stream=[_delta_chunk("z"), _usage_chunk()])
    _install(monkeypatch, comp)
    list(llm.chat_stream_events(
        system="s", messages=[], route=llm_usage.ROUTE_READER_CHAT))
    assert comp.kwargs["stream_options"] == {"include_usage": True}
