"""管理台登录日志（spec 2026-10-10 三期 §2.3）：过滤恒 AND + id 降序 + ip 反查写审计。"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ...feed import deps
from ...sqlutil import like_pattern
from ...traffic import day_bounds_utc, login_ip_hash
from ..audit import record_audit
from ..deps import require_admin

router = APIRouter()

_EVENTS = ("login", "logout")
_TRUNC = 12
_Q_MAX = 50


def _row_out(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "ts": r["ts"], "user_id": r["user_id"], "login": r["login"],
        "ip_hash": (r["ip_hash"] or "")[:_TRUNC], "event": r["event"], "ok": r["ok"],
    }


def _day(s: str, name: str) -> int:
    try:
        return day_bounds_utc(s)[0]
    except Exception:
        raise HTTPException(422, f"{name} 须为 YYYY-MM-DD") from None


@router.get("/login-events")
def list_login_events(
    conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)],
    admin=Depends(require_admin),
    q: str = "",
    ok: str = "",
    event: str = "",
    from_: str = Query("", alias="from"),
    to: str = "",
    ip: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    where, args = ["1=1"], []
    if q:
        q = q.strip()
        if not q or len(q) > _Q_MAX:
            raise HTTPException(422, "q 须为 1–50 字符")
        where.append("login LIKE ? ESCAPE '\\'")
        args.append(like_pattern(q))
    if ok:
        if ok not in ("0", "1"):
            raise HTTPException(422, "ok 须为 0 或 1")
        where.append("ok=?")
        args.append(int(ok))
    if event:
        if event not in _EVENTS:
            raise HTTPException(422, "event 须为 login 或 logout")
        where.append("event=?")
        args.append(event)
    f0 = _day(from_, "from") if from_ else None
    t0 = _day(to, "to") if to else None
    if f0 is not None and t0 is not None and f0 > t0:
        raise HTTPException(422, "from 不得晚于 to")
    if f0 is not None:
        where.append("ts>=?")
        args.append(f0)
    if t0 is not None:
        where.append("ts<?")
        args.append(t0 + 86400)
    if ip:
        try:
            ip_h = login_ip_hash(ip)
        except ValueError:
            raise HTTPException(422, "ip 非法") from None
        where.append("ip_hash=?")
        args.append(ip_h)
        record_audit(conn, admin_login=admin["login"], action="login_events.ip_lookup",
                     target_type="login_events", target_id=None,
                     detail={"ip": ip[:8] + "…"})
    w = " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM login_events WHERE {w}", args).fetchone()["n"]
    rows = conn.execute(
        f"SELECT * FROM login_events WHERE {w} ORDER BY id DESC LIMIT ? OFFSET ?",
        [*args, page_size, (page - 1) * page_size]).fetchall()
    return {"data": [_row_out(r) for r in rows], "total": total}
