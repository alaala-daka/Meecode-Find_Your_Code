"""管理台鉴权：白名单 401/403/me 语义。"""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.feed import auth, deps
from app.main import app


@pytest.fixture()
def client(conn, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_MOCK", True)
    app.dependency_overrides[deps.get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def _login(conn, client, *, gh_id=700, login="demo"):
    uid = auth.upsert_user(conn, {"id": gh_id, "login": login, "avatar_url": "https://a/x"})
    client.cookies.set(config.SESSION_COOKIE, auth.sign(uid), domain="testserver.local")
    return uid


def test_admin_me_401_when_anonymous(client):
    assert client.get("/api/admin/me").status_code == 401


def test_admin_me_403_when_not_in_whitelist(conn, client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_LOGINS", ("boss",))
    _login(conn, client, login="demo")
    assert client.get("/api/admin/me").status_code == 403


def test_admin_me_200_when_whitelisted(conn, client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_LOGINS", ("demo",))
    _login(conn, client, login="Demo")  # 大小写不敏感
    body = client.get("/api/admin/me").json()
    assert body == {"login": "Demo", "avatar_url": "https://a/x", "is_admin": True}


# ---------- OAuth 回跳白名单 + admin 限流桶（F1/F5） ----------
def test_oauth_entry_stores_whitelisted_redirect(client):
    r = client.get("/api/auth/github?redirect=/admin/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "mc_oauth_redirect" in r.headers.get("set-cookie", "")


def test_oauth_entry_rejects_open_redirect(client):
    r = client.get("/api/auth/github?redirect=https://evil.example/", follow_redirects=False)
    cookie = r.headers.get("set-cookie", "")
    # 回退 "/"：Python 3.14 SimpleCookie 把含 / 的值序列化为带引号形式，jar 解回 "/"
    assert ('mc_oauth_redirect=/;' in cookie or "mc_oauth_redirect=/ " in cookie
            or 'mc_oauth_redirect="/";' in cookie)
    assert "evil.example" not in cookie


def test_admin_bucket_routed_before_repo_prefix():
    from app.security import bucket_for

    assert bucket_for("POST", "/api/admin/repos/1/delist") == "admin"
    assert bucket_for("POST", "/api/repos/1/delist") == "delist"  # 存量规则不受影响


def test_oauth_callback_redirects_back_to_admin(client, monkeypatch):
    from urllib.parse import parse_qs, urlparse

    from app.feed import star_sync

    monkeypatch.setattr(star_sync, "backfill_after_auth", lambda uid: None)
    entry = client.get("/api/auth/github?redirect=/admin/", follow_redirects=False)
    state = parse_qs(urlparse(entry.headers["location"]).query)["state"][0]
    r = client.get("/api/auth/callback", params={"code": "x", "state": state},
                   follow_redirects=False)
    assert r.headers["location"] == config.FRONTEND_ORIGIN.rstrip("/") + "/admin/"
    assert config.SESSION_COOKIE in r.cookies


def test_oauth_callback_rejects_tampered_redirect_cookie(client, monkeypatch):
    """回跳 cookie 回来再校验一次（纵深防御）：被篡改成外站 URL 也只回 "/"."""
    from urllib.parse import parse_qs, urlparse

    from app.feed import star_sync

    monkeypatch.setattr(star_sync, "backfill_after_auth", lambda uid: None)
    entry = client.get("/api/auth/github?redirect=/admin/", follow_redirects=False)
    state = parse_qs(urlparse(entry.headers["location"]).query)["state"][0]
    client.cookies.set("mc_oauth_redirect", "https://evil.example/",
                       domain="testserver.local")
    r = client.get("/api/auth/callback", params={"code": "x", "state": state},
                   follow_redirects=False)
    assert r.headers["location"] == config.FRONTEND_ORIGIN.rstrip("/") + "/"
    assert "evil.example" not in r.headers.get("location", "")
