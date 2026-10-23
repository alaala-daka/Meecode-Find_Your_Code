"""feed：预留位生效、曝光计数、分类与搜索、delisted 不可见。"""
import time

import pytest
from fastapi.testclient import TestClient

from app import config
from app.feed import db, deps
from app.main import app

NOW = 1_700_000_000


@pytest.fixture()
def client(conn, monkeypatch):
    app.dependency_overrides[deps.get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def client_and_conn():
    c = db.connect(":memory:")
    db.init_db(c)
    app.dependency_overrides[deps.get_conn] = lambda: c
    yield TestClient(app), c
    app.dependency_overrides.clear()
    c.close()


def add_repo(conn, gid: int, *, source="crawled", status="published",
             quality=3, published_at=NOW, category="开发工具", tagline="卖点"):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, language, source, status,"
        " quality, published_at, category, tagline_zh, screened)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,1)",
        (gid, f"dev{gid}/proj{gid}", f"dev{gid}", "Python", source, status,
         quality, published_at, category, tagline),
    )
    conn.commit()


def _seed(conn, *, github_id=1, full_name="a/b", category="开发工具", source="submitted",
          published_at=None, stars=5, status="published", views=7,
          language="Python", topics="t1,t2", pushed_at=0):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, language, topics, stars,"
        " source, status, category, tagline_zh, published_at, repo_view_count, pushed_at)"
        " VALUES (?, ?, 'a', ?, ?, ?, ?, ?, ?, '一句话', ?, ?, ?)",
        (github_id, full_name, language, topics, stars, source, status, category,
         published_at or 0, views, pushed_at),
    )
    conn.commit()


def test_categories_endpoint(client_and_conn):
    client, _conn = client_and_conn
    resp = client.get("/api/categories")
    assert resp.status_code == 200
    cats = resp.json()
    assert cats[0] == "开发工具" and len(cats) == 8


def test_feed_shape_matches_frontend(client_and_conn):
    client, conn = client_and_conn
    _seed(conn, published_at=1756000000)
    body = client.get("/api/feed").json()
    assert set(body.keys()) == {"cards", "has_more", "total"}   # ← 新增 total
    assert body["total"] == 1
    c = body["cards"][0]
    assert c["title"] == "b" and c["views"] == 7 and c["likes"] == 0
    assert c["published_at"] == "2025-08-24T01:46:40+00:00"
    assert c["cover_url"] is None and c["language"] == "Python"


def test_feed_filters_lang_and_stars(client_and_conn):
    client, conn = client_and_conn
    _seed(conn, github_id=1, full_name="a/py", language="Python", stars=200)
    _seed(conn, github_id=2, full_name="a/go", language="Go", stars=200)
    _seed(conn, github_id=3, full_name="a/py-small", language="Python", stars=10)
    names = lambda body: {c["full_name"] for c in body["cards"]}
    assert names(client.get("/api/feed", params={"lang": "python"}).json()) == {"a/py", "a/py-small"}
    assert names(client.get("/api/feed", params={"lang": "Python", "stars": "100"}).json()) == {"a/py"}
    body = client.get("/api/feed", params={"stars_max": "50"}).json()
    assert names(body) == {"a/py-small"} and body["total"] == 1


def test_feed_filters_since_uses_pushed_at(client_and_conn):
    """时间范围按最近更新时间（pushed_at），不是入库时间（spec 决策 #2）。"""
    client, conn = client_and_conn
    now = int(time.time())   # test_feed.py 顶部已有 import time
    _seed(conn, github_id=1, full_name="a/fresh", published_at=0, pushed_at=now - 86400)
    _seed(conn, github_id=2, full_name="a/stale", published_at=now, pushed_at=now - 40 * 86400)
    body = client.get("/api/feed", params={"since": "7d"}).json()
    assert {c["full_name"] for c in body["cards"]} == {"a/fresh"}
    assert body["total"] == 1


