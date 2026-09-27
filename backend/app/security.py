"""安全中间件：内存滑动窗口限流 + Origin 白名单 CSRF 校验。

限流/校验面零第三方依赖（token 密封面用 cryptography，见文件末尾）：
计数器为进程内 dict，单 worker 部署（systemd 单元）语义完备。
限流键登录用户优先（HMAC cookie 验签，不查库），匿名取客户端 IP——仅受信对端
的 XFF 末段采信，非受信来源一律取 socket 对端（防伪造 XFF 换限流键）。
设计依据：docs/superpowers/specs/2026-09-21-觅码-安全基线-design.md。
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import threading
import time

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
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
    ("POST", "/api/comments", "ugc"),
    ("DELETE", "/api/comments", "ugc"),
    ("GET", "/api/comments", "browse"),
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
    """受信对端(nginx 回环)的 XFF 末段才采信;否则忽略 XFF 取 socket 对端。

    nginx $proxy_add_x_forwarded_for 由受信代理追加真实客户端到末段，
    前置段可伪造故弃用；非受信来源整头可伪造，一律不看。
    """
    peer = request.client.host if request.client else ""
    if peer not in config.TRUSTED_PROXIES:
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip() or peer
    return peer


def rate_key(request: Request) -> str:
    """登录用户按 (user_id, session_epoch)（验签纯计算不查库），匿名按 IP。

    吊销靠 current_user 的 epoch 比对；限流键含 epoch 以隔离吊销前的旧 token
    （其签名在 SESSION_MAX_AGE 内仍有效），防止旧 token 烧掉受害者的共享配额。
    """
    token = request.cookies.get(config.SESSION_COOKIE, "")
    verified = auth.verify(token) if token else None
    if verified is None:
        return f"ip:{client_ip(request)}"
    user_id, epoch = verified
    return f"u:{user_id}:{epoch}"


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


# ---------- GitHub token 密封（spec 2026-09-26 决策 1：红线修订的补偿面） ----------
_TOKEN_SALT = b"meecode-gh-token-v1"


class TokenKeyMismatchError(ValueError):
    """密文的密钥指纹（kid）与当前 TOKEN_ENC_KEY 不匹配：换钥/配错钥。

    与篡改 ValueError 区分：密文仍可凭原密钥恢复，调用方不得销毁密文/清列，
    应保留并提示运维恢复密钥（A1）。继承 ValueError 兼容既有 except ValueError。
    """


def _key_id(key: bytes) -> str:
    """密钥指纹 kid：sha256(key)[:8] 的 base64url（去 padding），随密文存储供换钥识别。"""
    return base64.urlsafe_b64encode(hashlib.sha256(key).digest()[:8]).decode("ascii").rstrip("=")


def _token_key() -> bytes:
    """AES-GCM 密钥：TOKEN_ENC_KEY（base64 32 字节）优先；空则从 SESSION_SECRET 派生（仅 dev）。
    密钥配置错误（长度/base64 非法）独立上抛 RuntimeError，不混入解封 ValueError。
    base64 严格解码（validate=True）：夹带非法字符一律拒收（宽松解码会静默丢弃，
    凭「凑出来 32 字节」蒙混过关）；仅容缺 padding（openssl rand -base64 32 去尾等号仍可跑）。"""
    raw = config.TOKEN_ENC_KEY
    if raw:
        try:
            key = base64.b64decode(raw + "=" * (-len(raw) % 4), validate=True)
        except ValueError as exc:
            raise RuntimeError("TOKEN_ENC_KEY 必须是 base64 编码的 32 字节") from exc
        if len(key) != 32:
            raise RuntimeError("TOKEN_ENC_KEY 必须是 base64 编码的 32 字节")
        return key
    return hashlib.pbkdf2_hmac("sha256", config.SESSION_SECRET.encode(), _TOKEN_SALT, 200_000, dklen=32)


def ensure_token_key() -> None:
    """启动校验 TOKEN_ENC_KEY（spec §4.2，final review Important 3）。

    配错 fail-fast 拒启：否则到首个 seal_token/open_token 才以 RuntimeError 爆炸，
    set_interaction 本地已 commit 后 500（违反决策 5「本地永远成功返回」）。
    生产（GITHUB_MOCK=false）缺配同样拒启（对齐 ensure_prod_secrets）：派生密钥随
    SESSION_SECRET/机器漂移，会让已存 token 无法解封且无法撤销 GitHub 授权。
    未配置仅 dev（GITHUB_MOCK）从 SESSION_SECRET 派生，启动打警告提醒补配。
    """
    if config.TOKEN_ENC_KEY:
        _token_key()  # 配错（非法 base64 / 非 32 字节）即 RuntimeError 拒启
        return
    if not config.GITHUB_MOCK:
        raise RuntimeError(
            "GITHUB_MOCK=false 时必须配置 TOKEN_ENC_KEY（生产加密密钥，"
            "openssl rand -base64 32 生成；缺失时 dev 派生密钥不稳，"
            "换机会导致已存 GitHub token 无法解封也无法撤销）")
    logging.getLogger(__name__).warning(
        "TOKEN_ENC_KEY 未配置：dev 派生密钥，生产请配置 TOKEN_ENC_KEY")


def seal_token(plaintext: str, aad: str) -> str:
    """密封 token，输出 v1.<kid>.<base64url(nonce+ct)>。

    kid = 当前密钥指纹，open_token 据此把换钥（TokenKeyMismatchError，密文可恢复）
    与篡改（ValueError）分开（A1）；AAD 绑定 user_id，跨行互换密文解不开（A3）。"""
    key = _token_key()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
    payload = base64.urlsafe_b64encode(nonce + ct).decode("ascii")
    return f"v1.{_key_id(key)}.{payload}"


def open_token(blob: str, aad: str) -> str:
    """解封 token。换钥（kid 不符）上抛 TokenKeyMismatchError；篡改/坏格式/AAD 不符
    一律 ValueError，绝不部分返回；密钥配置错误独立上抛。"""
    key = _token_key()
    parts = blob.split(".")
    if len(parts) != 3 or parts[0] != "v1" or not parts[1] or not parts[2]:
        raise ValueError("token 解封失败")
    if parts[1] != _key_id(key):
        raise TokenKeyMismatchError("TOKEN_ENC_KEY 与密封时所用密钥不匹配")
    try:
        raw = base64.b64decode(parts[2], altchars=b"-_", validate=True)
        if len(raw) < 13:
            raise ValueError("密文过短")
        return AESGCM(key).decrypt(raw[:12], raw[12:], aad.encode("utf-8")).decode("utf-8")
    except (ValueError, InvalidTag) as exc:
        raise ValueError("token 解封失败") from exc
