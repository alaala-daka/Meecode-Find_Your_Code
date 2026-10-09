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