def test_feed_filters_topic_and_semantics(client_and_conn):
    client, conn = client_and_conn
    _seed(conn, github_id=1, full_name="a/both", topics="llm,self-hosted")
    _seed(conn, github_id=2, full_name="a/one", topics="llm")
    body = client.get("/api/feed", params={"topic": ["llm", "self-hosted"]}).json()
    assert {c["full_name"] for c in body["cards"]} == {"a/both"}
    # 逗号子串不误命中：topic=hosted 不得命中 self-hosted
    assert client.get("/api/feed", params={"topic": "hosted"}).json()["total"] == 0


def test_feed_filters_combined_and_pagination(client_and_conn):
    client, conn = client_and_conn
    for i in range(30):
        _seed(conn, github_id=i, full_name=f"a/r{i}", language="Python",
              stars=100 + i, topics="llm", pushed_at=1)
    body = client.get("/api/feed", params={"lang": "Python", "stars": "100", "topic": "llm"})
    data = body.json()
    assert data["total"] == 30 and data["has_more"] is True and len(data["cards"]) == 24
    page2 = client.get("/api/feed", params={"lang": "Python", "stars": "100", "topic": "llm", "page": 2}).json()
    assert len(page2["cards"]) == 6 and page2["has_more"] is False


def test_feed_filters_reject_bad_values(client_and_conn):
    client, _conn = client_and_conn
    assert client.get("/api/feed", params={"lang": "语言"}).status_code == 422
    assert client.get("/api/feed", params={"since": "2024"}).status_code == 422
    assert client.get("/api/feed", params={"stars": "500", "stars_max": "100"}).status_code == 422
    assert client.get("/api/feed", params={"topic": ["a", "b", "c", "d", "e", "f"]}).status_code == 422


def test_feed_unknown_params_ignored(client_and_conn):
    """未知参数静默忽略（白名单硬约束的另一半）；非法值才 422。"""
    client, conn = client_and_conn
    _seed(conn)
    assert client.get("/api/feed", params={"foo": "1", "bar": "x"}).status_code == 200


def test_feed_likes_counted(client_and_conn):
    client, conn = client_and_conn
    _seed(conn)
    conn.execute("INSERT INTO users (github_id, login) VALUES (1, 'u')")
    conn.execute("INSERT INTO interactions (user_id, repo_id, kind, updated_at) VALUES (1, 1, 'like', 1)")
    conn.execute("INSERT INTO interactions (user_id, repo_id, kind, updated_at) VALUES (1, 1, 'favorite', 1)")
    conn.commit()
    card = client.get("/api/feed").json()["cards"][0]
    assert card["likes"] == 1  # favorite 不计入 likes


def test_search_sort_and_total(client_and_conn):
    client, conn = client_and_conn
    _seed(conn, full_name="a/fastdb", category="系统与底层")
    _seed(conn, github_id=2, full_name="a/otherdb", category="系统与底层", stars=99)
    body = client.get("/api/search", params={"q": "otherdb", "sort": "default", "page": 1}).json()
    assert body["total"] == 1 and body["cards"][0]["full_name"] == "a/otherdb"
    assert set(body.keys()) == {"cards", "has_more", "total"}
    assert client.get("/api/search", params={"q": "db", "sort": "stars"}).json()["cards"][0]["stars"] == 99
    assert client.get("/api/search", params={"q": "db", "sort": "newest"}).status_code == 200
    assert client.get("/api/search", params={"q": "db", "sort": "bogus"}).status_code == 422


def test_search_short_query_like_fallback(client_and_conn):
    """FTS5 trigram 需要 >=3 字符;短词回退 LIKE,否则 'AI' 静默零结果。"""
    client, conn = client_and_conn
    _seed(conn, full_name="ai-tools/helper")
    body = client.get("/api/search", params={"q": "ai-tools", "page": 1}).json()
    assert body["total"] == 1 and body["cards"][0]["full_name"] == "ai-tools/helper"


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_feed_shows_published_and_pending_claim(conn, client):
    """采集仓库入库即 pending_claim，必须能上首页 —— 否则第二目的落空。
    只有 delisted（作者 opt-out）不可见。"""
    add_repo(conn, 1, status="published")
    add_repo(conn, 2, status="pending_claim")
    add_repo(conn, 3, status="delisted")
    names = {c["full_name"] for c in client.get("/api/feed").json()["cards"]}
    assert names == {"dev1/proj1", "dev2/proj2"}


