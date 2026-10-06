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
