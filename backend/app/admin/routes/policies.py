"""API 管控（spec §3）：桶级开关/限额；default/admin 桶禁改 enabled（防自锁）。"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ... import security
from ...feed import deps
from .. import audit
from ..deps import require_admin

router = APIRouter()

PROTECTED_BUCKETS = security.PROTECTED_BUCKETS  # 不可停用（防自锁），PolicyCache 同源钳制


class PolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    limit_per_min: int | None = Field(default=None, ge=1, le=100_000)


@router.get("/api-policies")
def list_policies(conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)]) -> dict:
    rows = conn.execute(
        "SELECT route_key, enabled, limit_per_min FROM api_policies ORDER BY route_key"
    ).fetchall()
    data = [{"route_key": r["route_key"], "enabled": bool(r["enabled"]),
             "limit_per_min": r["limit_per_min"]} for r in rows]
    return {"data": data, "total": len(data)}


@router.patch("/api-policies/{key}")
def update_policy(
    key: str,
    body: PolicyPatch,
    conn: Annotated[sqlite3.Connection, Depends(deps.get_conn)],
    admin=Depends(require_admin),
) -> dict:
    row = conn.execute("SELECT * FROM api_policies WHERE route_key=?", (key,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="未知桶")
    if key in PROTECTED_BUCKETS:
        if body.enabled is not None:
            raise HTTPException(status_code=400, detail="default/admin 桶不可停用")
        if body.limit_per_min is not None and body.limit_per_min < 60:
            raise HTTPException(status_code=400, detail="default/admin 桶限额下限 60")
    enabled = row["enabled"] if body.enabled is None else int(body.enabled)
    if key in PROTECTED_BUCKETS:
        enabled = 1  # 与 PolicyCache 同源钳制：保护桶恒启用，脏行不回显 false
    limit = row["limit_per_min"] if body.limit_per_min is None else body.limit_per_min
    conn.execute(
        "UPDATE api_policies SET enabled=?, limit_per_min=? WHERE route_key=?",
        (enabled, limit, key))
    conn.commit()
    audit.record_audit(conn, admin_login=admin["login"], action="api_policy.update",
                       target_type="api_policy", target_id=key,
                       detail={"enabled": bool(enabled), "limit_per_min": limit})
    security.policies.invalidate()  # 保存即失效：先失效再 set，消 refresh 回滚竞态
    security.policies.set(key, bool(enabled), limit)
    return {"route_key": key, "enabled": bool(enabled), "limit_per_min": limit}