def test_feed_reserves_slots_for_recent_submissions(conn, client, monkeypatch):
    monkeypatch.setattr(config, "FEED_PAGE_SIZE", 10)
    for i in range(30):
        # 采集侧质量 5 > 投稿质量 1，且同样新鲜：纯 score 投稿永远排不进
        # 第一页 —— 只有预留位接线能让低质投稿上榜，测试才具区分度
        add_repo(conn, 100 + i, source="crawled", quality=5,
                 published_at=int(time.time()))
    for i in range(5):
        # 投稿须在 72h 首发窗口内才占预留位（spec：预留位只给窗口内投稿），
        # 故 published_at 取真实当前时间，与路由内 time.time() 对齐
        add_repo(conn, 200 + i, source="submitted", quality=1,
                 published_at=int(time.time()))  # 质量最低
    cards = client.get("/api/feed").json()["cards"]
    assert len(cards) == 10
    n_sub = sum(1 for c in cards if c["source"] == "submitted")
    assert n_sub >= 4  # ceil(10*0.4)：低质投稿也拿到预留位


def test_feed_bumps_impression_count(conn, client):
    add_repo(conn, 1)
    client.get("/api/feed")
    client.get("/api/feed")
    row = conn.execute("SELECT impression_count FROM repos WHERE github_id=1").fetchone()
    assert row["impression_count"] == 2


def test_feed_does_not_bump_repos_not_returned(conn, client, monkeypatch):
    monkeypatch.setattr(config, "FEED_PAGE_SIZE", 1)
    add_repo(conn, 1, published_at=NOW)
    add_repo(conn, 2, published_at=NOW - 90 * 86400)  # 很旧，排第二页
    client.get("/api/feed")
    counts = {r["github_id"]: r["impression_count"]
              for r in conn.execute("SELECT github_id, impression_count FROM repos")}
    assert counts[1] == 1 and counts[2] == 0


def test_feed_filters_by_category(conn, client):
    add_repo(conn, 1, category="开发工具")
    add_repo(conn, 2, category="AI 与机器学习")
    cards = client.get("/api/feed", params={"category": "AI 与机器学习"}).json()["cards"]
    assert [c["full_name"] for c in cards] == ["dev2/proj2"]


def test_feed_rejects_unknown_category(client):
    assert client.get("/api/feed", params={"category": "编造的"}).status_code == 422


def test_feed_pagination_has_no_overlap(conn, client, monkeypatch):
    monkeypatch.setattr(config, "FEED_PAGE_SIZE", 5)
    for i in range(12):
        add_repo(conn, 300 + i, published_at=NOW - i * 3600)
    p1 = {c["id"] for c in client.get("/api/feed", params={"page": 1}).json()["cards"]}
    p2 = {c["id"] for c in client.get("/api/feed", params={"page": 2}).json()["cards"]}
    assert len(p1) == len(p2) == 5 and not (p1 & p2)


def test_feed_card_carries_cover_inputs(conn, client):
    add_repo(conn, 1)
    card = client.get("/api/feed").json()["cards"][0]
    for key in ("language", "topics", "stars", "source", "tagline_zh", "owner_login"):
        assert key in card  # 前端 SVG 封面所需


def test_search_matches_chinese_tagline(conn, client):
    add_repo(conn, 1, tagline="给 Agent 的最小运行时")
    add_repo(conn, 2, tagline="一个数据可视化工具")
    cards = client.get("/api/search", params={"q": "运行时"}).json()["cards"]
    assert [c["full_name"] for c in cards] == ["dev1/proj1"]


def test_search_includes_pending_claim(conn, client):
    add_repo(conn, 1, status="pending_claim", tagline="待认领的采集仓库")
    cards = client.get("/api/search", params={"q": "待认领"}).json()["cards"]
    assert [c["full_name"] for c in cards] == ["dev1/proj1"]


