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

from . import config, traffic
from .feed import auth

API_PREFIX = "/api"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# (方法或 None=不限, 路径前缀, 桶名)；按序首个命中，未命中落 default。
# admin 必须排最前：管理台批量操作独立宽松桶（F5），否则落 default 与其他路径抢配额。
# llm 六条必须排在 delist 之前：POST /api/repos/root 同时匹配 /api/repos/ 前缀。
_RATE_RULES: tuple[tuple[str | None, str, str], ...] = (
    (None, "/api/admin/", "admin"),
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
    ("DELETE", "/api/me/gh-star-auth", "interact"),
    ("POST", "/api/comments", "ugc"),
    ("DELETE", "/api/comments", "ugc"),
    ("GET", "/api/comments", "browse"),
    ("POST", "/api/repos/", "delist"),
    ("GET", "/api/feed", "browse"),
    ("GET", "/api/search", "browse"),
    ("GET", "/api/repos/", "browse"),
    (None, "/api/auth/", "auth"),
    ("POST", "/api/hit", "hit"),   # 页面访问 beacon：独立桶防灌水（60/min）
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


HIT_PATH = "/api/hit"


def session_user_id(request: Request) -> int | None:
    token = request.cookies.get(config.SESSION_COOKIE, "")
    verified = auth.verify(token) if token else None
    return verified[0] if verified else None


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

POLICY_TTL_SECONDS = 30.0
PROTECTED_BUCKETS = frozenset({"default", "admin"})  # 不可停用（防自锁），Task 9 复用


class PolicyCache:
    """api_policies → 限流参数缓存：30s 惰性刷新 + 保存即失效（spec §2.4）。

    安全复审修订（2026-10-09）：
    - 缺桶/未刷新回落 config.RATE_LIMITS（冷启动与测试不依赖库），fail-open 仅限限流阈值；
    - 保护桶 enabled 恒钳为 True（set/refresh_from 双侧，防直调与库被误改后自锁）；
    - _gen 代数守卫：并发 refresh 不回滚刚保存的值（保存后 _gen 自增，过期快照丢弃）；
    - schedule_refresh 在守护线程刷新，不阻塞事件循环。
    """

    def __init__(self) -> None:
        self._data: dict[str, tuple[bool, int]] = {}
        self._loaded_at = 0.0
        self._gen = 0
        self._lock = threading.Lock()

    def get(self, bucket: str) -> tuple[bool, int]:
        with self._lock:
            hit = self._data.get(bucket)
        if hit is not None:
            return hit
        return True, config.RATE_LIMITS.get(bucket, config.RATE_LIMITS["default"])

    def set(self, bucket: str, enabled: bool, limit: int) -> None:
        if bucket in PROTECTED_BUCKETS:
            enabled = True  # 纵深防御：保护桶永不停用
        with self._lock:
            self._data[bucket] = (enabled, limit)
            self._gen += 1

    def refresh_from(self, conn) -> None:
        with self._lock:
            gen0 = self._gen
        rows = conn.execute(
            "SELECT route_key, enabled, limit_per_min FROM api_policies").fetchall()
        data = {}
        for r in rows:
            enabled = bool(r["enabled"])
            if r["route_key"] in PROTECTED_BUCKETS:
                enabled = True
            data[r["route_key"]] = (enabled, int(r["limit_per_min"]))
        with self._lock:
            if gen0 != self._gen:
                return  # 刷新期间有保存发生：丢弃过期快照，防回滚
            self._data = data
            self._loaded_at = time.time()

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = 0.0
            self._gen += 1

    def maybe_refresh(self, factory) -> None:
        if factory is None:
            return
        with self._lock:
            stale = time.time() - self._loaded_at >= POLICY_TTL_SECONDS
        if not stale:
            return
        try:
            conn = factory()
        except Exception:
            logging.getLogger(__name__).exception("api_policies 刷新开连接失败，沿用旧缓存")
            return
        try:
            self.refresh_from(conn)
        except Exception:
            logging.getLogger(__name__).exception("api_policies 刷新失败，沿用旧缓存")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def schedule_refresh(self, factory) -> None:
        """stale 时在守护线程刷新（dispatch 在事件循环线程，同步 I/O 会停摆全服务）。"""
        if factory is None:
            return
        with self._lock:
            stale = time.time() - self._loaded_at >= POLICY_TTL_SECONDS
        if stale:
            threading.Thread(target=self.maybe_refresh, args=(factory,), daemon=True).start()

    def reset(self) -> None:
        with self._lock:
            self._data = {}
            self._loaded_at = 0.0
            self._gen += 1


policies = PolicyCache()
_policy_factory = None


def bind_policy_source(factory) -> None:
    global _policy_factory
    _policy_factory = factory


class SecurityMiddleware(BaseHTTPMiddleware):
    """先 Origin 校验（403），再限流（429）；仅拦 /api 前缀路径。

    二期（spec §2.4）：每请求缓冲写 access_events（含 4xx/5xx）；
    HIT beacon 端点自身不入 api_calls（HIT 行由端点写入）。
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith(API_PREFIX):
            return await call_next(request)
        try:
            policies.schedule_refresh(_policy_factory)
            response = await self._respond(request, call_next)
        except Exception:
            # 真 5xx（无响应对象）也落一行补全「含 4xx/5xx」口径；不吞异常，照常上抛
            if not (path == HIT_PATH and request.method == "POST"):
                try:
                    traffic.writer.record(
                        ts=int(time.time()), user_id=session_user_id(request),
                        ip=client_ip(request), path=path,
                        method=request.method, status_code=500)
                except Exception:  # pragma: no cover - record 内已吞，双保险
                    pass
            raise
        # 429 不落明细（限流器自知被拒量；落行会放大洪水面）。埋点吞异常（纵深）。
        if not (path == HIT_PATH and request.method == "POST") and response.status_code != 429:
            try:
                traffic.writer.record(
                    ts=int(time.time()), user_id=session_user_id(request),
                    ip=client_ip(request), path=path,
                    method=request.method, status_code=response.status_code)
            except Exception:  # pragma: no cover - record 内已吞，双保险
                pass
        return response

    async def _respond(self, request: Request, call_next):
        path = request.url.path
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and origin not in config.ALLOWED_ORIGINS:
                return JSONResponse({"detail": "非法来源请求"}, status_code=403)

        bucket = bucket_for(request.method, path)
        enabled, limit = policies.get(bucket)
        if not enabled:
            return JSONResponse(
                {"detail": "接口已停用", "code": "disabled"}, status_code=403)

        if config.RATE_LIMIT_ENABLED:
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
