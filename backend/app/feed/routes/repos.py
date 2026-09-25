"""仓库详情与文件预览。

文件预览走 GitHub API 实时代理 —— 绝不 clone、绝不落地仓库文件。
瞬时故障（GitHubError）抛 502，确定性结果（二进制/超大文件）抛 422，
不再用 error 字段降级：空内容对前端就是错的，明确报错才能引导用户。
降级结果不进缓存：GitHubError 穿过 lru_cache 往外抛（抛异常的调用不会被
缓存），下次请求自动重试，限流窗口过去即恢复（见 spec 第 9 节）。
"""
from __future__ import annotations

import sqlite3
import time
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ... import config
from .. import auth, cards, github, ranking
from ..deps import get_conn
from ..schemas import RepoCardOut, RepoDetailOut, RepoFileOut, TreeItem

router = APIRouter()


def _load(conn: sqlite3.Connection, repo_id: int) -> sqlite3.Row:
    # 卡片查询带 like_count 实时子查询:详情/related 直接复用卡片字段口径
    row = conn.execute(
        cards._card_select("FROM repos r")
        + " WHERE r.id = ? AND r.status != 'delisted'", (repo_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="仓库不存在或已下架")
    return row


def _safe_path(path: str) -> str:
    """只允许仓库内相对路径：拒绝 .. 与绝对路径，防路径穿越。"""
    p = (path or "").strip().replace("\\", "/")
    if not p or p.startswith("/") or ".." in p.split("/"):
        raise HTTPException(status_code=422, detail="非法文件路径")
    return p


@router.get("/repos/{repo_id}", response_model=RepoDetailOut)
def get_repo(
    repo_id: int,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> RepoDetailOut:
    row = _load(conn, repo_id)
    conn.execute(
        "UPDATE repos SET repo_view_count = repo_view_count + 1 WHERE id = ?", (repo_id,)
    )

    user = auth.current_user(request, conn)
    if user is not None:
        conn.execute(
            "INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
            " VALUES (?,?,'visit',?)"
            " ON CONFLICT(user_id, repo_id, kind) DO UPDATE SET updated_at = excluded.updated_at",
            (user["id"], repo_id, int(time.time())),
        )
    conn.commit()

    # 重读：views/likes 要含本次浏览（卡片口径实时算,不能拿浏览前的旧行）
    row = _load(conn, repo_id)

    liked = favorited = False
    if user is not None:
        kinds = {
            r["kind"]
            for r in conn.execute(
                "SELECT kind FROM interactions WHERE user_id = ? AND repo_id = ?"
                " AND kind IN ('like', 'favorite')",
                (user["id"], repo_id),
            ).fetchall()
        }
        liked = "like" in kinds
        favorited = "favorite" in kinds

    card = cards.to_card(row)
    return RepoDetailOut(
        **card.model_dump(),
        intro_zh=row["intro_zh"],
        github_url=f"https://github.com/{row['full_name']}",
        default_branch=row["default_branch"],
        liked=liked,
        favorited=favorited,
    )


@lru_cache(maxsize=config.TREE_CACHE_SIZE)
def _cached_tree(full_name: str, branch: str) -> tuple[tuple, str]:
    """缓存文件树，省 GitHub 配额。不落库（见 spec 第 7 节）。

    GitHubError 直接往外抛：lru_cache 不缓存抛异常的调用，
    降级结果不会卡在缓存里，下次请求自然重试。
    """
    entries = github.get_tree(full_name, branch, interactive=True)
    return tuple((e["path"], e["type"], e.get("size", 0)) for e in entries), ""


def _to_frontend_tree(rows: list[dict]) -> list[dict]:
    """GitHub 递归树按父先子后返回;blob/tree 转前端 file/dir 并组装 children。"""
    roots: list[dict] = []
    index: dict[str, dict] = {}
    for e in rows:
        node = {"name": e["path"].rsplit("/", 1)[-1], "path": e["path"],
                "type": "file" if e["type"] == "blob" else "dir"}
        if node["type"] == "dir":
            node["children"] = []
        index[e["path"]] = node
        parent_path, _, _ = e["path"].rpartition("/")
        parent = index.get(parent_path) if parent_path else None
        (parent["children"] if parent else roots).append(node)
    return roots


# exclude_unset：file 节点不带 children 键,dir 节点始终带(含空目录)
@router.get("/repos/{repo_id}/tree", response_model=list[TreeItem],
            response_model_exclude_unset=True)
def get_repo_tree(
    repo_id: int, conn: sqlite3.Connection = Depends(get_conn)
) -> list[TreeItem]:
    row = _load(conn, repo_id)
    try:
        packed, _ = _cached_tree(row["full_name"], row["default_branch"])
    except github.GitHubError as exc:
        raise HTTPException(status_code=502, detail=f"暂时无法读取文件列表:{exc}") from exc
    rows = [{"path": p, "type": t, "size": s} for p, t, s in packed]
    return [TreeItem(**n) for n in _to_frontend_tree(rows)]


@lru_cache(maxsize=config.FILE_CACHE_SIZE)
def _cached_file(full_name: str, path: str, branch: str) -> tuple[str, str]:
    """缓存文件内容。GitHubError 往外抛（不进缓存）；
    二进制判定与截断由内容决定，结果可安全缓存。
    """
    content = github.get_file(full_name, path, branch, interactive=True)
    if "\x00" in content[:4096]:
        return "", "该文件为二进制，请到 GitHub 查看"
    if len(content) > config.MAX_FILE_CHARS:
        return content[:config.MAX_FILE_CHARS], "文件过大，已截断，完整内容请到 GitHub 查看"
    return content, ""


@router.get("/repos/{repo_id}/files", response_model=RepoFileOut)
def get_repo_file(
    repo_id: int,
    path: str = Query(...),
    conn: sqlite3.Connection = Depends(get_conn),
) -> RepoFileOut:
    row = _load(conn, repo_id)
    safe = _safe_path(path)
    try:
        content, error = _cached_file(row["full_name"], safe, row["default_branch"])
    except github.GitHubError as exc:
        raise HTTPException(status_code=502, detail=f"暂时无法读取该文件:{exc}") from exc
    if error:
        # 二进制/截断是确定性结果,不是瞬时故障:422 让前端走错误提示而不是空文件
        raise HTTPException(status_code=422, detail=error)
    return RepoFileOut(path=safe, content=content)


@router.get("/repos/{repo_id}/related", response_model=list[RepoCardOut])
def related(
    repo_id: int, conn: sqlite3.Connection = Depends(get_conn)
) -> list[RepoCardOut]:
    """同分类按 score 取前 N;mock 契约有、worktree 漏实现,此处补齐(spec 第 4 节)。"""
    row = _load(conn, repo_id)
    now = int(time.time())
    rows = conn.execute(
        cards._card_select("FROM repos r")
        + " WHERE r.status != 'delisted' AND r.category = ? AND r.id != ?"
        " ORDER BY r.published_at DESC LIMIT ?",
        (row["category"], repo_id, config.FEED_CANDIDATE_LIMIT),
    ).fetchall()
    ranked = sorted(rows, key=lambda r: ranking.score(r, now), reverse=True)
    return [cards.to_card(r) for r in ranked[: config.RELATED_LIMIT]]
