"""record_usage 缓冲化（F2/N1）：内存缓冲 + 守护线程批量落库，调用方永不阻塞。

缓冲语义：record_usage 只入内存缓冲，不即时落库；flush_for_test(conn) 显式冲刷
（测试确定性）；守护线程在 FLUSH_ROWS/FLUSH_SECONDS 达阈时后台冲刷。
"""
import time

import pytest

from app import config, llm_usage
from app.feed import db


@pytest.fixture(autouse=True)
def _unmock(monkeypatch):
    """LLM_MOCK=1 跑测环境钉住 False：本模块要验证真实缓冲写路径。"""
    monkeypatch.setattr(config, "LLM_MOCK", False)


def _usage_db():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def test_record_usage_buffers_and_flushes_on_demand():
    conn = _usage_db()
    llm_usage.reset()
    llm_usage.bind(lambda: conn)  # 绑定须在 reset 之后（reset 解绑 + 清缓冲）
    llm_usage.record_usage(route="expand", repo_id=None, model="m",
                           prompt_tokens=10, completion_tokens=5, ok=1, latency_ms=100)
    # 记录后应先进缓冲，未 flush 前不应落库
    assert conn.execute("SELECT COUNT(*) AS n FROM llm_usage").fetchone()["n"] == 0
    n = llm_usage.flush_for_test(conn)
    assert n == 1
    row = conn.execute("SELECT * FROM llm_usage").fetchone()
    assert row["prompt_tokens"] == 10 and row["completion_tokens"] == 5 and row["ok"] == 1
    conn.close()


def test_record_usage_never_blocks_on_full_buffer(monkeypatch):
    conn = _usage_db()
    llm_usage.reset()
    llm_usage.bind(lambda: conn)
    # 钉死自动冲刷：缓冲保持满额，溢出断言确定（守护线程并发冲刷会清空缓冲使断言翻车）
    monkeypatch.setattr(llm_usage, "_flush_auto", lambda: None)
    started = time.monotonic()
    for _ in range(llm_usage.BUFFER_MAX + 10):
        llm_usage.record_usage(route="expand", repo_id=None, model="m",
                               prompt_tokens=1, completion_tokens=1, ok=1, latency_ms=1)
    elapsed = time.monotonic() - started
    assert elapsed < 1  # 满额路径不阻塞、不抛：全部调用立即返回
    assert llm_usage.failures >= 10  # 溢出的 10 行计为失败（满额丢新行）
    assert len(llm_usage._buf) <= llm_usage.BUFFER_MAX  # 缓冲有界
    conn.close()
