"""登录、签名、互动显式 on/off、个人三个 tab。"""
import base64
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.feed import auth, deps, github, star_sync
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
    r1 = client.post("/api/interactions", json=on).json()
    assert r1["active"] is True and r1["sync"] == "need_auth"
    # 显式语义:重复 on 不翻转;响应恒为传入的目标状态
    r2 = client.post("/api/interactions", json=on).json()
    assert r2["active"] is True and r2["sync"] == "need_auth"
    assert conn.execute(
        "SELECT count(*) c FROM interactions WHERE kind='favorite'").fetchone()["c"] == 1
    off = InteractionIn(repo_id=rid, kind="favorite", active=False).model_dump()
    r3 = client.post("/api/interactions", json=off).json()
    assert r3["active"] is False and r3["sync"] == "need_auth"
    assert conn.execute("SELECT count(*) c FROM star_syncs").fetchone()["c"] == 1
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


@pytest.fixture(autouse=True)
def _no_bg_file_db(monkeypatch):
    """BackgroundTasks 的 backfill_after_auth 自开文件连接——测试一律替换为空操作，
    需断言调度的用例单独 patch 成记录器（见 test_oauth_callback_seals_token）。"""
    monkeypatch.setattr(star_sync, "backfill_after_auth", lambda uid: None)


# ---------- 收藏同步 GitHub 星：OAuth 扩权与 token 落库（spec 2026-09-26） ----------
def test_oauth_entry_requests_public_repo_scope(client):
    from urllib.parse import parse_qs, urlparse
    entry = client.get("/api/auth/github", follow_redirects=False)
    q = parse_qs(urlparse(entry.headers["location"]).query)
    assert "public_repo" in q["scope"][0].split()


def test_oauth_callback_seals_token(conn, client, monkeypatch):
    from app import security
    scheduled = []
    monkeypatch.setattr(star_sync, "backfill_after_auth", lambda uid: scheduled.append(uid))
    from urllib.parse import parse_qs, urlparse
    entry = client.get("/api/auth/github", follow_redirects=False)
    state = parse_qs(urlparse(entry.headers["location"]).query)["state"][0]
    client.get("/api/auth/callback", params={"code": "x", "state": state}, follow_redirects=False)
    row = conn.execute("SELECT * FROM users").fetchone()
    assert security.open_token(row["gh_token_enc"], str(row["id"])) == "mock-token"
    assert row["gh_star_authed_at"] > 0
    assert scheduled == [row["id"]]


def test_me_carries_gh_star_authed(conn, client, login):
    assert client.get("/api/me").json()["gh_star_authed"] is False
    conn.execute("UPDATE users SET gh_token_enc='sealed' WHERE id=?", (login,))
    conn.commit()
    assert client.get("/api/me").json()["gh_star_authed"] is True


def test_disconnect_star_auth_clears_everything(conn, client, login, monkeypatch):
    from app import security
    revoked = []
    monkeypatch.setattr(github, "revoke_oauth_token", lambda tok: revoked.append(tok))
    conn.execute("UPDATE users SET gh_token_enc=? WHERE id=?",
                 (security.seal_token("tok", str(login)), login))  # 真实密封密文：open_token 成功才轮到 revoke
    add_repo(conn, 1)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, updated_at)"
                 " VALUES (?, 1, 'starred', 'done', 1)", (login,))
    conn.commit()
    assert client.delete("/api/me/gh-star-auth").json() == {"ok": True}
    assert revoked == ["tok"]                       # revoke 被调用
    row = conn.execute("SELECT * FROM users WHERE id=?", (login,)).fetchone()
    assert row["gh_token_enc"] == "" and row["gh_star_authed_at"] == 0
    assert conn.execute("SELECT count(*) c FROM star_syncs").fetchone()["c"] == 0