def test_search_empty_query_returns_empty(client):
    assert client.get("/api/search", params={"q": "  "}).json()["cards"] == []


def test_search_special_chars_do_not_crash(conn, client):
    add_repo(conn, 1)
    for q in ('"', "AND", "*", "a OR b", "NEAR("):
        assert client.get("/api/search", params={"q": q}).status_code == 200


def test_search_excludes_delisted(conn, client):
    add_repo(conn, 1, status="delisted", tagline="给 Agent 的最小运行时")
    assert client.get("/api/search", params={"q": "运行时"}).json()["cards"] == []


def test_search_filters_apply_over_fts_and_like(client_and_conn):
    """过滤条件 AND 进两种命中路径：FTS（>=3 字符）与 LIKE 回退（<3 字符）。"""
    client, conn = client_and_conn
    _seed(conn, github_id=1, full_name="a/fastdb", language="Python", stars=500, topics="db")
    _seed(conn, github_id=2, full_name="a/fastdb2", language="Go", stars=10, topics="db")

    fts = client.get("/api/search", params={"q": "fastdb", "lang": "Python"}).json()
    assert {c["full_name"] for c in fts["cards"]} == {"a/fastdb"} and fts["total"] == 1

    like = client.get("/api/search", params={"q": "db", "stars": "100"}).json()
    assert {c["full_name"] for c in like["cards"]} == {"a/fastdb"} and like["total"] == 1


def test_search_filters_with_sort_and_topics(client_and_conn):
    client, conn = client_and_conn
    _seed(conn, github_id=1, full_name="a/aaa", stars=10, topics="llm,self-hosted")
    _seed(conn, github_id=2, full_name="a/bbb", stars=99, topics="llm")
    # brief 允许的改写："aaa bbb" 整串短语在本 trigram 实现不分别命中，
    # 改为两个单独 q 断言；过滤交集断言（topic AND）不变
    # q=bbb 命中 a/bbb，但 topic 交集（llm AND self-hosted）把它排除
    body = client.get("/api/search", params={"q": "bbb", "topic": ["llm", "self-hosted"]}).json()
    assert body["cards"] == [] and body["total"] == 0
    # q=aaa 命中 a/aaa，sort=stars 不影响集合
    body = client.get("/api/search", params={
        "q": "aaa", "sort": "stars", "topic": ["llm", "self-hosted"]}).json()
    assert {c["full_name"] for c in body["cards"]} == {"a/aaa"} and body["total"] == 1


def test_search_filters_bad_values_422(client_and_conn):
    client, _conn = client_and_conn
    assert client.get("/api/search", params={"q": "x", "since": "forever"}).status_code == 422


def test_facets_counts_and_delisted_excluded(client_and_conn):
    client, conn = client_and_conn
    _seed(conn, github_id=1, language="Python", topics="llm,self-hosted")
    _seed(conn, github_id=2, language="Python", topics="llm")
    _seed(conn, github_id=3, language="Go", topics="llm", status="delisted")
    body = client.get("/api/facets").json()
    langs = {x["name"]: x["count"] for x in body["languages"]}
    topics = {x["name"]: x["count"] for x in body["topics"]}
    assert langs == {"Python": 2}   # delisted 的 Go 不计入
    assert topics == {"llm": 2, "self-hosted": 1}


def test_facets_cache_hits_until_cleared(client_and_conn):
    client, conn = client_and_conn
    _seed(conn, github_id=1, language="Python", topics="llm")
    assert client.get("/api/facets").json()["languages"][0]["count"] == 1
    _seed(conn, github_id=2, language="Go", topics="cli")   # 缓存未过期：不反映
    stale = client.get("/api/facets").json()
    # 判别性断言（2026-10-23 用户裁决修订）：零缓存实现会算出 Go，命中缓存才必然不含 Go
    assert {x["name"] for x in stale["languages"]} == {"Python"}
    assert [x["count"] for x in stale["languages"]] == [1]
    from app.feed.routes import feed as feed_routes
    feed_routes._clear_facets_cache()
    langs = client.get("/api/facets").json()["languages"]
    assert sum(x["count"] for x in langs) == 2
