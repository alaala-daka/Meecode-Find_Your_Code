"""用户反馈（spec 2026-10-10 三期 §3.2/§3.4）：提交 + 我的反馈 + 回复通知。

路径扁平挂 /api/feedback（与评论区同款，避开嵌套前缀与限流桶冲突）。
一切 UGC 面向用户只出摘要（substr）与纯文本，管理侧 contact 才全量回。
"""
from __future__ import annotations

import logging
import sqlite3
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import auth
from ..deps import get_conn
from ..schemas import (FeedbackDetailOut, FeedbackIn, FeedbackOut, FeedbackReply,
                       MyFeedbackItem, MyFeedbackOut)

log = logging.getLogger(__name__)

router = APIRouter()

_BODY_PREVIEW = 60
_REPLY_PREVIEW = 80


def _mark_replies_read(conn: sqlite3.Connection, feedback_id: int) -> None:
    """置已读。首写生效不覆盖（WHERE read_at IS NULL），失败吞异常绝不 500。"""
    try:
        conn.execute(
            "UPDATE feedback_replies SET read_at=? WHERE feedback_id=? AND read_at IS NULL",
            (int(time.time()), feedback_id))
        conn.commit()
    except Exception:
        log.exception("feedback_replies 置已读失败（feedback_id=%s）", feedback_id)


@router.post("/feedback", response_model=FeedbackOut, status_code=201)
def create_feedback(body: FeedbackIn, request: Request,
                    conn: sqlite3.Connection = Depends(get_conn)) -> FeedbackOut:
    """提交反馈。禁言/禁投稿任一命中即 403（spec §3.2：被封用户不得走反馈通道）。"""
    user = auth.require_user(request, conn)
    auth.ensure_not_banned(conn, user["id"], "comment")
    auth.ensure_not_banned(conn, user["id"], "submit")
    now = int(time.time())
    cur = conn.execute(
        "INSERT INTO feedback (user_id, category, body, contact, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?)",
        (user["id"], body.category, body.body, body.contact, now, now))
    conn.commit()
    return FeedbackOut(id=cur.lastrowid)


@router.get("/my/feedback", response_model=MyFeedbackOut)
def list_my_feedback(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    conn: sqlite3.Connection = Depends(get_conn),
) -> MyFeedbackOut:
    """我的反馈列表。摘要与未读数由子查询算，不把正文整段下发。"""
    user = auth.require_user(request, conn)
    total = conn.execute("SELECT COUNT(*) AS n FROM feedback WHERE user_id=?",
                         (user["id"],)).fetchone()["n"]
    rows = conn.execute(
        f"""SELECT f.id, f.category, substr(f.body, 1, {_BODY_PREVIEW}) AS body_preview,
                   f.status, f.created_at, f.updated_at,
                   (SELECT substr(r.body, 1, {_REPLY_PREVIEW}) FROM feedback_replies r
                     WHERE r.feedback_id = f.id
                     ORDER BY r.created_at DESC, r.id DESC LIMIT 1) AS last_reply_preview,
                   (SELECT r.created_at FROM feedback_replies r WHERE r.feedback_id = f.id
                     ORDER BY r.created_at DESC, r.id DESC LIMIT 1) AS last_reply_at,
                   (SELECT COUNT(*) FROM feedback_replies r
                     WHERE r.feedback_id = f.id AND r.read_at IS NULL) AS unread_count
              FROM feedback f WHERE f.user_id = ?
             ORDER BY f.id DESC LIMIT ? OFFSET ?""",
        (user["id"], page_size, (page - 1) * page_size)).fetchall()
    return MyFeedbackOut(items=[MyFeedbackItem(**dict(r)) for r in rows], total=total)


@router.get("/feedback/{feedback_id}", response_model=FeedbackDetailOut)
def get_my_feedback(feedback_id: int, request: Request,
                    conn: sqlite3.Connection = Depends(get_conn)) -> FeedbackDetailOut:
    """我的反馈详情。非本人与不存在统一 404 防 id 枚举；成功返回后把回复置已读。

    GET 带写副作用属接受风险：SameSite=Lax + 顶层导航最坏结果是「自己未读被消」。
    """
    user = auth.require_user(request, conn)
    row = conn.execute("SELECT id, category, body, status, created_at, updated_at"
                       " FROM feedback WHERE id=? AND user_id=?",
                       (feedback_id, user["id"])).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    replies = conn.execute(
        "SELECT id, body, author_login, created_at FROM feedback_replies"
        " WHERE feedback_id=? ORDER BY created_at ASC, id ASC",
        (feedback_id,)).fetchall()
    out = FeedbackDetailOut(**dict(row), replies=[FeedbackReply(**dict(r)) for r in replies])
    try:
        _mark_replies_read(conn, feedback_id)
    except Exception:                       # 置已读是写副作用，炸出也不许拖垮读面
        log.exception("feedback_replies 置已读调用炸出（feedback_id=%s）", feedback_id)
    return out
