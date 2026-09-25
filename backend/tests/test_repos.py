"""仓库详情与文件预览：浏览计数、路径穿越防护、GitHub 故障抛 502/422。"""
import time

import pytest
from fastapi.testclient import TestClient

from app.feed import auth, deps, github
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
def client_and_conn(client, conn):
    """brief 用例按 (client, conn) 解包：复用既有装置，不另起炉灶。"""
    yield client, conn


@pytest.fixture()
def repo_id(conn):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, language, source, status,"
        " quality, published_at, readme_md, default_branch, tagline_zh, screened)"
        " VALUES (1, 'demo/agent-runtime', 'demo', 'TypeScript', 'crawled',"
        " 'published', 4, ?, '# 说明', 'main', '最小运行时', 1)", (NOW,))
    conn.commit()
    return conn.execute("SELECT id FROM repos WHERE github_id=1").fetchone()["id"]


def test_detail_returns_repo(client, repo_id):
    body = client.get(f"/api/repos/{repo_id}").json()
    assert body["full_name"] == "demo/agent-runtime"
    assert body["title"] == "agent-runtime"
    assert body["github_url"] == "https://github.com/demo/agent-runtime"
    assert "readme_md" not in body


def test_detail_bumps_repo_view_count(conn, client, repo_id):
    client.get(f"/api/repos/{repo_id}")
    client.get(f"/api/repos/{repo_id}")
    row = conn.execute("SELECT repo_view_count FROM repos WHERE id=?", (repo_id,)).fetchone()
    assert row["repo_view_count"] == 2


def test_detail_records_visit_for_logged_in_user(conn, client, repo_id):
    uid = auth.upsert_user(conn, {"id": 42, "login": "u", "avatar_url": ""})
    client.cookies.set(config.SESSION_COOKIE, auth.sign(uid))
    client.get(f"/api/repos/{repo_id}")
    client.get(f"/api/repos/{repo_id}")
    rows = conn.execute(
        "SELECT * FROM interactions WHERE kind='visit' AND user_id=?", (uid,)).fetchall()
    assert len(rows) == 1  # visit 去重，供浏览历史


def test_detail_no_visit_row_for_anonymous(conn, client, repo_id):
    client.get(f"/api/repos/{repo_id}")
    assert conn.execute("SELECT count(*) c FROM interactions").fetchone()["c"] == 0


def test_detail_404_for_unknown(client):
    assert client.get("/api/repos/9999").status_code == 404


def test_detail_404_for_delisted(conn, client, repo_id):
    conn.execute("UPDATE repos SET status='delisted' WHERE id=?", (repo_id,))
    conn.commit()
    assert client.get(f"/api/repos/{repo_id}").status_code == 404


def test_tree_returns_nested_items(client, repo_id):
    items = client.get(f"/api/repos/{repo_id}/tree").json()
    assert isinstance(items, list)
    src = next(i for i in items if i["path"] == "src")
    assert src["type"] == "dir"
    assert any(c["path"] == "src/main.ts" for c in src["children"])


def test_file_returns_content(client, repo_id):
    body = client.get(f"/api/repos/{repo_id}/files", params={"path": "src/main.ts"}).json()
    assert body["path"] == "src/main.ts"
    assert "src/main.ts" in body["content"]


def test_file_rejects_path_traversal(client, repo_id):
    for bad in ("../secrets", "/etc/passwd", "a/../../b", "..\\win"):
        resp = client.get(f"/api/repos/{repo_id}/files", params={"path": bad})
        assert resp.status_code == 422, bad


def test_file_rejects_empty_path(client, repo_id):
    assert client.get(f"/api/repos/{repo_id}/files", params={"path": " "}).status_code == 422


def test_file_502_when_github_fails(client, repo_id, monkeypatch):
    """GitHub 故障不是合法的空文件：502 让前端走错误提示。"""
    monkeypatch.setattr(config, "GITHUB_MOCK", False)
    def boom(*a, **kw):
        raise github.GitHubError("限流")
    monkeypatch.setattr(github, "get_file", boom)
    resp = client.get(f"/api/repos/{repo_id}/files", params={"path": "src/main.ts"})
    assert resp.status_code == 502


