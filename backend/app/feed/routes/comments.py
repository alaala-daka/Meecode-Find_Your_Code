"""评论区路由：两层平铺（顶层 + 回复），LLM 异步预审见 moderation.py（spec 2026-09-24）。

路径扁平挂 /api/comments（repo_id 进 body/query）——嵌套 /api/repos/{id}/comments
会与 delist 限流桶前缀冲突（差异在路径尾段，排序不可解，spec 决策 9）。
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from .. import auth, cards
from .. import moderation
from ..deps import get_conn
from ..schemas import CommentIn, CommentOut, CommentsOut

router = APIRouter()


def _to_out(row: sqlite3.Row) -> CommentOut:
    return CommentOut(
        id=row["id"], repo_id=row["repo_id"], user_id=row["user_id"],
        user_login=row["user_login"], user_avatar=row["user_avatar"] or "",
        parent_id=row["parent_id"], content=row["content"],
        status=row["status"], moderation_reason=row["moderation_reason"],
        created_at=row["created_at"],
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


def _normalize_parent(conn: sqlite3.Connection, repo_id: int, parent_id: int) -> int:
    """parent_id 归一到顶层祖先：两层平铺，对回复点「回复」落到同一顶层（spec 决策 3）。

    被隐藏/已删除的评论不可回复（作者本人也不例外）：直接父与归一后的顶层
    都必须是 pending/visible（spec 决策 12）。
    """
    row = conn.execute(
        "SELECT id, parent_id, status FROM comments WHERE id = ? AND repo_id = ?",
        (parent_id, repo_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=422, detail="回复的父评论不存在")
    if row["status"] in ("hidden", "deleted"):
        raise HTTPException(status_code=422, detail="不能回复已隐藏或已删除的评论")
    top_id = row["parent_id"] if row["parent_id"] is not None else row["id"]
    if top_id != row["id"]:
        top = conn.execute("SELECT status FROM comments WHERE id = ?", (top_id,)).fetchone()
        if top is None or top["status"] in ("hidden", "deleted"):
            raise HTTPException(status_code=422, detail="不能回复已隐藏或已删除的评论")
    return top_id


@router.post("/comments", response_model=CommentOut)
def create_comment(
    body: CommentIn,
    request: Request,
    background: BackgroundTasks,
    conn: sqlite3.Connection = Depends(get_conn),
) -> CommentOut:
    """发表评论/回复。落库即 pending（LLM 预审由 Task 5 接入），响应不等判定。"""
    if conn.execute(
        "SELECT 1 FROM repos WHERE id = ? AND status != 'delisted'", (body.repo_id,)
    ).fetchone() is None:
        raise HTTPException(status_code=404, detail="仓库不存在或已下架")
    user = auth.require_user(request, conn)
    parent = (
        _normalize_parent(conn, body.repo_id, body.parent_id)
        if body.parent_id is not None else None
    )
    cur = conn.execute(
        "INSERT INTO comments (repo_id, user_id, parent_id, content) VALUES (?,?,?,?)",
        (body.repo_id, user["id"], parent, body.content),
    )
    conn.commit()
    comment_id = cur.lastrowid
    background.add_task(moderation.moderate_comment_bg, comment_id)
    row = conn.execute(
        "SELECT c.*, u.login AS user_login, u.avatar_url AS user_avatar"
        " FROM comments c JOIN users u ON u.id = c.user_id WHERE c.id = ?",
        (comment_id,),
    ).fetchone()
    return _to_out(row)


def _load_comment(conn: sqlite3.Connection, comment_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if row is None or row["status"] == "deleted":
        raise HTTPException(status_code=404, detail="评论不存在")
    return row


def _is_repo_author(conn: sqlite3.Connection, repo_id: int, user: sqlite3.Row) -> bool:
    """作者 = owner_login 匹配或 claimed_by 认领（与 delist 权限同口径，submit.py:180）。"""
    row = conn.execute(
        "SELECT owner_login, claimed_by FROM repos WHERE id = ?", (repo_id,)
    ).fetchone()
    return bool(row) and (row["claimed_by"] == user["id"] or row["owner_login"] == user["login"])


@router.delete("/comments/{comment_id}")
def delete_comment(
    comment_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """软删自己的评论（status='deleted'，内容保留供审计）。幂等：已删除再删返回 ok。"""
    user = auth.require_user(request, conn)
    row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="评论不存在")
    if row["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="只能删除自己的评论")
    if row["status"] != "deleted":
        conn.execute("UPDATE comments SET status = 'deleted' WHERE id = ?", (comment_id,))
        conn.execute(
            "UPDATE comments SET status = 'deleted' WHERE parent_id = ? AND status != 'deleted'",
            (comment_id,),
        )
        conn.commit()
    return {"ok": True}


@router.post("/comments/{comment_id}/hide")
def hide_comment(
    comment_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """作者/认领者隐藏本仓库评论。幂等：已 hidden 再隐返回 ok；deleted 行 404。"""
    user = auth.require_user(request, conn)
    row = _load_comment(conn, comment_id)
    if not _is_repo_author(conn, row["repo_id"], user):
        raise HTTPException(status_code=403, detail="只有仓库作者可以隐藏评论")
    if row["status"] != "hidden":
        conn.execute("UPDATE comments SET status = 'hidden' WHERE id = ?", (comment_id,))
        conn.execute(
            "UPDATE comments SET status = 'hidden' WHERE parent_id = ? AND status != 'deleted'",
            (comment_id,),
        )
        conn.commit()
    return {"ok": True}
