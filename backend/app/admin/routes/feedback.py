# backend/app/admin/routes/feedback.py
"""管理台反馈收件箱：列表/详情（spec 2026-10-10 三期 §3.3）。

列表刻意不 SELECT contact——PII 只在详情单点回，避免整页外泄。
"""
from __future__ import annotations

import sqlite3
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...feed import deps
from ...sqlutil import like_pattern
from ..audit import record_audit
from ..deps import require_admin

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


_DETAIL_MAX = 200


def _summarize(body: str) -> str:
    return body[:_DETAIL_MAX]


class FeedbackPatchIn(BaseModel):
    """部分更新。exclude_unset 区分「键缺省」与「显式空串」——note:"" 即清空；
    status 显式 null 直接 422（否则会拼出 SET status=NULL 撞 NOT NULL 约束变 500）。"""
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "done", "ignored"] | None = None
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str | None) -> str | None:
        if v is None:
            raise ValueError("status 不可为 null（缺省该键即不更新）")
        return v


@router.patch("/feedback/{feedback_id}")
def patch_feedback(feedback_id: int, body: FeedbackPatchIn, request: Request,
                   conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "至少提供 status 或 note")
    row = conn.execute("SELECT status FROM feedback WHERE id=?", (feedback_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "反馈不存在")
    admin = require_admin(request, conn)
    sets, args = [], []
    if "status" in fields:
        sets.append("status=?")
        args.append(fields["status"])
    if "note" in fields:
        sets.append("note=?")
        args.append(fields["note"] or "")   # 显式 null ≡ "" ≡ 清空，不落 NULL
    sets.append("updated_at=?")
    args.append(int(time.time()))
    args.append(feedback_id)
    conn.execute(f"UPDATE feedback SET {', '.join(sets)} WHERE id=?", args)
    conn.commit()
    if "status" in fields:
        record_audit(conn, admin_login=admin["login"], action="feedback.status",
                     target_type="feedback", target_id=feedback_id,
                     detail={"from": row["status"], "to": fields["status"]})
    if "note" in fields:
        record_audit(conn, admin_login=admin["login"], action="feedback.note",
                     target_type="feedback", target_id=feedback_id,
                     detail={"note": _summarize(fields["note"] or "")})
    return {"ok": True}


class FeedbackReplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str

    @field_validator("body")
    @classmethod
    def _check_body(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("回复内容不能为空")
        if len(v) > 1000:
            raise ValueError("回复内容过长（上限 1000 字符）")
        return v


@router.post("/feedback/{feedback_id}/replies", status_code=201)
def create_reply(feedback_id: int, body: FeedbackReplyIn, request: Request,
                 conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    """管理回复可多轮；只增线程不改 status（状态流转一律走 PATCH）。"""
    row = conn.execute("SELECT id FROM feedback WHERE id=?", (feedback_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "反馈不存在")
    admin = require_admin(request, conn)
    now = int(time.time())
    cur = conn.execute(
        "INSERT INTO feedback_replies (feedback_id, body, author_login, created_at)"
        " VALUES (?,?,?,?)", (feedback_id, body.body, admin["login"], now))
    conn.execute("UPDATE feedback SET updated_at=? WHERE id=?", (now, feedback_id))
    conn.commit()
    record_audit(conn, admin_login=admin["login"], action="feedback.reply",
                 target_type="feedback", target_id=feedback_id,
                 detail={"body": _summarize(body.body)})
    return {"id": cur.lastrowid}
