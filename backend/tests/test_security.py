"""安全中间件：限流分桶、Origin 校验、IP/键提取、CORS 层序回归。

conftest 已 autouse 关闭限流；本文件 autouse 开回（模块级 autouse 后于 conftest
执行，已实验验证），并用 monkeypatch 把阈值压到 1~2 做超限断言，避免真发几百个请求。
"""
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import config, security
from app.feed import auth, deps
from app.main import app

NOW = 1_700_000_000


@pytest.fixture(autouse=True)
def _rate_limit_on(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)
    security._limiter.reset()
    yield
    security._limiter.reset()


@pytest.fixture()
def client(conn, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_MOCK", True)
    app.dependency_overrides[deps.get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def _request(headers=None, cookies=None, client_host="9.9.9.9"):
    """构造最小 HTTP 请求（不走网络），供 client_ip / rate_key 单测。"""
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookies:
        raw.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    scope = {"type": "http", "method": "GET", "path": "/api/me",
             "headers": raw, "client": (client_host, 12345)}
    return Request(scope)


# ---------- 纯函数 ----------

def test_client_ip_takes_last_xff_segment_from_trusted_proxy():
    # 受信代理(nginx 同机)追加的末段才可信
    req = _request(headers={"x-forwarded-for": "1.1.1.1, 2.2.2.2"}, client_host="127.0.0.1")
    assert security.client_ip(req) == "2.2.2.2"


def test_client_ip_falls_back_to_socket_peer():
    assert security.client_ip(_request()) == "9.9.9.9"


def test_client_ip_ignores_xff_from_untrusted_peer():
    # 直连伪造 XFF 换限流键——必须无视,取对端
    req = _request(headers={"x-forwarded-for": "6.6.6.6"}, client_host="9.9.9.9")
    assert security.client_ip(req) == "9.9.9.9"


def test_rate_key_ignores_forged_xff_from_untrusted_peer():
    req = _request(headers={"x-forwarded-for": "6.6.6.6"}, client_host="9.9.9.9")
    assert security.rate_key(req) == "ip:9.9.9.9"


def test_rate_key_prefers_logged_in_user(conn):
    uid = auth.upsert_user(conn, {"id": 42, "login": "k", "avatar_url": ""})
    req = _request(cookies={config.SESSION_COOKIE: auth.sign(uid)})
    assert security.rate_key(req) == f"u:{uid}:0"


def test_rate_key_isolates_revoked_token_from_fresh_token(conn):
    """吊销后旧 token 签名未过期，限流键须带旧 epoch 落独立桶，不得烧受害者新配额。"""
    uid = auth.upsert_user(conn, {"id": 43, "login": "rev", "avatar_url": ""})
    old_token = auth.issue_token(conn, uid)      # epoch 0
    auth.revoke_all(conn, uid)                   # epoch -> 1
    new_token = auth.issue_token(conn, uid)      # epoch 1
    old_key = security.rate_key(_request(cookies={config.SESSION_COOKIE: old_token}))
    new_key = security.rate_key(_request(cookies={config.SESSION_COOKIE: new_token}))
    assert old_key == f"u:{uid}:0"
    assert new_key == f"u:{uid}:1"
    assert old_key != new_key                    # 配额隔离


def test_rate_key_bad_signature_is_anonymous():
    req = _request(cookies={config.SESSION_COOKIE: "forged.token"})
    assert security.rate_key(req).startswith("ip:")


def test_bucket_for_routes():
    assert security.bucket_for("POST", "/api/ai-draft") == "llm"
    assert security.bucket_for("POST", "/api/repos/root") == "llm"      # 先于 delist 命中
    assert security.bucket_for("POST", "/api/expand") == "llm"
    assert security.bucket_for("POST", "/api/nodes/detail") == "llm"
    assert security.bucket_for("POST", "/api/reader/chat") == "llm"
    assert security.bucket_for("POST", "/api/roots") == "llm"
    assert security.bucket_for("POST", "/api/sessions") == "session"
    assert security.bucket_for("POST", "/api/submit") == "submit"
    assert security.bucket_for("GET", "/api/my/github-repos") == "submit"
    assert security.bucket_for("POST", "/api/interactions") == "interact"
    assert security.bucket_for("POST", "/api/repos/7/delist") == "delist"
    assert security.bucket_for("GET", "/api/feed") == "browse"
    assert security.bucket_for("GET", "/api/repos/7") == "browse"
    assert security.bucket_for("GET", "/api/auth/callback") == "auth"
    assert security.bucket_for("GET", "/api/me") == "default"


# ---------- 限流器 ----------

def test_limiter_allows_until_limit_then_rejects():
    limiter = security.SlidingWindowLimiter()
    for i in range(3):
        assert limiter.allow("k", 3, 60, NOW + i)[0]
    allowed, retry = limiter.allow("k", 3, 60, NOW + 4)
    assert not allowed and retry >= 1


def test_limiter_window_slide_recovers():
    limiter = security.SlidingWindowLimiter()
    limiter.allow("k", 2, 60, NOW)
    limiter.allow("k", 2, 60, NOW + 1)
    assert not limiter.allow("k", 2, 60, NOW + 1)[0]
    assert limiter.allow("k", 2, 60, NOW + 61)[0]       # 窗口滑过即恢复


def test_limiter_rejects_new_key_at_capacity():
    limiter = security.SlidingWindowLimiter()
    for i in range(3):
        assert limiter.allow(f"k{i}", 5, 60, NOW)[0]
    allowed, retry = limiter.allow("new", 5, 60, NOW, max_keys=3)
    assert not allowed and retry >= 1                       # 满额拒新键，不淘汰
    assert "new" not in limiter._hits and "k0" in limiter._hits


def test_limiter_existing_key_allowed_at_capacity():
    limiter = security.SlidingWindowLimiter()
    for i in range(3):
        limiter.allow(f"k{i}", 5, 60, NOW, max_keys=3)
    assert limiter.allow("k0", 5, 60, NOW + 1, max_keys=3)[0]   # 洪水不重置既有配额


def test_limiter_sweeps_expired_keys_before_rejecting():
    limiter = security.SlidingWindowLimiter()
    for i in range(3):
        limiter.allow(f"stale{i}", 5, 60, NOW, max_keys=3)
    allowed, _ = limiter.allow("new", 5, 60, NOW + 120, max_keys=3)  # 全过期后清槽
    assert allowed and "new" in limiter._hits
    assert len(limiter._hits) == 1


def test_limiter_concurrent_allow_never_exceeds_limit():
    """同步路由跑线程池:read-modify-write 无锁会丢计数、超放。"""
    from concurrent.futures import ThreadPoolExecutor

    limiter = security.SlidingWindowLimiter()
    limit = 100

    def one(_):
        return limiter.allow("k", limit, 60, NOW)[0]

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(one, range(500)))
    assert sum(results) == limit          # 恰好 limit 个放行，不多不少


def test_limiter_concurrent_distinct_keys_respect_max_keys():
    from concurrent.futures import ThreadPoolExecutor

    limiter = security.SlidingWindowLimiter()
    max_keys = 50

    def one(i):
        return limiter.allow(f"k{i}", 5, 60, NOW, max_keys=max_keys)[0]

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(one, range(200)))
    assert sum(results) == max_keys       # 满额拒新键，并发下不超卖


