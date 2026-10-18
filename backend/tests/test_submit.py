"""投稿：归属校验、LLM 故障不阻塞发布、认领复用记录、下架。"""
import pytest
from fastapi.testclient import TestClient

from app.feed import auth, deps, github, screening
from app.feed.schemas import ScreeningResult
from app import config, llm_usage
from app.main import app

NOW = 1_700_000_000


@pytest.fixture()
def client(conn, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_MOCK", True)
    monkeypatch.setattr(config, "LLM_MOCK", True)
    app.dependency_overrides[deps.get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def login(conn, client):
    uid = auth.upsert_user(conn, {"id": 700, "login": "demo", "avatar_url": ""})
    client.cookies.set(config.SESSION_COOKIE, auth.sign(uid))
    return uid


def payload(**kw) -> dict:
    base = {
        "full_name": "demo/agent-runtime", "tagline_zh": "我写的卖点",
        "intro_zh": "我写的介绍", "category": "开发工具", "cover_url": "",
    }
    return {**base, **kw}


def test_requires_login(client):
    assert client.post("/api/submit", json=payload()).status_code == 401
    assert client.get("/api/my/github-repos").status_code == 401


def test_lists_own_repos(client, login):
    items = client.get("/api/my/github-repos").json()
    assert items and all("full_name" in r for r in items)


def test_submit_publishes_immediately(conn, client, login):
    card = client.post("/api/submit", json=payload()).json()
    row = conn.execute("SELECT * FROM repos WHERE id=?", (card["id"],)).fetchone()
    assert row["source"] == "submitted"
    assert row["status"] == "published"
    assert row["tagline_zh"] == "我写的卖点"   # 作者文案优先于 LLM
    assert row["claimed_by"] == login
    assert row["published_at"] > 0


def test_submit_rejects_repo_not_owned(client, login, monkeypatch):
    """归属校验：只能投自己 owner 的仓库。"""
    monkeypatch.setattr(github, "list_user_repos", lambda login_: [
        {"id": 55555, "full_name": "someone-else/proj", "owner_login": "someone-else",
         "language": "Go", "topics": [], "stars": 1, "created_at": NOW,
         "pushed_at": NOW, "license": "", "default_branch": "main"}
    ])
    resp = client.post("/api/submit", json=payload(full_name="someone-else/proj"))
    assert resp.status_code == 403
    assert "自己" in resp.json()["detail"]


def test_submit_rejects_unknown_full_name(client, login):
    assert client.post("/api/submit", json=payload(full_name="demo/ghost")).status_code == 404


def test_submit_rejects_unknown_category(client, login):
    resp = client.post("/api/submit", json=payload(category="编造的分类"))
    assert resp.status_code == 422


def test_submit_rejects_empty_tagline(client, login):
    assert client.post("/api/submit", json=payload(tagline_zh="   ")).status_code == 422


def test_no_quality_gate_low_score_still_publishes(conn, client, login, monkeypatch):
    """投稿不设质量门：LLM 判低分甚至判非真实项目，照样发布。"""
    from app.feed.schemas import ScreeningResult
    monkeypatch.setattr(screening, "screen_repo", lambda *a, **kw: ScreeningResult(
        is_real_project=False, category="其他", tagline_zh="", why_zh="", quality=1))
    card = client.post("/api/submit", json=payload()).json()
    row = conn.execute("SELECT * FROM repos WHERE id=?", (card["id"],)).fetchone()
    assert row["status"] == "published" and row["quality"] == 1


def test_llm_failure_does_not_block_publish(conn, client, login, monkeypatch):
    """spec 第 9 节：作者的发布动作永不因 LLM 故障被阻塞。"""
    def boom(*a, **kw):
        raise RuntimeError("LLM 挂了")
    monkeypatch.setattr(screening, "screen_repo", boom)
    resp = client.post("/api/submit", json=payload())
    assert resp.status_code == 200
    row = conn.execute("SELECT * FROM repos WHERE id=?", (resp.json()["id"],)).fetchone()
    assert row["status"] == "published"
    assert row["quality"] == config.NEUTRAL_QUALITY
    assert row["screened"] == 0  # 待日跑补齐


def test_github_failure_does_not_block_publish(conn, client, login, monkeypatch):
    """README 拉不到也能发 —— 作者文案已经够展示。"""
    monkeypatch.setattr(config, "GITHUB_MOCK", False)
    monkeypatch.setattr(github, "list_user_repos", lambda l: [
        {"id": 90001, "full_name": "demo/agent-runtime", "owner_login": "demo",
         "language": "TypeScript", "topics": [], "stars": 3, "created_at": NOW,
         "pushed_at": NOW, "license": "MIT", "default_branch": "main"}])
    def boom(*a, **kw):
        raise github.GitHubError("限流")
    monkeypatch.setattr(github, "get_readme", boom)
    monkeypatch.setattr(github, "get_tree", boom)
    assert client.post("/api/submit", json=payload()).status_code == 200


def test_claim_reuses_crawled_record_and_keeps_counters(conn, client, login):
    """认领 = 同一条流程：复用原记录，计数与 id 不丢。"""
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, language, source, status,"
        " quality, published_at, tagline_zh, impression_count, repo_view_count, screened)"
        " VALUES (90001, 'demo/agent-runtime', 'demo', 'TypeScript', 'crawled',"
        " 'pending_claim', 4, ?, 'LLM 写的卖点', 120, 30, 1)", (NOW,))
    conn.commit()
    old_id = conn.execute("SELECT id FROM repos WHERE github_id=90001").fetchone()["id"]

    rid = client.post("/api/submit", json=payload()).json()["id"]
    assert rid == old_id  # 复用，不新建
    row = conn.execute("SELECT * FROM repos WHERE id=?", (rid,)).fetchone()
    assert row["source"] == "submitted" and row["status"] == "published"
    assert row["claimed_by"] == login
    assert row["tagline_zh"] == "我写的卖点"      # 作者文案覆盖 LLM 文案
    assert row["impression_count"] == 120         # 互动数据不丢
    assert row["repo_view_count"] == 30
    assert conn.execute("SELECT count(*) c FROM repos").fetchone()["c"] == 1


def test_claiming_old_crawled_repo_grants_fresh_debut_window(conn, client, login):
    """认领 30 天前采集的仓库，也要拿到 72 小时首发窗口 ——
    否则「投了就有一波真实曝光」对认领者不成立。"""
    old = 1_600_000_000  # 远早于窗口
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, language, source, status,"
        " quality, published_at, tagline_zh, screened)"
        " VALUES (90001, 'demo/agent-runtime', 'demo', 'TypeScript', 'crawled',"
        " 'pending_claim', 4, ?, 'LLM 写的卖点', 1)", (old,))
    conn.commit()

    rid = client.post("/api/submit", json=payload()).json()["id"]
    row = conn.execute("SELECT published_at FROM repos WHERE id=?", (rid,)).fetchone()
    assert row["published_at"] > old  # 认领时刷新，重新起算窗口


