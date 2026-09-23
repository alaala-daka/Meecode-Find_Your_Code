"""安全中间件：内存滑动窗口限流 + Origin 白名单 CSRF 校验。

零第三方依赖：计数器为进程内 dict，单 worker 部署（systemd 单元）语义完备。
限流键登录用户优先（HMAC cookie 验签，不查库），匿名回退 XFF 末段 IP
（nginx $proxy_add_x_forwarded_for 由受信代理追加，前置段可伪造，弃用）。
设计依据：docs/superpowers/specs/2026-09-21-觅码-安全基线-design.md。
"""
from __future__ import annotations

import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import config
from .feed import auth

API_PREFIX = "/api"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# (方法或 None=不限, 路径前缀, 桶名)；按序首个命中，未命中落 default。
# llm 六条必须排在 delist 之前：POST /api/repos/root 同时匹配 /api/repos/ 前缀。
_RATE_RULES: tuple[tuple[str | None, str, str], ...] = (
    ("POST", "/api/ai-draft", "llm"),
    ("POST", "/api/repos/root", "llm"),
    ("POST", "/api/roots", "llm"),
    ("POST", "/api/expand", "llm"),
    ("POST", "/api/nodes/detail", "llm"),
    ("POST", "/api/reader/chat", "llm"),
    ("POST", "/api/sessions", "session"),
    ("POST", "/api/submit", "submit"),
    ("GET", "/api/my/github-repos", "submit"),
    ("POST", "/api/interactions", "interact"),
    ("POST", "/api/repos/", "delist"),
    ("GET", "/api/feed", "browse"),
    ("GET", "/api/search", "browse"),
    ("GET", "/api/repos/", "browse"),
    (None, "/api/auth/", "auth"),
)


def bucket_for(method: str, path: str) -> str:
    for rule_method, prefix, bucket in _RATE_RULES:
        if path.startswith(prefix) and (rule_method is None or rule_method == method):
            return bucket
    return "default"


def client_ip(request: Request) -> str:
    """取 XFF 末段（nginx 受信追加），无 XFF 回退 socket 对端。"""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else ""


def rate_key(request: Request) -> str:
    """登录用户按 user_id（验签纯计算不查库），匿名按 IP。"""
    token = request.cookies.get(config.SESSION_COOKIE, "")
    verified = auth.verify(token) if token else None
    return f"u:{verified[0]}" if verified else f"ip:{client_ip(request)}"


class SlidingWindowLimiter:
    """进程内滑动窗口计数。多 worker 部署时各进程独立计数（见 spec 风险表）。

    键满额时拒新键（先清过期键再拒），不淘汰既有键——淘汰会把受害者配额一并清零。
    同步路由跑在线程池：allow/_sweep/reset 全部在同一把锁内，防 read-modify-write 丢计数。
    """

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float, now: float,
              max_keys: int = 10_000) -> tuple[bool, int]:
        """第 2 个返回值为超限时的 Retry-After 秒数（≥1）。"""
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= max_keys:
                    self._sweep_expired(now, window)
                    if len(self._hits) >= max_keys:
                        return False, 1   # 满额拒新键：不淘汰既有键，防洪水重置配额
                hits = []
            hits = [t for t in hits if t > now - window]     # 剪枝过期命中即清理
            if len(hits) >= limit:
                self._hits[key] = hits
                return False, max(1, int(hits[0] + window - now))
            hits.append(now)
            self._hits[key] = hits
            return True, 0

    def _sweep_expired(self, now: float, window: float) -> None:
        """清理窗口内无命中的键（hits 末位即最新时间戳）。仅满额路径触发；调用方持锁。"""
        cutoff = now - window
        for k in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_limiter = SlidingWindowLimiter()


class SecurityMiddleware(BaseHTTPMiddleware):
    """先 Origin 校验（403），再限流（429）；仅拦 /api 前缀路径。"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith(API_PREFIX):
            return await call_next(request)

        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and origin not in config.ALLOWED_ORIGINS:
                return JSONResponse({"detail": "非法来源请求"}, status_code=403)

        if config.RATE_LIMIT_ENABLED:
            bucket = bucket_for(request.method, path)
            limit = config.RATE_LIMITS.get(bucket, config.RATE_LIMITS["default"])
            allowed, retry_after = _limiter.allow(
                f"{bucket}:{rate_key(request)}", limit, config.RATE_LIMIT_WINDOW,
                time.time(), config.RATE_LIMIT_MAX_KEYS,
            )
            if not allowed:
                return JSONResponse(
                    {"detail": "请求过于频繁，请稍后再试"},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )
        return await call_next(request)
