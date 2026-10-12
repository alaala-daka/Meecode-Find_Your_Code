"""管理台登录日志（spec 2026-10-10 三期 §2.3）。"""
from app import traffic


def _seed(conn, *, login="alice", event="login", ok=1, ts=1_700_000_000, ip="9.9.9.9"):
    conn.execute(
        "INSERT INTO login_events (ts, user_id, login, ip_hash, event, ok) VALUES (?,?,?,?,?,?)",
        (ts, 7, login, traffic.login_ip_hash(ip), event, ok))
    conn.commit()


def test_匿名401(client):
    assert client.get("/api/admin/login-events").status_code == 401


def test_列表倒序与过滤_and(conn, client, admin):
    _seed(conn, login="alice", ok=1, ts=1_700_000_000)
    _seed(conn, login="bob", ok=0, ts=1_700_000_100)
    _seed(conn, login="ab%cd", ok=1, ts=1_700_000_200)

    r = client.get("/api/admin/login-events").json()
    assert r["total"] == 3
    assert [x["login"] for x in r["data"]] == ["ab%cd", "bob", "alice"]

    r = client.get("/api/admin/login-events", params={"ok": "0"}).json()
    assert r["total"] == 1 and r["data"][0]["login"] == "bob"

    r = client.get("/api/admin/login-events", params={"q": "ali"}).json()
    assert r["total"] == 1

    r = client.get("/api/admin/login-events", params={"q": "%"}).json()
    assert r["total"] == 1 and r["data"][0]["login"] == "ab%cd"

    r = client.get("/api/admin/login-events",
                   params={"q": "alice", "ok": "0"}).json()
    assert r["total"] == 0


def test_时间区间与422(conn, client, admin):
    _seed(conn, ts=1_700_000_000)
    r = client.get("/api/admin/login-events",
                   params={"from": "2023-11-14", "to": "2023-11-14"}).json()
    assert r["total"] == 1
    r = client.get("/api/admin/login-events",
                   params={"from": "2023-11-15", "to": "2023-11-16"}).json()
    assert r["total"] == 0
    assert client.get("/api/admin/login-events",
                      params={"from": "2023-11-20", "to": "2023-11-14"}).status_code == 422
    assert client.get("/api/admin/login-events",
                      params={"from": "bad"}).status_code == 422
    assert client.get("/api/admin/login-events",
                      params={"to": "bad"}).status_code == 422
    assert client.get("/api/admin/login-events",
                      params={"ok": "x"}).status_code == 422
    assert client.get("/api/admin/login-events",
                      params={"event": "nope"}).status_code == 422


def test_from或to单边可用(conn, client, admin):
    _seed(conn, login="old", ts=1_699_920_100)  # 2023-11-14
    _seed(conn, login="new", ts=1_700_006_500)  # 2023-11-15
    r = client.get("/api/admin/login-events",
                   params={"from": "2023-11-15"}).json()
    assert r["total"] == 1 and r["data"][0]["login"] == "new"
    r = client.get("/api/admin/login-events",
                   params={"to": "2023-11-14"}).json()
    assert r["total"] == 1 and r["data"][0]["login"] == "old"


def test_ip反查精确匹配并写审计(conn, client, admin):
    _seed(conn, ip="9.9.9.9")
    _seed(conn, ip="8.8.8.8")
    r = client.get("/api/admin/login-events", params={"ip": "9.9.9.9"}).json()
    assert r["total"] == 1
    assert client.get("/api/admin/login-events",
                      params={"ip": "garbage"}).status_code == 422
    row = conn.execute(
        "SELECT * FROM audit_logs WHERE action='login_events.ip_lookup'").fetchone()
    assert row is not None and row["admin_login"] == "boss"


def test_ip_hash截断12位(client, conn, admin):
    _seed(conn)
    r = client.get("/api/admin/login-events").json()
    assert len(r["data"][0]["ip_hash"]) == 12


def test_分页与上界(client, conn, admin):
    for i in range(5):
        _seed(conn, login=f"u{i}")
    r = client.get("/api/admin/login-events",
                   params={"page": 2, "page_size": 2}).json()
    assert len(r["data"]) == 2 and r["total"] == 5
    assert client.get("/api/admin/login-events",
                      params={"page_size": 101}).status_code == 422