def test_resubmit_updates_in_place(conn, client, login):
    first = client.post("/api/submit", json=payload()).json()["id"]
    second = client.post("/api/submit", json=payload(tagline_zh="改了卖点")).json()["id"]
    assert first == second
    row = conn.execute("SELECT * FROM repos WHERE id=?", (first,)).fetchone()
    assert row["tagline_zh"] == "改了卖点"


def test_claiming_someone_elses_crawled_repo_is_forbidden(conn, client, login):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status, published_at)"
        " VALUES (88888, 'other/proj', 'other', 'crawled', 'pending_claim', ?)", (NOW,))
    conn.commit()
    assert client.post("/api/submit", json=payload(full_name="other/proj")).status_code in (403, 404)


def test_delist_by_owner(conn, client, login):
    rid = client.post("/api/submit", json=payload()).json()["id"]
    assert client.post(f"/api/repos/{rid}/delist").status_code == 200
    row = conn.execute("SELECT status FROM repos WHERE id=?", (rid,)).fetchone()
    assert row["status"] == "delisted"


def test_delist_unclaimed_crawled_repo_by_github_owner(conn, client, login):
    """opt-out：未认领也能下架，只要 owner_login 是自己。"""
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status, published_at)"
        " VALUES (77777, 'demo/other-proj', 'demo', 'crawled', 'pending_claim', ?)", (NOW,))
    conn.commit()
    rid = conn.execute("SELECT id FROM repos WHERE github_id=77777").fetchone()["id"]
    assert client.post(f"/api/repos/{rid}/delist").status_code == 200


