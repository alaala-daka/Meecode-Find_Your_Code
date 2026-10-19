"""独立 cron 入口使用真实文件库与 recorder，覆盖批处理事务和记账连接。"""
import json
from types import SimpleNamespace

import pytest

from app import config, llm_usage
from app.feed import auth, db, github, llm, screening
from app.feed.jobs import crawl, moderate


@pytest.fixture()
def job_db(tmp_path, monkeypatch):
    path = str(tmp_path / "jobs.db")
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "LLM_MOCK", False)
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    conn = db.connect()
    db.init_db(conn)
    yield conn
    conn.close()


def _install_llm(monkeypatch, payload):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=2),
        )

    monkeypatch.setattr(llm, "_client", SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    return calls


def _repo(conn, github_id):
    return conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status, screened)"
        " VALUES (?, ?, 'o', 'submitted', 'published', 0)",
        (github_id, f"o/r{github_id}"),
    ).lastrowid


def test_crawl入口精筛和多条补筛全部记账(job_db, monkeypatch):
    pending_ids = {_repo(job_db, 1), _repo(job_db, 2)}
    job_db.commit()
    calls = _install_llm(monkeypatch, {
        "is_real_project": True, "category": "开发工具",
        "tagline_zh": "工具", "why_zh": "说明", "quality": 4,
    })
    monkeypatch.setattr(config, "CRAWL_LANGUAGES", ("Python",))
    monkeypatch.setattr(config, "CRAWL_DAILY_QUOTA", 1)
    monkeypatch.setattr(config, "CRAWL_SCREEN_BUFFER", 0)
    monkeypatch.setattr(config, "CRAWL_RESCREEN_LIMIT", 10)
    monkeypatch.setattr(github, "search_new_repos", lambda *a, **k: [{
        "id": 3, "full_name": "o/new", "owner_login": "o", "stars": 10,
    }])
    monkeypatch.setattr(github, "get_readme", lambda *a, **k: "README")
    monkeypatch.setattr(github, "get_tree", lambda *a, **k: [])
    monkeypatch.setattr(github, "get_user", lambda *a, **k: {"followers": 10})
    monkeypatch.setattr(screening, "passes_rules", lambda *a, **k: (True, ""))

    crawl.main()  # 不经过 Web lifespan，不在测试中预先 bind

    assert llm_usage.flush_for_test(job_db) == 3  # 缓冲语义：显式冲刷后落库
    rows = job_db.execute("SELECT * FROM llm_usage ORDER BY id").fetchall()
    assert len(calls) == len(rows) == 3
    assert rows[0]["repo_id"] is None
    assert {r["repo_id"] for r in rows[1:]} == pending_ids
    assert all(r["route"] == "crawl-screen" and r["ok"] == 1 for r in rows)
    assert all((r["prompt_tokens"], r["completion_tokens"]) == (11, 2) for r in rows)
    assert llm_usage.failures == 0
    assert job_db.execute("SELECT COUNT(*) FROM repos WHERE screened=1").fetchone()[0] == 3


@pytest.mark.parametrize("fail_first", [False, True])
def test_moderate入口逐条提交记账且失败回滚(job_db, monkeypatch, fail_first):
    monkeypatch.setattr(config, "MODERATE_BATCH", 10)
    monkeypatch.setattr(config, "MODERATE_GRACE_SECONDS", 0)
    rid = _repo(job_db, 1)
    uid = auth.upsert_user(job_db, {"id": 1, "login": "u", "avatar_url": "https://a/u"})
    for _ in range(2):
        job_db.execute(
            "INSERT INTO comments (repo_id, user_id, content, status, screened, created_at)"
            " VALUES (?, ?, '评论', 'pending', 0, 0)", (rid, uid))
    job_db.commit()
    ids = [r[0] for r in job_db.execute("SELECT id FROM comments ORDER BY id")]
    calls = _install_llm(monkeypatch, {"is_compliant": True, "reason": ""})
    original = moderate.moderate_comment

    def verdict(conn, cid):
        if fail_first and cid == ids[0]:
            conn.execute("UPDATE comments SET status='hidden' WHERE id=?", (cid,))
            raise RuntimeError("模拟单条事务失败")
        original(conn, cid)

    monkeypatch.setattr(moderate, "moderate_comment", verdict)
    moderate.main()

    assert llm_usage.flush_for_test(job_db) == (1 if fail_first else 2)  # 缓冲语义：显式冲刷后落库
    rows = job_db.execute("SELECT * FROM llm_usage ORDER BY id").fetchall()
    assert len(calls) == len(rows) == (1 if fail_first else 2)
    assert all(r["route"] == "comment-moderate" and r["repo_id"] == rid for r in rows)
    assert all((r["prompt_tokens"], r["completion_tokens"]) == (11, 2) for r in rows)
    assert llm_usage.failures == 0
    comments = [tuple(r) for r in job_db.execute("SELECT status, screened FROM comments ORDER BY id")]
    assert comments == ([("pending", 0), ("visible", 1)] if fail_first else [("visible", 1)] * 2)
