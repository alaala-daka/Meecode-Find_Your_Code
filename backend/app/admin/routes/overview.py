# backend/app/admin/routes/overview.py
"""管理台概览计数（spec §5）：6 项整数；在线/今日 PV/本年累计属二期，响应不含。"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from ...feed import deps

router = APIRouter()


def _count(conn: sqlite3.Connection, sql: str) -> int:
    return conn.execute(sql).fetchone()["n"]


@router.get("/overview")
def overview(conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
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
    }
