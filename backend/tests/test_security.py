"""安全中间件：限流分桶、Origin 校验、IP/键提取、CORS 层序回归。

conftest 已 autouse 关闭限流；本文件 autouse 开回（模块级 autouse 后于 conftest
执行，已实验验证），并用 monkeypatch 把阈值压到 1~2 做超限断言，避免真发几百个请求。
"""
import base64

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
    assert security.bucket_for("POST", "/api/comments") == "ugc"
    assert security.bucket_for("POST", "/api/comments/7/hide") == "ugc"
    assert security.bucket_for("DELETE", "/api/comments/7") == "ugc"
    assert security.bucket_for("GET", "/api/comments") == "browse"
    assert security.bucket_for("POST", "/api/repos/7/delist") == "delist"   # 回归：不受影响


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


def test_ugc_endpoint_429_with_retry_after(client, monkeypatch):
    monkeypatch.setitem(config.RATE_LIMITS, "ugc", 1)
    client.post("/api/comments", json={"repo_id": 1, "content": "a"})
    resp = client.post("/api/comments", json={"repo_id": 1, "content": "b"})
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert resp.json()["detail"] == "请求过于频繁，请稍后再试"


# ---------- token 加密封装（spec 2026-09-26 决策 1） ----------
def test_seal_open_roundtrip(monkeypatch):
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", "")
    blob = security.seal_token("ghp_secret_example", "1")
    assert blob != "ghp_secret_example"
    assert "ghp_secret_example" not in blob
    assert blob.startswith("v1.")
    assert security.open_token(blob, "1") == "ghp_secret_example"


def test_open_token_rejects_tampered_blob(monkeypatch):
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", "")
    blob = security.seal_token("ghp_secret_example", "1")
    bad = blob[:-4] + ("AAAA" if not blob.endswith("AAAA") else "BBBB")
    with pytest.raises(ValueError) as excinfo:
        security.open_token(bad, "1")
    assert not isinstance(excinfo.value, security.TokenKeyMismatchError)  # kid 相符=篡改


def test_open_token_rejects_key_mismatch(monkeypatch):
    """改写自旧版（final review A1）：换钥不得再泛化成 tamper ValueError——
    须上抛 TokenKeyMismatchError，调用方据此保留密文不销毁（旧断言只查 ValueError）。"""
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"k" * 32).decode())
    blob = security.seal_token("t", "1")
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"j" * 32).decode())
    with pytest.raises(security.TokenKeyMismatchError):
        security.open_token(blob, "1")
    assert issubclass(security.TokenKeyMismatchError, ValueError)  # 兼容既有 except ValueError


def test_open_token_rejects_aad_swap(monkeypatch):
    """A3 跨行互换回归：AAD 绑定 user_id，user B 的密文拿到 user A 名下解不开。"""
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", "")
    blob = security.seal_token("ghp_secret_example", "1")
    with pytest.raises(ValueError) as excinfo:
        security.open_token(blob, "2")
    assert not isinstance(excinfo.value, security.TokenKeyMismatchError)


# ---------- 回归：严格 base64 + 配置错误独立上抛（fix round 1） ----------
def test_open_token_rejects_non_alphabet_char(monkeypatch):
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", "")
    blob = security.seal_token("ghp_secret_example", "1")
    head, kid, payload = blob.split(".")
    with pytest.raises(ValueError) as excinfo:
        security.open_token(f"{head}.{kid}.{payload[:4]}!{payload[4:]}", "1")
    assert not isinstance(excinfo.value, security.TokenKeyMismatchError)


def test_open_token_malformed_key_is_config_error(monkeypatch):
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"k" * 32).decode())
    blob = security.seal_token("t", "1")
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", "not-base64")
    with pytest.raises(RuntimeError):
        security.open_token(blob, "1")


# ---------- TOKEN_ENC_KEY 启动校验 + 派生告警（spec §4.2，final review Important 3） ----------
def test_ensure_token_key_rejects_wrong_length(monkeypatch):
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"short").decode())
    with pytest.raises(RuntimeError):
        security.ensure_token_key()


def test_ensure_token_key_rejects_bad_base64(monkeypatch):
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", "not-base64")
    with pytest.raises(RuntimeError):
        security.ensure_token_key()


def test_ensure_token_key_rejects_junk_chars_in_base64(monkeypatch):
    """A5 严格解码回归：宽松 b64decode 会静默丢弃非法字符（'A!…' 也凑出 32 字节），
    夹带垃圾必须拒收，不得蒙混成合法密钥。"""
    good = base64.b64encode(b"k" * 32).decode()
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", good[:2] + "!" + good[2:])
    with pytest.raises(RuntimeError):
        security.ensure_token_key()


def test_ensure_token_key_accepts_openssl_base64(monkeypatch):
    """openssl rand -base64 32 同形输出（标准字母表 + padding）必须可用。"""
    good = base64.b64encode(b"k" * 32).decode()
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", good)
    security.ensure_token_key()  # 不抛即通过
    assert security.open_token(security.seal_token("t", "1"), "1") == "t"


def test_ensure_token_key_accepts_missing_padding(monkeypatch):
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"k" * 32).decode().rstrip("="))
    security.ensure_token_key()  # 容缺 padding，不抛即通过


def test_ensure_token_key_accepts_valid(monkeypatch):
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"k" * 32).decode())
    security.ensure_token_key()  # 不抛即通过


def test_ensure_token_key_rejects_unset_in_prod(monkeypatch):
    """A2 生产 fail-fast 回归：GITHUB_MOCK=false 缺 TOKEN_ENC_KEY 拒启，
    不得默默走 dev 派生密钥（换机即无法解封已存 token、无法撤销授权）。"""
    monkeypatch.setattr(config, "GITHUB_MOCK", False)
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", "")
    with pytest.raises(RuntimeError) as excinfo:
        security.ensure_token_key()
    msg = str(excinfo.value)
    assert "TOKEN_ENC_KEY" in msg and "openssl rand -base64 32" in msg


def test_ensure_token_key_warns_when_unset(monkeypatch, caplog):
    monkeypatch.setattr(config, "GITHUB_MOCK", True)
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", "")
    with caplog.at_level("WARNING"):
        security.ensure_token_key()
    assert any("TOKEN_ENC_KEY" in r.message and "生产请配置" in r.message
               for r in caplog.records)
