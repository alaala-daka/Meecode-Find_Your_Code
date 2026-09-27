"""收藏同步 GitHub 星：状态机（spec 2026-09-26）。

本地 interactions 是第一真源，GitHub 星是投影：本模块把投影推向 desired 状态。
不变量（Global Constraints）：origin 溯源保持；取消按 desired 判别；
401 清 token 返 need_auth；收藏方向 404/422 置 attempts=MAX 停止重试。
"""
from __future__ import annotations

import sqlite3
import time

from .. import config, security
from . import db, github


def _now() -> int:
    return int(time.time())


def _put_row(conn: sqlite3.Connection, user_id: int, repo_id: int, *,
             desired: str, applied: str, origin: str,
             error: str = "", bump: bool = False, final: bool = False) -> None:
    row = conn.execute(
        "SELECT attempts FROM star_syncs WHERE user_id = ? AND repo_id = ?", (user_id, repo_id)
    ).fetchone()
    attempts = ((row["attempts"] if row else 0) + 1) if bump else (row["attempts"] if row else 0)
    if final:
        attempts = config.STAR_SYNC_MAX_ATTEMPTS
    conn.execute(
        "INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, attempts, last_error, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?)"
        " ON CONFLICT(user_id, repo_id) DO UPDATE SET"
        "  desired = excluded.desired, applied = excluded.applied, origin = excluded.origin,"
        "  attempts = excluded.attempts, last_error = excluded.last_error, updated_at = excluded.updated_at",
        (user_id, repo_id, desired, applied, origin, attempts, error, _now()),
    )
    conn.commit()


def _del_row(conn: sqlite3.Connection, user_id: int, repo_id: int) -> None:
    conn.execute("DELETE FROM star_syncs WHERE user_id = ? AND repo_id = ?", (user_id, repo_id))
    conn.commit()


def _mark_token_dead(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("UPDATE users SET gh_token_enc = '', gh_star_authed_at = 0 WHERE id = ?", (user_id,))
    conn.execute("UPDATE star_syncs SET last_error = 'token revoked'"
                 " WHERE user_id = ? AND applied = 'pending'", (user_id,))
    conn.commit()


def _load_token(conn: sqlite3.Connection, user: sqlite3.Row) -> str | None:
    enc = user["gh_token_enc"]
    if not enc:
        return None
    try:
        return security.open_token(enc)
    except ValueError:
        _mark_token_dead(conn, user["id"])
        return None


def sync_favorite_on(conn: sqlite3.Connection, user: sqlite3.Row, repo: sqlite3.Row, *,
                     interactive: bool = True) -> str:
    token = _load_token(conn, user)
    if token is None:
        if conn.execute("SELECT 1 FROM star_syncs WHERE user_id = ? AND repo_id = ?",
                        (user["id"], repo["id"])).fetchone():
            conn.execute("UPDATE star_syncs SET desired = 'starred', updated_at = ?"
                         " WHERE user_id = ? AND repo_id = ?", (_now(), user["id"], repo["id"]))
            conn.commit()
        return "need_auth"
    if repo["owner_login"] == user["login"]:
        _put_row(conn, user["id"], repo["id"], desired="starred", applied="done", origin="external")
        return "skipped"
    prev = conn.execute("SELECT origin FROM star_syncs WHERE user_id = ? AND repo_id = ?",
                        (user["id"], repo["id"])).fetchone()
    try:
        if github.is_starred(token, repo["full_name"], interactive=interactive):
            # 溯源保持：星是觅码点的就仍是 meecode，防止取消收藏时漏撤
            origin = "meecode" if (prev and prev["origin"] == "meecode") else "external"
            _put_row(conn, user["id"], repo["id"], desired="starred", applied="done", origin=origin)
            return "synced"
        github.star_repo(token, repo["full_name"], interactive=interactive)
        _put_row(conn, user["id"], repo["id"], desired="starred", applied="done", origin="meecode")
        return "synced"
    except github.GitHubError as exc:
        if exc.status == 401:
            _mark_token_dead(conn, user["id"])
            return "need_auth"
        _put_row(conn, user["id"], repo["id"], desired="starred", applied="pending", origin="meecode",
                 error=str(exc), bump=True, final=exc.status in (404, 422))
        return "pending"


def sync_favorite_off(conn: sqlite3.Connection, user: sqlite3.Row, repo: sqlite3.Row, *,
                      interactive: bool = True) -> str:
    row = conn.execute("SELECT * FROM star_syncs WHERE user_id = ? AND repo_id = ?",
                       (user["id"], repo["id"])).fetchone()
    if row is None or row["origin"] == "external":
        _del_row(conn, user["id"], repo["id"])
        return "kept"
    if row["desired"] == "starred" and row["applied"] == "pending":
        # 星从未点上（或永久失败）：GitHub 无事发生，直接收敛
        _del_row(conn, user["id"], repo["id"])
        return "unstarred"
    token = _load_token(conn, user)
    if token is None:
        _put_row(conn, user["id"], repo["id"], desired="unstarred", applied="pending", origin="meecode",
                 error="token missing", bump=True)
        return "need_auth"
    try:
        github.unstar_repo(token, repo["full_name"], interactive=interactive)
        _del_row(conn, user["id"], repo["id"])
        return "unstarred"
    except github.GitHubError as exc:
        if exc.status == 401:
            _mark_token_dead(conn, user["id"])
            _put_row(conn, user["id"], repo["id"], desired="unstarred", applied="pending", origin="meecode",
                     error=str(exc), bump=True)
            return "need_auth"
        if exc.status in (404, 422):
            _del_row(conn, user["id"], repo["id"])  # 星随仓库消失，视为完成
            return "unstarred"
        _put_row(conn, user["id"], repo["id"], desired="unstarred", applied="pending", origin="meecode",
                 error=str(exc), bump=True)
        return "pending"


def backfill_user(conn: sqlite3.Connection, user_id: int) -> None:
    """对「已收藏但无同步记录」的仓库跑收藏方向同步（授权成功后的补同步）。已有行不动。"""
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None or not user["gh_token_enc"]:
        return
    favs = conn.execute(
        "SELECT r.* FROM interactions i JOIN repos r ON r.id = i.repo_id"
        " WHERE i.user_id = ? AND i.kind = 'favorite' AND r.status != 'delisted'",
        (user_id,),
    ).fetchall()
    for repo in favs:
        exists = conn.execute("SELECT 1 FROM star_syncs WHERE user_id = ? AND repo_id = ?",
                              (user_id, repo["id"])).fetchone()
        if exists is None:
            sync_favorite_on(conn, user, repo, interactive=False)
    conn.commit()


def backfill_after_auth(user_id: int) -> None:
    """BackgroundTasks 入口：自开连接（请求级 conn 已随响应关闭，moderate_comment_bg 同款）。"""
    conn = db.connect()
    try:
        backfill_user(conn, user_id)
    finally:
        conn.close()
