"""管理台评论：隐藏/恢复/软删/批量/统计。"""
import json
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


def _mk_comment(conn, status="visible", reason=None, gid=50):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, language, source, status,"
        " quality, published_at, tagline_zh, screened)"
        " VALUES (?,?, 'demo','Python','submitted','published',3,?,'卖点',1)", (gid, f"demo/c{gid}", NOW))
    uid = auth.upsert_user(conn, {"id": 100 + gid, "login": f"u{gid}", "avatar_url": "https://a/u"})
    cid = conn.execute(
        "INSERT INTO comments (repo_id, user_id, parent_id, content, status, screened, moderation_reason)"
        " VALUES ((SELECT id FROM repos WHERE github_id=?),?,NULL,'内容',?,1,?)",
        (gid, uid, status, reason or "")).lastrowid
    conn.commit()
    return cid


def test_comment_filters_and_soft_delete(conn, client, admin):
    cid = _mk_comment(conn, "visible", gid=50)
    _mk_comment(conn, "pending", reason="疑似广告", gid=51)
    body = client.get("/api/admin/comments?status=pending").json()
    assert body["total"] == 1 and body["data"][0]["moderation_reason"] == "疑似广告"
    assert client.delete(f"/api/admin/comments/{cid}").status_code == 200
    row = conn.execute("SELECT status, content FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "deleted" and row["content"] == "内容"  # 软删保留原文


def test_comment_hide_restore_bulk_and_stats(conn, client, admin):
    c1, c2 = _mk_comment(conn, "visible", gid=60), _mk_comment(conn, "visible", gid=61)
    assert client.post(f"/api/admin/comments/{c1}/hide").status_code == 200
    assert client.post(f"/api/admin/comments/{c1}/restore").status_code == 200
    r = client.post("/api/admin/comments/bulk", json={"ids": [c1, c2], "action": "hide"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "affected": 2, "not_found": [], "skipped": []}
    stats = client.get("/api/admin/comments/stats").json()
    assert stats["hidden"] == 2 and stats["visible"] == 0


def test_comment_bulk_validation_audits_and_404s(conn, client, admin):
    c1 = _mk_comment(conn, "visible", gid=70)
    assert client.post("/api/admin/comments/bulk", json={"ids": [], "action": "hide"}).status_code == 422
    assert client.post("/api/admin/comments/bulk",
                       json={"ids": list(range(1, 202)), "action": "hide"}).status_code == 422  # 上限 200
    assert client.post("/api/admin/comments/bulk",
                       json={"ids": [c1], "action": "hide", "x": 1}).status_code == 422  # extra=forbid
    assert client.post("/api/admin/comments/bulk", json={"ids": [c1], "action": "restore"}).status_code == 422
    assert client.post("/api/admin/comments/bulk", json={"ids": [c1], "action": "hide"}).status_code == 200
    assert client.post(f"/api/admin/comments/{c1}/restore").status_code == 200
    assert client.post(f"/api/admin/comments/{c1}/hide").status_code == 200
    assert client.delete(f"/api/admin/comments/{c1}").status_code == 200
    assert client.post(f"/api/admin/comments/9999/hide").status_code == 404
    assert client.delete("/api/admin/comments/9999").status_code == 404
    rows = conn.execute("SELECT * FROM audit_logs ORDER BY id").fetchall()
    assert [(r["action"], r["target_type"], r["target_id"]) for r in rows] == [
        ("comment.bulk_hide", "comment", None), ("comment.restore", "comment", str(c1)),
        ("comment.hide", "comment", str(c1)), ("comment.delete", "comment", str(c1))]
    assert json.loads(rows[0]["detail"]) == {"ids": [c1]}


def test_comment_bulk_affected_not_found_skipped_partition(conn, client, admin):
    vis = _mk_comment(conn, "visible", gid=62)
    hid = _mk_comment(conn, "hidden", gid=63)
    de = _mk_comment(conn, "deleted", gid=64)
    ghost = 9999
    r = client.post("/api/admin/comments/bulk",
                    json={"ids": [vis, hid, de, ghost, vis], "action": "hide"})  # 重复 vis
    assert r.status_code == 200
    body = r.json()
    assert body["affected"] == 1                      # 重复 id 不膨胀；hidden/deleted 不算命中
    assert body["not_found"] == [ghost]
    assert body["skipped"] == [hid, de]               # 命中但不可迁移：hidden + deleted
    rows = {row["id"]: row["status"] for row in conn.execute(
        "SELECT id, status FROM comments WHERE id IN (?,?,?)", (vis, hid, de))}
    assert rows == {vis: "hidden", hid: "hidden", de: "deleted"}  # skipped 行不被改动
    log = conn.execute("SELECT * FROM audit_logs").fetchone()
    assert log["action"] == "comment.bulk_hide"
    assert json.loads(log["detail"]) == {"ids": [vis]}  # 只记真正迁移的 id


def test_comment_bulk_all_skipped_still_single_audit_entry(conn, client, admin):
    hid = _mk_comment(conn, "hidden", gid=65)
    r = client.post("/api/admin/comments/bulk", json={"ids": [hid], "action": "hide"})
    assert r.json() == {"ok": True, "affected": 0, "not_found": [], "skipped": [hid]}
    rows = conn.execute("SELECT * FROM audit_logs").fetchall()
    assert len(rows) == 1 and json.loads(rows[0]["detail"]) == {"ids": []}  # 批量单条审计


def test_comment_restore_hidden_to_visible(conn, client, admin):
    cid = _mk_comment(conn, "hidden", gid=66)
    r = client.post(f"/api/admin/comments/{cid}/restore")
    assert r.status_code == 200 and r.json()["status"] == "visible"
    assert conn.execute("SELECT status FROM comments WHERE id=?", (cid,)).fetchone()["status"] == "visible"


def test_comment_state_machine_guards(conn, client, admin):
    cid = _mk_comment(conn, "visible", gid=67)
    assert client.post(f"/api/admin/comments/{cid}/hide").status_code == 200
    assert client.post(f"/api/admin/comments/{cid}/hide").status_code == 409   # hidden -> hide
    assert client.post(f"/api/admin/comments/{cid}/restore").status_code == 200
    assert client.post(f"/api/admin/comments/{cid}/restore").status_code == 409  # visible -> restore
    assert client.delete(f"/api/admin/comments/{cid}").status_code == 200
    assert client.delete(f"/api/admin/comments/{cid}").status_code == 409      # deleted -> delete
    assert conn.execute("SELECT status FROM comments WHERE id=?", (cid,)).fetchone()["status"] == "deleted"


def test_comment_deleted_is_terminal_409s(conn, client, admin):
    cid = _mk_comment(conn, "deleted", gid=68)
    assert client.post(f"/api/admin/comments/{cid}/hide").status_code == 409    # 不可覆盖软删
    assert client.post(f"/api/admin/comments/{cid}/restore").status_code == 409  # 不可复活
    assert client.delete(f"/api/admin/comments/{cid}").status_code == 409
    row = conn.execute("SELECT status, content FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "deleted" and row["content"] == "内容"  # 软删保留原文
    assert conn.execute("SELECT COUNT(*) AS n FROM audit_logs").fetchone()["n"] == 0  # 409 不写审计
    assert client.post(f"/api/admin/comments/{cid}/restore").json()["detail"] == "非法状态转移: deleted -> restore"
    assert client.delete(f"/api/admin/comments/{cid}").json()["detail"] == "非法状态转移: deleted -> delete"


def test_comment_list_shape_and_repo_filter(conn, client, admin):
    c1 = _mk_comment(conn, "visible", gid=80)
    c2 = _mk_comment(conn, "hidden", reason="广告", gid=81)
    rid = conn.execute("SELECT repo_id FROM comments WHERE id=?", (c2,)).fetchone()["repo_id"]
    rows = client.get(f"/api/admin/comments?repo_id={rid}").json()
    assert rows["total"] == 1 and rows["data"][0]["id"] == c2
    row = rows["data"][0]
    assert set(row) == {"id", "repo_id", "repo_full_name", "user_id", "user_login", "parent_id",
                        "content", "status", "moderation_reason", "screened", "created_at"}
    assert row["repo_full_name"] == "demo/c81" and row["user_login"] == "u81"
    assert row["content"] == "内容" and row["screened"] == 1 and row["parent_id"] is None
    assert [r["id"] for r in client.get("/api/admin/comments").json()["data"]] == [c2, c1]  # id DESC
    assert client.get("/api/admin/comments?status=nope").json()["total"] == 2  # 非法 status 不过滤
    assert client.get("/api/admin/comments?page=0").status_code == 422
