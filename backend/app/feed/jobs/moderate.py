"""评论 LLM 预审重试 job：补判 screened=0 的 pending 评论（LLM 故障遗留，spec 决策 2）。

形态对齐 crawl.rescreen_pending：批量拾取、异常 log 后留待下轮、cron 调 main()。
"""
from __future__ import annotations

import logging
import sqlite3
import time

from ... import config
from .. import db
from ..moderation import moderate_comment

log = logging.getLogger(__name__)


def moderate_pending(
    conn: sqlite3.Connection, *, now: int | None = None, limit: int | None = None
) -> int:
    """补判 status='pending' AND screened=0 且过宽限期的评论。返回成功判定条数。"""
    limit = limit if limit is not None else config.MODERATE_BATCH
    cutoff = int(now or time.time()) - config.MODERATE_GRACE_SECONDS
    rows = conn.execute(
        "SELECT id FROM comments WHERE status = 'pending' AND screened = 0 AND created_at <= ?"
        " LIMIT ?", (cutoff, limit),
    ).fetchall()
    done = 0
    for row in rows:
        try:
            moderate_comment(conn, row["id"])
        except Exception as exc:
            log.warning("[moderate] 评论 %s 判定失败,下轮重试:%s", row["id"], exc)
            continue
        done += 1
    conn.commit()
    return done


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    conn = db.connect()
    db.init_db(conn)
    try:
        n = moderate_pending(conn)
        log.info("评论预审补判完成:%s 条", n)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
