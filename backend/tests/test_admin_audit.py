"""审计写入器：落库正确性 + 失败不抛。概览计数 + 审计日志查询。"""
import json
import logging
import time

from app.admin import audit
from app.feed import auth

NOW = int(time.time())


def test_record_audit_persists_row(conn):
    audit.record_audit(conn, admin_login="boss", action="user.ban", target_type="user",
                       target_id=7, detail={"mute_comment": True})
    row = conn.execute("SELECT * FROM audit_logs").fetchone()
    assert row["admin_login"] == "boss"
    assert row["action"] == "user.ban"
    assert row["target_id"] == "7"
    assert json.loads(row["detail"]) == {"mute_comment": True}


def test_record_audit_swallows_db_error(conn, caplog):
    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError("db down")

    with caplog.at_level(logging.ERROR):
        audit.record_audit(Boom(), admin_login="boss", action="user.ban",
                           target_type="user", target_id=1)  # 不抛
    assert any("audit" in r.message.lower() or "db down" in r.message.lower()
               or "audit" in r.name.lower() for r in caplog.records)


def _mk_user(conn, gh_id, login, created_at=None):
    uid = auth.upsert_user(conn, {"id": gh_id, "login": login, "avatar_url": "https://a/x"})
    if created_at is not None:
        conn.execute("UPDATE users SET created_at=? WHERE id=?", (created_at, uid))
        conn.commit()
    return uid


def _mk_repo(conn, gid, status):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, language, source, status,"
        " quality, published_at, tagline_zh, screened)"
        " VALUES (?,?, 'demo','Python','submitted',?,3,?,'卖点',1)", (gid, f"demo/p{gid}", status, NOW))
    conn.commit()
    return conn.execute("SELECT id FROM repos WHERE github_id=?", (gid,)).fetchone()["id"]


def _mk_comment(conn, status, rid, uid):
    cid = conn.execute(
        "INSERT INTO comments (repo_id, user_id, parent_id, content, status, screened)"
        " VALUES (?,?,NULL,'内容',?,1)", (rid, uid, status)).lastrowid
    conn.commit()
    return cid


def test_overview_counts(conn, client, admin):
    uid = _mk_user(conn, 10, "alice")
    rid = _mk_repo(conn, 50, "published")
    _mk_comment(conn, "pending", rid, uid)
    r = client.get("/api/admin/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["total_users"] >= 1 and body["pending_comments"] >= 0


def test_audit_logs_query_filters(conn, client, admin):
    audit.record_audit(conn, admin_login="boss", action="user.ban", target_type="user",
                       target_id=1, detail={"x": 1})
    r = client.get("/api/admin/audit-logs?action=user.ban")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["data"][0]["detail"] == {"x": 1}


def test_overview_shape_includes_phase2_fields(conn, client, admin):
    body = client.get("/api/admin/overview").json()
    assert set(body) == {"total_users", "new_users_today", "total_repos",
                         "published_repos", "delisted_repos", "pending_comments",
                         "online", "today_pv", "year_pv"}
    assert all(type(v) is int for v in body.values())


def test_overview_counts_breakdown(conn, client, admin):
    uid = _mk_user(conn, 10, "old", created_at=NOW - 3 * 86400)
    _mk_user(conn, 11, "fresh")
    r_pub = _mk_repo(conn, 100, "published")
    _mk_repo(conn, 101, "delisted")
    _mk_repo(conn, 102, "pending_claim")
    _mk_comment(conn, "pending", r_pub, uid)
    _mk_comment(conn, "visible", r_pub, uid)
    body = client.get("/api/admin/overview").json()
    assert body == {"total_users": 3, "new_users_today": 2, "total_repos": 3,
                    "published_repos": 1, "delisted_repos": 1, "pending_comments": 1,
                    "online": 0, "today_pv": 0, "year_pv": 0}


def test_audit_logs_row_shape_and_ts_desc(conn, client, admin):
    audit.record_audit(conn, admin_login="boss", action="user.ban", target_type="user",
                       target_id=1, detail={"x": 1})
    audit.record_audit(conn, admin_login="boss", action="user.unban", target_type="user",
                       target_id=2)
    rows = client.get("/api/admin/audit-logs").json()["data"]
    assert set(rows[0]) == {"id", "ts", "admin_login", "action", "target_type",
                            "target_id", "detail"}
    assert rows[0]["target_id"] == "2" and rows[0]["detail"] is None
    assert rows[1]["target_id"] == "1" and rows[1]["detail"] == {"x": 1}


def test_audit_logs_corrupt_detail_returns_raw(conn, client, admin):
    conn.execute(
        "INSERT INTO audit_logs (ts, admin_login, action, target_type, target_id, detail)"
        " VALUES ('2026-10-05T10:00:00Z','boss','user.ban','user','1','{broken json')")
    conn.commit()
    body = client.get("/api/admin/audit-logs").json()
    assert body["total"] == 1
    assert body["data"][0]["detail"] == "{broken json"


def test_audit_logs_admin_filter_exact(conn, client, admin):
    audit.record_audit(conn, admin_login="boss", action="user.ban", target_type="user", target_id=1)
    audit.record_audit(conn, admin_login="alice", action="user.ban", target_type="user", target_id=2)
    body = client.get("/api/admin/audit-logs?admin=boss").json()
    assert body["total"] == 1 and body["data"][0]["admin_login"] == "boss"
    assert client.get("/api/admin/audit-logs?admin=BOSS").json()["total"] == 0


def test_audit_logs_pagination(conn, client, admin):
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        conn.execute(
            "INSERT INTO audit_logs (ts, admin_login, action, target_type, target_id, detail)"
            " VALUES (?,?,?, 'user','1',NULL)", (f"{day}T00:00:00Z", "boss", "user.ban"))
    conn.commit()
    body = client.get("/api/admin/audit-logs?page=1&page_size=2").json()
    assert body["total"] == 3
    assert [r["ts"] for r in body["data"]] == ["2026-10-03T00:00:00Z", "2026-10-02T00:00:00Z"]
    body = client.get("/api/admin/audit-logs?page=2&page_size=2").json()
    assert [r["ts"] for r in body["data"]] == ["2026-10-01T00:00:00Z"]
    assert client.get("/api/admin/audit-logs?page=0").status_code == 422


def test_overview_and_audit_logs_require_admin(conn, client):
    assert client.get("/api/admin/overview").status_code == 401
    assert client.get("/api/admin/audit-logs").status_code == 401


def test_overview_observation_fields_from_access_events(conn, client, admin):
    from app import traffic as t
    ts = int(time.time())
    t.writer.reset()
    t.writer.record(ts=ts, user_id=None, ip="1.1.1.1", path="/",
                    method="HIT", status_code=200)
    t.writer.flush(conn)
    body = client.get("/api/admin/overview").json()
    assert body["today_pv"] == 1 and body["year_pv"] == 1 and body["online"] == 1
