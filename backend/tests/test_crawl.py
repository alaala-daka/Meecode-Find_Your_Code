"""采集任务：日配额、单仓库失败不中断整批、已存在仓库不覆盖作者文案。"""
from app import config
from app.feed import github, screening
from app.feed.jobs import crawl
from app.feed.schemas import ScreeningResult

NOW = 1_700_000_000
LONG_README = "这是一个真实项目的说明文档。" * 60


def _stub_pipeline(monkeypatch, *, n_repos: int = 5, fail_on: str = ""):
    repos = [
        {
            "id": 1000 + i, "full_name": f"dev{i}/proj{i}", "owner_login": f"dev{i}",
            "language": "Python", "topics": [], "stars": 30,
            "created_at": NOW - 7 * 86400, "pushed_at": NOW - 86400,
            "license": "MIT", "default_branch": "main", "archived": False,
        }
        for i in range(n_repos)
    ]
    monkeypatch.setattr(config, "CRAWL_LANGUAGES", ("Python",))
    monkeypatch.setattr(github, "search_new_repos", lambda lang, now=None: repos)
    monkeypatch.setattr(github, "get_user", lambda login: {"followers": 10})

    def readme(full_name: str) -> str:
        if fail_on and fail_on in full_name:
            raise github.GitHubError("模拟单仓库失败")
        return LONG_README

    monkeypatch.setattr(github, "get_readme", readme)
    monkeypatch.setattr(github, "get_tree", lambda fn, br="main": [
        {"path": f"src/f{i}.py", "type": "blob", "size": 100} for i in range(8)
    ])
    monkeypatch.setattr(config, "LLM_MOCK", True)
    return repos


def test_inserts_passing_repos(conn, monkeypatch):
    _stub_pipeline(monkeypatch, n_repos=3)
    stats = crawl.crawl_once(conn, now=NOW)
    assert stats["inserted"] == 3
    rows = conn.execute("SELECT * FROM repos").fetchall()
    assert {r["source"] for r in rows} == {"crawled"}
    assert {r["status"] for r in rows} == {"pending_claim"}
    assert all(r["tagline_zh"] for r in rows)


def test_respects_daily_quota(conn, monkeypatch):
    _stub_pipeline(monkeypatch, n_repos=10)
    monkeypatch.setattr(config, "CRAWL_DAILY_QUOTA", 4)
    stats = crawl.crawl_once(conn, now=NOW)
    assert stats["inserted"] == 4
    assert conn.execute("SELECT count(*) c FROM repos").fetchone()["c"] == 4


def test_single_repo_failure_does_not_abort_batch(conn, monkeypatch):
    _stub_pipeline(monkeypatch, n_repos=5, fail_on="proj2")
    stats = crawl.crawl_once(conn, now=NOW)
    assert stats["inserted"] == 4
    assert stats["skipped"] >= 1
    names = {r["full_name"] for r in conn.execute("SELECT full_name FROM repos")}
    assert "dev2/proj2" not in names


def test_rule_rejected_repos_never_reach_llm(conn, monkeypatch):
    _stub_pipeline(monkeypatch, n_repos=2)
    monkeypatch.setattr(github, "get_readme", lambda fn: "太短")
    called = {"n": 0}

    def spy(*a, **kw):
        called["n"] += 1
        raise AssertionError("粗筛未通过的仓库不应调用 LLM")

    monkeypatch.setattr(screening, "screen_repo", spy)
    stats = crawl.crawl_once(conn, now=NOW)
    assert stats["inserted"] == 0 and called["n"] == 0


def test_llm_rejected_repo_is_discarded(conn, monkeypatch):
    """采集端精筛不达标即丢弃（与投稿端不同）。"""
    _stub_pipeline(monkeypatch, n_repos=2)
    from app.feed.schemas import ScreeningResult
    monkeypatch.setattr(screening, "screen_repo", lambda *a, **kw: ScreeningResult(
        is_real_project=False, category="其他", tagline_zh="", why_zh="", quality=2))
    stats = crawl.crawl_once(conn, now=NOW)
    assert stats["inserted"] == 0


def test_rerun_does_not_duplicate_or_overwrite_author_copy(conn, monkeypatch):
    """作者认领后再次采集到同一仓库，不能覆盖作者写的文案。"""
    _stub_pipeline(monkeypatch, n_repos=1)
    crawl.crawl_once(conn, now=NOW)
    conn.execute(
        "UPDATE repos SET status='published', source='submitted',"
        " tagline_zh='作者亲手写的卖点' WHERE github_id = 1000"
    )
    conn.commit()
    crawl.crawl_once(conn, now=NOW + 86400)
    rows = conn.execute("SELECT * FROM repos WHERE github_id = 1000").fetchall()
    assert len(rows) == 1
    assert rows[0]["tagline_zh"] == "作者亲手写的卖点"
    assert rows[0]["status"] == "published"


def test_llm_failure_skips_repo_without_crashing(conn, monkeypatch):
    _stub_pipeline(monkeypatch, n_repos=3)

    def boom(*a, **kw):
        raise RuntimeError("LLM 挂了")

    monkeypatch.setattr(screening, "screen_repo", boom)
    stats = crawl.crawl_once(conn, now=NOW)  # 不抛异常
    assert stats["inserted"] == 0 and stats["skipped"] == 3


