"""收藏同步 GitHub 星：状态机全分支（spec 2026-09-26）。"""
import base64

import pytest

from app import config, security
from app.feed import star_sync
from app.feed.jobs import star_sync as sync_job

NOW = 1_700_000_000


def make_user(conn, *, uid=1, login="demo", token="ghp_t"):
    conn.execute(
        "INSERT INTO users (id, github_id, login, gh_token_enc, gh_star_authed_at)"
        " VALUES (?,?,?,?,?)",
        (uid, 1000 + uid, login,
         security.seal_token(token, str(uid)) if token else "", NOW if token else 0),
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


def patch_github(monkeypatch, *, star=None, unstar=None):
    """star/unstar 传 GitHubError 实例即抛出，否则成功；返回调用记录。"""
    calls = {"star": [], "unstar": []}

    def _do(record, err):
        def fn(token, full_name, **kw):
            record.append(full_name)
            if err is not None:
                raise err
        return fn

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
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, attempts, last_error, updated_at)"
                 " VALUES (1, 1, 'unstarred', 'pending', 1, 'boom', 1)")
    conn.commit()
    assert star_sync.sync_favorite_on(conn, user, repo) == "need_auth"
    row = sync_row(conn)
    assert row["desired"] == "starred"
    assert (row["applied"], row["attempts"], row["last_error"]) == ("pending", 1, "boom")


def test_on_own_repo_goes_regular_path(conn, monkeypatch):
    """own-repo 无特判（自点星合规，实测）：常规 PUT，正常 synced。"""
    user = make_user(conn, login="alice")
    repo = make_repo(conn, owner="alice", full_name="alice/proj")
    make_fav(conn)
    calls = patch_github(monkeypatch)
    assert star_sync.sync_favorite_on(conn, user, repo) == "synced"
    assert calls["star"] == ["alice/proj"]


def test_on_preexisting_star_still_puts(conn, monkeypatch):
    """幂等 PUT：已 star 也走 PUT（无预查），GitHub 无变化。"""
    user = make_user(conn)
    repo = make_repo(conn)
    make_fav(conn)
    calls = patch_github(monkeypatch)
    assert star_sync.sync_favorite_on(conn, user, repo) == "synced"
    assert calls["star"] == ["other/proj"]


def test_on_put_404_is_skipped_terminal(conn, monkeypatch):
    """仓库消失：skipped 终态，无行不建、不重试不报错。"""
    from app.feed import github
    user = make_user(conn)
    repo = make_repo(conn)
    make_fav(conn)
    patch_github(monkeypatch, star=github.GitHubError("gone", status=404))
    assert star_sync.sync_favorite_on(conn, user, repo) == "skipped"
    assert sync_row(conn) is None


def test_on_put_422_dels_existing_row(conn, monkeypatch):
    """不可点星：已有行删行（星从未点上，无泄漏）。"""
    from app.feed import github
    user = make_user(conn)
    repo = make_repo(conn)
    make_fav(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, attempts, updated_at)"
                 " VALUES (1, 1, 'starred', 'pending', 1, 1)")
    conn.commit()
    patch_github(monkeypatch, star=github.GitHubError("nope", status=422))
    assert star_sync.sync_favorite_on(conn, user, repo) == "skipped"
    assert sync_row(conn) is None


def test_on_star_success_is_done(conn, monkeypatch):
    user = make_user(conn)
    repo = make_repo(conn)
    make_fav(conn)
    calls = patch_github(monkeypatch)
    assert star_sync.sync_favorite_on(conn, user, repo) == "synced"
    row = sync_row(conn)
    assert (row["desired"], row["applied"]) == ("starred", "done")
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


def test_on_401_flips_pending_desired_to_starred(conn, monkeypatch):
    """B6：401 早期退出也要翻 desired——否则重授权后 job 按陈旧 'unstarred'
    撤掉用户已重新收藏的星。TokenKeyMismatchError 不同：异常上抛，行不动。"""
    from app.feed import github
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, attempts, last_error, updated_at)"
                 " VALUES (1, 1, 'unstarred', 'pending', 1, 'boom', 1)")
    conn.commit()
    patch_github(monkeypatch, star=github.GitHubError("bad", status=401))
    assert star_sync.sync_favorite_on(conn, user, repo) == "need_auth"
    row = sync_row(conn)
    assert row["desired"] == "starred"
    assert (row["applied"], row["attempts"], row["last_error"]) == ("pending", 1, "token revoked")


