# backend/app/admin/routes/llm.py
"""管理台 LLM 用量统计（spec 2026-10-10 三期 §4.3，纯观测）。"""
from __future__ import annotations

import sqlite3
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ... import llm_usage, traffic
from ...feed import deps

router = APIRouter()

_MAX_SPAN_DAYS = 92  # 跨度上界（§4.3）：防一次拖垮全表聚合


def _day(s: str, name: str) -> int:
    try:
        return traffic.day_bounds_utc(s)[0]
    except Exception:
        raise HTTPException(422, f"{name} 须为 YYYY-MM-DD") from None


@router.get("/llm/stats")
def llm_stats(
    conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)],
    from_: str = Query("", alias="from"),
    to: str = "",
) -> dict:
    """区间统计：from/to 为 UTC 日闭区间；缺省=近 7 个 UTC 日；仅传一者 422。"""
    if not from_ and not to:
        to = time.strftime("%Y-%m-%d", time.gmtime())
        from_ = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 6 * 86400))
    elif not from_ or not to:
        raise HTTPException(422, "from/to 须成对提供")
    f0 = _day(from_, "from")
    t0 = _day(to, "to")
    if f0 > t0:
        raise HTTPException(422, "from 不得晚于 to")
    if (t0 - f0) // 86400 + 1 > _MAX_SPAN_DAYS:
        raise HTTPException(422, f"区间跨度不得超过 {_MAX_SPAN_DAYS} 天")
    return llm_usage.stats(conn, from_, to)
