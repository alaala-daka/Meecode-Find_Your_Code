"""建表与 FTS5 同步的最小验证。"""
import sqlite3

from app.feed import db


def test_init_db_creates_tables(conn):
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    )}
    assert {"users", "repos", "interactions", "repos_fts"} <= names


def test_repos_defaults_are_zero(conn):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status)"
        " VALUES (1, 'a/b', 'a', 'submitted', 'published')"
    )
    row = conn.execute("SELECT * FROM repos WHERE github_id = 1").fetchone()
    assert row["impression_count"] == 0
    assert row["repo_view_count"] == 0
    assert row["quality"] == 3  # NEUTRAL_QUALITY：LLM 未跑完也能排序


def test_fts_follows_insert_and_update(conn):
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status, tagline_zh)"
        " VALUES (2, 'x/agent-runtime', 'x', 'submitted', 'published', '给 Agent 的最小运行时')"
    )
    hits = conn.execute(
        "SELECT r.github_id FROM repos_fts f JOIN repos r ON r.id = f.rowid"
        " WHERE repos_fts MATCH '运行时'"
    ).fetchall()
    assert [h["github_id"] for h in hits] == [2]

    conn.execute("UPDATE repos SET tagline_zh = '换成别的说法' WHERE github_id = 2")
    assert conn.execute(
        "SELECT count(*) c FROM repos_fts WHERE repos_fts MATCH '运行时'"
    ).fetchone()["c"] == 0


def test_interactions_upsert_is_idempotent(conn):
    conn.execute("INSERT INTO users (github_id, login) VALUES (9, 'u')")
    conn.execute(
        "INSERT INTO repos (github_id, full_name, owner_login, source, status)"
        " VALUES (3, 'a/c', 'a', 'crawled', 'pending_claim')"
    )
    for _ in range(3):
        conn.execute(
            "INSERT INTO interactions (user_id, repo_id, kind, updated_at)"
            " VALUES (1, 1, 'favorite', 100)"
            " ON CONFLICT(user_id, repo_id, kind) DO UPDATE SET updated_at = excluded.updated_at"
        )
    assert conn.execute("SELECT count(*) c FROM interactions").fetchone()["c"] == 1


def test_init_db_migrates_legacy_users_without_session_epoch():
    """生产升级唯一路径：旧库 users 无 session_epoch，init_db 须 ALTER 补列且默认 0。"""
    legacy = sqlite3.connect(":memory:")
    legacy.row_factory = sqlite3.Row
    legacy.executescript(
        """
        CREATE TABLE users (
            id         INTEGER PRIMARY KEY,
            github_id  INTEGER NOT NULL UNIQUE,
            login      TEXT    NOT NULL,
            avatar_url TEXT    NOT NULL DEFAULT '',
            bio        TEXT    NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL DEFAULT (unixepoch())
        );
        INSERT INTO users (github_id, login) VALUES (7, 'old-user');
        """
    )
    db.init_db(legacy)
    cols = {r["name"]: r["dflt_value"] for r in legacy.execute("PRAGMA table_info(users)")}
    assert "session_epoch" in cols
    assert cols["session_epoch"] == "0"
    row = legacy.execute("SELECT session_epoch FROM users WHERE github_id = 7").fetchone()
    assert row["session_epoch"] == 0
    legacy.close()


def test_init_db_migrates_legacy_comments_without_moderation_reason():
    """生产升级：旧库 comments 无 moderation_reason；ALTER 补列，并把误判 hidden 行
    重置 pending 重审（2026-09-25 上线误杀存量的一次性恢复，仅在补列时执行一次）。"""
    legacy = sqlite3.connect(":memory:")
    legacy.row_factory = sqlite3.Row
    legacy.executescript(
        """
        CREATE TABLE comments (
            id         INTEGER PRIMARY KEY,
            repo_id    INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            parent_id  INTEGER,
            content    TEXT    NOT NULL,
            status     TEXT    NOT NULL DEFAULT 'pending',
            screened   INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL DEFAULT (unixepoch())
        );
        INSERT INTO comments (repo_id, user_id, content, status, screened)
            VALUES (1, 1, '被误杀', 'hidden', 1);
        INSERT INTO comments (repo_id, user_id, content, status, screened)
            VALUES (1, 1, '正常可见', 'visible', 1);
        """
    )
    db.init_db(legacy)
    cols = {r["name"] for r in legacy.execute("PRAGMA table_info(comments)")}
    assert "moderation_reason" in cols
    rows = {r["content"]: r for r in legacy.execute("SELECT * FROM comments")}
    assert rows["被误杀"]["status"] == "pending" and rows["被误杀"]["screened"] == 0
    assert rows["正常可见"]["status"] == "visible"
    legacy.close()
