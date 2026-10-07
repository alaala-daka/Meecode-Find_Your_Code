# backend/app/admin/audit.py
"""管理操作审计（spec §5.4）：写失败吞异常仅记日志，绝不阻塞主操作。"""
from __future__ import annotations

import json
import logging
import sqlite3
import time

log = logging.getLogger(__name__)

AUDIT_ACTIONS = frozenset({
    "user.ban", "user.unban", "user.note",
    "repo.publish", "repo.delist", "repo.restore", "repo.edit",
    "comment.hide", "comment.restore", "comment.delete", "comment.bulk_hide",
})


def record_audit(conn: sqlite3.Connection, *, admin_login: str, action: str,
                 target_type: str, target_id: int | str | None,
                 detail: dict | None = None) -> None:
    if action not in AUDIT_ACTIONS:
        log.warning("未知审计动作 %s（前向兼容照写）", action)
    try:
        conn.execute(
            "INSERT INTO audit_logs (ts, admin_login, action, target_type, target_id, detail)"
            " VALUES (?,?,?,?,?,?)",
            (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), admin_login, action,
             target_type, None if target_id is None else str(target_id),
             None if detail is None else json.dumps(detail, ensure_ascii=False)),
        )
        conn.commit()
    except Exception:
        log.exception("audit_logs 写失败（action=%s target=%s:%s）", action, target_type, target_id)