def test_llm_only_for_topk(monkeypatch, conn):
    """规则通过 3 个、配额 1 + 缓冲 1:LLM 只跑 2 次,而不是 3 次。"""
    monkeypatch.setattr(config, "CRAWL_LANGUAGES", ("Python",))
    monkeypatch.setattr(config, "CRAWL_DAILY_QUOTA", 1)
    monkeypatch.setattr(config, "CRAWL_SCREEN_BUFFER", 1)
    # created_at/pushed_at 取近期(相对 now):否则粗筛必拒,测不到 top-K 语义
    monkeypatch.setattr(github, "search_new_repos", lambda lang, now=None: [
        {"id": 100 + i, "full_name": f"o/r{i}", "owner_login": "o", "language": "Python",
         "topics": [], "stars": 50, "created_at": (now or 1_800_000_000) - 7 * 86400,
         "pushed_at": (now or 1_800_000_000) - 86400, "license": "",
         "default_branch": "main", "archived": False} for i in range(3)])
    monkeypatch.setattr(github, "get_readme", lambda *a: "r" * 600)
    monkeypatch.setattr(github, "get_tree", lambda *a, **k: [
        {"path": f"f{i}.py", "type": "blob", "size": 1} for i in range(6)])
    monkeypatch.setattr(github, "get_user", lambda *a: {"followers": 0})
    calls: list[str] = []

    def fake_screen(full_name, readme, tree, **kw):
        calls.append(full_name)
        return ScreeningResult(is_real_project=True, category="开发工具",
                               tagline_zh="t", why_zh="w", quality=4)

    monkeypatch.setattr(screening, "screen_repo", fake_screen)
    stats = crawl.crawl_once(conn, now=1_800_000_000)
    assert len(calls) == 2  # K = quota + buffer
    assert stats["inserted"] == 1


def test_rescreen_pending_updates_quality_only(conn, monkeypatch):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status, tagline_zh,"
        " intro_zh, quality, screened, readme_md, default_branch, category, published_at)"
        " VALUES (1, 'a/b', 'a', 'submitted', 'published', '作者卖点', '作者介绍', 3, 0,"
        " 'r' * 600, 'main', '其他', 1756000000)"
    )
    conn.commit()
    monkeypatch.setattr(github, "get_tree", lambda *a, **k: [
        {"path": f"f{i}.py", "type": "blob", "size": 1} for i in range(6)])
    monkeypatch.setattr(screening, "screen_repo", lambda *a, **k: ScreeningResult(
        is_real_project=True, category="数据处理", tagline_zh="AI 卖点", why_zh="w", quality=5))
    done = crawl.rescreen_pending(conn)
    assert done == 1
    row = conn.execute("SELECT * FROM repos WHERE id = 1").fetchone()
    assert row["quality"] == 5 and row["screened"] == 1
    assert row["tagline_zh"] == "作者卖点"  # 作者文案绝不被 AI 覆盖
    assert row["category"] == "其他"       # 投稿的分类也不动


def test_rescreen_llm_failure_keeps_pending(conn, monkeypatch):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status, quality,"
        " screened, readme_md, default_branch, published_at)"
        " VALUES (1, 'a/b', 'a', 'crawled', 'pending_claim', 3, 0, 'r' * 600, 'main', 1756000000)"
    )
    conn.commit()

    def boom(*a, **k):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(github, "get_tree", lambda *a, **k: [])
    monkeypatch.setattr(screening, "screen_repo", boom)
    assert crawl.rescreen_pending(conn) == 0
    assert conn.execute("SELECT screened FROM repos WHERE id = 1").fetchone()["screened"] == 0


def test_crawl_once精筛记账route归属(conn, monkeypatch):
    from app import llm_usage

    seen: list[tuple] = []

    def spy(*a, **kw):
        seen.append((kw.get("route"), kw.get("repo_id")))
        return ScreeningResult(is_real_project=True, category="其他",
                               tagline_zh="x", why_zh="y", quality=3)

    _stub_pipeline(monkeypatch, n_repos=2)
    monkeypatch.setattr(screening, "screen_repo", spy)  # 覆盖 _stub_pipeline 的替换（后者生效）
    crawl.crawl_once(conn, now=NOW)
    assert seen and all((r, ri) == (llm_usage.ROUTE_CRAWL_SCREEN, None) for r, ri in seen)


def test_rescreen补筛记账route与repo_id归属(conn, monkeypatch):
    from app import llm_usage

    seen: list[tuple] = []

    def spy(*a, **kw):
        seen.append((kw.get("route"), kw.get("repo_id")))
        return ScreeningResult(is_real_project=True, category="数据处理",
                               tagline_zh="x", why_zh="w", quality=5)

    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status, tagline_zh,"
        " intro_zh, quality, screened, readme_md, default_branch, category, published_at)"
        " VALUES (1, 'a/b', 'a', 'submitted', 'published', '作者卖点', '作者介绍', 3, 0,"
        " 'r' * 600, 'main', '其他', 1756000000)")
    conn.commit()
    rid = conn.execute("SELECT id FROM repos").fetchone()["id"]
    monkeypatch.setattr(github, "get_tree", lambda *a, **k: [
        {"path": f"f{i}.py", "type": "blob", "size": 1} for i in range(6)])
    monkeypatch.setattr(screening, "screen_repo", spy)

    assert crawl.rescreen_pending(conn) == 1
    assert seen == [(llm_usage.ROUTE_CRAWL_SCREEN, rid)]
