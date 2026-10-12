"""用户反馈（spec 2026-10-10 三期 §3.2/§3.4）：提交 + 我的反馈 + 回复通知。

路径扁平挂 /api/feedback（与评论区同款，避开嵌套前缀与限流桶冲突）。
一切 UGC 面向用户只出摘要（substr）与纯文本，管理侧 contact 才全量回。
"""
from __future__ import annotations

import logging
import sqlite3
import time

from fastapi import APIRouter, Depends, Request

from .. import auth
from ..deps import get_conn
from ..schemas import FeedbackIn, FeedbackOut

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
