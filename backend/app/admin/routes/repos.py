# backend/app/admin/routes/repos.py
"""管理台仓库：上下架状态机 + 元数据编辑。"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ...feed import deps
from ..audit import record_audit
from ..deps import require_admin

router = APIRouter()

# 合法转移表：action -> (允许的源状态集合, 目标状态)。单连接串行「先读后校验再写」无竞态。
TRANSITIONS = {
    "publish": ({"pending_claim", "delisted"}, "published"),
    "delist": ({"published", "pending_claim"}, "delisted"),
    "restore": ({"delisted"}, "published"),
}

_STATUSES = ("published", "pending_claim", "delisted")


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _row_out(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "github_id": r["github_id"], "full_name": r["full_name"],
        "owner_login": r["owner_login"], "language": r["language"], "stars": r["stars"],
        "source": r["source"], "status": r["status"], "category": r["category"],
        "quality": r["quality"], "tagline_zh": r["tagline_zh"],
        "impression_count": r["impression_count"], "repo_view_count": r["repo_view_count"],
        "published_at": r["published_at"],
    }


@router.get("/repos")
def list_repos(
    conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)],
    q: str = "", status: str = "", page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    where, args = ["1=1"], []
    if q:
        where.append("full_name LIKE ? ESCAPE '\\'")
        args.append(_like(q))
    if status in _STATUSES:
        where.append("status=?")
        args.append(status)
    w = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) AS n FROM repos WHERE {w}", args).fetchone()["n"]
    rows = conn.execute(
        f"SELECT * FROM repos WHERE {w} ORDER BY id DESC LIMIT ? OFFSET ?",
        [*args, page_size, (page - 1) * page_size]).fetchall()
    return {"data": [_row_out(r) for r in rows], "total": total}


class RepoEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None = Field(max_length=50, default=None)
    quality: int | None = Field(ge=0, le=10, default=None)
    tagline_zh: str | None = Field(max_length=200, default=None)


@router.patch("/repos/{repo_id}")
def patch_repo(repo_id: int, body: RepoEditIn, request: Request,
               conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    if conn.execute("SELECT id FROM repos WHERE id=?", (repo_id,)).fetchone() is None:
        raise HTTPException(404, "仓库不存在")
    fields = body.model_dump(exclude_none=True)
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE repos SET {sets} WHERE id=?", (*fields.values(), repo_id))
        conn.commit()
        record_audit(conn, admin_login=require_admin(request, conn)["login"], action="repo.edit",
                     target_type="repo", target_id=repo_id, detail=fields)
    return {"ok": True}


@router.post("/repos/{repo_id}/{action}")
def transition(repo_id: int, action: str, request: Request,
               conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    if action not in TRANSITIONS:
        raise HTTPException(404, "未知动作")
    allowed, target = TRANSITIONS[action]
    row = conn.execute("SELECT status FROM repos WHERE id=?", (repo_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "仓库不存在")
    if row["status"] not in allowed:
        raise HTTPException(409, f"非法状态转移: {row['status']} -> {action}")
    conn.execute("UPDATE repos SET status=? WHERE id=?", (target, repo_id))
    conn.commit()
    record_audit(conn, admin_login=require_admin(request, conn)["login"],
                 action=f"repo.{action}", target_type="repo", target_id=repo_id,
                 detail={"from": row["status"], "to": target})
    return {"ok": True, "status": target}