# ---------- 取消方向（spec 2026-09-28：一律撤星，gh_sync 表达仅本地） ----------
def test_off_gh_sync_false_keeps_star_and_clears_rows(conn, monkeypatch):
    """仅取消本地：零 GitHub 调用，删同步行（含挂起待撤），星保留。"""
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, attempts, updated_at)"
                 " VALUES (1, 1, 'unstarred', 'pending', 1, 1)")
    conn.commit()
    calls = patch_github(monkeypatch)
    assert star_sync.sync_favorite_off(conn, user, repo, gh_sync=False) == "kept"
    assert sync_row(conn) is None
    assert calls["unstar"] == []


def test_off_unstars_even_existing_done_row(conn, monkeypatch):
    """推翻决策 4：原 external 手动星（既有 (starred, done) 行）同样撤，无豁免。"""
    user = make_user(conn)
    repo = make_repo(conn)
    make_fav(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, updated_at)"
                 " VALUES (1, 1, 'starred', 'done', 1)")
    conn.commit()
    calls = patch_github(monkeypatch)
    assert star_sync.sync_favorite_off(conn, user, repo) == "unstarred"
    assert sync_row(conn) is None
    assert calls["unstar"] == ["other/proj"]


def test_off_without_row_still_unstars(conn, monkeypatch):
    """无同步行也撤星（旧行为 kept 是逃逸口）。"""
    user = make_user(conn)
    repo = make_repo(conn)
    make_fav(conn)
    calls = patch_github(monkeypatch)
    assert star_sync.sync_favorite_off(conn, user, repo) == "unstarred"
    assert calls["unstar"] == ["other/proj"]


def test_off_unstar_404_is_done(conn, monkeypatch):
    from app.feed import github
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, updated_at)"
                 " VALUES (1, 1, 'starred', 'done', 1)")
    conn.commit()
    patch_github(monkeypatch, unstar=github.GitHubError("gone", status=404))
    assert star_sync.sync_favorite_off(conn, user, repo) == "unstarred"
    assert sync_row(conn) is None


def test_off_unstar_failure_queues_pending(conn, monkeypatch):
    from app.feed import github
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, attempts, updated_at)"
                 " VALUES (1, 1, 'starred', 'done', 1, 1)")
    conn.commit()
    patch_github(monkeypatch, unstar=github.GitHubError("boom", status=500))
    assert star_sync.sync_favorite_off(conn, user, repo) == "pending"
    row = sync_row(conn)
    assert (row["desired"], row["applied"], row["attempts"]) == ("unstarred", "pending", 2)


def test_off_without_token_queues_unstar(conn, monkeypatch):
    """gh_sync:true 即表达同意：无 token 落队列等授权。"""
    user = make_user(conn)
    conn.execute("UPDATE users SET gh_token_enc='' WHERE id=1")
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE id=1").fetchone()
    repo = make_repo(conn)
    make_fav(conn)
    calls = patch_github(monkeypatch)
    assert star_sync.sync_favorite_off(conn, user, repo) == "need_auth"
    row = sync_row(conn)
    assert (row["desired"], row["applied"]) == ("unstarred", "pending")
    assert calls["unstar"] == []


def test_off_401_clears_token_no_queue_row_untouched(conn, monkeypatch):
    """决策 8：401 不落队列、不动既有行——同意行不得被 401 吞掉。"""
    from app.feed import github
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, attempts, updated_at)"
                 " VALUES (1, 1, 'unstarred', 'pending', 1, 1)")
    conn.commit()
    patch_github(monkeypatch, unstar=github.GitHubError("bad", status=401))
    assert star_sync.sync_favorite_off(conn, user, repo) == "need_auth"
    u = conn.execute("SELECT gh_token_enc FROM users WHERE id=1").fetchone()
    assert u["gh_token_enc"] == ""
    row = sync_row(conn)
    assert (row["desired"], row["applied"], row["attempts"]) == ("unstarred", "pending", 1)


