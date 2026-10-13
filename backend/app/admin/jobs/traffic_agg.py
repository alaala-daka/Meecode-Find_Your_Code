"""夜间聚合：昨日 access_events → traffic_daily，清理 30 天前明细与 180 天前失败登录行（spec §2.5 / 三期 §2.1）。

昨日口径 = gmtime(now-86400) 的 UTC 日；cron 每日 00:05（deploy-runbook.md）。
手动触发：python -m app.admin.jobs.traffic_agg
"""
from __future__ import annotations

import sqlite3
import time

from ... import traffic
from ...feed import db


def aggregate_date(conn: sqlite3.Connection, date_str: str) -> dict:
    stats = traffic.day_stats(conn, date_str)
    conn.execute(
        "INSERT OR REPLACE INTO traffic_daily"
        " (date, pv, uv, new_users, active_users, api_calls, errors) VALUES (?,?,?,?,?,?,?)",
        (stats["date"], stats["pv"], stats["uv"], stats["new_users"],
         stats["active_users"], stats["api_calls"], stats["errors"]))
    conn.commit()
    return stats


def prune_access_events(conn: sqlite3.Connection, *, now: int | None = None) -> int:
    cutoff = int(now if now is not None else time.time()) - traffic.ACCESS_RETENTION_DAYS * 86400
    cur = conn.execute("DELETE FROM access_events WHERE ts < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def prune_login_fails(conn: sqlite3.Connection, *, now: int | None = None) -> int:
    cutoff = int(now if now is not None else time.time()) - traffic.LOGIN_FAIL_RETENTION_DAYS * 86400
    cur = conn.execute("DELETE FROM login_events WHERE ok=0 AND ts < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def aggregate_yesterday(conn: sqlite3.Connection, *, now: int | None = None) -> dict:
    now = int(now if now is not None else time.time())
    yesterday = time.strftime("%Y-%m-%d", time.gmtime(now - 86400))
    stats = aggregate_date(conn, yesterday)
    pruned = prune_access_events(conn, now=now)
    pruned_fails = prune_login_fails(conn, now=now)
    return {**stats, "pruned": pruned, "pruned_login_fails": pruned_fails}


def main() -> None:
    conn = db.connect()
    try:
        db.init_db(conn)
        print(aggregate_yesterday(conn))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
