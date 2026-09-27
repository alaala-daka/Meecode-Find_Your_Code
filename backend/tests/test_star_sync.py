"""收藏同步 GitHub 星：状态机全分支（spec 2026-09-26）。"""
import pytest

from app import config, security
from app.feed import star_sync
from app.feed.jobs import star_sync as sync_job

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


def make_fav(conn, *, uid=1, rid=1):
    """本地真源 interactions 收藏行：写回竞态守卫以其为准（final review Critical 1）。"""
    conn.execute("INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
                 " VALUES (?,?,?,?)", (uid, rid, "favorite", NOW))
    conn.commit()


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


def test_on_without_token_flips_pending_desired_to_starred(conn):
    user = make_user(conn, token="")
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, attempts, last_error, updated_at)"
                 " VALUES (1, 1, 'unstarred', 'pending', 'meecode', 1, 'boom', 1)")
    conn.commit()
    assert star_sync.sync_favorite_on(conn, user, repo) == "need_auth"
    row = sync_row(conn)
    assert row["desired"] == "starred"
    assert (row["applied"], row["origin"], row["attempts"], row["last_error"]) == ("pending", "meecode", 1, "boom")


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
    make_fav(conn)
    calls = patch_github(monkeypatch, starred=True)
    assert star_sync.sync_favorite_on(conn, user, repo) == "synced"
    row = sync_row(conn)
    assert (row["origin"], row["applied"]) == ("external", "done")
    assert calls["star"] == []


def test_on_keeps_meecode_origin_when_star_reappears(conn, monkeypatch):
    """溯源保持：撤星失败后再收藏，星仍在 GitHub → origin 不得漂成 external（防星泄漏）。"""
    user = make_user(conn)
    repo = make_repo(conn)
    make_fav(conn)
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
    make_fav(conn)
    calls = patch_github(monkeypatch, starred=False)
    assert star_sync.sync_favorite_on(conn, user, repo) == "synced"
    row = sync_row(conn)
    assert (row["origin"], row["applied"], row["attempts"]) == ("meecode", "done", 0)
    assert calls["star"] == ["other/proj"]


def test_on_star_failure_pends(conn, monkeypatch):
    from app.feed import github
    user = make_user(conn)
    repo = make_repo(conn)
    make_fav(conn)
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
    make_fav(conn)
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


def test_off_pending_row_attempts_unstar_and_404_completes(conn, monkeypatch):
    """改写自 test_off_never_starred_deletes_row_without_api（final review Critical 1 (iii)）：
    旧捷径「starred/pending 删行不调 GitHub」被删——pending ≠ 星从未点上（无 token 翻转
    desired、PUT 超时实已点上都会让星滞留）。新语义：撤星被尝试，从未点上的星得 404，
    视为完成删行。"""
    from app.feed import github
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, updated_at)"
                 " VALUES (1, 1, 'starred', 'pending', 'meecode', 1)")
    conn.commit()
    calls = patch_github(monkeypatch, unstar=github.GitHubError("gone", status=404))
    assert star_sync.sync_favorite_off(conn, user, repo) == "unstarred"
    assert calls["unstar"] == ["other/proj"]   # 撤星被尝试，不再跳过
    assert sync_row(conn) is None


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
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, attempts, updated_at)"
                 " VALUES (1, 1, 'unstarred', 'pending', 'meecode', 1, 1)")
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


