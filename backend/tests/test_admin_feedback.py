"""管理台反馈收件箱（spec 2026-10-10 三期 §3.3）。"""
import time

import pytest

from app import config
from app.feed import auth, deps
from app.main import app

NOW = 1_700_000_000


@pytest.fixture(autouse=True)
def _clean_overrides():
    """_admin_client 只设不清 app.dependency_overrides，统一每例后清，防泄漏到其它测试文件。"""
    yield
    app.dependency_overrides.clear()


def _admin_client(conn, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(config, "GITHUB_MOCK", True)
    monkeypatch.setattr(config, "ADMIN_LOGINS", ("boss",))
    app.dependency_overrides[deps.get_conn] = lambda: conn
    client = TestClient(app)
    uid = auth.upsert_user(conn, {"id": 1, "login": "boss", "avatar_url": "https://a/b"})
    client.cookies.set(config.SESSION_COOKIE, auth.sign(uid), domain="testserver.local")
    return client


def _mk(conn, uid, *, body="内容", category="bug", status="pending", note=None):
    cur = conn.execute(
        "INSERT INTO feedback (user_id, category, body, contact, status, note,"
        " created_at, updated_at) VALUES (?,?,?,'me@example.com',?,?,?,?)",
        (uid, category, body, status, note, NOW, NOW))
    conn.commit()
    return cur.lastrowid


def _mk_reply(conn, fid, body="回复", *, author="boss", read_at=None, created_at=NOW):
    cur = conn.execute(
        "INSERT INTO feedback_replies (feedback_id, body, author_login, created_at, read_at)"
        " VALUES (?,?,?,?,?)", (fid, body, author, created_at, read_at))
    conn.commit()
    return cur.lastrowid


def _audits(conn, action):
    return [r["detail"] for r in conn.execute(
        "SELECT * FROM audit_logs WHERE action=? ORDER BY id", (action,))]


def test_匿名401(conn):
    from fastapi.testclient import TestClient
    app.dependency_overrides[deps.get_conn] = lambda: conn
    c = TestClient(app)
    assert c.get("/api/admin/feedback").status_code == 401
    app.dependency_overrides.clear()


def test_列表倒序过滤与不外泄contact(conn, monkeypatch):
    client = _admin_client(conn, monkeypatch)
    uid = auth.upsert_user(conn, {"id": 7, "login": "alice", "avatar_url": ""})
    a = _mk(conn, uid, body="第一", category="bug")
    b = _mk(conn, uid, body="第二件", category="suggest", status="done")
    _mk(conn, uid, body="100% 符号", category="other", status="ignored")

    r = client.get("/api/admin/feedback").json()
    assert r["total"] == 3 and [x["id"] for x in r["data"]] == [b + 1, a + 1, a]
    assert "contact" not in r["data"][0]
    assert r["data"][0]["user_login"] == "alice"
    assert set(r["data"][0]) == {"id", "user_id", "user_login", "category", "body", "status",
                                 "note", "reply_count", "created_at", "updated_at"}

    assert client.get("/api/admin/feedback", params={"status": "done"}).json()["total"] == 1
    assert client.get("/api/admin/feedback", params={"category": "other"}).json()["total"] == 1
    assert client.get("/api/admin/feedback", params={"q": "第二"}).json()["total"] == 1
    assert client.get("/api/admin/feedback", params={"q": "100%"}).json()["total"] == 1
    assert client.get("/api/admin/feedback",
                      params={"q": "第二", "status": "done"}).json()["total"] == 1
    assert client.get("/api/admin/feedback",
                      params={"q": "第二", "status": "ignored"}).json()["total"] == 0
    assert client.get("/api/admin/feedback",
                      params={"status": "nope"}).status_code == 422
    assert client.get("/api/admin/feedback",
                      params={"category": "nope"}).status_code == 422
    assert client.get("/api/admin/feedback", params={"q": " "}).status_code == 422
    assert client.get("/api/admin/feedback",
                      params={"q": "x" * 51}).status_code == 422
    assert client.get("/api/admin/feedback",
                      params={"page_size": 101}).status_code == 422


def test_列表含reply_count(conn, monkeypatch):
    client = _admin_client(conn, monkeypatch)
    uid = auth.upsert_user(conn, {"id": 8, "login": "bob", "avatar_url": ""})
    fid = _mk(conn, uid)
    _mk_reply(conn, fid)
    _mk_reply(conn, fid, read_at=NOW)
    r = client.get("/api/admin/feedback").json()
    assert r["data"][0]["reply_count"] == 2


def test_详情含contact与note且回复正序(conn, monkeypatch):
    client = _admin_client(conn, monkeypatch)
    uid = auth.upsert_user(conn, {"id": 9, "login": "carol", "avatar_url": ""})
    fid = _mk(conn, uid, note="内部备注")
    r1 = _mk_reply(conn, fid, "第一条", created_at=NOW + 10)
    r2 = _mk_reply(conn, fid, "第二条", created_at=NOW, read_at=NOW + 5)
    d = client.get(f"/api/admin/feedback/{fid}").json()
    assert d["contact"] == "me@example.com" and d["note"] == "内部备注"
    assert [x["id"] for x in d["replies"]] == [r2, r1]
    assert d["replies"][0]["read_at"] == NOW + 5 and d["replies"][1]["read_at"] is None
    assert client.get("/api/admin/feedback/999999").status_code == 404
