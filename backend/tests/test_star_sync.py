"""收藏同步 GitHub 星：状态机全分支（spec 2026-09-26）。"""
import pytest

from app import config, security
from app.feed import star_sync

NOW = 1_700_000_000


def make_user(conn, *, uid=1, login="demo", token="ghp_t"):
    conn.execute(
        "INSERT INTO users (id, github_id, login, gh_token_enc, gh_star_authed_at)"
        " VALUES (?,?,?,?,?)",
        (uid, 1000 + uid, login, security.seal_token(token) if token else "", NOW if token else 0),
    )
    conn.commit()
    return conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def make_repo(conn, *, rid=1, gid=5001, owner="other", full_name="other/proj"):
    conn.execute(
        "INSERT INTO repos (id, github_id, full_name, owner_login, language, source, status,"
        " quality, published_at, tagline_zh, screened)"
        " VALUES (?,?,?,?,'Python','crawled','published',3,?,'卖点',1)",
        (rid, gid, full_name, owner, NOW),
    )
    conn.commit()
    return conn.execute("SELECT * FROM repos WHERE id=?", (rid,)).fetchone()


def sync_row(conn, uid=1, rid=1):
    return conn.execute(
        "SELECT * FROM star_syncs WHERE user_id=? AND repo_id=?", (uid, rid)).fetchone()


def patch_github(monkeypatch, *, starred=False, star=None, unstar=None):
    """star/unstar 传 GitHubError 实例即抛出，否则成功；返回调用记录。"""
    calls = {"star": [], "unstar": []}

    def _do(record, err):
        def fn(token, full_name, **kw):
            record.append(full_name)
            if err is not None:
                raise err
        return fn

    monkeypatch.setattr(star_sync.github, "is_starred", lambda token, full_name, **kw: starred)
    monkeypatch.setattr(star_sync.github, "star_repo", _do(calls["star"], star))
    monkeypatch.setattr(star_sync.github, "unstar_repo", _do(calls["unstar"], unstar))
    return calls


def test_on_without_token_is_need_auth_without_row(conn):
    user = make_user(conn, token="")
    repo = make_repo(conn)
    assert star_sync.sync_favorite_on(conn, user, repo) == "need_auth"
    assert sync_row(conn) is None


def test_on_own_repo_is_skipped(conn, monkeypatch):
    user = make_user(conn, login="alice")
    repo = make_repo(conn, owner="alice", full_name="alice/proj")
    calls = patch_github(monkeypatch)
    assert star_sync.sync_favorite_on(conn, user, repo) == "skipped"
    row = sync_row(conn)
    assert (row["desired"], row["applied"], row["origin"]) == ("starred", "done", "external")
    assert calls["star"] == []


def test_on_preexisting_star_is_external(conn, monkeypatch):
    user = make_user(conn)
    repo = make_repo(conn)
    calls = patch_github(monkeypatch, starred=True)
    assert star_sync.sync_favorite_on(conn, user, repo) == "synced"
    row = sync_row(conn)
    assert (row["origin"], row["applied"]) == ("external", "done")
    assert calls["star"] == []


def test_on_keeps_meecode_origin_when_star_reappears(conn, monkeypatch):
    """溯源保持：撤星失败后再收藏，星仍在 GitHub → origin 不得漂成 external（防星泄漏）。"""
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, updated_at)"
                 " VALUES (1, 1, 'unstarred', 'pending', 'meecode', 1)")
    conn.commit()
    patch_github(monkeypatch, starred=True)
    assert star_sync.sync_favorite_on(conn, user, repo) == "synced"
    row = sync_row(conn)
    assert (row["origin"], row["desired"], row["applied"]) == ("meecode", "starred", "done")


def test_on_star_success_is_meecode_done(conn, monkeypatch):
    user = make_user(conn)
    repo = make_repo(conn)
    calls = patch_github(monkeypatch, starred=False)
    assert star_sync.sync_favorite_on(conn, user, repo) == "synced"
    row = sync_row(conn)
    assert (row["origin"], row["applied"], row["attempts"]) == ("meecode", "done", 0)
    assert calls["star"] == ["other/proj"]


def test_on_star_failure_pends(conn, monkeypatch):
    from app.feed import github
    user = make_user(conn)
    repo = make_repo(conn)
    patch_github(monkeypatch, star=github.GitHubError("boom", status=500))
    assert star_sync.sync_favorite_on(conn, user, repo) == "pending"
    row = sync_row(conn)
    assert (row["desired"], row["applied"], row["attempts"]) == ("starred", "pending", 1)
    assert row["last_error"] == "boom"


