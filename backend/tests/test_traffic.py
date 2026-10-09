"""访问埋点：ip_hash 口径、缓冲 flush、day_stats 口径（spec §2.2）。"""
import time

from app import config
from app import security
from app import traffic

NOW = int(time.time())


def _insert(conn, ts, method, path="/api/x", status=200, ip="1.2.3.4", user_id=None):
    conn.execute(
        "INSERT INTO access_events (ts, user_id, ip_hash, path, method, status_code)"
        " VALUES (?,?,?,?,?,?)",
        (ts, user_id, traffic.ip_hash(ip), path, method, status))
    conn.commit()


def test_ip_hash_stable_and_opaque():
    a = traffic.ip_hash("1.2.3.4")
    assert a == traffic.ip_hash("1.2.3.4")
    assert a != traffic.ip_hash("1.2.3.5")
    assert "1.2.3.4" not in a and len(a) == 32


def test_writer_flush_inserts_rows(conn):
    traffic.writer.reset()
    traffic.writer.record(ts=NOW, user_id=None, ip="9.9.9.9", path="/",
                          method="HIT", status_code=200)
    traffic.writer.record(ts=NOW, user_id=None, ip="9.9.9.9", path="/api/feed",
                          method="GET", status_code=200)
    assert conn.execute("SELECT COUNT(*) AS n FROM access_events").fetchone()["n"] == 0
    assert traffic.writer.flush(conn) == 2
    rows = conn.execute("SELECT * FROM access_events ORDER BY method").fetchall()
    assert rows[0]["method"] == "GET" and rows[1]["method"] == "HIT"
    assert rows[1]["ip_hash"] == traffic.ip_hash("9.9.9.9")


def test_writer_flush_updates_last_active_throttled(conn):
    from app.feed import auth
    traffic.writer.reset()
    uid = auth.upsert_user(conn, {"id": 7, "login": "u7", "avatar_url": ""})
    t0 = NOW
    traffic.writer.record(ts=t0, user_id=uid, ip="1.1.1.1", path="/api/feed",
                          method="GET", status_code=200)
    traffic.writer.flush(conn)
    assert conn.execute(
        "SELECT last_active_at FROM users WHERE id=?", (uid,)).fetchone()[0] == t0
    traffic.writer.record(ts=t0 + 10, user_id=uid, ip="1.1.1.1", path="/api/feed",
                          method="GET", status_code=200)
    traffic.writer.flush(conn)
    assert conn.execute(
        "SELECT last_active_at FROM users WHERE id=?", (uid,)).fetchone()[0] == t0
    traffic.writer.record(ts=t0 + 70, user_id=uid, ip="1.1.1.1", path="/api/feed",
                          method="GET", status_code=200)
    traffic.writer.flush(conn)
    assert conn.execute(
        "SELECT last_active_at FROM users WHERE id=?", (uid,)).fetchone()[0] == t0 + 70


def test_writer_flush_swallows_db_error():
    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError("db down")

        def executemany(self, *a, **k):
            raise RuntimeError("db down")

        def commit(self):
            raise RuntimeError("db down")

    traffic.writer.reset()
    traffic.writer.record(ts=NOW, user_id=None, ip="1.1.1.1", path="/",
                          method="HIT", status_code=200)
    before = traffic.writer.failures
    assert traffic.writer.flush(Boom()) == 0  # 不抛
    assert traffic.writer.failures == before + 1


def test_writer_record_swallows_all_errors():
    traffic.writer.reset()
    before = traffic.writer.failures
    # ip 非法类型触发 record 内异常路径：不抛、计数
    traffic.writer.record(ts=NOW, user_id=None, ip=None, path="/",
                          method="HIT", status_code=200)
    assert traffic.writer.failures == before + 1


def test_writer_buffer_capped(monkeypatch):
    traffic.writer.reset()
    monkeypatch.setattr(traffic, "ACCESS_MAX_BUFFER", 3)
    for _ in range(5):
        traffic.writer.record(ts=NOW, user_id=None, ip="1.1.1.1", path="/",
                              method="HIT", status_code=200)
    assert len(traffic.writer._buf) == 3
    assert traffic.writer.failures == 2


