"""页面访问 beacon（spec 2026-10-09 §2.3）：匿名可发，落 HIT 行，204 无体。

安全复审修订（2026-10-09）：
- 手动解析 body：sendBeacon 字符串 body 是 text/plain，Pydantic 默认只收 JSON
  （实测 422），故对任意 content-type 容忍，解析失败静默 204 不落行；
- path 服务端规范化：剥 ?/# 后段与控制字符、强制 / 开头、截断 200（防敏感片段落库）。
"""
from __future__ import annotations

import json
import re
import time

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from ... import security, traffic

router = APIRouter()

MAX_PATH_LEN = 200
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


class HitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=4000)


def normalize_path(raw: str) -> str:
    path = _CTRL_RE.sub("", raw).split("#", 1)[0].split("?", 1)[0].strip()
    if not path.startswith("/"):
        path = "/" + path
    return path[:MAX_PATH_LEN] or "/"


@router.post("/hit", status_code=204)
async def hit(request: Request) -> Response:
    try:
        payload = json.loads(await request.body() or b"{}")
        body = HitBody.model_validate(payload)
    except Exception:
        return Response(status_code=204)  # 无效体不落行，beacon 永不报错
    try:
        traffic.writer.record(
            ts=int(time.time()),
            user_id=security.session_user_id(request),
            ip=security.client_ip(request),
            path=normalize_path(body.path),
            method="HIT",
            status_code=200,
        )
    except Exception:
        pass  # 埋点绝不把 204 打成 500
    return Response(status_code=204)
