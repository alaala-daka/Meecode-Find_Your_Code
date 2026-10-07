"""管理台鉴权：ADMIN_LOGINS 白名单（spec 2026-10-05 §2，无角色体系）。"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from .. import config
from ..feed import auth, deps


def require_admin(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)],
) -> sqlite3.Row:
    user = auth.require_user(request, conn)  # 匿名 401
    if user["login"].lower() not in config.ADMIN_LOGINS:
        raise HTTPException(status_code=403, detail="无管理权限")
    return user
