"""评论区路由：两层平铺（顶层 + 回复），LLM 异步预审见 moderation.py（spec 2026-09-24）。

路径扁平挂 /api/comments（repo_id 进 body/query）——嵌套 /api/repos/{id}/comments
会与 delist 限流桶前缀冲突（差异在路径尾段，排序不可解，spec 决策 9）。
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import auth, cards
from ..deps import get_conn
from ..schemas import CommentOut, CommentsOut

router = APIRouter()


def _to_out(row: sqlite3.Row) -> CommentOut:
    return CommentOut(
        id=row["id"], repo_id=row["repo_id"], user_id=row["user_id"],
        user_login=row["user_login"], user_avatar=row["user_avatar"] or "",
        parent_id=row["parent_id"], content=row["content"],
        status=row["status"], created_at=row["created_at"],
        created_at_iso=cards._iso(row["created_at"]),
    )


@router.get("/comments", response_model=CommentsOut)
def list_comments(
    request: Request,
    repo_id: int = Query(...),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_conn),
) -> CommentsOut:
    """平铺列表。分页对象为顶层线程（线程不跨页），items 每顶层后跟可见回复。

    可见性：status='visible' 全员 + 本人的 pending/hidden；deleted 永不返回；
    回复跟随顶层可见性（顶层不可见则回复一并不返回，避免孤儿楼层）。
    """
    if conn.execute(
        "SELECT 1 FROM repos WHERE id = ? AND status != 'delisted'", (repo_id,)
    ).fetchone() is None:
        raise HTTPException(status_code=404, detail="仓库不存在或已下架")
    user = auth.current_user(request, conn)
    uid = user["id"] if user is not None else -1
    vis = "(c.status = 'visible' OR c.user_id = ?)"
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM comments c WHERE c.repo_id = ?"
        f" AND c.parent_id IS NULL AND c.status != 'deleted' AND {vis}",
        (repo_id, uid),
    ).fetchone()["n"]
    tops = conn.execute(
        "SELECT c.*, u.login AS user_login, u.avatar_url AS user_avatar"
        " FROM comments c JOIN users u ON u.id = c.user_id"
        f" WHERE c.repo_id = ? AND c.parent_id IS NULL AND c.status != 'deleted' AND {vis}"
        " ORDER BY c.created_at ASC, c.id ASC LIMIT ? OFFSET ?",
        (repo_id, uid, limit, offset),
    ).fetchall()
    replies: dict[int, list[CommentOut]] = {}
    top_ids = [r["id"] for r in tops]
    if top_ids:
        marks = ",".join("?" * len(top_ids))
        rows = conn.execute(
            "SELECT c.*, u.login AS user_login, u.avatar_url AS user_avatar"
            " FROM comments c JOIN users u ON u.id = c.user_id"
            f" WHERE c.parent_id IN ({marks}) AND c.status != 'deleted' AND {vis}"
            " ORDER BY c.created_at ASC, c.id ASC",
            (*top_ids, uid),
        ).fetchall()
        for r in rows:
            replies.setdefault(r["parent_id"], []).append(_to_out(r))
    items: list[CommentOut] = []
    for r in tops:
        items.append(_to_out(r))
        items.extend(replies.get(r["id"], []))
    return CommentsOut(items=items, total=total)
