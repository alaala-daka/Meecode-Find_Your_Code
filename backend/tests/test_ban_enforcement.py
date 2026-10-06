"""禁言/禁投稿写操作拦截（spec §5.2）。"""
import time

import pytest
from fastapi.testclient import TestClient

from app import config
from app.feed import auth, deps
from app.main import app

NOW = int(time.time())


@pytest.fixture(autouse=True)
def _no_bg_file_db(monkeypatch):
    """BackgroundTasks 的 moderate_comment_bg 自开文件连接——测试一律替换为空操作
    （同 test_comments.py）：过期解禁用例的 POST 会走完落库并调度后台预审。"""
    from app.feed import moderation
    monkeypatch.setattr(moderation, "moderate_comment_bg", lambda comment_id: None)


@pytest.fixture()
def client(conn, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_MOCK", True)
    app.dependency_overrides[deps.get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def _banned_user(conn, client, *, mute_comment_until=None, mute_submit_until=None):
    uid = auth.upsert_user(conn, {"id": 9, "login": "mallory", "avatar_url": "https://a/m"})
    conn.execute("UPDATE users SET ban_comment_until=?, ban_submit_until=? WHERE id=?",
                 (mute_comment_until, mute_submit_until, uid))
    conn.commit()
    client.cookies.set(config.SESSION_COOKIE, auth.sign(uid), domain="testserver.local")
    return uid


def _mk_repo(conn):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, language, source, status,"
        " quality, published_at, tagline_zh, screened)"
        " VALUES (1,'demo/p1','demo','Python','submitted','published',3,?,'卖点',1)", (NOW,))
    conn.commit()
    return conn.execute("SELECT id FROM repos WHERE github_id=1").fetchone()["id"]


def test_muted_user_cannot_comment(conn, client):
    rid = _mk_repo(conn)
    _banned_user(conn, client, mute_comment_until=NOW + 3600)
    r = client.post("/api/comments", json={"repo_id": rid, "content": "试图发言"})
    assert r.status_code == 403
    body = r.json()["detail"]
    assert body["code"] == "banned" and body["action"] == "comment" and body["until"] == NOW + 3600


def test_expired_mute_allows_comment(conn, client):
    rid = _mk_repo(conn)
    _banned_user(conn, client, mute_comment_until=NOW - 10)
    r = client.post("/api/comments", json={"repo_id": rid, "content": "过期解禁"})
    assert r.status_code == 200


def test_submit_banned_cannot_submit_or_ai_draft(conn, client, monkeypatch):
    _banned_user(conn, client, mute_submit_until=NOW + 3600)
    r = client.post("/api/submit", json={"full_name": "demo/p1", "tagline_zh": "卖点"})
    assert r.status_code == 403
    assert r.json()["detail"]["action"] == "submit"
    r2 = client.post("/api/ai-draft", json={"github_id": 1, "full_name": "demo/p1"})
    assert r2.status_code == 403          # F3：LLM 入口同样拦
    assert r2.json()["detail"]["action"] == "submit"


def test_mute_does_not_block_delete_own_comment(conn, client):
    rid = _mk_repo(conn)
    uid = _banned_user(conn, client, mute_comment_until=NOW + 3600)
    cid = conn.execute(
        "INSERT INTO comments (repo_id, user_id, parent_id, content, status, screened)"
        " VALUES (?,?,NULL,'旧评论','visible',1)", (rid, uid)).lastrowid
    conn.commit()
    assert client.delete(f"/api/comments/{cid}").status_code == 200  # F7：退出通道