# ---------- 星泄漏回归（final review Critical 1） ----------
def test_cancel_after_token_loss_never_leaks_star(conn, monkeypatch):
    """5 步泄漏序列终态断言：token 失效后 取消→再收藏→再取消 不得让星滞留 GitHub。

    旧捷径在第 5 步命中（starred/pending 删行不调 GitHub）→ 行已删、星仍在，永久泄漏；
    新语义把取消收敛到撤星意图，token 恢复后 job 撤星删行。
    """
    user = make_user(conn)
    repo = make_repo(conn)
    make_fav(conn)                                                       # 本地真源：收藏已生效
    calls = patch_github(monkeypatch)
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
                 (security.seal_token("tok2", "1"),))
    conn.commit()
    stats = sync_job.sync_pending_once(conn)                             # token 恢复后收敛
    assert stats == {"picked": 1, "done": 1, "failed": 0, "skipped": 0}
    assert calls["unstar"] == ["other/proj"]                             # unstar 被调用（星不泄漏）
    assert sync_row(conn) is None


def test_on_writeback_retracted_when_favorite_cancelled(conn, monkeypatch):
    """job 在途竞态：写回前本地真源已删（用户并发取消）→ 撤销本次点星、不留孤儿行。"""
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, attempts, updated_at)"
                 " VALUES (1, 1, 'starred', 'pending', 1, 1)")
    conn.commit()
    calls = patch_github(monkeypatch)
    assert star_sync.sync_favorite_on(conn, user, repo) == "unstarred"
    assert calls["star"] == ["other/proj"]      # 点星已发出
    assert calls["unstar"] == ["other/proj"]    # star_repo 后的写回被撤销
    assert sync_row(conn) is None               # 无孤儿行


def test_backfill_only_touches_favorites_without_rows(conn, monkeypatch):
    user = make_user(conn)
    repo_a = make_repo(conn, rid=1, gid=5001, full_name="other/a")
    make_repo(conn, rid=2, gid=5002, full_name="other/b")
    for rid in (1, 2):
        conn.execute("INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
                     " VALUES (1, ?, 'favorite', 1)", (rid,))
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, updated_at)"
                 " VALUES (1, 1, 'starred', 'done', 1)")
    conn.commit()
    calls = patch_github(monkeypatch)
    star_sync.backfill_user(conn, 1)
    assert calls["star"] == ["other/b"]  # repo 1 已有行不动，repo 2 补同步
    assert sync_row(conn, rid=2)["applied"] == "done"


def test_backfill_pending_loop_survives_single_row_exception(conn, monkeypatch):
    """单行异常不中断整轮：首尾行照常收敛，中断行留待 cron 重试。"""
    make_user(conn)
    for rid in (1, 2, 3):
        make_repo(conn, rid=rid, gid=5000 + rid, full_name=f"other/{rid}")
        conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, attempts, updated_at)"
                     " VALUES (1, ?, 'unstarred', 'pending', 1, 1)", (rid,))
    conn.commit()
    calls = patch_github(monkeypatch)
    real_replay = star_sync.replay_row

    def flaky(conn, row):
        if row["repo_id"] == 2:
            raise RuntimeError("boom")
        return real_replay(conn, row)

    monkeypatch.setattr(star_sync, "replay_row", flaky)
    star_sync.backfill_user(conn, 1)  # 不得抛出
    assert calls["unstar"] == ["other/1", "other/3"]
    assert sync_row(conn, rid=2) is not None


def test_backfill_fav_loop_survives_single_row_exception(conn, monkeypatch):
    """补收藏循环同样单行容错，后续收藏照常补同步。"""
    make_user(conn)
    for rid in (1, 2, 3):
        make_repo(conn, rid=rid, gid=5000 + rid, full_name=f"other/{rid}")
        conn.execute("INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
                     " VALUES (1, ?, 'favorite', 1)", (rid,))
    conn.commit()
    calls = patch_github(monkeypatch)
    real_on = star_sync.sync_favorite_on

    def flaky(conn, user, repo, *, interactive=True):
        if repo["id"] == 2:
            raise RuntimeError("boom")
        return real_on(conn, user, repo, interactive=interactive)

    monkeypatch.setattr(star_sync, "sync_favorite_on", flaky)
    star_sync.backfill_user(conn, 1)  # 不得抛出
    assert calls["star"] == ["other/1", "other/3"]