def test_day_stats_split_hit_and_api(conn):
    day = traffic.today_utc(NOW)
    start, _ = traffic.day_bounds_utc(day)
    _insert(conn, start + 10, "HIT", path="/search", ip="a")
    _insert(conn, start + 20, "HIT", path="/search", ip="a")
    _insert(conn, start + 30, "HIT", path="/repo/1", ip="b")
    _insert(conn, start + 40, "GET", path="/api/feed", status=200, user_id=1, ip="a")
    _insert(conn, start + 50, "POST", path="/api/comments", status=500, user_id=1, ip="a")
    s = traffic.day_stats(conn, day)
    assert s == {"date": day, "pv": 3, "uv": 2, "api_calls": 2, "errors": 1,
                 "active_users": 1, "new_users": 0}


def test_day_stats_counts_new_users(conn):
    from app.feed import auth
    day = traffic.today_utc(NOW)
    start, _ = traffic.day_bounds_utc(day)
    uid = auth.upsert_user(conn, {"id": 8, "login": "u8", "avatar_url": ""})
    conn.execute("UPDATE users SET created_at=? WHERE id=?", (start + 5, uid))
    conn.commit()
    assert traffic.day_stats(conn, day)["new_users"] == 1
    assert traffic.day_stats(conn, traffic.today_utc(start - 86400))["new_users"] == 0


def test_online_count_window(conn):
    _insert(conn, NOW - 30, "HIT", path="/", ip="a")
    _insert(conn, NOW - 200, "HIT", path="/", ip="b")
    _insert(conn, NOW - 400, "HIT", path="/", ip="c")
    assert traffic.online_count(conn, 5) == 2
    assert traffic.online_count(conn, 1) == 1


def test_online_window_minutes_bad_value_falls_back(conn):
    conn.execute("UPDATE app_config SET value='abc' WHERE key='online_window_minutes'")
    conn.commit()
    assert traffic.online_window_minutes(conn) == traffic.DEFAULT_ONLINE_WINDOW_MINUTES


def test_writer_single_flight_dispatch(monkeypatch, tmp_path):
    import threading as _threading

    from app.feed import db
    db_path = str(tmp_path / "access.db")
    boot = db.connect(db_path)
    db.init_db(boot)
    boot.close()

    started = _threading.Event()
    release = _threading.Event()
    calls = []

    def factory():
        calls.append(1)
        started.set()
        assert release.wait(timeout=10)
        return db.connect(db_path)

    traffic.writer.reset()
    traffic.writer.bind(factory)
    try:
        monkeypatch.setattr(traffic, "ACCESS_FLUSH_ROWS", 1)
        for _ in range(5):
            traffic.writer.record(ts=NOW, user_id=None, ip="1.1.1.1", path="/",
                                  method="HIT", status_code=200)
        assert started.wait(timeout=10)
        for _ in range(5):
            traffic.writer.record(ts=NOW, user_id=None, ip="1.1.1.1", path="/",
                                  method="HIT", status_code=200)
        assert len(calls) == 1
        assert traffic.writer._flush_scheduled is True
        release.set()
        conn = db.connect(db_path)
        try:
            n = 0
            deadline = time.time() + 10
            while time.time() < deadline:
                n = conn.execute("SELECT COUNT(*) AS n FROM access_events").fetchone()["n"]
                if n == 10:
                    break
                time.sleep(0.01)
            assert n == 10
        finally:
            conn.close()
        assert traffic.writer._flush_scheduled is False
        assert len(calls) == 1
        assert traffic.writer.failures == 0
    finally:
        release.set()
        traffic.writer.bind(None)


def test_writer_last_active_max_no_regress(conn):
    from app.feed import auth
    traffic.writer.reset()
    uid = auth.upsert_user(conn, {"id": 11, "login": "u11", "avatar_url": ""})
    t_new, t_old = 2_000_000, 1_000_000
    traffic.writer.record(ts=t_new, user_id=uid, ip="1.1.1.1", path="/api/feed",
                          method="GET", status_code=200)
    traffic.writer.flush(conn)
    assert conn.execute(
        "SELECT last_active_at FROM users WHERE id=?", (uid,)).fetchone()[0] == t_new
    traffic.writer.reset()
    traffic.writer.record(ts=t_old, user_id=uid, ip="1.1.1.1", path="/api/feed",
                          method="GET", status_code=200)
    traffic.writer.flush(conn)
    assert conn.execute(
        "SELECT last_active_at FROM users WHERE id=?", (uid,)).fetchone()[0] == t_new
    assert traffic.writer.failures == 0


