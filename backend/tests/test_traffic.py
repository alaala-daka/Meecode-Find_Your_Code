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


def test_writer_timer_flush_dispatch(tmp_path):
    """定时触发：不足 ACCESS_FLUSH_ROWS 时，ts 超出 _last_flush+ACCESS_FLUSH_SECONDS 也派发守护 flush。"""
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
        ts = int(traffic.writer._last_flush) + int(traffic.ACCESS_FLUSH_SECONDS) + 10
        traffic.writer.record(ts=ts, user_id=None, ip="1.1.1.1", path="/",
                              method="HIT", status_code=200)
        assert started.wait(timeout=10)  # 1 行 < ACCESS_FLUSH_ROWS=200 也须定时派发
        assert traffic.writer._flush_scheduled is True
        release.set()
        conn = db.connect(db_path)
        try:
            n = 0
            deadline = time.time() + 10
            while time.time() < deadline:
                n = conn.execute("SELECT COUNT(*) AS n FROM access_events").fetchone()["n"]
                if n == 1:
                    break
                time.sleep(0.01)
            assert n == 1
        finally:
            conn.close()
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


# ---------- HIT beacon 端点（二期 §2.3） ----------

def test_hit_records_hit_row_anonymous(conn, client):
    traffic.writer.reset()
    r = client.post("/api/hit", json={"path": "/" + "a" * 3000})
    assert r.status_code == 204 and r.text == ""
    traffic.writer.flush(conn)
    row = conn.execute("SELECT * FROM access_events").fetchone()
    assert row["method"] == "HIT" and row["user_id"] is None
    assert len(row["path"]) == 200 and row["path"].startswith("/aaa")


def test_hit_accepts_text_plain_beacon_body(conn, client):
    """sendBeacon 字符符 body = text/plain（安全复审 P0）：必须 204 且落行。"""
    traffic.writer.reset()
    r = client.post("/api/hit", content=b'{"path":"/search"}',
                    headers={"Content-Type": "text/plain;charset=UTF-8"})
    assert r.status_code == 204
    traffic.writer.flush(conn)
    row = conn.execute("SELECT * FROM access_events").fetchone()
    assert row["method"] == "HIT" and row["path"] == "/search"


def test_hit_normalizes_path_strips_query_and_controls(conn, client):
    traffic.writer.reset()
    client.post("/api/hit", json={"path": "/x?token=secret#frag\x01"})
    client.post("/api/hit", json={"path": "no-slash"})
    client.post("/api/hit", json={"path": ""})
    traffic.writer.flush(conn)
    paths = [r["path"] for r in conn.execute(
        "SELECT path FROM access_events ORDER BY id")]
    assert paths == ["/x", "/no-slash", "/"]


def test_hit_invalid_body_silent_204(conn, client):
    traffic.writer.reset()
    assert client.post("/api/hit", content=b"not-json",
                       headers={"Content-Type": "text/plain"}).status_code == 204
    assert client.post("/api/hit", json={"nope": 1}).status_code == 204
    traffic.writer.flush(conn)
    assert conn.execute("SELECT COUNT(*) AS n FROM access_events").fetchone()["n"] == 0


def test_hit_records_user_id_when_logged_in(conn, client, admin):
    traffic.writer.reset()
    client.post("/api/hit", json={"path": "/search"})
    traffic.writer.flush(conn)
    row = conn.execute("SELECT * FROM access_events").fetchone()
    assert row["method"] == "HIT" and row["user_id"] == admin
    assert row["path"] == "/search"


def test_middleware_skips_hit_endpoint_itself(conn, client):
    traffic.writer.reset()
    client.post("/api/hit", json={"path": "/x"})
    traffic.writer.flush(conn)
    rows = conn.execute("SELECT * FROM access_events").fetchall()
    assert [r["method"] for r in rows] == ["HIT"]  # 无 POST /api/hit 的 API 行


def test_aggregate_yesterday_writes_traffic_daily(conn):
    from app.admin.jobs import traffic_agg

    yesterday = time.strftime("%Y-%m-%d", time.gmtime(NOW - 86400))
    start, _ = traffic.day_bounds_utc(yesterday)
    _insert(conn, start + 1, method="HIT", path="/", ip="a")
    _insert(conn, start + 2, method="HIT", path="/search", ip="a")
    _insert(conn, start + 3, method="HIT", path="/repo/1", ip="b")
    _insert(conn, start + 4, method="GET", path="/api/feed", status=200)
    _insert(conn, start + 5, method="POST", path="/api/comments", status=503)
    _insert(conn, start + 6, method="GET", path="/api/feed", status=404)
    out = traffic_agg.aggregate_yesterday(conn, now=NOW)
    assert out["pv"] == 3 and out["uv"] == 2
    assert out["api_calls"] == 3 and out["errors"] == 1
    row = conn.execute("SELECT * FROM traffic_daily WHERE date=?", (yesterday,)).fetchone()
    assert dict(row) == {"date": yesterday, "pv": 3, "uv": 2, "new_users": 0,
                         "active_users": 0, "api_calls": 3, "errors": 1}


