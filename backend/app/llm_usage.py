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


def stats(conn: sqlite3.Connection, from_date: str, to_date: str) -> dict:
    """三组聚合（§4.3）：daily 逐日补零、models 按 calls 降序、repos_top 按 tokens 降序取 10。"""
    f0, _ = traffic.day_bounds_utc(from_date)
    _, t1 = traffic.day_bounds_utc(to_date)
    rows = conn.execute(
        "SELECT date(ts, 'unixepoch') AS date, COUNT(*) AS calls,"
        " SUM(prompt_tokens) AS prompt_tokens,"
        " SUM(completion_tokens) AS completion_tokens,"
        " SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) AS errors,"
        " CAST(ROUND(AVG(latency_ms)) AS INTEGER) AS avg_latency_ms"
        " FROM llm_usage WHERE ts>=? AND ts<? GROUP BY date ORDER BY date",
        (f0, t1),
    ).fetchall()
    by_date = {r["date"]: r for r in rows}
    daily = []
    for i in range((t1 - f0) // 86400):
        date_str = time.strftime("%Y-%m-%d", time.gmtime(f0 + i * 86400))
        r = by_date.get(date_str)
        daily.append({
            "date": date_str,
            "calls": r["calls"] if r else 0,
            "prompt_tokens": (r["prompt_tokens"] or 0) if r else 0,
            "completion_tokens": (r["completion_tokens"] or 0) if r else 0,
            "errors": (r["errors"] or 0) if r else 0,
            "avg_latency_ms": (r["avg_latency_ms"] or 0) if r else 0,
        })
    models = [
        {"model": r["model"], "calls": r["calls"], "tokens": r["tokens"] or 0}
        for r in conn.execute(
            "SELECT model, COUNT(*) AS calls,"
            " SUM(prompt_tokens + completion_tokens) AS tokens"
            " FROM llm_usage WHERE ts>=? AND ts<?"
            " GROUP BY model ORDER BY calls DESC, model ASC", (f0, t1))
    ]
    repos_top = [
        {"repo_id": r["repo_id"], "name": r["name"],
         "calls": r["calls"], "tokens": r["tokens"] or 0}
        for r in conn.execute(
            "SELECT u.repo_id AS repo_id,"
            " COALESCE(r.full_name, '仓库 #' || u.repo_id) AS name,"
            " COUNT(*) AS calls, SUM(u.prompt_tokens + u.completion_tokens) AS tokens"
            " FROM llm_usage u LEFT JOIN repos r ON r.id = u.repo_id"
            " WHERE u.ts>=? AND u.ts<? AND u.repo_id IS NOT NULL"
            " GROUP BY u.repo_id ORDER BY tokens DESC, calls DESC LIMIT 10", (f0, t1))
    ]
    return {"daily": daily, "models": models, "repos_top": repos_top}


def month_stats(conn: sqlite3.Connection, now: int | None = None) -> dict:
    """当月 1 日 00:00 UTC 至今（§4.3 概览 llm_month）。"""
    now = int(now if now is not None else time.time())
    month_start = calendar.timegm(
        time.strptime(time.strftime("%Y-%m-01", time.gmtime(now)), "%Y-%m-%d"))
    row = conn.execute(
        "SELECT COUNT(*) AS calls, SUM(prompt_tokens) AS prompt_tokens,"
        " SUM(completion_tokens) AS completion_tokens FROM llm_usage WHERE ts>=?",
        (month_start,),
    ).fetchone()
    return {
        "calls": row["calls"] or 0,
        "prompt_tokens": row["prompt_tokens"] or 0,
        "completion_tokens": row["completion_tokens"] or 0,
    }
