"""解读会话存储：滑动 TTL、容量上限满额拒新、并发写入不丢。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app import config
from app.main import _SessionStore

NOW = 1_700_000_000.0


def test_create_and_get_roundtrip():
    s = _SessionStore()
    sid = s.create(NOW)
    assert sid and s.get(sid, NOW) is not None


def test_expired_session_is_rejected():
    s = _SessionStore()
    sid = s.create(NOW)
    assert s.get(sid, NOW + config.EXPLAIN_SESSION_TTL + 1) is None


def test_sliding_ttl_refreshes_on_access():
    s = _SessionStore()
    sid = s.create(NOW)
    t1 = NOW + config.EXPLAIN_SESSION_TTL - 10
    assert s.get(sid, t1) is not None                 # 访问即续期
    t2 = t1 + config.EXPLAIN_SESSION_TTL - 10
    assert s.get(sid, t2) is not None                 # 续期后的窗口内再次续期
    assert s.get(sid, t2 + config.EXPLAIN_SESSION_TTL + 1) is None


def test_capacity_rejects_new_and_keeps_existing():
    s = _SessionStore()
    made = [s.create(NOW) for _ in range(config.EXPLAIN_SESSION_MAX)]
    assert all(made)
    assert s.create(NOW) is None                      # 满额拒新
    assert s.get(made[0], NOW) is not None            # 既有会话不受影响


def test_capacity_reclaims_expired_first():
    s = _SessionStore()
    for _ in range(config.EXPLAIN_SESSION_MAX):
        s.create(NOW)
    later = NOW + config.EXPLAIN_SESSION_TTL + 1
    assert s.create(later) is not None                # 全过期后清槽放行


def test_concurrent_create_respects_capacity():
    s = _SessionStore()
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda _: s.create(NOW), range(config.EXPLAIN_SESSION_MAX * 2)))
    ok = [r for r in results if r]
    assert len(ok) == config.EXPLAIN_SESSION_MAX      # 并发下不超卖
    assert len(set(ok)) == config.EXPLAIN_SESSION_MAX