def test_on_401_clears_token_and_need_auth(conn, monkeypatch):
    from app.feed import github
    user = make_user(conn)
    repo = make_repo(conn)
    patch_github(monkeypatch, star=github.GitHubError("bad", status=401))
    assert star_sync.sync_favorite_on(conn, user, repo) == "need_auth"
    u = conn.execute("SELECT gh_token_enc FROM users WHERE id=1").fetchone()
    assert u["gh_token_enc"] == ""


def test_on_404_stops_retry(conn, monkeypatch):
    from app.feed import github
    user = make_user(conn)
    repo = make_repo(conn)
    patch_github(monkeypatch, star=github.GitHubError("gone", status=404))
    assert star_sync.sync_favorite_on(conn, user, repo) == "pending"
    row = sync_row(conn)
    assert row["attempts"] == config.STAR_SYNC_MAX_ATTEMPTS


def test_off_without_row_is_kept(conn):
    user = make_user(conn, token="")
    repo = make_repo(conn)
    assert star_sync.sync_favorite_off(conn, user, repo) == "kept"


def test_off_external_keeps_star(conn, monkeypatch):
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, updated_at)"
                 " VALUES (1, 1, 'starred', 'done', 'external', 1)")
    conn.commit()
    calls = patch_github(monkeypatch)
    assert star_sync.sync_favorite_off(conn, user, repo) == "kept"
    assert sync_row(conn) is None
    assert calls["unstar"] == []


def test_off_never_starred_deletes_row_without_api(conn, monkeypatch):
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, updated_at)"
                 " VALUES (1, 1, 'starred', 'pending', 'meecode', 1)")
    conn.commit()
    calls = patch_github(monkeypatch)
    assert star_sync.sync_favorite_off(conn, user, repo) == "unstarred"
    assert sync_row(conn) is None
    assert calls["unstar"] == []


def test_off_meecode_done_unstars(conn, monkeypatch):
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, updated_at)"
                 " VALUES (1, 1, 'starred', 'done', 'meecode', 1)")
    conn.commit()
    calls = patch_github(monkeypatch)
    assert star_sync.sync_favorite_off(conn, user, repo) == "unstarred"
    assert sync_row(conn) is None
    assert calls["unstar"] == ["other/proj"]


def test_off_unstar_failure_keeps_pending_row(conn, monkeypatch):
    """spec §4.3 精确化：desired='unstarred' 的 pending 行必须可重试撤星，不得删行。"""
    from app.feed import github
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, updated_at)"
                 " VALUES (1, 1, 'unstarred', 'pending', 'meecode', 1)")
    conn.commit()
    patch_github(monkeypatch, unstar=github.GitHubError("boom", status=500))
    assert star_sync.sync_favorite_off(conn, user, repo) == "pending"
    row = sync_row(conn)
    assert (row["desired"], row["applied"], row["attempts"]) == ("unstarred", "pending", 2)


def test_off_404_star_gone_is_done(conn, monkeypatch):
    from app.feed import github
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, updated_at)"
                 " VALUES (1, 1, 'starred', 'done', 'meecode', 1)")
    conn.commit()
    patch_github(monkeypatch, unstar=github.GitHubError("gone", status=404))
    assert star_sync.sync_favorite_off(conn, user, repo) == "unstarred"
    assert sync_row(conn) is None


def test_off_without_token_queues_unstar(conn, monkeypatch):
    user = make_user(conn, token="ghp_t")
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, updated_at)"
                 " VALUES (1, 1, 'starred', 'done', 'meecode', 1)")
    conn.commit()
    conn.execute("UPDATE users SET gh_token_enc='' WHERE id=1")
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE id=1").fetchone()
    calls = patch_github(monkeypatch)
    assert star_sync.sync_favorite_off(conn, user, repo) == "need_auth"
    row = sync_row(conn)
    assert (row["desired"], row["applied"]) == ("unstarred", "pending")
    assert calls["unstar"] == []


def test_backfill_only_touches_favorites_without_rows(conn, monkeypatch):
    user = make_user(conn)
    repo_a = make_repo(conn, rid=1, gid=5001, full_name="other/a")
    make_repo(conn, rid=2, gid=5002, full_name="other/b")
    for rid in (1, 2):
        conn.execute("INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
                     " VALUES (1, ?, 'favorite', 1)", (rid,))
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, updated_at)"
                 " VALUES (1, 1, 'starred', 'done', 'meecode', 1)")
    conn.commit()
    calls = patch_github(monkeypatch)
    star_sync.backfill_user(conn, 1)
    assert calls["star"] == ["other/b"]  # repo 1 已有行不动，repo 2 补同步
    assert sync_row(conn, rid=2)["applied"] == "done"