# ---------- 星泄漏回归（final review Critical 1） ----------
def test_cancel_after_token_loss_never_leaks_star(conn, monkeypatch):
    """5 步泄漏序列终态断言：token 失效后 取消→再收藏→再取消 不得让星滞留 GitHub。

    旧捷径在第 5 步命中（starred/pending 删行不调 GitHub）→ 行已删、星仍在，永久泄漏；
    新语义把取消收敛到撤星意图，token 恢复后 job 撤星删行。
    """
    user = make_user(conn)
    repo = make_repo(conn)
    make_fav(conn)                                                       # 本地真源：收藏已生效
    calls = patch_github(monkeypatch, starred=False)
    assert star_sync.sync_favorite_on(conn, user, repo) == "synced"      # 1) 收藏成功，星点上
    assert calls["star"] == ["other/proj"]
    conn.execute("UPDATE users SET gh_token_enc='' WHERE id=1")
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE id=1").fetchone()     # 2) token 失效被清
    conn.execute("DELETE FROM interactions WHERE kind='favorite'")       # 3) 取消：本地真源删除
    conn.commit()
    assert star_sync.sync_favorite_off(conn, user, repo) == "need_auth"  # 3) 取消：排撤星意图
    assert sync_row(conn)["desired"] == "unstarred"
    make_fav(conn)                                                       # 4) 无 token 再收藏：本地真源恢复
    assert star_sync.sync_favorite_on(conn, user, repo) == "need_auth"   # 4) 无 token 再收藏：翻转
    assert sync_row(conn)["desired"] == "starred"
    conn.execute("DELETE FROM interactions WHERE kind='favorite'")       # 5) 再取消：本地真源删除
    conn.commit()
    assert star_sync.sync_favorite_off(conn, user, repo) == "need_auth"  # 5) 再取消：不得删行了事
    row = sync_row(conn)
    assert row is not None and row["desired"] == "unstarred"             # 星仍在 GitHub，行必须留痕
    conn.execute("UPDATE users SET gh_token_enc=? WHERE id=1",
                 (security.seal_token("tok2"),))
    conn.commit()
    stats = sync_job.sync_pending_once(conn)                             # token 恢复后收敛
    assert stats == {"picked": 1, "done": 1, "failed": 0, "skipped": 0}
    assert calls["unstar"] == ["other/proj"]                             # unstar 被调用（星不泄漏）
    assert sync_row(conn) is None


def test_on_writeback_retracted_when_favorite_cancelled(conn, monkeypatch):
    """job 在途竞态：写回前本地真源已删（用户并发取消）→ 撤销本次点星、不留孤儿行。"""
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, attempts, updated_at)"
                 " VALUES (1, 1, 'starred', 'pending', 'meecode', 1, 1)")
    conn.commit()
    calls = patch_github(monkeypatch, starred=False)
    assert star_sync.sync_favorite_on(conn, user, repo) == "unstarred"
    assert calls["star"] == ["other/proj"]      # 点星已发出
    assert calls["unstar"] == ["other/proj"]    # star_repo 后的写回被撤销
    assert sync_row(conn) is None               # 无孤儿行


def test_on_retract_unstars_when_star_is_ours(conn, monkeypatch):
    """is_starred=True 且溯源 meecode（此前 PUT 超时实已点上）时，取消后不得把星留在 GitHub；
    外部星（无 meecode 溯源）不在此列——见 test_off_external_keeps_star。"""
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, attempts, updated_at)"
                 " VALUES (1, 1, 'starred', 'pending', 'meecode', 1, 1)")
    conn.commit()
    calls = patch_github(monkeypatch, starred=True)
    assert star_sync.sync_favorite_on(conn, user, repo) == "unstarred"
    assert calls["unstar"] == ["other/proj"]
    assert sync_row(conn) is None


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


# ---------- 重试 job（spec 2026-09-26 §4.4） ----------
def _seed_sync_row(conn, *, rid=1, desired="starred", applied="pending", origin="meecode", attempts=1):
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, origin, attempts, updated_at)"
                 " VALUES (1, ?, ?, ?, ?, ?, 1)", (rid, desired, applied, origin, attempts))
    conn.commit()


def test_job_retries_pending_row(conn, monkeypatch):
    make_user(conn)
    make_repo(conn)
    make_fav(conn)
    _seed_sync_row(conn)
    calls = patch_github(monkeypatch)
    stats = sync_job.sync_pending_once(conn)
    assert stats == {"picked": 1, "done": 1, "failed": 0, "skipped": 0}
    assert calls["star"] == ["other/proj"]
    assert sync_row(conn)["applied"] == "done"


def test_job_skips_rows_without_token(conn, monkeypatch):
    make_user(conn, token="")
    make_repo(conn)
    _seed_sync_row(conn)
    calls = patch_github(monkeypatch)
    stats = sync_job.sync_pending_once(conn)
    assert stats == {"picked": 0, "done": 0, "failed": 0, "skipped": 1}
    assert calls["star"] == []
    assert sync_row(conn)["attempts"] == 1  # 不烧 attempts


