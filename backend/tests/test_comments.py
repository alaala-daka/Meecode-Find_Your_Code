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


@pytest.fixture(autouse=True)
def _no_bg_file_db(monkeypatch):
    """BackgroundTasks 的 moderate_comment_bg 自开文件连接——测试一律替换为空操作，
    需断言调度的用例单独 patch 成记录器（见 test_post_schedules_background_moderation）。"""
    from app.feed import moderation
    monkeypatch.setattr(moderation, "moderate_comment_bg", lambda comment_id: None)


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


def test_post_top_level_creates_pending(conn, client, login):
    rid = add_repo(conn)
    resp = client.post("/api/comments", json={"repo_id": rid, "content": "  你好  "})
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "你好" and body["status"] == "pending"
    assert body["parent_id"] is None and body["user_id"] == login


def test_post_reply_normalizes_parent_to_top(conn, client, login):
    rid = add_repo(conn)
    top = add_comment(conn, rid, login, content="顶", status="visible", screened=1)
    reply = add_comment(conn, rid, login, parent_id=top, content="回", status="visible", screened=1)
    resp = client.post("/api/comments", json={"repo_id": rid, "content": "回回", "parent_id": reply})
    assert resp.status_code == 200
    assert resp.json()["parent_id"] == top   # 回复的回复归到同一顶层


def test_post_rejects_empty_content(conn, client, login):
    rid = add_repo(conn)
    resp = client.post("/api/comments", json={"repo_id": rid, "content": "   "})
    assert resp.status_code == 422
    assert "不能为空" in resp.text


def test_post_rejects_too_long_content(conn, client, login, monkeypatch):
    monkeypatch.setattr(config, "COMMENT_MAX_LEN", 10)
    rid = add_repo(conn)
    resp = client.post("/api/comments", json={"repo_id": rid, "content": "x" * 11})
    assert resp.status_code == 422
    assert "过长" in resp.text


def test_post_rejects_cross_repo_parent(conn, client, login):
    rid = add_repo(conn, gid=1)
    rid2 = add_repo(conn, gid=2, owner="other")
    foreign = add_comment(conn, rid2, login, content="别处", status="visible", screened=1)
    resp = client.post("/api/comments", json={"repo_id": rid, "content": "x", "parent_id": foreign})
    assert resp.status_code == 422
    assert "父评论" in resp.text


def test_post_rejects_unknown_parent(conn, client, login):
    rid = add_repo(conn)
    resp = client.post("/api/comments", json={"repo_id": rid, "content": "x", "parent_id": 999})
    assert resp.status_code == 422


def test_post_requires_login(conn, client):
    rid = add_repo(conn)
    resp = client.post("/api/comments", json={"repo_id": rid, "content": "x"})
    assert resp.status_code == 401


def test_post_404_for_delisted_or_unknown_repo(conn, client, login):
    rid = add_repo(conn, status="delisted")
    assert client.post("/api/comments", json={"repo_id": rid, "content": "x"}).status_code == 404
    assert client.post("/api/comments", json={"repo_id": 999, "content": "x"}).status_code == 404


