"""管理台 LLM 用量统计 API（spec 2026-10-10 三期 §4.3）。"""
import time


def _seed(conn, *, ts, route="roots", repo_id=None, model="m1", p=0, c=0, ok=1, lat=0):
    conn.execute(
        "INSERT INTO llm_usage (ts, route, repo_id, model, prompt_tokens,"
        " completion_tokens, ok, latency_ms) VALUES (?,?,?,?,?,?,?,?)",
        (ts, route, repo_id, model, p, c, ok, lat))
    conn.commit()


def test_形状锁三键与补零(client, conn, admin):
    now = int(time.time())
    _seed(conn, ts=now, p=2, c=3)
    body = client.get("/api/admin/llm/stats").json()
    assert set(body) == {"daily", "models", "repos_top"}
    assert len(body["daily"]) == 7  # 缺省近 7 个 UTC 日
    assert body["daily"][-1]["calls"] == 1  # 今日行
    assert sum(d["calls"] for d in body["daily"]) == 1
    assert body["models"] == [{"model": "m1", "calls": 1, "tokens": 5}]


def test_from_to闭区间与三组聚合(client, conn, admin):
    day = 86400
    base = int(time.time()) // day * day - 2 * day
    d0 = time.strftime("%Y-%m-%d", time.gmtime(base))
    d1 = time.strftime("%Y-%m-%d", time.gmtime(base + day))
    _seed(conn, ts=base + 100, repo_id=7, p=1, c=1)
    _seed(conn, ts=base + day + 100, model="m2", p=2, c=2, ok=0, lat=50)
    conn.execute(
        "INSERT INTO repos (id, github_id, full_name, owner_login, source, status)"
        " VALUES (7, 7, 'a/b', 'a', 'submitted', 'published')")
    conn.commit()
    body = client.get("/api/admin/llm/stats", params={"from": d0, "to": d1}).json()
    assert [d["date"] for d in body["daily"]] == [d0, d1]
    assert body["daily"][1]["errors"] == 1
    assert body["repos_top"] == [{"repo_id": 7, "name": "a/b", "calls": 1, "tokens": 2}]
    assert {m["model"] for m in body["models"]} == {"m1", "m2"}


def test_参数校验422(client, conn, admin):
    ok_params = [
        {"from": "2026-10-13"},                                   # 只传 from
        {"to": "2026-10-13"},                                     # 只传 to
        {"from": "2026-10-14", "to": "2026-10-13"},               # from > to
        {"from": "2026-01-01", "to": "2026-10-13"},               # 跨度 > 92 天
        {"from": "2026/10/01", "to": "2026-10-13"},               # 非法格式
    ]
    for params in ok_params:
        assert client.get("/api/admin/llm/stats", params=params).status_code == 422, params


def test_跨度92天上界放行(client, conn, admin):
    day = 86400
    base = int(time.time()) // day * day - 91 * day
    d0 = time.strftime("%Y-%m-%d", time.gmtime(base))
    d1 = time.strftime("%Y-%m-%d", time.gmtime(base + 91 * day))
    assert client.get("/api/admin/llm/stats",
                      params={"from": d0, "to": d1}).status_code == 200


def test_匿名401(client, conn):
    assert client.get("/api/admin/llm/stats").status_code == 401
