"""登录、签名、互动显式 on/off、个人三个 tab。"""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.feed import auth, deps
from app.feed.routes.me import _set_interaction_row
from app.feed.schemas import InteractionIn
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
    # domain 必须写 testserver.local：cookiejar 对无点主机补 .local（erhn），
    # 与服务端 delete_cookie 计算出的域一致，登出才能真正清掉这枚 cookie。
    client.cookies.set(config.SESSION_COOKIE, auth.sign(uid), domain="testserver.local")
    return uid


def add_repo(conn, gid: int, *, owner="demo", source="crawled", status="published"):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, language, source, status,"
        " quality, published_at, tagline_zh, screened)"
        " VALUES (?,?,?,'Python',?,?,3,?,'卖点',1)",
        (gid, f"{owner}/proj{gid}", owner, source, status, NOW))
    conn.commit()
    return conn.execute("SELECT id FROM repos WHERE github_id=?", (gid,)).fetchone()["id"]


def test_me_returns_null_when_anonymous(client):
    assert client.get("/api/me").json() is None


def test_me_returns_user_when_logged_in(client, login):
    body = client.get("/api/me").json()
    assert body["login"] == "demo" and body["id"] == login


def test_oauth_entry_redirects_to_github(client):
    resp = client.get("/api/auth/github", follow_redirects=False)
    assert resp.status_code == 307
    assert "github.com/login/oauth/authorize" in resp.headers["location"]


def test_oauth_callback_sets_cookie(conn, client):
    from urllib.parse import parse_qs, urlparse
    entry = client.get("/api/auth/github", follow_redirects=False)
    state = parse_qs(urlparse(entry.headers["location"]).query)["state"][0]
    resp = client.get("/api/auth/callback", params={"code": "x", "state": state},
                      follow_redirects=False)
    assert resp.status_code == 307
    assert config.SESSION_COOKIE in resp.cookies
    assert conn.execute("SELECT count(*) c FROM users").fetchone()["c"] == 1


def test_oauth_callback_rejects_missing_state(conn, client):
    resp = client.get("/api/auth/callback", params={"code": "x"}, follow_redirects=False)
    assert resp.status_code == 422
    assert conn.execute("SELECT count(*) c FROM users").fetchone()["c"] == 0


def test_oauth_callback_rejects_bad_state(conn, client):
    client.get("/api/auth/github", follow_redirects=False)
    resp = client.get("/api/auth/callback", params={"code": "x", "state": "wrong"},
                      follow_redirects=False)
    assert resp.status_code == 400
    assert conn.execute("SELECT count(*) c FROM users").fetchone()["c"] == 0


def test_oauth_callback_without_code_is_422(client):
    assert client.get("/api/auth/callback").status_code == 422


def test_logout_clears_cookie(client, login):
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/me").json() is None


def test_bio_update_and_length_limit(client, login):
    assert client.put("/api/me/bio", json={"bio": "写代码的人"}).json()["bio"] == "写代码的人"
    assert client.put("/api/me/bio", json={"bio": "x" * 300}).status_code == 422


def test_bio_requires_login(client):
    assert client.put("/api/me/bio", json={"bio": "x"}).status_code == 401


def test_interaction_on_and_off_explicit(conn, client, login):
    rid = add_repo(conn, 1)
    on = InteractionIn(repo_id=rid, kind="favorite", active=True).model_dump()
    assert client.post("/api/interactions", json=on).json() == {"active": True}
    # 显式语义:重复 on 不翻面,响应恒为传入的目标状态
    assert client.post("/api/interactions", json=on).json() == {"active": True}
    assert conn.execute(
        "SELECT count(*) c FROM interactions WHERE kind='favorite'").fetchone()["c"] == 1
    off = InteractionIn(repo_id=rid, kind="favorite", active=False).model_dump()
    assert client.post("/api/interactions", json=off).json() == {"active": False}
    assert conn.execute(
        "SELECT count(*) c FROM interactions WHERE kind='favorite'").fetchone()["c"] == 0


def test_interaction_rejects_bad_kind(conn, client, login):
    rid = add_repo(conn, 1)
    assert client.post("/api/interactions",
                       json={"repo_id": rid, "kind": "visit", "active": True}).status_code == 422
    assert client.post("/api/interactions",
                       json={"repo_id": rid, "kind": "hack", "active": True}).status_code == 422


def test_interaction_rejects_unknown_repo(client, login):
    assert client.post("/api/interactions",
                       json={"repo_id": 9999, "kind": "like", "active": True}).status_code == 404


def test_interaction_requires_login(conn, client):
    rid = add_repo(conn, 1)
    assert client.post("/api/interactions",
                       json={"repo_id": rid, "kind": "like", "active": True}).status_code == 401


def test_my_repos_excludes_delisted(conn, client, login):
    add_repo(conn, 1, owner="demo", source="submitted")
    add_repo(conn, 2, owner="other", source="submitted")
    rid3 = add_repo(conn, 3, owner="demo", source="submitted")
    conn.execute("UPDATE repos SET status='delisted' WHERE id=?", (rid3,))
    conn.commit()
    names = {c["full_name"] for c in client.get("/api/me/repos").json()}
    assert names == {"demo/proj1"}  # 已下架不再出现在个人主页，避免 404


def test_favorites_returns_only_favorited(conn, client, login):
    a, b = add_repo(conn, 1), add_repo(conn, 2)
    client.post("/api/interactions", json={"repo_id": a, "kind": "favorite", "active": True})
    items = client.get("/api/me/favorites").json()
    assert [c["id"] for c in items] == [a]