# ---------- 中间件（经 TestClient 走真实栈） ----------

def test_llm_endpoint_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMITS", {**config.RATE_LIMITS, "session": 2})
    assert client.post("/api/sessions").status_code == 200
    assert client.post("/api/sessions").status_code == 200
    resp = client.post("/api/sessions")
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1
    assert "detail" in resp.json()


def test_429_still_carries_cors_header(client, monkeypatch):
    # 层序回归：security 内层、CORS 外层，429 出栈时补 CORS 头
    monkeypatch.setattr(config, "RATE_LIMITS", {**config.RATE_LIMITS, "default": 1})
    origin = {"Origin": "http://localhost:5173"}
    client.get("/api/me", headers=origin)
    resp = client.get("/api/me", headers=origin)
    assert resp.status_code == 429
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_origin_not_in_whitelist_rejected(client):
    resp = client.put("/api/me/bio", json={"bio": "x"},
                      headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403


def test_missing_origin_passes_middleware(client):
    # 无 Origin（curl/TestClient）：放行至路由层，由路由自己的 401 回答
    assert client.put("/api/me/bio", json={"bio": "x"}).status_code == 401


def test_allowed_origin_passes_middleware(client):
    resp = client.put("/api/me/bio", json={"bio": "x"},
                      headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 401


def test_get_with_bad_origin_not_blocked(client):
    # GET 非状态变更，不在 CSRF 威胁模型内
    assert client.get("/api/me", headers={"Origin": "https://evil.example"}).json() is None


def test_rate_limit_disabled_passes(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(config, "RATE_LIMITS", {**config.RATE_LIMITS, "default": 1})
    for _ in range(4):
        assert client.get("/api/me").status_code == 200


def test_browse_traffic_does_not_consume_llm_quota(client, monkeypatch):
    # 跨桶隔离回归：default 桶流量不得吃掉 session 桶独立配额
    monkeypatch.setattr(config, "RATE_LIMITS",
                        {**config.RATE_LIMITS, "default": 50, "session": 2})
    for _ in range(5):
        assert client.get("/api/me").status_code == 200
    assert client.post("/api/sessions").status_code == 200
    assert client.post("/api/sessions").status_code == 200
    assert client.post("/api/sessions").status_code == 429