def test_tree_502_when_github_fails(client, repo_id, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_MOCK", False)
    def boom(*a, **kw):
        raise github.GitHubError("限流")
    monkeypatch.setattr(github, "get_tree", boom)
    resp = client.get(f"/api/repos/{repo_id}/tree")
    assert resp.status_code == 502


def test_binary_file_is_not_dumped(client, repo_id, monkeypatch):
    """图片等二进制不该塞进 JSON：422 是确定性结果，前端提示去 GitHub 查看。"""
    monkeypatch.setattr(config, "GITHUB_MOCK", False)
    monkeypatch.setattr(github, "get_file", lambda *a, **kw: "\x00\x01\x02binary")
    resp = client.get(f"/api/repos/{repo_id}/files", params={"path": "logo.png"})
    assert resp.status_code == 422
    assert "二进制" in resp.json()["detail"]


def test_oversized_file_is_rejected(client, repo_id, monkeypatch):
    """超大文件不再截断直出：422 提示去 GitHub 看完整内容。"""
    monkeypatch.setattr(config, "GITHUB_MOCK", False)
    monkeypatch.setattr(
        github, "get_file", lambda *a, **kw: "x" * (config.MAX_FILE_CHARS + 10))
    resp = client.get(f"/api/repos/{repo_id}/files", params={"path": "big.log"})
    assert resp.status_code == 422
    assert "截断" in resp.json()["detail"]


def test_repo_detail_frontend_shape(client_and_conn):
    client, conn = client_and_conn
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, language, topics, stars,"
        " source, status, category, tagline_zh, intro_zh, published_at, repo_view_count,"
        " default_branch) VALUES (1, 'a/b', 'a', 'Python', 'x', 3, 'submitted',"
        " 'published', '开发工具', '卖点', '介绍', 1756000000, 41, 'main')"
    )
    conn.commit()
    body = client.get("/api/repos/1").json()
    assert body["title"] == "b" and body["views"] == 42 and body["likes"] == 0
    assert body["github_url"] == "https://github.com/a/b"
    assert body["default_branch"] == "main"
    assert body["intro_zh"] == "介绍"
    assert body["liked"] is False and body["favorited"] is False
    assert "readme_md" not in body and "giscus_repo_id" not in body


def test_detail_liked_favorited_reflect_interactions(conn, client, repo_id):
    uid = auth.upsert_user(conn, {"id": 42, "login": "u", "avatar_url": ""})
    conn.execute(
        "INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
        " VALUES (?, ?, 'like', 1)", (uid, repo_id))
    conn.execute(
        "INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
        " VALUES (?, ?, 'favorite', 1)", (uid, repo_id))
    conn.commit()
    client.cookies.set(config.SESSION_COOKIE, auth.sign(uid))
    body = client.get(f"/api/repos/{repo_id}").json()
    assert body["liked"] is True and body["favorited"] is True


def test_detail_liked_favorited_false_for_anonymous(conn, client, repo_id):
    uid = auth.upsert_user(conn, {"id": 42, "login": "u", "avatar_url": ""})
    conn.execute(
        "INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
        " VALUES (?, ?, 'like', 1)", (uid, repo_id))
    conn.commit()
    body = client.get(f"/api/repos/{repo_id}").json()
    assert body["liked"] is False and body["favorited"] is False


def test_detail_is_owner_for_claimer(conn, client, repo_id):
    uid = auth.upsert_user(conn, {"id": 50, "login": "boss", "avatar_url": ""})
    conn.execute("UPDATE repos SET claimed_by = ? WHERE id = ?", (uid, repo_id))
    conn.commit()
    client.cookies.set(config.SESSION_COOKIE, auth.sign(uid))
    assert client.get(f"/api/repos/{repo_id}").json()["is_owner"] is True


def test_detail_is_owner_false_for_stranger(conn, client, repo_id):
    uid = auth.upsert_user(conn, {"id": 51, "login": "stranger", "avatar_url": ""})
    client.cookies.set(config.SESSION_COOKIE, auth.sign(uid))
    assert client.get(f"/api/repos/{repo_id}").json()["is_owner"] is False


def test_tree_nested_and_types(monkeypatch, client_and_conn):
    client, conn = client_and_conn
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status, default_branch)"
        " VALUES (1, 'a/b', 'a', 'submitted', 'published', 'main')"
    )
    conn.commit()
    monkeypatch.setattr(github, "get_tree", lambda *a, **k: [
        {"path": "README.md", "type": "blob", "size": 10},
        {"path": "src", "type": "tree", "size": 0},
        {"path": "src/main.py", "type": "blob", "size": 5},
    ])
    items = client.get("/api/repos/1/tree").json()
    assert items[0] == {"name": "README.md", "path": "README.md", "type": "file"}
    src = next(i for i in items if i["path"] == "src")
    assert src["type"] == "dir" and src["children"][0]["path"] == "src/main.py"


def test_related_same_category(client_and_conn):
    client, conn = client_and_conn
    now = int(time.time())
    for i, cat in [(1, "开发工具"), (2, "开发工具"), (3, "数据处理")]:
        conn.execute(
            "INSERT INTO repos (github_id, full_name, owner_login, source, status,"
            " category, published_at) VALUES (?, ?, 'a', 'submitted', 'published', ?, ?)",
            (i, f"a/r{i}", cat, now - i),
        )
    conn.commit()
    body = client.get("/api/repos/1/related").json()
    assert [c["id"] for c in body] == [2]  # 同分类、排除自身
