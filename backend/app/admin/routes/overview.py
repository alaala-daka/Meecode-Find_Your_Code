# backend/app/admin/routes/overview.py
"""管理台概览计数：6 项实况 + 二期观测三字段（spec 2026-10-09 §3）。"""
from __future__ import annotations

import sqlite3
import time
from typing import Annotated

from fastapi import APIRouter, Depends

from ... import traffic
from ...feed import deps

router = APIRouter()


def _count(conn: sqlite3.Connection, sql: str) -> int:
    return conn.execute(sql).fetchone()["n"]


@router.get("/overview")
def overview(conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    now = int(time.time())
    year = time.gmtime(now).tm_year
    return {
        "total_users": _count(conn, "SELECT COUNT(*) AS n FROM users"),
        "new_users_today": _count(
            conn,
            "SELECT COUNT(*) AS n FROM users"
            " WHERE created_at >= CAST(strftime('%s','now','start of day') AS INTEGER)"),
        "total_repos": _count(conn, "SELECT COUNT(*) AS n FROM repos"),
        "published_repos": _count(
            conn, "SELECT COUNT(*) AS n FROM repos WHERE status='published'"),
        "delisted_repos": _count(
            conn, "SELECT COUNT(*) AS n FROM repos WHERE status='delisted'"),
        "pending_comments": _count(
            conn, "SELECT COUNT(*) AS n FROM comments WHERE status='pending'"),
        "online": traffic.online_count(conn),
        "today_pv": traffic.day_stats(conn, traffic.today_utc(now))["pv"],
        "year_pv": traffic.year_view(conn, year, now)["summary"]["year_pv"],
    }
