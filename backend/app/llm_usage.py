# backend/app/llm_usage.py
"""LLM 用量记账（spec 2026-10-10 三期 §4，纯观测）。

每次 `completions.create` 落一行 llm_usage（多轮工具调用的每轮各记一行；SDK 内部
max_retries 不可见不计）。tokens 以 provider 上报的 usage 为准——未上报或真零均记 0
且统计不区分，不做本地估算。写侧「内存缓冲 + 守护线程批量落库」（照 traffic.AccessWriter
的 single-flight + fail-swallow + 有界缓冲，但用独立守护线程，不占 asyncio.to_thread
默认执行器），record_usage 全路径吞异常，绝不阻塞调用方（含 async finally）；
LLM_MOCK 不落行。route 取值收敛于本模块常量登记（ROUTES），测试断言枚举与调用点一致。
"""
from __future__ import annotations

import calendar
import logging
import sqlite3
import threading
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

BUFFER_MAX = 10_000  # 硬上限：满则丢新行计 failures（防内存 DoS）
FLUSH_ROWS = 200  # 达 200 行触发后台冲刷
FLUSH_SECONDS = 30.0  # 距上次冲刷超 30s 触发后台冲刷

_factory: Callable[[], sqlite3.Connection] | None = None
_lock = threading.Lock()
_buf: list[tuple[int, str, int | None, str, int, int, int, int]] = []
_flush_scheduled = False  # single-flight：防 record 洪峰刷出线程风暴与并发写连接
_last_flush = time.time()
failures = 0


def bind(factory: Callable[[], sqlite3.Connection] | None) -> None:
    """Web/任务入口绑定零锁等待连接工厂；None = 丢弃（测试缺省）。"""
    global _factory
    _factory = factory


def reset() -> None:
    """测试隔离：解绑 + 清空缓冲/调度标志 + 失败计数清零。"""
    global _factory, _flush_scheduled, _last_flush, failures
    with _lock:
        _factory = None
        _buf.clear()
        _flush_scheduled = False
        _last_flush = time.time()
        failures = 0


def record_usage(*, route: str, repo_id: int | None, model: str,
                 prompt_tokens: int, completion_tokens: int,
                 ok: int, latency_ms: int) -> None:
    """入内存缓冲，由守护线程批量落库。全路径吞异常（fail-swallow），
    绝不让记账把主调用打挂、绝不阻塞调用方（含 async finally）。"""
    global failures, _flush_scheduled
    if config.LLM_MOCK or _factory is None:
        return
    try:
        row = (int(time.time()), route, repo_id, (model or "")[:_MODEL_MAX],
               max(0, int(prompt_tokens or 0)), max(0, int(completion_tokens or 0)),
               1 if ok else 0, max(0, int(latency_ms or 0)))
        with _lock:
            if len(_buf) >= BUFFER_MAX:
                failures += 1  # 满额丢新行：宁失真不炸内存
                return
            _buf.append(row)
            due = (len(_buf) >= FLUSH_ROWS
                   or time.time() - _last_flush >= FLUSH_SECONDS)
            spawn = due and not _flush_scheduled
            if spawn:
                _flush_scheduled = True
        if spawn:
            try:
                threading.Thread(target=_flush_auto, daemon=True).start()
            except Exception:
                with _lock:
                    _flush_scheduled = False  # 起线程失败须解除 single-flight，防永久停摆
                    failures += 1
                log.exception("llm_usage flush 线程启动失败（fail-swallow）")
    except Exception:
        with _lock:
            failures += 1
        log.exception("llm_usage 记账失败（fail-swallow, route=%s）", route)


def _flush_auto() -> None:
    """守护线程冲刷：自开连接、用完即关；异常全吞（fail-swallow）。"""
    global _flush_scheduled, failures
    try:
        if _factory is None:
            with _lock:
                _flush_scheduled = False
            return
        try:
            conn = _factory()
        except Exception:
            with _lock:
                failures += 1
                _flush_scheduled = False
            return
        try:
            flush_for_test(conn)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        with _lock:
            _flush_scheduled = False  # 兜底解除 single-flight，防永久停摆
        log.exception("llm_usage 后台 flush 异常（fail-swallow）")


def flush_for_test(conn: sqlite3.Connection) -> int:
    """冲刷缓冲批量落库，返回写入行数；测试与后台守护线程共用，写失败吞异常计 failures。"""
    global _flush_scheduled, _last_flush, failures
    with _lock:
        rows = _buf[:]
        _buf.clear()
        _flush_scheduled = False  # single-flight 解除
        _last_flush = time.time()
    if not rows:
        return 0
    try:
        conn.execute("PRAGMA busy_timeout = 0")  # 观测写不排队等待业务写锁
        conn.executemany(
            "INSERT INTO llm_usage (ts, route, repo_id, model, prompt_tokens,"
            " completion_tokens, ok, latency_ms) VALUES (?,?,?,?,?,?,?,?)", rows)
        conn.commit()
    except Exception:
        with _lock:
            failures += 1
        log.exception("llm_usage flush 写失败（fail-swallow）")
        return 0
    return len(rows)


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
        " SUM(completion_tokens) AS completion_tokens FROM llm_usage"
        " WHERE ts>=? AND ts<=?",
        (month_start, now),
    ).fetchone()
    return {
        "calls": row["calls"] or 0,
        "prompt_tokens": row["prompt_tokens"] or 0,
        "completion_tokens": row["completion_tokens"] or 0,
    }