def test_job_ignores_exhausted_and_done_rows(conn, monkeypatch):
    make_user(conn)
    make_repo(conn, rid=1, gid=5001, full_name="other/a")
    make_repo(conn, rid=2, gid=5002, full_name="other/b")
    _seed_sync_row(conn, rid=1, applied="done")
    _seed_sync_row(conn, rid=2, attempts=config.STAR_SYNC_MAX_ATTEMPTS)
    calls = patch_github(monkeypatch)
    stats = sync_job.sync_pending_once(conn)
    assert stats == {"picked": 0, "done": 0, "failed": 0, "skipped": 0}
    assert calls["star"] == []


def test_job_retries_unstar_desired(conn, monkeypatch):
    make_user(conn)
    make_repo(conn)
    _seed_sync_row(conn, desired="unstarred", origin="meecode", attempts=1)
    calls = patch_github(monkeypatch)
    stats = sync_job.sync_pending_once(conn)
    assert stats == {"picked": 1, "done": 1, "failed": 0, "skipped": 0}
    assert calls["unstar"] == ["other/proj"]
    assert sync_row(conn) is None


# ---------- 重试 job 补测（spec §5 点名缺口，final review Important 4） ----------
def test_job_401_clears_token_and_stops_batch(conn, monkeypatch):
    """401 清 token 并停全部 pending：同批后续行不得再拿死 token 打 GitHub。"""
    from app.feed import github
    make_user(conn)
    make_repo(conn, rid=1, gid=5001, full_name="other/a")
    make_repo(conn, rid=2, gid=5002, full_name="other/b")
    make_fav(conn, rid=1)
    make_fav(conn, rid=2)
    _seed_sync_row(conn, rid=1)
    _seed_sync_row(conn, rid=2)
    calls = patch_github(monkeypatch, star=github.GitHubError("bad", status=401))
    stats = sync_job.sync_pending_once(conn)
    assert calls["star"] == ["other/a"]        # 第二行不再打 GitHub
    u = conn.execute("SELECT gh_token_enc FROM users WHERE id=1").fetchone()
    assert u["gh_token_enc"] == ""
    for rid in (1, 2):
        assert sync_row(conn, rid=rid)["last_error"] == "token revoked"
    assert stats == {"picked": 2, "done": 0, "failed": 2, "skipped": 0}


def test_job_404_stops_single_row(conn, monkeypatch):
    """404 停单行：attempts 置 MAX 终态化，不无限打。"""
    from app.feed import github
    make_user(conn)
    make_repo(conn)
    make_fav(conn)
    _seed_sync_row(conn)
    patch_github(monkeypatch, star=github.GitHubError("gone", status=404))
    stats = sync_job.sync_pending_once(conn)
    assert stats == {"picked": 1, "done": 0, "failed": 1, "skipped": 0}
    row = sync_row(conn)
    assert (row["applied"], row["attempts"]) == ("pending", config.STAR_SYNC_MAX_ATTEMPTS)


def test_job_failure_counts_failed_without_aborting_batch(conn, monkeypatch):
    """重放失败计 failed 不中断整批（crawl.py 同款）：单行异常跳过，后续行照常收敛。"""
    make_user(conn)
    make_repo(conn, rid=1, gid=5001, full_name="other/a")
    make_repo(conn, rid=2, gid=5002, full_name="other/b")
    make_fav(conn, rid=1)
    make_fav(conn, rid=2)
    _seed_sync_row(conn, rid=1)
    _seed_sync_row(conn, rid=2)
    calls = {"star": []}

    def star(token, full_name, **kw):
        calls["star"].append(full_name)
        if full_name == "other/a":
            raise RuntimeError("boom")

    monkeypatch.setattr(star_sync.github, "is_starred", lambda token, full_name, **kw: False)
    monkeypatch.setattr(star_sync.github, "star_repo", star)
    monkeypatch.setattr(star_sync.github, "unstar_repo", lambda token, full_name, **kw: None)
    stats = sync_job.sync_pending_once(conn)
    assert stats == {"picked": 2, "done": 1, "failed": 1, "skipped": 0}
    assert calls["star"] == ["other/a", "other/b"]
    assert sync_row(conn, rid=1)["applied"] == "pending"
    assert sync_row(conn, rid=2)["applied"] == "done"
