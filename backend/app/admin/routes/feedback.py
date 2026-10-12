# backend/app/admin/routes/feedback.py
"""管理台反馈收件箱：列表/详情（spec 2026-10-10 三期 §3.3）。

列表刻意不 SELECT contact——PII 只在详情单点回，避免整页外泄。
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ...feed import deps
from ...sqlutil import like_pattern

router = APIRouter()

_STATUSES = ("pending", "done", "ignored")
_CATEGORIES = ("bug", "suggest", "other")
_Q_MAX = 50


def _clean_q(q: str) -> str:
    q = q.strip()
    if not q or len(q) > _Q_MAX:
        raise HTTPException(422, f"q 须为 1–{_Q_MAX} 字符")
    return q


def _row_out(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "user_id": r["user_id"], "user_login": r["user_login"],
        "category": r["category"], "body": r["body"], "status": r["status"],
        "note": r["note"] or "", "reply_count": r["reply_count"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


@router.get("/feedback")
def list_feedback(
    conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)],
    q: str = "", status: str = "", category: str = "",
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
) -> dict:
    where, args = ["1=1"], []
    if q:
        where.append("f.body LIKE ? ESCAPE '\\'")
        args.append(like_pattern(_clean_q(q)))
    if status:
        if status not in _STATUSES:
            raise HTTPException(422, "status 须为 pending/done/ignored")
        where.append("f.status=?")
        args.append(status)
    if category:
        if category not in _CATEGORIES:
            raise HTTPException(422, "category 须为 bug/suggest/other")
        where.append("f.category=?")
        args.append(category)
    w = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) AS n FROM feedback f WHERE {w}", args).fetchone()["n"]
    rows = conn.execute(
        f"""SELECT f.id, f.user_id, u.login AS user_login, f.category, f.body, f.status,
                   f.note, f.created_at, f.updated_at,
                   (SELECT COUNT(*) FROM feedback_replies r
                     WHERE r.feedback_id = f.id) AS reply_count
              FROM feedback f JOIN users u ON u.id = f.user_id
             WHERE {w} ORDER BY f.id DESC LIMIT ? OFFSET ?""",
        [*args, page_size, (page - 1) * page_size]).fetchall()
    return {"data": [_row_out(r) for r in rows], "total": total}


@router.get("/feedback/{feedback_id}")
def get_feedback(feedback_id: int,
                 conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    r = conn.execute(
        "SELECT f.*, u.login AS user_login FROM feedback f"
        " JOIN users u ON u.id = f.user_id WHERE f.id=?", (feedback_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "反馈不存在")
    replies = conn.execute(
        "SELECT id, body, author_login, created_at, read_at FROM feedback_replies"
        " WHERE feedback_id=? ORDER BY created_at ASC, id ASC", (feedback_id,)).fetchall()
    return {
        "id": r["id"], "user_id": r["user_id"], "user_login": r["user_login"],
        "category": r["category"], "body": r["body"], "contact": r["contact"],
        "status": r["status"], "note": r["note"] or "",
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "replies": [dict(x) for x in replies],
    }