def test_delist_rejects_non_owner(conn, client, login):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status, published_at)"
        " VALUES (66666, 'other/proj', 'other', 'crawled', 'pending_claim', ?)", (NOW,))
    conn.commit()
    rid = conn.execute("SELECT id FROM repos WHERE github_id=66666").fetchone()["id"]
    assert client.post(f"/api/repos/{rid}/delist").status_code == 403


def test_ai_draft_returns_text(client, login):
    body = client.post("/api/ai-draft", json={"github_id": 90001}).json()
    assert body["tagline_zh"]


def test_ai_draft_failure_returns_empty_not_500(client, login, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("LLM 挂了")
    monkeypatch.setattr(screening, "screen_repo", boom)
    resp = client.post("/api/ai-draft", json={"github_id": 90001})
    assert resp.status_code == 200
    assert resp.json()["tagline_zh"] == ""  # 前端提示手写


import pytest as _pytest
from pydantic import ValidationError

from app.feed.schemas import SubmitIn


def test_cover_url_rejects_non_http():
    with _pytest.raises(ValidationError):
        SubmitIn(full_name="demo/agent-runtime", tagline_zh="x", cover_url="javascript:alert(1)")


def test_cover_url_rejects_too_long():
    with _pytest.raises(ValidationError):
        SubmitIn(full_name="demo/agent-runtime", tagline_zh="x", cover_url="https://" + "a" * 500)


def test_cover_url_accepts_https_and_empty():
    assert SubmitIn(full_name="demo/agent-runtime", tagline_zh="x", cover_url="https://x/y.png").cover_url
    assert SubmitIn(full_name="demo/agent-runtime", tagline_zh="x", cover_url="").cover_url == ""


def test_cover_url_accepts_null_as_empty():
    """前端恒发 cover_url=null:必须归一为空串而非 422(后端适配前端类型)。"""
    assert SubmitIn(full_name="demo/agent-runtime", tagline_zh="x", cover_url=None).cover_url == ""


def test_my_github_repos_shape(client, login, conn, monkeypatch):
    monkeypatch.setattr(github, "list_user_repos", lambda login_: [
        {"id": 7, "full_name": "demo/mine", "owner_login": "demo", "language": "Go",
         "topics": [], "stars": 12, "created_at": NOW, "pushed_at": NOW,
         "license": "", "default_branch": "main"},
        {"id": 8, "full_name": "demo/published", "owner_login": "demo", "language": "Rust",
         "topics": [], "stars": 3, "created_at": NOW, "pushed_at": NOW,
         "license": "", "default_branch": "main"},
    ])
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status)"
        " VALUES (8, 'demo/published', 'demo', 'submitted', 'published')"
    )
    conn.commit()
    body = client.get("/api/my/github-repos").json()
    mine = {r["full_name"]: r for r in body}
    assert mine["demo/mine"]["status"] == "" and mine["demo/mine"]["title"] == "mine"
    assert mine["demo/published"]["status"] == "published"
    assert all("github_id" in r for r in body)


