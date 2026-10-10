"""系统配置（spec §3）：读脱敏，写拒密钥字段 + version 乐观锁。"""
from __future__ import annotations

import sqlite3
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ...feed import deps
from .. import audit
from ..deps import require_admin

router = APIRouter()

# 安全复审修订（2026-10-09）：默认脱敏、白名单放行。
# 后缀启发式（*_KEY/_SECRET/_TOKEN）拦不住 DB_PASSWORD/GH_PAT 等非标准命名，
# 而 app_config 是运维直接插库的开放表——改为仅白名单键展示/可改，其余一律 ***。
PUBLIC_VALUE_KEYS = frozenset({"online_window_minutes"})


def mask_value(key: str, value: str) -> str:
    return value if key in PUBLIC_VALUE_KEYS else "***"


class ConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(max_length=2000)
    version: int = Field(ge=1)


def _row_out(row: sqlite3.Row) -> dict:
    return {"key": row["key"], "value": mask_value(row["key"], row["value"]),
            "version": row["version"], "updated_at": row["updated_at"],
            "updated_by": row["updated_by"]}


@router.get("/config")
def list_config(conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    rows = conn.execute(
        "SELECT key, value, version, updated_at, updated_by FROM app_config ORDER BY key"
    ).fetchall()
    data = [_row_out(r) for r in rows]
    return {"data": data, "total": len(data)}


@router.patch("/config")
def update_config(
    body: ConfigPatch,
    conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)],
    admin=Depends(require_admin),
) -> dict:
    # 未知键 404 先于白名单 400（测试语义：nope → 404，存在但非白名单 → 400）
    if conn.execute("SELECT 1 FROM app_config WHERE key=?", (body.key,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="未知配置键")
    if body.key not in PUBLIC_VALUE_KEYS:
        raise HTTPException(status_code=400, detail="该键不可经界面修改")
    cur = conn.execute(
        "UPDATE app_config SET value=?, version=version+1, updated_at=?, updated_by=?"
        " WHERE key=? AND version=?",
        (body.value, int(time.time()), admin["login"], body.key, body.version))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=409, detail="配置已被他人修改，请刷新重试")
    audit.record_audit(conn, admin_login=admin["login"], action="config.update",
                       target_type="config", target_id=body.key,
                       detail={"value": body.value[:200]})  # 白名单键非密钥，记值供问责
    row = conn.execute("SELECT * FROM app_config WHERE key=?", (body.key,)).fetchone()
    return _row_out(row)
