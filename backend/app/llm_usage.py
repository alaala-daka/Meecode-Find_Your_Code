# backend/app/llm_usage.py
"""LLM 用量记账（spec 2026-10-10 三期 §4，纯观测）。

每次 `completions.create` 落一行 llm_usage（多轮工具调用的每轮各记一行；SDK 内部
max_retries 不可见不计）。tokens 以 provider 上报的 usage 为准——未上报或真零均记 0
且统计不区分，不做本地估算。写库 INSERT + 吞异常，绝不阻塞主调用（量小不做缓冲）；
LLM_MOCK 不落行。route 取值收敛于本模块常量登记（ROUTES），测试断言枚举与调用点一致。
"""
from __future__ import annotations

import calendar
import logging
import sqlite3
import time
from typing import Callable

from . import config, traffic

log = logging.getLogger(__name__)

# route 常量登记（§4.2）：9 值收敛于此。<job 名> 口径见 plan 期修正 1。
ROUTE_ROOTS = "roots"
ROUTE_REPO_ROOT = "repo-root"
ROUTE_EXPAND = "expand"
ROUTE_NODES_DETAIL = "nodes-detail"
ROUTE_READER_CHAT = "reader-chat"
ROUTE_AI_DRAFT = "ai-draft"
ROUTE_SUBMIT_SCREEN = "submit-screen"
ROUTE_COMMENT_MODERATE = "comment-moderate"
ROUTE_CRAWL_SCREEN = "crawl-screen"

ROUTES = frozenset({
    ROUTE_ROOTS, ROUTE_REPO_ROOT, ROUTE_EXPAND, ROUTE_NODES_DETAIL,
    ROUTE_READER_CHAT, ROUTE_AI_DRAFT, ROUTE_SUBMIT_SCREEN,
    ROUTE_COMMENT_MODERATE, ROUTE_CRAWL_SCREEN,
})

_MODEL_MAX = 100  # BYOK 可自填模型名，超长截断入库

_factory: Callable[[], sqlite3.Connection] | None = None
failures = 0


def bind(factory: Callable[[], sqlite3.Connection] | None) -> None:
    """绑定写库连接工厂（lifespan 绑 db.connect）；None = 丢弃（测试缺省）。"""
    global _factory
    _factory = factory


def reset() -> None:
    """测试隔离：解绑 + 失败计数清零。"""
    global _factory, failures
    _factory = None
    failures = 0


def record_usage(*, route: str, repo_id: int | None, model: str,
                 prompt_tokens: int, completion_tokens: int,
                 ok: int, latency_ms: int) -> None:
    """落一行。全路径吞异常（fail-swallow），绝不让记账把主调用打挂。"""
    global failures
    if config.LLM_MOCK or _factory is None:
        return
    try:
        conn = _factory()
        try:
            conn.execute(
                "INSERT INTO llm_usage (ts, route, repo_id, model, prompt_tokens,"
                " completion_tokens, ok, latency_ms) VALUES (?,?,?,?,?,?,?,?)",
                (int(time.time()), route, repo_id, (model or "")[:_MODEL_MAX],
                 max(0, int(prompt_tokens or 0)), max(0, int(completion_tokens or 0)),
                 1 if ok else 0, max(0, int(latency_ms or 0))),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        failures += 1
        log.exception("llm_usage 记账失败（fail-swallow, route=%s）", route)