# ---------- 重试 job（spec 2026-09-26 §4.4） ----------
def _seed_sync_row(conn, *, rid=1, desired="starred", applied="pending", attempts=1):
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, attempts, updated_at)"
                 " VALUES (1, ?, ?, ?, ?, 1)", (rid, desired, applied, attempts))
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
    _seed_sync_row(conn, desired="unstarred", attempts=1)
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
    """404 停单行：skipped 终态删行，不无限打。"""
    from app.feed import github
    make_user(conn)
    make_repo(conn)
    make_fav(conn)
    _seed_sync_row(conn)
    patch_github(monkeypatch, star=github.GitHubError("gone", status=404))
    stats = sync_job.sync_pending_once(conn)
    assert stats == {"picked": 1, "done": 1, "failed": 0, "skipped": 0}
    assert sync_row(conn) is None


def test_job_failure_counts_failed_without_aborting_batch(conn, monkeypatch):
    """重放失败计 failed 不中断整批（crawl.py 同款）：单行异常跳过，后续行照常收敛。
    改写自旧版（B1）：旧实现异常路径不落 attempts/last_error，非 GitHubError 行会无限重试；
    新语义 attempts+1、last_error 落库，与 §4.4「attempts+1、成败落库」一致。"""
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

    monkeypatch.setattr(star_sync.github, "star_repo", star)
    monkeypatch.setattr(star_sync.github, "unstar_repo", lambda token, full_name, **kw: None)
    stats = sync_job.sync_pending_once(conn)
    assert stats == {"picked": 2, "done": 1, "failed": 1, "skipped": 0}
    assert calls["star"] == ["other/a", "other/b"]
    row = sync_row(conn, rid=1)
    assert (row["applied"], row["attempts"], row["last_error"]) == ("pending", 2, "boom")
    assert sync_row(conn, rid=2)["applied"] == "done"


def test_job_generic_error_exhausts_row_at_max_attempts(conn, monkeypatch):
    """B1：非 GitHubError 异常也落 attempts，到 STAR_SYNC_MAX_ATTEMPTS 终态不再拾起——
    旧实现漏 bump，持久抛错的行会无限重试（违 §4.4 attempts 上限终态化）。"""
    make_user(conn)
    make_repo(conn)
    make_fav(conn)
    _seed_sync_row(conn, attempts=config.STAR_SYNC_MAX_ATTEMPTS - 1)

    def star(token, full_name, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(star_sync.github, "star_repo", star)
    monkeypatch.setattr(star_sync.github, "unstar_repo", lambda token, full_name, **kw: None)
    stats = sync_job.sync_pending_once(conn)
    assert stats == {"picked": 1, "done": 0, "failed": 1, "skipped": 0}
    row = sync_row(conn)
    assert (row["attempts"], row["last_error"]) == (config.STAR_SYNC_MAX_ATTEMPTS, "boom")
    assert sync_job.sync_pending_once(conn) == {"picked": 0, "done": 0, "failed": 0, "skipped": 0}


def test_job_key_mismatch_skips_without_burning_attempts(conn, monkeypatch):
    """B1 例外：换钥（TokenKeyMismatchError）与无 token 同款跳过不烧 attempts——
    密文凭原密钥可恢复（wave-A A1），行须留待运维恢复 TOKEN_ENC_KEY 后收敛。"""
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"k" * 32).decode())
    make_user(conn)
    make_repo(conn)
    make_fav(conn)
    _seed_sync_row(conn)
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"j" * 32).decode())
    stats = sync_job.sync_pending_once(conn)
    assert stats == {"picked": 1, "done": 0, "failed": 0, "skipped": 1}
    row = sync_row(conn)
    assert row["attempts"] == 1
    assert conn.execute("SELECT gh_token_enc FROM users WHERE id=1").fetchone()["gh_token_enc"] != ""


