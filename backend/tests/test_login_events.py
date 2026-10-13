"""登录事件采集（spec 2026-10-10 三期 §2.2）：写失败吞异常，绝不阻塞登录。"""
import pytest

from app import security
from app.feed import github as feed_github
from app.feed import star_sync


def _rows(conn, event):
    return conn.execute(
        "SELECT * FROM login_events WHERE event=? ORDER BY id", (event,)).fetchall()


def test_callback_成功落_login_ok行(conn, client, monkeypatch):
    monkeypatch.setattr(security, "client_ip", lambda request: "203.0.113.7")
    # 后台星同步自开文件库连接（backfill_after_auth → db.connect()），与登录落库断言无关；
    # 打桩隔离，否则干净检出（无存量 meecode.db）会建空库并报 no such table: users
    monkeypatch.setattr(star_sync, "backfill_after_auth", lambda user_id: None)
    client.cookies.set("oauth_state", "st1", domain="testserver.local")
    resp = client.get("/api/auth/callback", params={"code": "c", "state": "st1"},
                      follow_redirects=False)
    assert resp.status_code in (302, 307)
    rows = _rows(conn, "login")
    assert len(rows) == 1
    assert rows[0]["ok"] == 1 and rows[0]["login"] != ""
    assert rows[0]["user_id"] is not None and rows[0]["ip_hash"] != ""


def test_callback_OAuth出错落_ok0行(conn, client, monkeypatch):
    def boom(code):
        raise feed_github.GitHubError("boom")

    monkeypatch.setattr(feed_github, "exchange_oauth_code", boom)
    client.cookies.set("oauth_state", "st1", domain="testserver.local")
    resp = client.get("/api/auth/callback", params={"code": "c", "state": "st1"},
                      follow_redirects=False)
    assert resp.status_code == 502
    rows = _rows(conn, "login")
    assert len(rows) == 1 and rows[0]["ok"] == 0
    assert rows[0]["login"] == "" and rows[0]["user_id"] is None


def test_callback_state不匹配不落行(conn, client):
    client.cookies.set("oauth_state", "aaa", domain="testserver.local")
    resp = client.get("/api/auth/callback", params={"code": "c", "state": "bbb"},
                      follow_redirects=False)
    assert resp.status_code == 400
    assert conn.execute("SELECT COUNT(*) AS n FROM login_events").fetchone()["n"] == 0


def test_logout_落_logout行(conn, client, admin):
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    rows = _rows(conn, "logout")
    assert len(rows) == 1 and rows[0]["ok"] == 1 and rows[0]["login"] == "boss"


def test_匿名logout不落行(conn, client):
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert conn.execute("SELECT COUNT(*) AS n FROM login_events").fetchone()["n"] == 0


def test_鉴权拒绝403不落行(conn, client):
    from app import config
    from app.feed import auth

    uid = auth.upsert_user(conn, {"id": 9, "login": "eve", "avatar_url": "https://a/e"})
    client.cookies.set(config.SESSION_COOKIE, auth.sign(uid), domain="testserver.local")
    assert client.get("/api/admin/users").status_code == 403
    assert conn.execute("SELECT COUNT(*) AS n FROM login_events").fetchone()["n"] == 0


def test_record_写失败吞异常(conn, caplog):
    import logging
    from app.feed import login_events

    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError("db down")

    class Req:
        client = None
        headers = {}

    with caplog.at_level(logging.ERROR):
        login_events.record(Boom(), Req(), user_id=1, login="x", event="login", ok=1)  # 不抛
