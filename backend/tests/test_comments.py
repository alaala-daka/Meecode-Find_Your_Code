"""评论区：数据模型、GET 可见性与线程分页（spec 2026-09-24）。"""
import pytest
from fastapi.testclient import TestClient

from app.feed import auth, deps
from app import config
from app.main import app

NOW = 1_700_000_000


@pytest.fixture()
def client(conn, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_MOCK", True)
    app.dependency_overrides[deps.get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def login(conn, client):
    uid = auth.upsert_user(conn, {"id": 700, "login": "demo", "avatar_url": "https://a/x"})
    client.cookies.set(config.SESSION_COOKIE, auth.sign(uid), domain="testserver.local")
    return uid


def add_repo(conn, gid: int = 1, *, owner="demo", status="published"):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, language, source, status,"
        " quality, published_at, tagline_zh, screened)"
        " VALUES (?,?,?,'Python','crawled',?,3,?,'卖点',1)",
        (gid, f"{owner}/proj{gid}", owner, status, NOW))
    conn.commit()
    return conn.execute("SELECT id FROM repos WHERE github_id=?", (gid,)).fetchone()["id"]


def add_user(conn, uid: int, login: str):
    return auth.upsert_user(conn, {"id": uid, "login": login, "avatar_url": ""})


def add_comment(conn, repo_id: int, user_id: int, *, parent_id=None,
                content="内容", status="pending", screened=0, created_at=NOW) -> int:
    conn.execute(
        "INSERT INTO comments (repo_id, user_id, parent_id, content, status, screened, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (repo_id, user_id, parent_id, content, status, screened, created_at))
    conn.commit()
    return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def test_insert_defaults_to_pending_unscreened(conn):
    rid = add_repo(conn)
    uid = add_user(conn, 701, "u1")
    cid = add_comment(conn, rid, uid)
    row = conn.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "pending" and row["screened"] == 0
    assert row["parent_id"] is None


def test_get_empty_returns_zero_total(conn, client):
    rid = add_repo(conn)
    body = client.get(f"/api/comments?repo_id={rid}").json()
    assert body == {"items": [], "total": 0}


def test_get_returns_visible_to_anonymous(conn, client):
    rid = add_repo(conn)
    uid = add_user(conn, 701, "u1")
    cid = add_comment(conn, rid, uid, content="正常评论", status="visible", screened=1)
    body = client.get(f"/api/comments?repo_id={rid}").json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == cid
    assert body["items"][0]["user_login"] == "u1"
    assert body["items"][0]["status"] == "visible"
    assert body["items"][0]["created_at_iso"]


def test_get_hides_pending_and_hidden_from_others(conn, client, login):
    rid = add_repo(conn)
    other = add_user(conn, 702, "u2")
    add_comment(conn, rid, other, content="审核中", status="pending")
    add_comment(conn, rid, other, content="被隐", status="hidden", screened=1)
    body = client.get(f"/api/comments?repo_id={rid}").json()
    assert body == {"items": [], "total": 0}


def test_get_shows_own_pending_and_hidden_with_status(conn, client, login):
    rid = add_repo(conn)
    add_comment(conn, rid, login, content="我的审核中", status="pending")
    add_comment(conn, rid, login, content="我的被隐", status="hidden", screened=1)
    body = client.get(f"/api/comments?repo_id={rid}").json()
    assert body["total"] == 2
    assert {i["status"] for i in body["items"]} == {"pending", "hidden"}


def test_get_never_returns_deleted(conn, client, login):
    rid = add_repo(conn)
    add_comment(conn, rid, login, content="已删", status="deleted", screened=1)
    body = client.get(f"/api/comments?repo_id={rid}").json()
    assert body == {"items": [], "total": 0}


def test_get_replies_follow_parent_visibility(conn, client):
    rid = add_repo(conn)
    u1 = add_user(conn, 701, "u1")
    u2 = add_user(conn, 702, "u2")
    top = add_comment(conn, rid, u1, content="父", status="pending")
    add_comment(conn, rid, u2, parent_id=top, content="子", status="visible", screened=1)
    body = client.get(f"/api/comments?repo_id={rid}").json()
    assert body == {"items": [], "total": 0}


def test_get_threads_paginate_by_top_level(conn, client):
    rid = add_repo(conn)
    u1 = add_user(conn, 701, "u1")
    t1 = add_comment(conn, rid, u1, content="一楼", status="visible", screened=1, created_at=NOW)
    add_comment(conn, rid, u1, parent_id=t1, content="一楼回复", status="visible", screened=1,
                created_at=NOW + 1)
    add_comment(conn, rid, u1, content="二楼", status="visible", screened=1, created_at=NOW + 2)
    page = client.get(f"/api/comments?repo_id={rid}&limit=1").json()
    assert page["total"] == 2
    assert [i["content"] for i in page["items"]] == ["一楼", "一楼回复"]
    page2 = client.get(f"/api/comments?repo_id={rid}&limit=1&offset=1").json()
    assert [i["content"] for i in page2["items"]] == ["二楼"]


def test_get_404_for_unknown_repo(conn, client):
    assert client.get("/api/comments?repo_id=999").status_code == 404


def test_get_404_for_delisted(conn, client):
    rid = add_repo(conn, status="delisted")
    assert client.get(f"/api/comments?repo_id={rid}").status_code == 404
