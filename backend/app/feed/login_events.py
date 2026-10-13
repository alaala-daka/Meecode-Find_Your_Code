"""登录事件采集（spec 2026-10-10 三期 §2.2）：写失败吞异常，绝不阻塞登录。"""
from __future__ import annotations

import logging
import sqlite3
import time

from fastapi import Request

from .. import security, traffic

log = logging.getLogger(__name__)


def record(conn: sqlite3.Connection, request: Request, *, user_id: int | None,
           login: str, event: str, ok: int) -> None:
    try:
        try:
            ip_hash = traffic.login_ip_hash(security.client_ip(request))
        except ValueError:
            ip_hash = ""
        conn.execute(
            "INSERT INTO login_events (ts, user_id, login, ip_hash, event, ok)"
            " VALUES (?,?,?,?,?,?)",
            (int(time.time()), user_id, login, ip_hash, event, ok),
        )
        conn.commit()
    except Exception:
        log.exception("login_events 写失败（event=%s ok=%s）", event, ok)