# ---------- 密钥指纹/换钥保密文（final review A1） ----------
def test_load_token_key_mismatch_raises_and_keeps_ciphertext(conn, monkeypatch):
    """换钥（错但合法的 key）不得销毁密文：TokenKeyMismatchError 上抛，
    gh_token_enc 原样保留——密文凭原密钥可恢复，恢复 key 后 job/断开还能收敛撤销。"""
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"k" * 32).decode())
    user = make_user(conn)
    sealed = user["gh_token_enc"]
    monkeypatch.setattr(config, "TOKEN_ENC_KEY", base64.b64encode(b"j" * 32).decode())
    with pytest.raises(security.TokenKeyMismatchError):
        star_sync._load_token(conn, user)
    u = conn.execute("SELECT gh_token_enc, gh_star_authed_at FROM users WHERE id=1").fetchone()
    assert u["gh_token_enc"] == sealed and u["gh_star_authed_at"] > 0
    assert conn.execute("SELECT count(*) c FROM star_syncs WHERE last_error='token revoked'"
                        ).fetchone()["c"] == 0


def test_load_token_tamper_still_wipes_dead_token(conn):
    """对照：kid 相符但解不开（真篡改）才按死 token 清密文——已无恢复可能。"""
    user = make_user(conn)
    head, kid, payload = user["gh_token_enc"].split(".")
    tampered = f"{head}.{kid}.{'A' if payload[0] != 'A' else 'B'}{payload[1:]}"
    conn.execute("UPDATE users SET gh_token_enc=? WHERE id=1", (tampered,))
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE id=1").fetchone()
    assert star_sync._load_token(conn, user) is None
    u = conn.execute("SELECT gh_token_enc FROM users WHERE id=1").fetchone()
    assert u["gh_token_enc"] == ""


def test_on_done_writeback_retracted_when_cancel_lands_midwrite(conn, monkeypatch):
    """A6 写回夹缝 TOCTOU：取消落在「写回前检查」与 (starred, done) 写回之间——
    守卫翻转模拟该夹缝，写回后复查必须走撤销路径，孤儿 done 行不得存活。"""
    user = make_user(conn)
    repo = make_repo(conn)
    make_fav(conn)
    calls = patch_github(monkeypatch)
    real = star_sync._favorite_still_wanted
    state = {"checks": 0}

    def flip(c, uid, rid):
        state["checks"] += 1
        if state["checks"] == 2:  # 写回后复查：此刻用户取消已落地
            c.execute("DELETE FROM interactions WHERE user_id=? AND repo_id=? AND kind='favorite'",
                      (uid, rid))
            c.commit()
        return real(c, uid, rid)

    monkeypatch.setattr(star_sync, "_favorite_still_wanted", flip)
    assert star_sync.sync_favorite_on(conn, user, repo) == "unstarred"
    assert calls["star"] == ["other/proj"]      # 点星已发出
    assert calls["unstar"] == ["other/proj"]    # 写回被复查撤销
    assert sync_row(conn) is None               # 无孤儿 (starred, done) 行


# ---------- 授权回调当场重放（spec 2026-09-28，replay_row）----------
def test_backfill_replays_pending_unstar(conn, monkeypatch):
    """【授权并同步取消】落的待撤行在授权回调当场撤星。"""
    user = make_user(conn)
    repo = make_repo(conn)
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, attempts, updated_at)"
                 " VALUES (1, 1, 'unstarred', 'pending', 1, 1)")
    conn.commit()
    calls = patch_github(monkeypatch)
    star_sync.backfill_user(conn, 1)
    assert calls["unstar"] == ["other/proj"]
    assert sync_row(conn) is None


def test_replay_row_dels_row_when_user_missing(conn, monkeypatch):
    conn.execute("PRAGMA foreign_keys=OFF")  # 直接种孤儿行（user_id=9 不存在），FK 需暂关
    conn.execute("INSERT INTO star_syncs (user_id, repo_id, desired, applied, updated_at)"
                 " VALUES (9, 1, 'unstarred', 'pending', 1)")
    conn.commit()
    calls = patch_github(monkeypatch)
    row = conn.execute("SELECT * FROM star_syncs").fetchone()
    assert star_sync.replay_row(conn, row) == "kept"
    assert conn.execute("SELECT count(*) c FROM star_syncs").fetchone()["c"] == 0
    assert calls["unstar"] == []