def test_my_github_repos_masks_delisted_as_unsubmitted(client, login, conn, monkeypatch):
    """三态徽标契约只有 ''|published|pending_claim:已下架的仓库必须回落到 '',
    下架后允许重新投稿,前端据此把按钮恢复成「投稿」。"""
    monkeypatch.setattr(github, "list_user_repos", lambda login_: [
        {"id": 9, "full_name": "demo/gone", "owner_login": "demo", "language": "Go",
         "topics": [], "stars": 1, "created_at": NOW, "pushed_at": NOW,
         "license": "", "default_branch": "main"},
    ])
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status)"
        " VALUES (9, 'demo/gone', 'demo', 'submitted', 'delisted')"
    )
    conn.commit()
    mine = {r["full_name"]: r for r in client.get("/api/my/github-repos").json()}
    assert mine["demo/gone"]["status"] == ""


def test_submit_by_full_name_returns_card(client, login, conn, monkeypatch):
    monkeypatch.setattr(github, "list_user_repos", lambda login_: [
        {"id": 7, "full_name": "demo/mine", "owner_login": "demo", "language": "Go",
         "topics": [], "stars": 12, "created_at": NOW, "pushed_at": NOW,
         "license": "", "default_branch": "main"},
    ])
    monkeypatch.setattr(github, "get_readme", lambda *a, **k: "x" * 600)
    monkeypatch.setattr(github, "get_tree", lambda *a, **k: [
        {"path": f"f{i}.py", "type": "blob", "size": 1} for i in range(6)])
    monkeypatch.setattr(screening, "screen_repo",
                        lambda *a, **k: ScreeningResult(is_real_project=True, category="开发工具",
                                                        tagline_zh="t", why_zh="w", quality=4))
    resp = client.post("/api/submit", json={
        "full_name": "demo/mine", "tagline_zh": "卖点", "intro_zh": "介绍",
        "category": "开发工具", "cover_url": None})  # 前端真实载荷:恒发 null,不得因封面 422
    assert resp.status_code == 200, resp.text
    card = resp.json()
    assert card["full_name"] == "demo/mine" and card["title"] == "mine"
    assert card["source"] == "submitted" and card["views"] == 0
    row = conn.execute("SELECT id FROM repos WHERE github_id = 7").fetchone()
    assert row["id"] == card["id"]  # 卡片 id = 觅码内部 id


def test_ai_draft_has_suggested_category(client, login, monkeypatch):
    monkeypatch.setattr(github, "list_user_repos", lambda login_: [
        {"id": 7, "full_name": "demo/mine", "owner_login": "demo", "language": "Go",
         "topics": [], "stars": 12, "created_at": NOW, "pushed_at": NOW,
         "license": "", "default_branch": "main"}])
    monkeypatch.setattr(github, "get_readme", lambda *a, **k: "x")
    monkeypatch.setattr(github, "get_tree", lambda *a, **k: [])
    monkeypatch.setattr(screening, "screen_repo",
                        lambda *a, **k: ScreeningResult(is_real_project=True, category="数据处理",
                                                        tagline_zh="t", why_zh="w", quality=4))
    body = client.post("/api/ai-draft", json={"github_id": 7}).json()
    assert body["suggested_category"] == "数据处理"


def test_screen_repo记账route归属_submit与ai_draft(client, login, monkeypatch):
    from app.feed import screening
    from app.feed.schemas import ScreeningResult

    seen: list[str] = []

    def spy(*a, **kw):
        seen.append(kw.get("route"))
        return ScreeningResult(is_real_project=True, category="其他",
                               tagline_zh="x", why_zh="y", quality=3)

    monkeypatch.setattr(screening, "screen_repo", spy)
    client.post("/api/submit", json=payload())
    client.post("/api/ai-draft", json={"github_id": 90001})
    assert seen == [llm_usage.ROUTE_SUBMIT_SCREEN, llm_usage.ROUTE_AI_DRAFT]
