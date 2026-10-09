"""流量观测 API（spec 2026-10-09 §3）。"""
from __future__ import annotations

import sqlite3
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ... import security, traffic
from ...feed import deps

router = APIRouter()


@router.get("/traffic")
def traffic_series(
    conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)],
    range: str = Query("7d", pattern=r"^(7d|30d|12m|year=\d{4})$"),
) -> dict:
    now = int(time.time())
    if range == "7d":
        return {"range": range, "days": traffic.day_series(conn, 7, now)}
    if range == "30d":
        return {"range": range, "days": traffic.day_series(conn, 30, now)}
    if range == "12m":
        return {"range": range, "months": traffic.month_series(conn, 12, now)}
    year = int(range.split("=")[1])
    if not 2020 <= year <= time.gmtime(now).tm_year + 1:
        # 收敛年份区间：year=1900 也会触发全年逐日扫描（放大面，安全复审）
        raise HTTPException(status_code=422, detail="year 超出范围")
    view = traffic.year_view(conn, year, now)
    return {"range": range, "months": view["months"], "summary": view["summary"]}


@router.get("/traffic/yearly")
def traffic_yearly(conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    return {"years": traffic.yearly(conn)}


@router.get("/online")
def online(conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    window = traffic.online_window_minutes(conn)
    return {"online": traffic.online_count(conn, window), "window_minutes": window}


@router.get("/api-stats")
def api_stats(
    conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)],
    range: str = Query("7d", pattern=r"^(7d|30d)$"),
) -> dict:
    days = 7 if range == "7d" else 30
    cutoff = int(time.time()) - days * 86400
    agg: dict[str, dict] = {}
    for r in conn.execute(  # 游标流式迭代，勿 fetchall（防 30 天明细内存尖峰）
            "SELECT method, path, status_code FROM access_events"
            " WHERE ts>=? AND method!='HIT'", (cutoff,)):
        bucket = security.bucket_for(r["method"], r["path"])
        e = agg.setdefault(bucket, {"route_key": bucket, "calls": 0, "errors": 0})
        e["calls"] += 1
        if r["status_code"] >= 500:
            e["errors"] += 1
    for r in conn.execute("SELECT route_key FROM api_policies").fetchall():
        agg.setdefault(r["route_key"],
                       {"route_key": r["route_key"], "calls": 0, "errors": 0})
    out = []
    for e in agg.values():
        e["error_rate"] = round(e["errors"] / e["calls"], 4) if e["calls"] else 0.0
        out.append(e)
    out.sort(key=lambda x: -x["calls"])
    return {"range": range, "buckets": out}