def test_disconnect_survives_revoke_exception(conn, client, login, monkeypatch):
    """spec §4.2「失败也照清本地」（final review Critical 2）：revoke 抛非 HTTPError
    （httpx.InvalidURL 等）也必须清 gh_token_enc/gh_star_authed_at、删 star_syncs、返回 ok。"""
    import httpx
    from app import security

    def boom(_tok):
        raise httpx.InvalidURL("not a url")

    monkeypatch.setattr(github, "revoke_oauth_token", boom)
    conn.execute("UPDATE users SET gh_token_enc=? WHERE id=?",
                 (security.seal_token("tok", str(login)), login))
    add_repo(conn, 1)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, updated_at)"
                 " VALUES (?, 1, 'starred', 'done', 1)", (login,))
    conn.commit()
    assert client.delete("/api/me/gh-star-auth").json() == {"ok": True}
    row = conn.execute("SELECT * FROM users WHERE id=?", (login,)).fetchone()
    assert row["gh_token_enc"] == "" and row["gh_star_authed_at"] == 0
    assert conn.execute("SELECT count(*) c FROM star_syncs").fetchone()["c"] == 0


def test_disconnect_star_auth_requires_login(client):
    assert client.delete("/api/me/gh-star-auth").status_code == 401


# ---------- interactions 内联同步（spec 2026-09-26） ----------
def test_favorite_without_token_returns_need_auth(conn, client, login):
    rid = add_repo(conn, 1)
    body = client.post("/api/interactions",
                       json={"repo_id": rid, "kind": "favorite", "active": True}).json()
    assert body == {"active": True, "sync": "need_auth"}
    assert conn.execute("SELECT count(*) c FROM star_syncs").fetchone()["c"] == 0


def test_favorite_with_token_syncs_in_mock(conn, client, login):
    from app import security
    conn.execute("UPDATE users SET gh_token_enc=? WHERE id=?",
                 (security.seal_token("tok", str(login)), login))
    conn.commit()
    rid = add_repo(conn, 1, owner="other")  # 跨用户场景；own-repo 已无特判，走常规 PUT
    on = client.post("/api/interactions",
                     json={"repo_id": rid, "kind": "favorite", "active": True}).json()
    assert on == {"active": True, "sync": "synced"}
    row = conn.execute("SELECT * FROM star_syncs").fetchone()
    assert (row["desired"], row["applied"]) == ("starred", "done")
    off = client.post("/api/interactions",
                      json={"repo_id": rid, "kind": "favorite", "active": False}).json()
    assert off == {"active": False, "sync": "unstarred"}
    assert conn.execute("SELECT count(*) c FROM star_syncs").fetchone()["c"] == 0


def test_like_has_empty_sync(conn, client, login):
    rid = add_repo(conn, 1)
    body = client.post("/api/interactions",
                       json={"repo_id": rid, "kind": "like", "active": True}).json()
    assert body == {"active": True, "sync": ""}


def test_interaction_sync_error_degrades_to_pending(conn, client, login, monkeypatch):
    """同步边界兜底（final review Important 3）：TOKEN_ENC_KEY 配错在 seal/open 以
    RuntimeError 爆炸时，不得 500；本地已提交不回滚，sync 降级 pending。"""
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"short").decode())
    conn.execute("UPDATE users SET gh_token_enc='blob' WHERE id=?", (login,))
    conn.commit()
    rid = add_repo(conn, 1)
    body = client.post("/api/interactions",
                       json={"repo_id": rid, "kind": "favorite", "active": True}).json()
    assert body == {"active": True, "sync": "pending"}
    assert conn.execute("SELECT count(*) c FROM interactions WHERE kind='favorite'"
                        ).fetchone()["c"] == 1  # 本地已提交不回滚


