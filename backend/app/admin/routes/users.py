# backend/app/admin/routes/users.py
"""管理台用户：列表/详情/备注/封禁/解封。状态由 ban 时间戳派生（spec §3）。"""
from __future__ import annotations

import sqlite3
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ...feed import deps
from ..deps import require_admin

router = APIRouter()

BAN_FOREVER = 253402300799


def _status_sql(alias: str = "u") -> str:
    return (f"(CASE WHEN COALESCE({alias}.ban_comment_until,0) > CAST(strftime('%s','now') AS INTEGER)"
            f" OR COALESCE({alias}.ban_submit_until,0) > CAST(strftime('%s','now') AS INTEGER)"
            f" THEN 'banned' ELSE 'normal' END)")


def _row_out(r: sqlite3.Row, counts: dict | None = None) -> dict:
    now = int(time.time())
    banned = (r["ban_comment_until"] or 0) > now or (r["ban_submit_until"] or 0) > now
    return {
        "id": r["id"], "login": r["login"], "avatar_url": r["avatar_url"],
        "created_at": r["created_at"], "ban_comment_until": r["ban_comment_until"],
        "ban_submit_until": r["ban_submit_until"], "ban_note": r["ban_note"],
        "admin_note": r["admin_note"], "status": "banned" if banned else "normal",
        "counts": counts or {"likes": 0, "favorites": 0, "visits": 0, "comments": 0},
    }


def _counts(conn: sqlite3.Connection, user_id: int) -> dict:
    row = conn.execute(
        """SELECT
             SUM(CASE WHEN kind='like' THEN 1 ELSE 0 END) AS likes,
             SUM(CASE WHEN kind='favorite' THEN 1 ELSE 0 END) AS favorites,
             SUM(CASE WHEN kind='visit' THEN 1 ELSE 0 END) AS visits
           FROM interactions WHERE user_id=?""",
        (user_id,)).fetchone()
    n = conn.execute("SELECT COUNT(*) AS n FROM comments WHERE user_id=? AND status!='deleted'",
                     (user_id,)).fetchone()["n"]
    return {"likes": row["likes"] or 0, "favorites": row["favorites"] or 0,
            "visits": row["visits"] or 0, "comments": n}


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/users")
def list_users(
    conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)],
    q: str = "", status: str = "", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
) -> dict:
    where, args = ["1=1"], []
    if q:
        where.append("u.login LIKE ? ESCAPE '\\'")
        args.append(_like(q))
    if status == "banned":
        where.append(_status_sql() + "='banned'")
    elif status == "normal":
        where.append(_status_sql() + "='normal'")
    w = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) AS n FROM users u WHERE {w}", args).fetchone()["n"]
    rows = conn.execute(
        f"SELECT u.* FROM users u WHERE {w} ORDER BY u.id DESC LIMIT ? OFFSET ?",
        [*args, page_size, (page - 1) * page_size]).fetchall()
    return {"data": [_row_out(r, _counts(conn, r["id"])) for r in rows], "total": total}


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    admin_note: str = Field(max_length=2000)


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: NoteIn, request: Request,
               conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    cur = conn.execute("UPDATE users SET admin_note=? WHERE id=?", (body.admin_note, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "用户不存在")
    from ..audit import record_audit  # Task 4 已存在
    record_audit(conn, admin_login=require_admin(request, conn)["login"], action="user.note",
                 target_type="user", target_id=user_id, detail={"admin_note": body.admin_note})
    return {"ok": True}


@router.get("/users/{user_id}")
def get_user(user_id: int, conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    r = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "用户不存在")
    out = _row_out(r, _counts(conn, user_id))
    out["recent_interactions"] = [dict(x) for x in conn.execute(
        "SELECT repo_id, kind, updated_at AS created_at FROM interactions WHERE user_id=?"
        " ORDER BY updated_at DESC, id DESC LIMIT 10", (user_id,)).fetchall()]
    return out


class BanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mute_comment: bool = False
    mute_submit: bool = False
    until: int = Field(ge=0)   # Unix epoch 秒；永久=BAN_FOREVER
    note: str = Field(max_length=500, default="")


@router.post("/users/{user_id}/ban")
def ban_user(user_id: int, body: BanIn, request: Request,
             conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    from ...admin.audit import record_audit
    from ...feed import auth as feed_auth

    cur = conn.execute(
        "UPDATE users SET ban_comment_until=?, ban_submit_until=?, ban_note=? WHERE id=?",
        (body.until if body.mute_comment else None,
         body.until if body.mute_submit else None,
         body.note, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "用户不存在")
    feed_auth.revoke_all(conn, user_id)  # 封禁即时全端下线
    admin = require_admin(request, conn)
    record_audit(conn, admin_login=admin["login"], action="user.ban", target_type="user",
                 target_id=user_id, detail=body.model_dump())
    return {"ok": True}


@router.post("/users/{user_id}/unban")
def unban_user(user_id: int, request: Request,
               conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    from ...admin.audit import record_audit
    from ...feed import auth as feed_auth

    cur = conn.execute(
        "UPDATE users SET ban_comment_until=NULL, ban_submit_until=NULL, ban_note='' WHERE id=?",
        (user_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "用户不存在")
    feed_auth.revoke_all(conn, user_id)
    admin = require_admin(request, conn)
    record_audit(conn, admin_login=admin["login"], action="user.unban", target_type="user",
                 target_id=user_id)
    return {"ok": True}
