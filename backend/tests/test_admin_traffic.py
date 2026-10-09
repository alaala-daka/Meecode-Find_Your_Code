"""流量/在线/接口统计 API（Task 7）。"""
import time

from app import traffic

NOW = int(time.time())


def _insert(conn, ts, method="GET", path="/api/feed", status=200, ip="1.1.1.1", user_id=None):
    conn.execute(
        "INSERT INTO access_events (ts, user_id, ip_hash, path, method, status_code)"
        " VALUES (?,?,?,?,?,?)",
        (ts, user_id, traffic.ip_hash(ip), path, method, status))
    conn.commit()


def test_traffic_7d_shape_and_today_live(conn, client, admin):
    today = traffic.today_utc(NOW)
    start, _ = traffic.day_bounds_utc(today)
    _insert(conn, start + 1, method="HIT", path="/", ip="a")
    _insert(conn, start + 2, method="GET", path="/api/feed", ip="a")
    body = client.get("/api/admin/traffic?range=7d").json()
    assert body["range"] == "7d" and len(body["days"]) == 7
    last = body["days"][-1]
    assert last["date"] == today
    assert last["pv"] == 1 and last["uv"] == 1 and last["api_calls"] == 1
    assert all(set(d) == {"date", "pv", "uv", "new_users", "active_users",
                          "api_calls", "errors"} for d in body["days"])


def test_traffic_reads_traffic_daily_for_completed_days(conn, client, admin):
    yesterday = traffic.today_utc(NOW - 86400)
    conn.execute(
        "INSERT INTO traffic_daily (date, pv, uv, new_users, active_users, api_calls, errors)"
        " VALUES (?,?,?,?,?,?,?)", (yesterday, 9, 4, 1, 2, 3, 0))
    conn.commit()
    body = client.get("/api/admin/traffic?range=7d").json()
    row = next(d for d in body["days"] if d["date"] == yesterday)
    assert row["pv"] == 9 and row["uv"] == 4


def test_traffic_year_endpoint(conn, client, admin):
    year = time.gmtime(NOW).tm_year
    body = client.get(f"/api/admin/traffic?range=year={year}").json()
    assert body["range"] == f"year={year}"
    assert len(body["months"]) == 12 and "summary" in body


def test_traffic_invalid_range_422(client, admin):
    assert client.get("/api/admin/traffic?range=99d").status_code == 422
    assert client.get("/api/admin/traffic?range=year=1900").status_code == 422


def test_traffic_yearly_endpoint(conn, client, admin):
    conn.execute("INSERT INTO traffic_daily (date, pv, uv) VALUES ('2025-06-01', 5, 2)")
    conn.commit()
    body = client.get("/api/admin/traffic/yearly").json()
    years = {y["year"]: y for y in body["years"]}
    assert years[2025]["pv"] == 5 and time.gmtime(NOW).tm_year in years


def test_online_endpoint_window_from_app_config(conn, client, admin):
    _insert(conn, NOW - 30, method="HIT", path="/", ip="a")
    _insert(conn, NOW - 120, method="HIT", path="/", ip="b")
    body = client.get("/api/admin/online").json()
    assert body == {"online": 2, "window_minutes": 5}
    conn.execute("UPDATE app_config SET value='1' WHERE key='online_window_minutes'")
    conn.commit()
    body = client.get("/api/admin/online").json()
    assert body == {"online": 1, "window_minutes": 1}


def test_api_stats_bucket_aggregation(conn, client, admin):
    _insert(conn, NOW - 100, method="GET", path="/api/feed", status=200)
    _insert(conn, NOW - 90, method="GET", path="/api/search", status=500)
    _insert(conn, NOW - 80, method="POST", path="/api/comments", status=200)
    _insert(conn, NOW - 70, method="HIT", path="/", status=200)  # 不计入
    body = client.get("/api/admin/api-stats?range=7d").json()
    buckets = {b["route_key"]: b for b in body["buckets"]}
    assert buckets["browse"]["calls"] == 2 and buckets["browse"]["errors"] == 1
    assert buckets["browse"]["error_rate"] == 0.5
    assert buckets["ugc"]["calls"] == 1 and buckets["ugc"]["errors"] == 0
    assert "default" in buckets and buckets["default"]["calls"] == 0


def test_traffic_endpoints_anonymous_401(conn, client):
    """鉴权边界守卫（安全复审）：匿名不得触达任何流量端点。"""
    for url in ("/api/admin/traffic?range=7d", "/api/admin/traffic/yearly",
                "/api/admin/online", "/api/admin/api-stats?range=7d"):
        assert client.get(url).status_code == 401, url
