"""管理台全局搜索（spec 2026-10-10 三期 §2.5）。"""
from app.feed import auth


def _mk_user(conn, login, bio=""):
    return auth.upsert_user(conn, {"id": hash(login) % 10**6, "login": login,
                                   "avatar_url": "https://a/x", "bio": bio})


def _mk_repo(conn, name, tagline_zh="", intro_zh=""):
    conn.execute(
        "INSERT OR IGNORE INTO repos (github_id, full_name, owner_login, language, stars, source,"
        " status, tagline_zh, intro_zh) VALUES (?,?,?,?,?,?,?,?,?)",
        (abs(hash(name)) % 10**6, name, "o", "py", 1, "submitted", "published",
         tagline_zh, intro_zh))
    conn.commit()
    return conn.execute("SELECT id FROM repos WHERE full_name=?", (name,)).fetchone()["id"]


def _mk_comment(conn, content, status="visible"):
    uid = _mk_user(conn, "c-user")
    rid = _mk_repo(conn, "o/r-c")
    conn.execute(
        "INSERT INTO comments (repo_id, user_id, content, status, created_at)"
        " VALUES (?,?,?,?,?)",
        (rid, uid, content, status, 1))
    conn.commit()


def test_q长度422(client, admin):
    assert client.get("/api/admin/search", params={"q": "a"}).status_code == 422
    assert client.get("/api/admin/search", params={"q": "x" * 51}).status_code == 422
    assert client.get("/api/admin/search", params={"q": "  "}).status_code == 422


def test_三组命中与字段(conn, client, admin):
    _mk_user(conn, "alice-dev", bio="前端工程师")
    _mk_repo(conn, "o/awesome", tagline_zh="好用的工具", intro_zh="intro")
    _mk_comment(conn, "这是一条测试评论")
    _mk_comment(conn, "已删除的", status="deleted")
    _mk_comment(conn, "被隐藏的", status="hidden")

    r = client.get("/api/admin/search", params={"q": "alice"}).json()
    assert r["users"]["count"] == 1
    assert r["users"]["items"][0]["login"] == "alice-dev"
    assert set(r["users"]["items"][0]) == {"id", "login", "bio"}

    r = client.get("/api/admin/search", params={"q": "好用"}).json()
    assert r["repos"]["count"] == 1
    assert r["repos"]["items"][0]["title"] == "好用的工具"

    r = client.get("/api/admin/search", params={"q": "测试评论"}).json()
    assert r["comments"]["count"] == 1
    item = r["comments"]["items"][0]
    assert item["body"] == "这是一条测试评论" and item["hidden"] is False

    r = client.get("/api/admin/search", params={"q": "被隐藏"}).json()
    assert r["comments"]["count"] == 1 and r["comments"]["items"][0]["hidden"] is True

    r = client.get("/api/admin/search", params={"q": "已删除"}).json()
    assert r["comments"]["count"] == 0


def test_短词回退LIKE且通配符转义(conn, client, admin):
    _mk_repo(conn, "o/AI-tool")
    _mk_repo(conn, "o/pct%name")
    _mk_user(conn, "ab%cd")
    _mk_comment(conn, "100%通过")
    r = client.get("/api/admin/search", params={"q": "AI"}).json()
    assert r["repos"]["count"] == 1
    r = client.get("/api/admin/search", params={"q": "t%"}).json()
    assert r["users"]["count"] == 0
    assert r["repos"]["count"] == 1 and r["repos"]["items"][0]["name"] == "o/pct%name"
    assert r["comments"]["count"] == 0
    r = client.get("/api/admin/search", params={"q": "0%"}).json()
    assert r["comments"]["count"] == 1 and r["comments"]["items"][0]["body"] == "100%通过"
    assert r["users"]["count"] == 0 and r["repos"]["count"] == 0


def test_三字符起走FTS分支命中(conn, client, admin):
    _mk_repo(conn, "o/awesome-tool", tagline_zh="好用的工具")
    r = client.get("/api/admin/search", params={"q": "awesome"}).json()
    assert r["repos"]["count"] == 1
    assert r["repos"]["items"][0]["name"] == "o/awesome-tool"


def test_count封顶1001(conn, client, admin):
    conn.executemany(
        "INSERT OR IGNORE INTO users (github_id, login, avatar_url) VALUES (?,?,?)",
        [(i, f"cap{i}", "https://a/x") for i in range(1005)])
    conn.commit()
    r = client.get("/api/admin/search", params={"q": "cap"}).json()
    assert r["users"]["count"] == 1001
    assert len(r["users"]["items"]) == 5