def test_writer_spawn_failure_releases_single_flight(monkeypatch):
    import types

    traffic.writer.reset()
    before = traffic.writer.failures
    spawns = []

    class _BoomThread:
        def __init__(self, *a, **k):
            raise RuntimeError("can't start new thread")

    class _CountThread:
        def __init__(self, target=None, daemon=None):
            self.target = target

        def start(self):
            spawns.append(self.target)

    monkeypatch.setattr(traffic, "ACCESS_FLUSH_ROWS", 1)
    monkeypatch.setattr(traffic, "threading", types.SimpleNamespace(Thread=_BoomThread))
    traffic.writer.record(ts=NOW, user_id=None, ip="1.1.1.1", path="/",
                          method="HIT", status_code=200)
    assert traffic.writer.failures == before + 1
    assert traffic.writer._flush_scheduled is False

    monkeypatch.setattr(traffic, "threading", types.SimpleNamespace(Thread=_CountThread))
    traffic.writer.record(ts=NOW, user_id=None, ip="1.1.1.1", path="/",
                          method="HIT", status_code=200)
    assert len(spawns) == 1
    assert traffic.writer._flush_scheduled is True
    traffic.writer.record(ts=NOW, user_id=None, ip="1.1.1.1", path="/",
                          method="HIT", status_code=200)
    assert len(spawns) == 1


# ---------- 中间件埋点（二期 §2.4） ----------

def test_middleware_records_api_row(conn, client):
    traffic.writer.reset()
    client.get("/api/health")
    traffic.writer.flush(conn)
    row = conn.execute("SELECT * FROM access_events").fetchone()
    assert row["path"] == "/api/health" and row["method"] == "GET"
    assert row["status_code"] == 200 and row["user_id"] is None


def test_middleware_records_4xx(conn, client):
    traffic.writer.reset()
    client.get("/api/no-such-route")
    traffic.writer.flush(conn)
    row = conn.execute("SELECT * FROM access_events").fetchone()
    assert row["status_code"] == 404


def test_middleware_records_user_id_for_logged_in(conn, client, admin):
    traffic.writer.reset()
    client.get("/api/health")
    traffic.writer.flush(conn)
    row = conn.execute("SELECT * FROM access_events").fetchone()
    assert row["user_id"] == admin


def test_middleware_records_true_5xx_then_reraises(conn, client, monkeypatch):
    """真 5xx（异常逃出 call_next）落 status_code=500 行后照常上抛（口径含 5xx）。"""
    import pytest

    from app.security import SecurityMiddleware

    traffic.writer.reset()

    async def boom(self, request, call_next):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(SecurityMiddleware, "_respond", boom)
    with pytest.raises(RuntimeError):
        client.get("/api/health")
    traffic.writer.flush(conn)
    row = conn.execute("SELECT * FROM access_events").fetchone()
    assert row["path"] == "/api/health" and row["status_code"] == 500


def test_middleware_skips_429_rows(conn, client, monkeypatch):
    traffic.writer.reset()
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(config, "RATE_LIMITS", {**config.RATE_LIMITS, "default": 1})
    security._limiter.reset()
    try:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health").status_code == 429
        traffic.writer.flush(conn)
        rows = conn.execute("SELECT * FROM access_events").fetchall()
        assert len(rows) == 1 and rows[0]["status_code"] == 200
    finally:
        security._limiter.reset()


def test_middleware_skips_hit_post_but_records_hit_get(conn, client):
    traffic.writer.reset()
    client.post(security.HIT_PATH)
    client.get(security.HIT_PATH)
    traffic.writer.flush(conn)
    rows = conn.execute("SELECT * FROM access_events").fetchall()
    assert len(rows) == 1
    assert rows[0]["method"] == "GET" and rows[0]["path"] == security.HIT_PATH
