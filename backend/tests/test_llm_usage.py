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
