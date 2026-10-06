# backend/app/admin/routes/audit.py
"""管理台审计日志查询（spec §5.4）：ts 降序 + action/admin 筛选 + 分页；detail 容错解析。"""
from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from ...feed import deps

router = APIRouter()


def _detail_out(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _row_out(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "ts": r["ts"], "admin_login": r["admin_login"],
        "action": r["action"], "target_type": r["target_type"],
        "target_id": r["target_id"], "detail": _detail_out(r["detail"]),
    }


@router.get("/audit-logs")
def list_audit_logs(
    conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)],
    action: str = "",
    admin: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    where, args = ["1=1"], []
    if action:
        where.append("action=?")
        args.append(action)
    if admin:
        where.append("admin_login=?")
        args.append(admin)
    w = " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM audit_logs WHERE {w}", args).fetchone()["n"]
    rows = conn.execute(
        f"SELECT * FROM audit_logs WHERE {w} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
        [*args, page_size, (page - 1) * page_size]).fetchall()
    return {"data": [_row_out(r) for r in rows], "total": total}