def test_aggregate_yesterday_prunes_old_rows(conn):
    from app.admin.jobs import traffic_agg

    _insert(conn, NOW - 31 * 86400, method="HIT", path="/")
    _insert(conn, NOW - 86400 + 10, method="HIT", path="/")
    out = traffic_agg.aggregate_yesterday(conn, now=NOW)
    assert out["pruned"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM access_events").fetchone()["n"] == 1


def test_aggregate_yesterday_idempotent(conn):
    from app.admin.jobs import traffic_agg

    _insert(conn, NOW - 86400 + 1, method="HIT", path="/")
    traffic_agg.aggregate_yesterday(conn, now=NOW)
    traffic_agg.aggregate_yesterday(conn, now=NOW)
    assert conn.execute("SELECT COUNT(*) AS n FROM traffic_daily").fetchone()["n"] == 1


# ---------- 流量查询助手（Task 7） ----------

def test_month_series_and_year_view(conn):
    year = time.gmtime(NOW).tm_year
    today = traffic.today_utc(NOW)
    start, _ = traffic.day_bounds_utc(today)
    for i in range(3):
        _insert(conn, start + i + 1, "HIT", path="/", ip="a")
    months = traffic.month_series(conn, 12, NOW)
    assert len(months) == 12 and months[-1]["month"] == today[:7]
    assert months[-1]["pv"] == 3
    view = traffic.year_view(conn, year, NOW)
    assert len(view["months"]) == 12
    s = view["summary"]
    assert s["year"] == year and s["year_pv"] == 3
    assert set(s) == {"year", "year_pv", "daily_pv_avg", "daily_uv_avg",
                      "new_users_year", "peak_day"}
    assert s["peak_day"] == {"date": today, "pv": 3}


def test_year_view_prefers_traffic_daily(conn):
    import calendar
    now = calendar.timegm((time.gmtime(NOW).tm_year, 6, 15, 12, 0, 0))
    yesterday = traffic.today_utc(now - 86400)  # 同年 6/14
    conn.execute(
        "INSERT INTO traffic_daily (date, pv, uv) VALUES (?,?,?)",
        (yesterday, 9, 4))
    conn.commit()
    view = traffic.year_view(conn, int(yesterday[:4]), now)
    month = next(m for m in view["months"] if m["month"] == yesterday[:7])
    assert month["pv"] == 9


def test_yearly_lists_years(conn):
    conn.execute("INSERT INTO traffic_daily (date, pv, uv) VALUES ('2025-06-01', 5, 2)")
    conn.commit()
    years = {y["year"]: y for y in traffic.yearly(conn, NOW)}
    assert years[2025]["pv"] == 5
    assert time.gmtime(NOW).tm_year in years


def test_year_pv_fast_path(conn):
    import calendar
    now = calendar.timegm((time.gmtime(NOW).tm_year, 6, 15, 12, 0, 0))
    seed = traffic.today_utc(now - 3 * 86400)  # 同年 6/12
    conn.execute("INSERT INTO traffic_daily (date, pv, uv) VALUES (?,?,?)",
                 (seed, 9, 2))
    conn.commit()
    assert traffic.year_pv(conn, int(seed[:4]), now) == 9
    today = traffic.today_utc(now)
    start, _ = traffic.day_bounds_utc(today)
    _insert(conn, start + 1, "HIT", path="/", ip="a")
    assert traffic.year_pv(conn, int(seed[:4]), now) == 10  # traffic_daily + 今日现算
    assert traffic.year_pv(conn, int(seed[:4]) - 1, now) == 0


def test_year_pv_backfills_missing_days_within_retention(conn):
    import calendar
    now = calendar.timegm((time.gmtime(NOW).tm_year, 12, 20, 12, 0, 0))
    year = time.gmtime(now).tm_year
    done = traffic.today_utc(now - 10 * 86400)  # 同年 12/10，已完成聚合
    gap = traffic.today_utc(now - 5 * 86400)    # 同年 12/15，缺失日仅剩原始行
    conn.execute("INSERT INTO traffic_daily (date, pv, uv) VALUES (?,?,?)", (done, 5, 2))
    conn.commit()
    start, _ = traffic.day_bounds_utc(gap)
    for i in range(3):
        _insert(conn, start + i + 1, "HIT", path="/", ip="a")
    assert traffic.year_pv(conn, year, now) == 5 + 3  # + 今日 live 0


def test_year_pv_agrees_with_year_view(conn):
    import calendar
    now = calendar.timegm((time.gmtime(NOW).tm_year, 12, 20, 12, 0, 0))
    year = time.gmtime(now).tm_year
    done = traffic.today_utc(now - 10 * 86400)
    gap = traffic.today_utc(now - 5 * 86400)
    conn.execute("INSERT INTO traffic_daily (date, pv, uv) VALUES (?,?,?)", (done, 5, 2))
    conn.commit()
    start, _ = traffic.day_bounds_utc(gap)
    for i in range(3):
        _insert(conn, start + i + 1, "HIT", path="/", ip="a")
    assert (traffic.year_pv(conn, year, now)
            == traffic.year_view(conn, year, now)["summary"]["year_pv"])