def test_delete_own_comment_soft_deletes(conn, client, login):
    rid = add_repo(conn)
    cid = add_comment(conn, rid, login, content="自删", status="visible", screened=1)
    resp = client.delete(f"/api/comments/{cid}")
    assert resp.status_code == 200 and resp.json() == {"ok": True}
    row = conn.execute("SELECT status FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "deleted"
    assert client.get(f"/api/comments?repo_id={rid}").json() == {"items": [], "total": 0}


def test_delete_other_comment_403(conn, client, login):
    rid = add_repo(conn)
    other = add_user(conn, 702, "u2")
    cid = add_comment(conn, rid, other, content="别人的", status="visible", screened=1)
    assert client.delete(f"/api/comments/{cid}").status_code == 403


def test_delete_anonymous_401(conn, client):
    rid = add_repo(conn)
    cid = add_comment(conn, rid, add_user(conn, 702, "u2"), content="x", status="visible", screened=1)
    assert client.delete(f"/api/comments/{cid}").status_code == 401


def test_delete_unknown_404(conn, client, login):
    assert client.delete("/api/comments/999").status_code == 404


def test_delete_idempotent_on_deleted(conn, client, login):
    rid = add_repo(conn)
    cid = add_comment(conn, rid, login, content="x", status="deleted", screened=1)
    assert client.delete(f"/api/comments/{cid}").status_code == 200


def test_hide_by_author_owner_login(conn, client, login):
    rid = add_repo(conn, owner="demo")          # owner_login == login 的 login 值
    other = add_user(conn, 702, "u2")
    cid = add_comment(conn, rid, other, content="被作者隐", status="visible", screened=1)
    resp = client.post(f"/api/comments/{cid}/hide")
    assert resp.status_code == 200
    row = conn.execute("SELECT status FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "hidden"


def test_hide_by_claimer(conn, client, login):
    rid = add_repo(conn, owner="stranger")
    conn.execute("UPDATE repos SET claimed_by = ? WHERE id = ?", (login, rid))
    conn.commit()
    other = add_user(conn, 702, "u2")
    cid = add_comment(conn, rid, other, content="被认领者隐", status="visible", screened=1)
    assert client.post(f"/api/comments/{cid}/hide").status_code == 200


def test_hide_by_stranger_403(conn, client, login):
    rid = add_repo(conn, owner="stranger")
    other = add_user(conn, 702, "u2")
    cid = add_comment(conn, rid, other, content="x", status="visible", screened=1)
    assert client.post(f"/api/comments/{cid}/hide").status_code == 403


def test_hide_idempotent(conn, client, login):
    rid = add_repo(conn, owner="demo")
    cid = add_comment(conn, rid, login, content="x", status="hidden", screened=1)
    assert client.post(f"/api/comments/{cid}/hide").status_code == 200


def test_hide_on_deleted_404(conn, client, login):
    rid = add_repo(conn, owner="demo")
    cid = add_comment(conn, rid, login, content="x", status="deleted", screened=1)
    assert client.post(f"/api/comments/{cid}/hide").status_code == 404


def test_hide_anonymous_401(conn, client):
    cid = 1
    assert client.post(f"/api/comments/{cid}/hide").status_code == 401


def test_moderate_pass_sets_visible(conn, client, login):
    from app.feed import moderation
    rid = add_repo(conn)
    cid = add_comment(conn, rid, login, content="这是一条正常的技术讨论")
    moderation.moderate_comment(conn, cid)
    conn.commit()
    row = conn.execute("SELECT status, screened FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "visible" and row["screened"] == 1


def test_moderate_fail_sets_hidden(conn, client, login):
    from app.feed import moderation
    rid = add_repo(conn)
    cid = add_comment(conn, rid, login, content="垃圾广告加微信")
    moderation.moderate_comment(conn, cid)
    conn.commit()
    row = conn.execute("SELECT status, screened FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "hidden" and row["screened"] == 1


def test_moderate_error_keeps_pending_unscreened(conn, client, login, monkeypatch):
    from app.feed import llm, moderation

    def boom(**kwargs):
        raise RuntimeError("LLM 挂了")

    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(llm, "chat_json", boom)
    rid = add_repo(conn)
    cid = add_comment(conn, rid, login, content="正常内容")
    with pytest.raises(RuntimeError):
        moderation.moderate_comment(conn, cid)
    row = conn.execute("SELECT status, screened FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "pending" and row["screened"] == 0


def test_moderate_skips_deleted(conn, client, login):
    from app.feed import moderation
    rid = add_repo(conn)
    cid = add_comment(conn, rid, login, content="垃圾", status="deleted", screened=1)
    moderation.moderate_comment(conn, cid)
    row = conn.execute("SELECT status, screened FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "deleted" and row["screened"] == 1


def test_moderate_does_not_flip_hidden_back_to_visible(conn, client, login):
    from app.feed import moderation
    rid = add_repo(conn)
    cid = add_comment(conn, rid, login, content="正常技术讨论")
    conn.execute("UPDATE comments SET status='hidden' WHERE id=?", (cid,))
    conn.commit()
    moderation.moderate_comment(conn, cid)
    conn.commit()
    row = conn.execute("SELECT status, screened FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "hidden" and row["screened"] == 0


def test_post_schedules_background_moderation(conn, client, login, monkeypatch):
    from app.feed import moderation
    called: list[int] = []
    monkeypatch.setattr(moderation, "moderate_comment_bg", called.append)
    rid = add_repo(conn)
    resp = client.post("/api/comments", json={"repo_id": rid, "content": "hi"})
    assert resp.status_code == 200
    assert called == [resp.json()["id"]]


def test_moderate_pending_picks_old_unscreened(conn, client, login, monkeypatch):
    from app.feed.jobs import moderate as job
    monkeypatch.setattr(config, "LLM_MOCK", True)
    rid = add_repo(conn)
    cid = add_comment(conn, rid, login, content="正常内容", created_at=NOW)
    n = job.moderate_pending(conn, now=NOW + 200)
    assert n == 1
    row = conn.execute("SELECT status, screened FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["screened"] == 1 and row["status"] == "visible"


def test_moderate_pending_skips_recent_within_grace(conn, client, login):
    from app.feed.jobs import moderate as job
    rid = add_repo(conn)
    cid = add_comment(conn, rid, login, content="正常内容", created_at=NOW)
    n = job.moderate_pending(conn, now=NOW + 10)   # 宽限期内
    assert n == 0
    row = conn.execute("SELECT screened FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["screened"] == 0


def test_moderate_pending_respects_batch_limit(conn, client, login, monkeypatch):
    from app.feed.jobs import moderate as job
    monkeypatch.setattr(config, "LLM_MOCK", True)
    rid = add_repo(conn)
    for i in range(3):
        add_comment(conn, rid, login, content=f"正常{i}", created_at=NOW + i)
    n = job.moderate_pending(conn, now=NOW + 200, limit=2)
    assert n == 2


def test_moderate_pending_skips_screened(conn, client, login):
    from app.feed.jobs import moderate as job
    rid = add_repo(conn)
    add_comment(conn, rid, login, content="已判", status="visible", screened=1, created_at=NOW)
    assert job.moderate_pending(conn, now=NOW + 200) == 0


def test_moderate_pending_skips_non_pending_status(conn, client, login, monkeypatch):
    from app.feed.jobs import moderate as job
    monkeypatch.setattr(config, "LLM_MOCK", True)
    rid = add_repo(conn)
    add_comment(conn, rid, login, content="已删", status="deleted", screened=0, created_at=NOW)
    add_comment(conn, rid, login, content="已显", status="visible", screened=0, created_at=NOW)
    assert job.moderate_pending(conn, now=NOW + 200) == 0


def test_moderate_pending_default_batch_from_config(conn, client, login, monkeypatch):
    from app.feed.jobs import moderate as job
    monkeypatch.setattr(config, "LLM_MOCK", True)
    monkeypatch.setattr(config, "MODERATE_BATCH", 2)
    rid = add_repo(conn)
    for i in range(3):
        add_comment(conn, rid, login, content=f"正常{i}", created_at=NOW + i)
    assert job.moderate_pending(conn, now=NOW + 200) == 2


def test_moderate_pending_error_leaves_for_next_round(conn, client, login, monkeypatch):
    from app.feed import llm
    from app.feed.jobs import moderate as job

    def boom(**kwargs):
        raise RuntimeError("LLM 故障")

    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(llm, "chat_json", boom)
    rid = add_repo(conn)
    cid = add_comment(conn, rid, login, content="待重试", created_at=NOW)
    assert job.moderate_pending(conn, now=NOW + 200) == 0
    row = conn.execute("SELECT status, screened FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "pending" and row["screened"] == 0
    monkeypatch.setattr(config, "LLM_MOCK", True)   # 下轮恢复后补判
    assert job.moderate_pending(conn, now=NOW + 400) == 1
    row = conn.execute("SELECT status, screened FROM comments WHERE id=?", (cid,)).fetchone()
    assert row["screened"] == 1 and row["status"] == "visible"
