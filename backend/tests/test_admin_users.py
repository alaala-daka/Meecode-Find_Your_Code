"""管理台用户 API：列表/筛选/详情/备注。"""
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
    monkeypatch.setattr(config, "ADMIN_LOGINS", ("boss",))
    app.dependency_overrides[deps.get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def admin(conn, client):
    uid = auth.upsert_user(conn, {"id": 1, "login": "boss", "avatar_url": "https://a/b"})
    client.cookies.set(config.SESSION_COOKIE, auth.sign(uid), domain="testserver.local")
    return uid


def _mk_user(conn, gh_id, login, *, ban_comment_until=None, ban_submit_until=None):
    uid = auth.upsert_user(conn, {"id": gh_id, "login": login, "avatar_url": "https://a/x"})
    conn.execute("UPDATE users SET ban_comment_until=?, ban_submit_until=? WHERE id=?",
                 (ban_comment_until, ban_submit_until, uid))
    conn.commit()
    return uid


def test_users_list_derives_status(conn, client, admin):
    _mk_user(conn, 10, "alice", ban_comment_until=NOW + 3600)          # banned
    _mk_user(conn, 11, "bob", ban_comment_until=NOW - 10)              # 过期=normal
    body = client.get("/api/admin/users?status=banned").json()
    assert [u["login"] for u in body["data"]] == ["alice"]
    assert body["total"] == 1


def test_users_search_escapes_like_wildcards(conn, client, admin):
    _mk_user(conn, 10, "alice")
    _mk_user(conn, 11, "a%b")
    body = client.get("/api/admin/users?q=%25").json()  # q="%" 应只命中字面 % 的 a%b
    assert [u["login"] for u in body["data"]] == ["a%b"]


def test_user_detail_includes_recent_interactions_and_patch_note(conn, client, admin):
    uid = _mk_user(conn, 10, "alice")
    conn.execute("INSERT INTO repos (github_id, full_name, owner_login, source, status)"
                 " VALUES (1, 'o/r', 'other', 'submitted', 'published')")
    conn.execute("INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
                 " VALUES (?, 1, 'visit', ?)", (uid, NOW))
    conn.commit()
    body = client.get(f"/api/admin/users/{uid}").json()
    assert body["counts"]["visits"] == 1
    r = client.patch(f"/api/admin/users/{uid}", json={"admin_note": "观察对象"})
    assert r.status_code == 200
    assert client.get(f"/api/admin/users/{uid}").json()["admin_note"] == "观察对象"


def test_recent_interactions_ordered_by_last_activity(conn, client, admin):
    uid = _mk_user(conn, 10, "alice")
    conn.execute("INSERT INTO repos (github_id, full_name, owner_login, source, status)"
                 " VALUES (1, 'o/r1', 'other', 'submitted', 'published')")
    conn.execute("INSERT INTO repos (github_id, full_name, owner_login, source, status)"
                 " VALUES (2, 'o/r2', 'other', 'submitted', 'published')")
    conn.execute("INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
                 " VALUES (?, 1, 'visit', ?)", (uid, NOW + 100))
    conn.execute("INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
                 " VALUES (?, 2, 'visit', ?)", (uid, NOW))
    conn.commit()
    rows = client.get(f"/api/admin/users/{uid}").json()["recent_interactions"]
    assert [r["repo_id"] for r in rows] == [1, 2]
    assert rows[0]["created_at"] == NOW + 100