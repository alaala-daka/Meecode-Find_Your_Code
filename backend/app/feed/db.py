"""SQLite 连接与建表。4 张表用 stdlib sqlite3 足够，不引 ORM。

FTS5 用 trigram 分词器：中文按 3 字符切分，无需分词库即可搜中文。
"""
from __future__ import annotations

import sqlite3

from .. import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    github_id     INTEGER NOT NULL UNIQUE,
    login         TEXT    NOT NULL,
    avatar_url    TEXT    NOT NULL DEFAULT '',
    bio           TEXT    NOT NULL DEFAULT '',
    session_epoch INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS repos (
    id            INTEGER PRIMARY KEY,
    -- GitHub 侧
    github_id     INTEGER NOT NULL UNIQUE,
    full_name     TEXT    NOT NULL,
    owner_login   TEXT    NOT NULL,
    language      TEXT    NOT NULL DEFAULT '',
    topics        TEXT    NOT NULL DEFAULT '',   -- 逗号分隔
    stars         INTEGER NOT NULL DEFAULT 0,
    star_velocity REAL    NOT NULL DEFAULT 0,
    pushed_at     INTEGER NOT NULL DEFAULT 0,
    license       TEXT    NOT NULL DEFAULT '',
    readme_md     TEXT    NOT NULL DEFAULT '',
    default_branch TEXT   NOT NULL DEFAULT 'main',
    -- 觅码侧
    source        TEXT    NOT NULL CHECK (source IN ('submitted','crawled')),
    status        TEXT    NOT NULL CHECK (status IN ('published','pending_claim','delisted')),
    claimed_by    INTEGER REFERENCES users(id),
    tagline_zh    TEXT    NOT NULL DEFAULT '',
    intro_zh      TEXT    NOT NULL DEFAULT '',
    category      TEXT    NOT NULL DEFAULT '其他',
    cover_url     TEXT    NOT NULL DEFAULT '',   -- 空 = 前端自动生成 SVG
    quality       INTEGER NOT NULL DEFAULT 3,    -- config.NEUTRAL_QUALITY
    screened      INTEGER NOT NULL DEFAULT 0,    -- 0=LLM 精筛未完成，待补齐
    published_at  INTEGER NOT NULL DEFAULT 0,
    -- 计数（原子自增，定义见 spec「指标定义」）
    impression_count INTEGER NOT NULL DEFAULT 0,
    repo_view_count  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_repos_feed ON repos (status, published_at);
CREATE INDEX IF NOT EXISTS idx_repos_owner ON repos (owner_login);

CREATE TABLE IF NOT EXISTS interactions (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    repo_id    INTEGER NOT NULL REFERENCES repos(id),
    kind       TEXT    NOT NULL CHECK (kind IN ('like','favorite','visit')),
    updated_at INTEGER NOT NULL,
    UNIQUE (user_id, repo_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_interactions_lookup
    ON interactions (user_id, kind, updated_at DESC);

CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY,
    repo_id     INTEGER NOT NULL REFERENCES repos(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    parent_id   INTEGER REFERENCES comments(id),  -- NULL=顶层；非 NULL 恒指顶层
    content     TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','visible','hidden','deleted')),
    screened    INTEGER NOT NULL DEFAULT 0,       -- 0=LLM 尚未判定（含失败待重试）；1=已判定
    moderation_reason TEXT NOT NULL DEFAULT '',   -- LLM 拒绝原因（空=通过/作者隐藏）
    created_at  INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE INDEX IF NOT EXISTS idx_comments_repo ON comments (repo_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_comments_parent ON comments (parent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_comments_unscreen ON comments (screened, created_at);

-- 搜索：external content 表，rowid 对齐 repos.id
CREATE VIRTUAL TABLE IF NOT EXISTS repos_fts USING fts5 (
    full_name, tagline_zh, intro_zh, topics,
    content='repos', content_rowid='id', tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS repos_fts_ai AFTER INSERT ON repos BEGIN
    INSERT INTO repos_fts (rowid, full_name, tagline_zh, intro_zh, topics)
    VALUES (new.id, new.full_name, new.tagline_zh, new.intro_zh, new.topics);
END;

CREATE TRIGGER IF NOT EXISTS repos_fts_ad AFTER DELETE ON repos BEGIN
    INSERT INTO repos_fts (repos_fts, rowid, full_name, tagline_zh, intro_zh, topics)
    VALUES ('delete', old.id, old.full_name, old.tagline_zh, old.intro_zh, old.topics);
END;

CREATE TRIGGER IF NOT EXISTS repos_fts_au AFTER UPDATE ON repos BEGIN
    INSERT INTO repos_fts (repos_fts, rowid, full_name, tagline_zh, intro_zh, topics)
    VALUES ('delete', old.id, old.full_name, old.tagline_zh, old.intro_zh, old.topics);
    INSERT INTO repos_fts (rowid, full_name, tagline_zh, intro_zh, topics)
    VALUES (new.id, new.full_name, new.tagline_zh, new.intro_zh, new.topics);
END;
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    """建立连接。WAL 让读写不互斥；外键约束默认关闭，需显式打开。"""
    target = path or config.DB_PATH
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")  # 写锁竞争时等 5s,而不是立刻 OperationalError
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "session_epoch" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0")
    ccols = {r["name"] for r in conn.execute("PRAGMA table_info(comments)")}
    if "moderation_reason" not in ccols:
        conn.execute("ALTER TABLE comments ADD COLUMN moderation_reason TEXT NOT NULL DEFAULT ''")
        # 一次性重审：旧 prompt 误杀的存量 hidden 行转回 pending，由 cron/预审用新口径重判
        # （作者手动隐藏的行也会重审——测试期样本，重判合规恢复可见，需再藏作者重操作）
        conn.execute("UPDATE comments SET status = 'pending', screened = 0 WHERE status = 'hidden'")
    conn.commit()
