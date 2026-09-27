"""收藏同步 GitHub 星重试 job：补做 star_syncs 中 applied='pending' 的操作（spec 2026-09-26 §4.4）。
形态对照 jobs/moderate：批量拾取、单行失败跳过、cron 进 main()。
无 token 的行跳过不烧 attempts（等重新授权后收敛）。cron 间隔即重试间隔。
手动触发：python -m app.feed.jobs.star_sync
"""
from __future__ import annotations

import logging
import sqlite3

from ... import config
from .. import db, star_sync

log = logging.getLogger(__name__)


def sync_pending_once(conn: sqlite3.Connection) -> dict:
    stats = {"picked": 0, "done": 0, "failed": 0, "skipped": 0}
    rows = conn.execute(
        "SELECT s.*, u.gh_token_enc FROM star_syncs s JOIN users u ON u.id = s.user_id"
        " WHERE s.applied = 'pending' AND s.attempts < ?",
        (config.STAR_SYNC_MAX_ATTEMPTS,),
    ).fetchall()
    for row in rows:
        if not row["gh_token_enc"]:
            stats["skipped"] += 1
            continue
        user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        repo = conn.execute("SELECT * FROM repos WHERE id = ?", (row["repo_id"],)).fetchone()
        if user is None or repo is None:
            conn.execute("DELETE FROM star_syncs WHERE user_id = ? AND repo_id = ?",
                         (row["user_id"], row["repo_id"]))
            conn.commit()
            continue
        stats["picked"] += 1
        try:
            state = (star_sync.sync_favorite_on(conn, user, repo, interactive=False)
                     if row["desired"] == "starred"
                     else star_sync.sync_favorite_off(conn, user, repo, interactive=False))
        except Exception as exc:  # 单行失败不中断整批（crawl.py 同款）
            log.warning("[star-sync] user=%s repo=%s 重试异常:%s", row["user_id"], row["repo_id"], exc)
            stats["failed"] += 1
            continue
        if state in ("synced", "unstarred", "kept", "skipped"):
            stats["done"] += 1
        else:
            stats["failed"] += 1
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    conn = db.connect()
    db.init_db(conn)
    try:
        stats = sync_pending_once(conn)
        log.info("点星同步重试完成:%s", stats)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
