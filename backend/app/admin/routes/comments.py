# backend/app/admin/routes/comments.py
"""管理台评论：隐藏/恢复/软删/批量/统计。四态迁移均 UPDATE status，绝不物理 DELETE。"""
from __future__ import annotations

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ...feed import deps
from ..audit import record_audit
from ..deps import require_admin

router = APIRouter()

# 合法转移表：action -> (允许的源状态集合, 目标状态)。软删为终态，防复活/防覆盖。
_TRANSITIONS = {
    "hide": ({"visible", "pending"}, "hidden"),
    "restore": ({"hidden"}, "visible"),
    "delete": ({"visible", "pending", "hidden"}, "deleted"),
}

_STATUSES = ("pending", "visible", "hidden", "deleted")


class BulkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[int] = Field(min_length=1, max_length=200)
    action: Literal["hide"]           # 一期仅批量隐藏


def _row_out(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "repo_id": r["repo_id"], "repo_full_name": r["repo_full_name"],
        "user_id": r["user_id"], "user_login": r["user_login"], "parent_id": r["parent_id"],
        "content": r["content"], "status": r["status"],
        "moderation_reason": r["moderation_reason"], "screened": r["screened"],
        "created_at": r["created_at"],
    }


@router.get("/comments")
def list_comments(
    conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)],
    status: str = "", repo_id: int | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
) -> dict:
    where, args = ["1=1"], []
    if status in _STATUSES:
        where.append("c.status=?")
        args.append(status)
    if repo_id is not None:
        where.append("c.repo_id=?")
        args.append(repo_id)
    w = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) AS n FROM comments c WHERE {w}", args).fetchone()["n"]
    rows = conn.execute(
        f"""SELECT c.*, r.full_name AS repo_full_name, u.login AS user_login
              FROM comments c
              JOIN repos r ON r.id = c.repo_id
              JOIN users u ON u.id = c.user_id
             WHERE {w} ORDER BY c.id DESC LIMIT ? OFFSET ?""",
        [*args, page_size, (page - 1) * page_size]).fetchall()
    return {"data": [_row_out(r) for r in rows], "total": total}


@router.get("/comments/stats")
def stats(conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    out = dict.fromkeys(_STATUSES, 0)
    for r in conn.execute("SELECT status, COUNT(*) AS n FROM comments GROUP BY status"):
        out[r["status"]] = r["n"]
    return out


@router.post("/comments/bulk")
def bulk_hide(body: BulkIn, request: Request,
              conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    unique_ids = list(dict.fromkeys(body.ids))
    allowed, _ = _TRANSITIONS["hide"]
    affected, not_found, skipped = [], [], []
    for cid in unique_ids:
        row = conn.execute("SELECT status FROM comments WHERE id=?", (cid,)).fetchone()
        if row is None:
            not_found.append(cid)
        elif row["status"] in allowed:
            conn.execute("UPDATE comments SET status='hidden' WHERE id=?", (cid,))
            affected.append(cid)
        else:
            skipped.append(cid)
    conn.commit()
    record_audit(conn, admin_login=require_admin(request, conn)["login"],
                 action="comment.bulk_hide", target_type="comment", target_id=None,
                 detail={"ids": affected})
    return {"ok": True, "affected": len(affected), "not_found": not_found, "skipped": skipped}


@router.post("/comments/{comment_id}/{action}")
def moderate(comment_id: int, action: Literal["hide", "restore"], request: Request,
             conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    allowed, target = _TRANSITIONS[action]
    row = conn.execute("SELECT status FROM comments WHERE id=?", (comment_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "评论不存在")
    if row["status"] not in allowed:
        raise HTTPException(409, f"非法状态转移: {row['status']} -> {action}")
    conn.execute("UPDATE comments SET status=? WHERE id=?", (target, comment_id))
    conn.commit()
    record_audit(conn, admin_login=require_admin(request, conn)["login"],
                 action=f"comment.{action}", target_type="comment", target_id=comment_id,
                 detail={"from": row["status"], "to": target})
    return {"ok": True, "status": target}


@router.delete("/comments/{comment_id}")
def soft_delete(comment_id: int, request: Request,
                conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    allowed, target = _TRANSITIONS["delete"]
    row = conn.execute("SELECT status FROM comments WHERE id=?", (comment_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "评论不存在")
    if row["status"] not in allowed:
        raise HTTPException(409, f"非法状态转移: {row['status']} -> delete")
    conn.execute("UPDATE comments SET status=? WHERE id=?", (target, comment_id))
    conn.commit()
    record_audit(conn, admin_login=require_admin(request, conn)["login"],
                 action="comment.delete", target_type="comment", target_id=comment_id,
                 detail={"from": row["status"], "to": target})
    return {"ok": True, "status": target}
