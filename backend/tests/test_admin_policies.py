"""api_policies 缓存与接口开关（Task 5）+ 管控 API（Task 9）。"""
from app import config, security


def test_policy_cache_fallback_to_config_defaults():
    security.policies.reset()
    assert security.policies.get("browse") == (True, config.RATE_LIMITS["browse"])
    assert security.policies.get("nope") == (True, config.RATE_LIMITS["default"])


def test_policy_cache_set_and_reset():
    security.policies.set("browse", False, 1)
    assert security.policies.get("browse") == (False, 1)
    security.policies.reset()
    assert security.policies.get("browse") == (True, config.RATE_LIMITS["browse"])


def test_policy_cache_refresh_from_db(conn):
    conn.execute("UPDATE api_policies SET enabled=0, limit_per_min=7 WHERE route_key='ugc'")
    conn.commit()
    security.policies.refresh_from(conn)
    assert security.policies.get("ugc") == (False, 7)


def test_policy_cache_maybe_refresh_ttl_and_invalidate(tmp_path):
    from app.feed import db

    path = str(tmp_path / "t.db")
    c = db.connect(path)
    db.init_db(c)
    c.execute("UPDATE api_policies SET limit_per_min=3 WHERE route_key='ugc'")
    c.commit()
    c.close()
    security.policies.reset()
    security.bind_policy_source(lambda: db.connect(path))
    try:
        security.policies.maybe_refresh(security._policy_factory)
        assert security.policies.get("ugc") == (True, 3)
        c2 = db.connect(path)
        c2.execute("UPDATE api_policies SET limit_per_min=9 WHERE route_key='ugc'")
        c2.commit()
        c2.close()
        security.policies.maybe_refresh(security._policy_factory)  # 30s TTL 内不刷
        assert security.policies.get("ugc") == (True, 3)
        security.policies.invalidate()  # 保存即失效/显式失效
        security.policies.maybe_refresh(security._policy_factory)
        assert security.policies.get("ugc") == (True, 9)
    finally:
        security.bind_policy_source(None)
        security.policies.reset()


def test_schedule_refresh_backoff_bounds_thread_spawn_on_failure(monkeypatch):
    security.policies.reset()
    spawns = []

    class CountingThread:
        def __init__(self, target=None, args=(), daemon=None):
            self._target, self._args = target, args
            spawns.append(target)

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(security.threading, "Thread", CountingThread)

    def boom():
        raise RuntimeError("db down")

    security.policies.schedule_refresh(boom)
    security.policies.schedule_refresh(boom)  # 失败也退避：TTL 内不得再起线程
    assert len(spawns) == 1


def test_policy_cache_protected_buckets_never_disabled():
    security.policies.reset()
    security.policies.set("admin", False, 300)
    assert security.policies.get("admin") == (True, 300)
    security.policies.set("default", False, 120)
    assert security.policies.get("default")[0] is True


def test_policy_cache_refresh_from_clamps_protected_buckets(conn):
    conn.execute("UPDATE api_policies SET enabled=0 WHERE route_key='admin'")
    conn.commit()
    security.policies.refresh_from(conn)
    assert security.policies.get("admin")[0] is True


def test_kill_switch_blocks_when_disabled(client):
    security.policies.set("browse", False, 240)
    r = client.get("/api/feed")
    assert r.status_code == 403
    assert r.json() == {"detail": "接口已停用", "code": "disabled"}
    security.policies.reset()
    assert client.get("/api/feed").status_code == 200


def test_api_policies_list_shape(conn, client, admin):
    body = client.get("/api/admin/api-policies").json()
    assert body["total"] == len(body["data"])
    row = next(r for r in body["data"] if r["route_key"] == "llm")
    assert set(row) == {"route_key", "enabled", "limit_per_min"}
    assert row["enabled"] is True and isinstance(row["limit_per_min"], int)


def test_api_policies_patch_updates_db_audit_and_cache(conn, client, admin):
    r = client.patch("/api/admin/api-policies/llm",
                     json={"enabled": False, "limit_per_min": 5})
    assert r.status_code == 200
    assert r.json() == {"route_key": "llm", "enabled": False, "limit_per_min": 5}
    row = conn.execute("SELECT * FROM api_policies WHERE route_key='llm'").fetchone()
    assert row["enabled"] == 0 and row["limit_per_min"] == 5
    a = conn.execute(
        "SELECT * FROM audit_logs WHERE action='api_policy.update'").fetchone()
    assert a["target_id"] == "llm"
    assert security.policies.get("llm") == (False, 5)
    # 保存即生效：llm 桶命中即 403
    resp = client.post("/api/ai-draft", json={"a": 1})
    assert resp.status_code == 403 and resp.json()["code"] == "disabled"


def test_api_policies_patch_rejects_unknown_and_extra(conn, client, admin):
    assert client.patch(
        "/api/admin/api-policies/nope", json={"enabled": False}).status_code == 404
    assert client.patch(
        "/api/admin/api-policies/llm", json={"nope": 1}).status_code == 422


def test_api_policies_protected_buckets_reject_enabled(conn, client, admin):
    for key in ("default", "admin"):
        assert client.patch(
            f"/api/admin/api-policies/{key}",
            json={"enabled": False}).status_code == 400
        r = client.patch(
            f"/api/admin/api-policies/{key}",
            json={"limit_per_min": 99})
        assert r.status_code == 200
        assert r.json()["enabled"] is True  # 保护桶响应恒启用，限额仍可调


def test_api_policies_protected_patch_clamps_enabled(conn, client, admin):
    """脏行（admin.enabled=0）时 PATCH 响应/落库与 PolicyCache 同源钳制为 True。"""
    conn.execute("UPDATE api_policies SET enabled=0 WHERE route_key='admin'")
    conn.commit()
    r = client.patch("/api/admin/api-policies/admin", json={"limit_per_min": 99})
    assert r.status_code == 200
    assert r.json() == {"route_key": "admin", "enabled": True, "limit_per_min": 99}
    row = conn.execute("SELECT enabled FROM api_policies WHERE route_key='admin'").fetchone()
    assert row["enabled"] == 1
    assert security.policies.get("admin") == (True, 99)


def test_api_policies_limit_validation(conn, client, admin):
    assert client.patch(
        "/api/admin/api-policies/llm",
        json={"limit_per_min": 0}).status_code == 422


def test_api_policies_protected_limit_floor(conn, client, admin):
    """保护桶限额下限 60（安全复审：防失手把兜底桶限成 1/min）。"""
    for key in ("default", "admin"):
        assert client.patch(
            f"/api/admin/api-policies/{key}",
            json={"limit_per_min": 5}).status_code == 400


def test_api_policies_anonymous_401(conn, client):
    assert client.get("/api/admin/api-policies").status_code == 401
    assert client.patch("/api/admin/api-policies/llm",
                        json={"enabled": False}).status_code == 401