def test_history_is_ordered_by_recent_visit(conn, client, login):
    a, b = add_repo(conn, 1), add_repo(conn, 2)
    client.get(f"/api/repos/{a}")
    client.get(f"/api/repos/{b}")
    ids = [c["id"] for c in client.get("/api/me/history").json()]
    assert ids == [b, a]


def test_history_excludes_delisted(conn, client, login):
    a = add_repo(conn, 1)
    client.get(f"/api/repos/{a}")
    conn.execute("UPDATE repos SET status='delisted' WHERE id=?", (a,))
    conn.commit()
    assert client.get("/api/me/history").json() == []


def test_personal_endpoints_require_login(client):
    for path in ("/api/me/repos", "/api/me/favorites", "/api/me/history"):
        assert client.get(path).status_code == 401, path


def _seed_user_repo(conn):
    conn.execute("INSERT INTO users (github_id, login) VALUES (1, 'u')")
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status)"
        " VALUES (10, 'a/b', 'a', 'submitted', 'published')"
    )
    conn.commit()


def test_set_interaction_on_off_explicit(conn):
    _seed_user_repo(conn)
    _set_interaction_row(conn, 1, 1, "like", True)
    n = conn.execute("SELECT COUNT(*) AS n FROM interactions").fetchone()["n"]
    assert n == 1
    _set_interaction_row(conn, 1, 1, "like", True)   # 幂等:重复 on 不翻面
    n = conn.execute("SELECT COUNT(*) AS n FROM interactions").fetchone()["n"]
    assert n == 1
    _set_interaction_row(conn, 1, 1, "like", False)
    n = conn.execute("SELECT COUNT(*) AS n FROM interactions").fetchone()["n"]
    assert n == 0
    _set_interaction_row(conn, 1, 1, "like", False)  # 幂等:重复 off 不报错


def test_set_interaction_concurrent_no_error(tmp_path):
    """并发 upsert/delete 不得 500 或 IntegrityError(WAL + busy_timeout 兜底)。"""
    from app.feed import db as feed_db

    db_path = str(tmp_path / "conc.db")
    boot = feed_db.connect(db_path)
    feed_db.init_db(boot)
    _seed_user_repo(boot)
    boot.close()

    def hit(active: bool) -> None:
        c = feed_db.connect(db_path)
        try:
            _set_interaction_row(c, 1, 1, "like", active)
        finally:
            c.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(hit, [True, False] * 8))


def test_interaction_ids(client, login, conn):
    conn.execute("INSERT INTO repos (github_id, full_name, owner_login, source, status)"
                 " VALUES (1, 'a/b', 'a', 'submitted', 'published')")
    conn.commit()
    client.post("/api/interactions", json={"repo_id": 1, "kind": "like", "active": True})
    client.post("/api/interactions", json={"repo_id": 1, "kind": "favorite", "active": True})
    assert client.get("/api/me/interaction-ids", params={"kind": "like"}).json() == [1]
    assert client.get("/api/me/interaction-ids", params={"kind": "favorite"}).json() == [1]
    assert client.get("/api/me/interaction-ids", params={"kind": "bogus"}).status_code == 422


def test_public_profile_and_privacy(client, login, conn):
    conn.execute("UPDATE users SET bio = '简介' WHERE id = ?", (login,))
    for i in (1, 2):
        conn.execute("INSERT INTO repos (github_id, full_name, owner_login, source, status,"
                     " stars, published_at) VALUES (?, ?, 'demo', 'submitted', 'published', 10, ?)",
                     (i, f"demo/r{i}", NOW + i))
    conn.execute("INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
                 " VALUES (?, 1, 'favorite', 1)", (login,))
    conn.commit()
    prof = client.get("/api/users/demo/profile").json()
    assert prof == {"login": "demo", "avatar_url": "https://a/x", "bio": "简介",
                    "repo_count": 2, "star_count": 20, "favorite_count": 1}
    assert len(client.get("/api/users/demo/repos").json()) == 2
    assert [c["id"] for c in client.get("/api/users/demo/favorites").json()] == [1]


def test_history_hidden_from_others(client, login, conn):
    # users.id 是自增 rowid(不是 github_id):显式给 id=999,下面的 interaction 才满足外键
    conn.execute("INSERT INTO users (id, github_id, login) VALUES (999, 999, 'other')")
    conn.execute("INSERT INTO repos (github_id, full_name, owner_login, source, status)"
                 " VALUES (1, 'o/r', 'other', 'submitted', 'published')")
    conn.execute("INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
                 " VALUES (999, 1, 'visit', 1)")
    conn.commit()
    # 他人浏览历史一律空列表,不 403(个人页一次 Promise.all 拉全,spec 第 4 节)
    assert client.get("/api/users/other/history").json() == []
    # 未见过的用户合成空档案而不是 404(采集仓库作者可能从未登录过觅码)
    prof = client.get("/api/users/ghost/profile").json()
    assert prof["login"] == "ghost" and prof["repo_count"] == 0


def test_logout_revokes_all_sessions(conn, client):
    uid = auth.upsert_user(conn, {"id": 710, "login": "demo", "avatar_url": ""})
    token = auth.issue_token(conn, uid)
    client.cookies.set(config.SESSION_COOKIE, token, domain="testserver.local")
    assert client.get("/api/me").json()["id"] == uid

    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200

    client.cookies.set(config.SESSION_COOKIE, token, domain="testserver.local")
    assert client.get("/api/me").json() is None      # 旧 cookie 已吊销
