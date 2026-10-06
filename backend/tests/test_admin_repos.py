"""管理台仓库：上下架状态机 + 元数据编辑。"""
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


def _mk_repo(conn, gid=100, status="published"):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, language, source, status,"
        " quality, published_at, tagline_zh, screened)"
        " VALUES (?,?, 'demo','Python','submitted',?,3,?,'卖点',1)", (gid, f"demo/p{gid}", status, NOW))
    conn.commit()
    return conn.execute("SELECT id FROM repos WHERE github_id=?", (gid,)).fetchone()["id"]


def test_repo_status_filter_and_patch(conn, client, admin):
    rid = _mk_repo(conn, 100, "published")
    _mk_repo(conn, 101, "delisted")
    body = client.get("/api/admin/repos?status=delisted").json()
    assert body["total"] == 1
    r = client.patch(f"/api/admin/repos/{rid}",
                     json={"category": "工具", "quality": 8, "tagline_zh": "新卖点"})
    assert r.status_code == 200
    row = conn.execute("SELECT * FROM repos WHERE id=?", (rid,)).fetchone()
    assert (row["category"], row["quality"], row["tagline_zh"]) == ("工具", 8, "新卖点")


def test_repo_state_machine(conn, client, admin):
    rid = _mk_repo(conn, 100, "published")
    assert client.post(f"/api/admin/repos/{rid}/delist").status_code == 200
    assert conn.execute("SELECT status FROM repos WHERE id=?", (rid,)).fetchone()["status"] == "delisted"
    assert client.post(f"/api/admin/repos/{rid}/restore").status_code == 200
    assert client.post(f"/api/admin/repos/{rid}/restore").status_code == 409  # 非法转移
    assert client.post(f"/api/admin/repos/{rid}/publish").status_code == 409
    assert client.post(f"/api/admin/repos/{rid}/delist").status_code == 200
    assert client.post(f"/api/admin/repos/{rid}/publish").status_code == 200  # delisted 可上架


def test_repo_transition_audits_and_404s(conn, client, admin):
    rid = _mk_repo(conn, 100, "pending_claim")
    assert client.post(f"/api/admin/repos/{rid}/publish").status_code == 200  # pending_claim 可上架
    assert client.post(f"/api/admin/repos/{rid}/delist").status_code == 200
    rows = conn.execute("SELECT * FROM audit_logs ORDER BY id").fetchall()
    assert [(r["action"], r["target_type"], r["target_id"]) for r in rows] == [
        ("repo.publish", "repo", str(rid)), ("repo.delist", "repo", str(rid))]
    assert [json.loads(r["detail"]) for r in rows] == [
        {"from": "pending_claim", "to": "published"}, {"from": "published", "to": "delisted"}]
    assert client.post(f"/api/admin/repos/{rid}/rename").status_code == 404  # 未知动作
    assert client.post("/api/admin/repos/9999/publish").status_code == 404  # 仓库不存在


def test_repo_transition_illegal_detail_message(conn, client, admin):
    rid = _mk_repo(conn, 100, "published")
    r = client.post(f"/api/admin/repos/{rid}/publish")
    assert r.status_code == 409
    assert r.json()["detail"] == "非法状态转移: published -> publish"


def test_repo_patch_partial_and_edit_audit(conn, client, admin):
    rid = _mk_repo(conn, 100, "published")
    r = client.patch(f"/api/admin/repos/{rid}", json={"quality": 9})
    assert r.status_code == 200
    row = conn.execute("SELECT * FROM repos WHERE id=?", (rid,)).fetchone()
    assert row["quality"] == 9
    assert (row["category"], row["tagline_zh"]) == ("其他", "卖点")  # 未提供的字段不动
    audit = conn.execute("SELECT * FROM audit_logs ORDER BY id DESC").fetchone()
    assert audit["action"] == "repo.edit"
    assert json.loads(audit["detail"]) == {"quality": 9}
    assert client.patch(f"/api/admin/repos/{rid}", json={"stars": 99}).status_code == 422  # extra=forbid
    assert client.patch(f"/api/admin/repos/{rid}", json={"quality": 11}).status_code == 422  # le=10
    assert client.patch(f"/api/admin/repos/{rid}", json={"category": "x" * 51}).status_code == 422
    assert client.patch("/api/admin/repos/9999", json={"quality": 5}).status_code == 404


def test_repo_list_search_escapes_like_wildcards(conn, client, admin):
    _mk_repo(conn, 100, "published")
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, language, source, status)"
        " VALUES (101, 'demo/p%q', 'demo', 'Python', 'submitted', 'published')")
    conn.commit()
    body = client.get("/api/admin/repos?q=%25").json()  # q="%" 应只命中字面 % 的 demo/p%q
    assert [r["full_name"] for r in body["data"]] == ["demo/p%q"]
    assert body["total"] == 1


def test_repo_list_shape_and_status_values(conn, client, admin):
    rid = _mk_repo(conn, 100, "published")
    rows = client.get("/api/admin/repos").json()
    assert rows["total"] == 1
    row = rows["data"][0]
    assert set(row) == {"id", "github_id", "full_name", "owner_login", "language", "stars",
                        "source", "status", "category", "quality", "tagline_zh",
                        "impression_count", "repo_view_count", "published_at"}
    assert row["id"] == rid and row["github_id"] == 100 and row["status"] == "published"
    for s in ("published", "pending_claim", "delisted"):
        assert client.get(f"/api/admin/repos?status={s}").status_code == 200
