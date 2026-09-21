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

def test_client_ip_takes_last_xff_segment():
    # nginx $proxy_add_x_forwarded_for 末段由受信代理追加；前置段可伪造，弃用
    assert security.client_ip(_request(headers={"x-forwarded-for": "1.1.1.1, 2.2.2.2"})) == "2.2.2.2"


def test_client_ip_falls_back_to_socket_peer():
    assert security.client_ip(_request()) == "9.9.9.9"


def test_rate_key_prefers_logged_in_user(conn):
    uid = auth.upsert_user(conn, {"id": 42, "login": "k", "avatar_url": ""})
    req = _request(cookies={config.SESSION_COOKIE: auth.sign(uid)})
    assert security.rate_key(req) == f"u:{uid}"


def test_rate_key_falls_back_to_ip():
    assert security.rate_key(_request(headers={"x-forwarded-for": "3.3.3.3"})) == "ip:3.3.3.3"


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


def test_limiter_evicts_oldest_key_at_capacity():
    limiter = security.SlidingWindowLimiter()
    for i in range(3):
        limiter.allow(f"k{i}", 5, 60, NOW)
    limiter.allow("new", 5, 60, NOW, max_keys=3)
    assert len(limiter._hits) == 3                       # 淘汰最早加入的 k0
    assert "new" in limiter._hits and "k0" not in limiter._hits


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
