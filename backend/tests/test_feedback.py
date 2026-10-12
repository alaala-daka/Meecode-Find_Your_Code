"""用户反馈全链路（spec 2026-10-10 三期 §3）。"""
import time

import pytest
from fastapi.testclient import TestClient

from app import config
from app.feed import auth, deps
from app.main import app

NOW = int(time.time())


@pytest.fixture()
def client(conn, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_MOCK", True)
    app.dependency_overrides[deps.get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def _login(conn, client, uid=700, login="demo"):
    real = auth.upsert_user(conn, {"id": uid, "login": login, "avatar_url": "https://a/x"})
    client.cookies.set(config.SESSION_COOKIE, auth.sign(real), domain="testserver.local")
    return real


def _ban(conn, uid, *, comment_until=None, submit_until=None):
    conn.execute("UPDATE users SET ban_comment_until=?, ban_submit_until=? WHERE id=?",
                 (comment_until, submit_until, uid))


def test_提交成功落pending并回id(conn, client):
    _login(conn, client)
    r = client.post("/api/feedback",
                    json={"category": "bug", "body": "  页面崩了  ", "contact": " a@b.c "})
    assert r.status_code == 201
    row = conn.execute("SELECT * FROM feedback WHERE id=?", (r.json()["id"],)).fetchone()
    assert row["status"] == "pending" and row["body"] == "页面崩了" and row["contact"] == "a@b.c"


def test_匿名401(client):
    assert client.post("/api/feedback", json={"category": "bug", "body": "x"}).status_code == 401


def test_字段非法422(conn, client):
    _login(conn, client)
    bad = [
        {"category": "nope", "body": "x"},
        {"category": "bug", "body": "   "},
        {"category": "bug", "body": "x" * 501},
        {"category": "bug", "body": "x", "contact": ""},
        {"category": "bug", "body": "x", "contact": "   "},
        {"category": "bug", "body": "x", "contact": "c" * 101},
        {"category": "bug", "body": "x", "extra": 1},
    ]
    for payload in bad:
        assert client.post("/api/feedback", json=payload).status_code == 422, payload
    ok = client.post("/api/feedback",
                     json={"category": "other", "body": "x" * 500, "contact": "c" * 100})
    assert ok.status_code == 201


def test_禁言或禁投稿用户403(conn, client):
    uid = _login(conn, client)
    _ban(conn, uid, comment_until=NOW + 3600)
    r = client.post("/api/feedback", json={"category": "bug", "body": "x"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "banned"

    _ban(conn, uid, comment_until=None, submit_until=NOW + 3600)
    assert client.post("/api/feedback", json={"category": "bug", "body": "y"}).status_code == 403


def test_过期解禁可提交(conn, client):
    uid = _login(conn, client)
    _ban(conn, uid, comment_until=NOW - 10, submit_until=NOW - 10)
    assert client.post("/api/feedback", json={"category": "bug", "body": "x"}).status_code == 201


def test_限流429(monkeypatch, conn, client):
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)
    from app import security
    security.policies.reset()
    _login(conn, client)
    codes = [client.post("/api/feedback",
                         json={"category": "bug", "body": f"x{i}"}).status_code
             for i in range(7)]
    assert 429 in codes
