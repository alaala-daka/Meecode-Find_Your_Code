"""管理台全局搜索（spec 2026-10-10 三期 §2.5）：三组各 ≤5 条，count 封顶 1001。"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ...feed import deps
from ...sqlutil import fts_escape, like_pattern

router = APIRouter()

_COUNT_CAP = 1001
_ITEMS = 5


def _capped_count(conn: sqlite3.Connection, tail: str, args: list) -> int:
    return conn.execute(
        f"SELECT COUNT(*) AS n FROM (SELECT 1 {tail} LIMIT ?)",
        [*args, _COUNT_CAP]).fetchone()["n"]


def _repos_search(conn: sqlite3.Connection, term: str, pat: str) -> tuple[list, int]:
    if len(term) >= 3:
        tail = ("FROM repos_fts f JOIN repos r ON r.id = f.rowid"
                " WHERE repos_fts MATCH ?")
        try:
            needle = fts_escape(term)
            items = conn.execute(
                f"SELECT r.id, r.full_name, r.tagline_zh, r.intro_zh {tail}"
                f" ORDER BY r.id DESC LIMIT ?", [needle, _ITEMS]).fetchall()
            return items, _capped_count(conn, tail, [needle])
        except sqlite3.OperationalError:
            pass
    tail = ("FROM repos r WHERE r.full_name LIKE ? ESCAPE '\\'"
            " OR r.tagline_zh LIKE ? ESCAPE '\\' OR r.intro_zh LIKE ? ESCAPE '\\'")
    args = [pat, pat, pat]
    items = conn.execute(
        f"SELECT r.id, r.full_name, r.tagline_zh, r.intro_zh {tail}"
        f" ORDER BY r.id DESC LIMIT ?", [*args, _ITEMS]).fetchall()
    return items, _capped_count(conn, tail, args)


@router.get("/search")
def global_search(
    conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)],
    q: str = Query(..., min_length=1, max_length=200),
) -> dict:
    term = q.strip()
    if len(term) < 2 or len(term) > 50:
        raise HTTPException(422, "q 须为 2–50 字符")
    pat = like_pattern(term)

    u_tail = "FROM users u WHERE u.login LIKE ? ESCAPE '\\' OR u.bio LIKE ? ESCAPE '\\'"
    u_args = [pat, pat]
    u_items = conn.execute(
        f"SELECT u.id, u.login, u.bio {u_tail} ORDER BY u.id DESC LIMIT ?",
        [*u_args, _ITEMS]).fetchall()
    u_count = _capped_count(conn, u_tail, u_args)

    r_items, r_count = _repos_search(conn, term, pat)

    c_tail = ("FROM comments c JOIN users u ON u.id = c.user_id"
              " WHERE c.status != 'deleted'"
              " AND c.content LIKE ? ESCAPE '\\'")
    c_args = [pat]
    c_items = conn.execute(
        f"SELECT c.id, c.content, c.repo_id, u.login AS user_login, c.status {c_tail}"
        f" ORDER BY c.id DESC LIMIT ?", [*c_args, _ITEMS]).fetchall()
    c_count = _capped_count(conn, c_tail, c_args)

    return {
        "users": {"count": u_count,
                  "items": [{"id": r["id"], "login": r["login"], "bio": r["bio"]}
                            for r in u_items]},
        "repos": {"count": r_count,
                  "items": [{"id": r["id"], "name": r["full_name"],
                             "title": r["tagline_zh"], "description": r["intro_zh"]}
                            for r in r_items]},
        "comments": {"count": c_count,
                     "items": [{"id": r["id"], "body": r["content"],
                                "author_login": r["user_login"], "repo_id": r["repo_id"],
                                "hidden": r["status"] == "hidden"}
                               for r in c_items]},
    }
