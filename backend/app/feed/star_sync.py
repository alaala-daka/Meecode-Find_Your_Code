"""收藏同步 GitHub 星：状态机（spec 2026-09-26）。

本地 interactions 是第一真源，GitHub 星是投影：本模块把投影推向 desired 状态。
不变量（Global Constraints + final review Critical 1 修订）：origin 溯源保持；
origin='meecode' 取消一律收敛撤星（不得按 applied='pending' 跳过）；写回前后重查
interactions 真源，撤销并发取消后的本次动作；401 清 token 返 need_auth；
收藏方向 404/422 置 attempts=MAX 停止重试。
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
             error: str = "", increment_attempts: bool = False, exhausted: bool = False) -> None:
    row = conn.execute(
        "SELECT attempts FROM star_syncs WHERE user_id = ? AND repo_id = ?", (user_id, repo_id)
    ).fetchone()
    attempts = ((row["attempts"] if row else 0) + 1) if increment_attempts else (row["attempts"] if row else 0)
    if exhausted:
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


def _flip_desired_starred(conn: sqlite3.Connection, user_id: int, repo_id: int) -> None:
    """收藏开启早期退出（无 token / 401）时翻转既有行 desired='starred'。

    用户重收藏的意图先落库，applied/origin/attempts/last_error 不动、updated_at 刷新；
    无行不建（授权补同步统一处理）。缺此翻转则重授权后 job 会按陈旧 desired='unstarred'
    撤掉用户已重新收藏的星。
    """
    if conn.execute("SELECT 1 FROM star_syncs WHERE user_id = ? AND repo_id = ?",
                    (user_id, repo_id)).fetchone():
        conn.execute("UPDATE star_syncs SET desired = 'starred', updated_at = ?"
                     " WHERE user_id = ? AND repo_id = ?", (_now(), user_id, repo_id))
        conn.commit()


def _clear_star_auth(conn: sqlite3.Connection, user_id: int) -> None:
    """清授权两列（gh_token_enc/gh_star_authed_at）：_mark_token_dead 与断开端点共用。"""
    conn.execute("UPDATE users SET gh_token_enc = '', gh_star_authed_at = 0 WHERE id = ?", (user_id,))
    conn.commit()


def _mark_token_dead(conn: sqlite3.Connection, user_id: int) -> None:
    _clear_star_auth(conn, user_id)
    conn.execute("UPDATE star_syncs SET last_error = 'token revoked'"
                 " WHERE user_id = ? AND applied = 'pending'", (user_id,))
    conn.commit()


def _load_token(conn: sqlite3.Connection, user: sqlite3.Row) -> str | None:
    """解封用户 token。AAD 绑定 user_id（A3）：跨行互换的密文解不开。

    换钥（TokenKeyMismatchError）不销毁密文直接上抛（A1）：密文凭原密钥仍可恢复，
    同步边界把异常降级 sync='pending' 保留密文，等运维恢复 TOKEN_ENC_KEY 后收敛；
    篡改（kid 相符但解不开）才按死 token 清密文——已无恢复可能。
    """
    enc = user["gh_token_enc"]
    if not enc:
        return None
    try:
        return security.open_token(enc, str(user["id"]))
    except security.TokenKeyMismatchError:
        raise
    except ValueError:
        _mark_token_dead(conn, user["id"])
        return None


def _favorite_still_wanted(conn: sqlite3.Connection, user_id: int, repo_id: int) -> bool:
    """写回前重查本地真源 interactions（final review Critical 1）。

    star_syncs 是投影，interactions 才是第一真源：用户并发取消后不得再落
    desired='starred' 行，否则 job 会把孤儿行复活成（starred, done）——星泄漏无从收敛。
    """
    return conn.execute(
        "SELECT 1 FROM interactions WHERE user_id = ? AND repo_id = ? AND kind = 'favorite'",
        (user_id, repo_id),
    ).fetchone() is not None


def _retract_star(conn: sqlite3.Connection, user: sqlite3.Row, repo: sqlite3.Row,
                  token: str | None, *, undo: bool, interactive: bool) -> str:
    """写回竞态守卫命中（用户并发取消）：撤销本次动作，不写回星意图行。

    undo=True 表示星可能由本次调用点上（PUT 已发出，含结果未知的超时）或星可溯源
    为本平台所点（origin='meecode'）→ best-effort 撤星；撤星失败留 desired='unstarred'
    行交 job 收敛，绝不删行泄漏。外部星路径 undo=False，永不动它（决策 4）。
    """
    if undo and token:
        try:
            github.unstar_repo(token, repo["full_name"], interactive=interactive)
        except Exception as exc:
            _put_row(conn, user["id"], repo["id"], desired="unstarred", applied="pending",
                     origin="meecode", error=f"撤销点星失败:{exc}", increment_attempts=True)
            return "pending"
    row = conn.execute("SELECT desired FROM star_syncs WHERE user_id = ? AND repo_id = ?",
                       (user["id"], repo["id"])).fetchone()
    if row is None or row["desired"] == "starred":
        _del_row(conn, user["id"], repo["id"])
    return "unstarred"


def sync_favorite_on(conn: sqlite3.Connection, user: sqlite3.Row, repo: sqlite3.Row, *,
                     interactive: bool = True) -> str:
    token = _load_token(conn, user)
    if token is None:
        _flip_desired_starred(conn, user["id"], repo["id"])
        return "need_auth"
    if repo["owner_login"] == user["login"]:
        _put_row(conn, user["id"], repo["id"], desired="starred", applied="done", origin="external")
        return "skipped"
    prev = conn.execute("SELECT origin FROM star_syncs WHERE user_id = ? AND repo_id = ?",
                        (user["id"], repo["id"])).fetchone()
    star_attempted = False
    try:
        already = github.is_starred(token, repo["full_name"], interactive=interactive)
        if not already:
            star_attempted = True
            github.star_repo(token, repo["full_name"], interactive=interactive)
    except github.GitHubError as exc:
        if exc.status == 401:
            _mark_token_dead(conn, user["id"])
            _flip_desired_starred(conn, user["id"], repo["id"])
            return "need_auth"
        if not _favorite_still_wanted(conn, user["id"], repo["id"]):
            return _retract_star(conn, user, repo, token, interactive=interactive,
                                 undo=star_attempted or bool(prev and prev["origin"] == "meecode"))
        _put_row(conn, user["id"], repo["id"], desired="starred", applied="pending", origin="meecode",
                 error=str(exc), increment_attempts=True, exhausted=exc.status in (404, 422))
        return "pending"
    if not _favorite_still_wanted(conn, user["id"], repo["id"]):
        return _retract_star(conn, user, repo, token, interactive=interactive,
                             undo=star_attempted or bool(prev and prev["origin"] == "meecode"))
    if already:
        # 溯源保持：星是觅码点的就仍是 meecode，防止取消收藏时漏撤
        origin = "meecode" if (prev and prev["origin"] == "meecode") else "external"
        _put_row(conn, user["id"], repo["id"], desired="starred", applied="done", origin=origin)
    else:
        _put_row(conn, user["id"], repo["id"], desired="starred", applied="done", origin="meecode")
    # 写回后复查（A6）：取消正落在上面检查与 (starred, done) 写回之间的夹缝时，
    # done 行不会再被 job 拾起（只捡 pending），必须就地撤销，孤儿行不得存活。
    if not _favorite_still_wanted(conn, user["id"], repo["id"]):
        return _retract_star(conn, user, repo, token, interactive=interactive,
                             undo=star_attempted or bool(prev and prev["origin"] == "meecode"))
    return "synced"


def sync_favorite_off(conn: sqlite3.Connection, user: sqlite3.Row, repo: sqlite3.Row, *,
                      gh_sync: bool = True, interactive: bool = True) -> str:
    """取消收藏：一律收敛撤星（spec 2026-09-28，推翻原决策 4——不护手动星）。

    gh_sync=False = 用户选择仅本地：删同步行（含挂起待撤），零 GitHub 调用。
    401 不落队列、不动既有行：同意行（决策 8）不得被 401 吞掉。
    无 token 且 gh_sync=True = 已同意：落 unstarred/pending 等授权后撤。
    """
    if not gh_sync:
        _del_row(conn, user["id"], repo["id"])
        return "kept"
    token = _load_token(conn, user)
    if token is None:
        _put_row(conn, user["id"], repo["id"], desired="unstarred", applied="pending",
                 origin="meecode", error="token missing", increment_attempts=True)
        return "need_auth"
    try:
        github.unstar_repo(token, repo["full_name"], interactive=interactive)
        _del_row(conn, user["id"], repo["id"])
        return "unstarred"
    except github.GitHubError as exc:
        if exc.status == 401:
            _mark_token_dead(conn, user["id"])
            return "need_auth"
        if exc.status in (404, 422):
            _del_row(conn, user["id"], repo["id"])  # 星本就不存在 = 目标态达成
            return "unstarred"
        _put_row(conn, user["id"], repo["id"], desired="unstarred", applied="pending",
                 origin="meecode", error=str(exc), increment_attempts=True)
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
