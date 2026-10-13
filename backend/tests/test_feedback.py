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


def _mk_feedback(conn, uid, *, body="内容", category="bug", status="pending", note=None,
                 created_at=NOW):
    cur = conn.execute(
        "INSERT INTO feedback (user_id, category, body, contact, status, note,"
        " created_at, updated_at) VALUES (?,?,?,'c@c.c',?,?,?,?)",
        (uid, category, body, status, note, created_at, created_at))
    conn.commit()
    return cur.lastrowid


def _mk_reply(conn, fid, body="回复内容", *, author="boss", read_at=None, created_at=NOW):
    cur = conn.execute(
        "INSERT INTO feedback_replies (feedback_id, body, author_login, created_at, read_at)"
        " VALUES (?,?,?,?,?)", (fid, body, author, created_at, read_at))
    conn.commit()
    return cur.lastrowid


def test_我的反馈列表项含摘要与未读数(conn, client):
    uid = _login(conn, client)
    fid = _mk_feedback(conn, uid, body="x" * 100)
    _mk_reply(conn, fid, body="r" * 100)                       # 最新回复（NOW）→ 80 字预览断言对象
    _mk_reply(conn, fid, body="已读", read_at=NOW, created_at=NOW - 10)
    r = client.get("/api/my/feedback").json()
    assert r["total"] == 1
    item = r["items"][0]
    assert len(item["body_preview"]) == 60
    assert len(item["last_reply_preview"]) == 80
    assert item["last_reply_at"] == NOW and item["unread_count"] == 1
    assert set(item) == {"id", "category", "body_preview", "status", "created_at",
                         "updated_at", "last_reply_preview", "last_reply_at", "unread_count"}


def test_我的反馈倒序分页(conn, client):
    uid = _login(conn, client)
    for i in range(5):
        _mk_feedback(conn, uid, body=f"b{i}")
    r = client.get("/api/my/feedback", params={"page": 2, "page_size": 2}).json()
    assert r["total"] == 5 and len(r["items"]) == 2
    assert [x["id"] for x in r["items"]] == sorted(
        [x["id"] for x in r["items"]], reverse=True)
    assert client.get("/api/my/feedback", params={"page_size": 51}).status_code == 422
    assert client.get("/api/my/feedback").status_code == 200


def test_我的反馈不含他人(conn, client):
    uid = _login(conn, client)
    _mk_feedback(conn, uid)
    other = auth.upsert_user(conn, {"id": 999, "login": "other", "avatar_url": ""})
    _mk_feedback(conn, other)
    assert client.get("/api/my/feedback").json()["total"] == 1


def test_详情置已读且不含contact与note(conn, client):
    uid = _login(conn, client)
    fid = _mk_feedback(conn, uid, body="正文", note="内部备注")
    rid = _mk_reply(conn, fid, body="管理员回复")
    r = client.get(f"/api/feedback/{fid}")
    assert r.status_code == 200
    body = r.json()
    assert body["body"] == "正文"
    assert "contact" not in body and "note" not in body
    assert [x["id"] for x in body["replies"]] == [rid]
    assert set(body["replies"][0]) == {"id", "body", "author_login", "created_at"}
    row = conn.execute("SELECT read_at FROM feedback_replies WHERE id=?", (rid,)).fetchone()
    assert row["read_at"] is not None


def test_详情重复访问不覆盖首写read_at(conn, client):
    uid = _login(conn, client)
    fid = _mk_feedback(conn, uid)
    rid = _mk_reply(conn, fid)
    client.get(f"/api/feedback/{fid}")
    first = conn.execute("SELECT read_at FROM feedback_replies WHERE id=?",
                         (rid,)).fetchone()["read_at"]
    conn.execute("UPDATE feedback_replies SET read_at=12345 WHERE id=?", (rid,))
    conn.commit()
    client.get(f"/api/feedback/{fid}")
    assert conn.execute("SELECT read_at FROM feedback_replies WHERE id=?",
                        (rid,)).fetchone()["read_at"] == 12345


def test_非本人与不存在统一404(conn, client):
    uid = _login(conn, client)
    fid = _mk_feedback(conn, uid)
    other = auth.upsert_user(conn, {"id": 998, "login": "mallory", "avatar_url": ""})
    _mk_feedback(conn, other, body="他人内容")
    r1 = client.get(f"/api/feedback/{fid + 1}")
    client.cookies.set(config.SESSION_COOKIE, auth.sign(other), domain="testserver.local")
    r2 = client.get(f"/api/feedback/{fid + 2}")   # fid+2：不存在的 id（非本人 = r1）
    assert r1.status_code == 404 and r2.status_code == 404
    assert r1.json() == r2.json()


def test_详情匿名401(client):
    assert client.get("/api/feedback/1").status_code == 401


def test_置已读失败吞异常(conn, client, monkeypatch):
    uid = _login(conn, client)
    fid = _mk_feedback(conn, uid)
    _mk_reply(conn, fid)
    import app.feed.routes.feedback as fb
    monkeypatch.setattr(fb, "_mark_replies_read",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    assert client.get(f"/api/feedback/{fid}").status_code == 200


def test_未读数只算本人未读(conn, client):
    uid = _login(conn, client)
    fid = _mk_feedback(conn, uid)
    _mk_reply(conn, fid)
    _mk_reply(conn, fid)
    _mk_reply(conn, fid, read_at=NOW)
    other = auth.upsert_user(conn, {"id": 997, "login": "x", "avatar_url": ""})
    _mk_reply(conn, _mk_feedback(conn, other))
    assert client.get("/api/notifications/replies/unread-count").json() == {"count": 2}
    client.cookies.set(config.SESSION_COOKIE, auth.sign(other), domain="testserver.local")
    assert client.get("/api/notifications/replies/unread-count").json() == {"count": 1}


def test_通知列表倒序含摘要(conn, client):
    uid = _login(conn, client)
    fid = _mk_feedback(conn, uid, body="f" * 100)
    r1 = _mk_reply(conn, fid, body="a" * 100, created_at=NOW)
    _mk_reply(conn, fid, body="bb", created_at=NOW + 10, read_at=NOW + 20)
    r = client.get("/api/notifications/replies").json()
    assert r["total"] == 2
    assert r["items"][0]["reply_id"] == r1 + 1          # ORDER BY id DESC（"bb" 仅 2 字符）
    assert len(r["items"][1]["reply_body_preview"]) == 80   # "a"*100 的截断在次新条
    assert len(r["items"][0]["feedback_body_preview"]) == 60
    assert set(r["items"][0]) == {"feedback_id", "feedback_body_preview", "reply_id",
                                  "reply_body_preview", "created_at"}
    assert client.get("/api/notifications/replies",
                      params={"limit": 51}).status_code == 422


def test_通知匿名401(client):
    assert client.get("/api/notifications/replies").status_code == 401
    assert client.get("/api/notifications/replies/unread-count").status_code == 401