# ---------- 密钥指纹/换钥路径（final review A1） ----------
def test_disconnect_key_mismatch_502_keeps_ciphertext_and_rows(conn, client, login, monkeypatch):
    """断开撞上换钥：fail loud 502 + 中文指引，密文/同步行原样保留等恢复密钥。
    旧路径静默 token="" 后照清列——密文销毁 + 撤销跳过，GitHub 侧 token 彻底孤儿化。"""
    from app import security
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"k" * 32).decode())
    conn.execute("UPDATE users SET gh_token_enc=?, gh_star_authed_at=? WHERE id=?",
                 (security.seal_token("tok", str(login)), NOW, login))
    add_repo(conn, 1)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, updated_at)"
                 " VALUES (?, 1, 'starred', 'done', 1)", (login,))
    conn.commit()
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"j" * 32).decode())
    resp = client.delete("/api/me/gh-star-auth")
    assert resp.status_code == 502
    assert resp.json()["detail"] == "加密密钥不匹配，无法撤销 GitHub 授权；请恢复 TOKEN_ENC_KEY 后重试"
    row = conn.execute("SELECT * FROM users WHERE id=?", (login,)).fetchone()
    assert row["gh_token_enc"] != "" and row["gh_star_authed_at"] > 0
    assert conn.execute("SELECT count(*) c FROM star_syncs").fetchone()["c"] == 1


def test_interaction_key_mismatch_degrades_pending_without_wipe(conn, client, login, monkeypatch):
    """换钥撞上同步边界：sync 降级 pending（决策 5 本地成功），密文不得被销毁。"""
    from app import security
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"k" * 32).decode())
    conn.execute("UPDATE users SET gh_token_enc=? WHERE id=?",
                 (security.seal_token("tok", str(login)), login))
    conn.commit()
    rid = add_repo(conn, 1, owner="other")
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"j" * 32).decode())
    body = client.post("/api/interactions",
                       json={"repo_id": rid, "kind": "favorite", "active": True}).json()
    assert body == {"active": True, "sync": "pending"}
    row = conn.execute("SELECT * FROM users WHERE id=?", (login,)).fetchone()
    assert row["gh_token_enc"] != ""  # 密文保留，恢复 key 后可继续收敛/撤销
    assert conn.execute("SELECT count(*) c FROM interactions WHERE kind='favorite'"
                        ).fetchone()["c"] == 1


def test_token_plaintext_never_leaks_to_api_or_last_error(conn, client, login, monkeypatch):
    """安全覆盖缺口回归：密封明文 token 不得出现在任何 API 响应体、异常 detail、
    last_error 或落库序列化输出中。同步错误路径全走一遍后统一 grep。"""
    from app import security
    canary = "ghp_CANARY_plain_secret_9f2x"
    conn.execute("UPDATE users SET gh_token_enc=? WHERE id=?",
                 (security.seal_token(canary, str(login)), login))
    conn.commit()
    rid = add_repo(conn, 1, owner="other")
    outputs: list[str] = []

    def boom(_token, _full_name, **_kw):
        raise github.GitHubError("upstream boom", status=500)

    monkeypatch.setattr(github, "star_repo", boom)
    monkeypatch.setattr(github, "unstar_repo", boom)

    def hit(resp):
        outputs.append(resp.text)
        return resp

    hit(client.post("/api/interactions", json={"repo_id": rid, "kind": "favorite", "active": True}))
    hit(client.post("/api/interactions", json={"repo_id": rid, "kind": "favorite", "active": False}))
    user = conn.execute("SELECT * FROM users WHERE id=?", (login,)).fetchone()
    repo = conn.execute("SELECT * FROM repos WHERE id=?", (rid,)).fetchone()
    try:
        star_sync.sync_favorite_on(conn, user, repo)   # 异常面：detail/repr 也不得带明文
        star_sync.sync_favorite_off(conn, user, repo)
    except Exception as exc:
        outputs.append(repr(exc))
    for table in ("star_syncs", "users"):               # 断开清列前先抓落库序列化输出
        for row in conn.execute(f"SELECT * FROM {table}").fetchall():
            outputs.append(json.dumps(dict(row), ensure_ascii=False, default=str))
    hit(client.delete("/api/me/gh-star-auth"))
    hit(client.get("/api/me"))
    hit(client.get("/api/me/favorites"))
    assert outputs and all(canary not in o for o in outputs)
