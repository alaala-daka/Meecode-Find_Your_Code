"""卡片流与搜索。

曝光计数在此：谁进了返回列表就 +1（见 spec「指标定义」）。服务端计数，
零前端埋点；偏乐观但对投稿/采集两侧同样宽松，不影响中位数比较。
"""
from __future__ import annotations

import sqlite3
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from ... import config
from ...sqlutil import fts_escape, like_pattern
from .. import ranking
from ..cards import to_card, _card_select
from ..deps import get_conn
from ..filters import filter_sql, parse_filters
from ..schemas import FeedOut, SearchOut

router = APIRouter()


def bump_impressions(conn: sqlite3.Connection, repo_ids: list[int]) -> None:
    """原子自增，不插行 —— feed 每次返回都要写，不能有行插入开销。"""
    if not repo_ids:
        return
    conn.executemany(
        "UPDATE repos SET impression_count = impression_count + 1 WHERE id = ?",
        [(i,) for i in repo_ids],
    )
    conn.commit()


@router.get("/categories", response_model=list[str])
def categories() -> list[str]:
    return list(config.CATEGORIES)


@router.get("/feed", response_model=FeedOut)
def get_feed(
    category: str | None = None,
    page: int = Query(1, ge=1),
    lang: str | None = None,
    stars: int | None = Query(None, ge=0),
    stars_max: int | None = Query(None, ge=0),
    since: str | None = None,
    topic: list[str] | None = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> FeedOut:
    if category and category not in config.CATEGORIES:
        raise HTTPException(status_code=422, detail=f"未知分类：{category}")
    f = parse_filters(lang, stars, stars_max, since, topic)

    now = int(time.time())
    # pending_claim（未认领的采集仓库）也要展示 —— 只有 delisted 不可见
    where = "FROM repos r WHERE r.status != 'delisted'"
    params: list = []
    if category:
        where += " AND r.category = ?"
        params.append(category)
    cond, fparams = filter_sql(f)          # 过滤在 SQL 层做完再进 ranking（spec §3.2）
    where += cond
    params += fparams

    total = conn.execute(f"SELECT COUNT(*) AS n {where}", params).fetchone()["n"]
    rows = conn.execute(
        _card_select(where) + " ORDER BY r.published_at DESC LIMIT ?",
        params + [config.FEED_CANDIDATE_LIMIT],
    ).fetchall()
    ranked = sorted(rows, key=lambda r: ranking.score(r, now), reverse=True)

    # 预留位只给窗口内的投稿；其余（含过窗投稿与全部采集）走普通位
    window = config.DEBUT_WINDOW_HOURS * 3600
    debut_ids = {
        r["id"] for r in ranked
        if r["source"] == "submitted" and now - r["published_at"] <= window
    }
    submitted = [r for r in ranked if r["id"] in debut_ids]
    others = [r for r in ranked if r["id"] not in debut_ids]

    size = config.FEED_PAGE_SIZE
    ordered = ranking.interleave(submitted, others, size)  # 全量成序，切片即翻页

    start = (page - 1) * size
    slice_ = ordered[start:start + size]
    bump_impressions(conn, [r["id"] for r in slice_])
    return FeedOut(cards=[to_card(r) for r in slice_],
                   has_more=len(ordered) > start + size, total=total)


_SEARCH_ORDER = {
    "default": "ORDER BY rank",
    "newest": "ORDER BY r.published_at DESC",
    "stars": "ORDER BY r.stars DESC",
}


@router.get("/search", response_model=SearchOut)
def search(
    q: str,
    sort: str = Query("default"),
    page: int = Query(1, ge=1),
    conn: sqlite3.Connection = Depends(get_conn),
) -> SearchOut:
    if sort not in _SEARCH_ORDER:
        raise HTTPException(status_code=422, detail=f"未知排序:{sort}")
    term = q.strip()
    if not term:
        return SearchOut(cards=[], has_more=False, total=0)
    size = config.FEED_PAGE_SIZE
    offset = (page - 1) * size

    if len(term) < 3:
        # FTS5 trigram 至少 3 字符:短词("AI"、"图")回退 LIKE,不再静默空结果
        pat = like_pattern(term)
        cond = ("r.status != 'delisted' AND (r.full_name LIKE ? ESCAPE '\\'"
                " OR r.tagline_zh LIKE ? ESCAPE '\\' OR r.topics LIKE ? ESCAPE '\\')")
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM repos r WHERE {cond}", (pat, pat, pat)
        ).fetchone()["n"]
        order = _SEARCH_ORDER[sort] if sort != "default" else "ORDER BY r.published_at DESC"
        rows = conn.execute(
            f"{_card_select('FROM repos r')} WHERE {cond} {order} LIMIT ? OFFSET ?",
            (pat, pat, pat, size + 1, offset),
        ).fetchall()
    else:
        needle = fts_escape(term)
        join = "FROM repos_fts f JOIN repos r ON r.id = f.rowid"
        cond = "repos_fts MATCH ? AND r.status != 'delisted'"
        try:
            total = conn.execute(
                f"SELECT COUNT(*) AS n {join} WHERE {cond}", (needle,)
            ).fetchone()["n"]
            rows = conn.execute(
                f"{_card_select(join)} WHERE {cond} {_SEARCH_ORDER[sort]} LIMIT ? OFFSET ?",
                (needle, size + 1, offset),
            ).fetchall()
        except sqlite3.OperationalError:
            return SearchOut(cards=[], has_more=False, total=0)  # 语法异常一律空结果

    has_more = len(rows) > size
    rows = rows[:size]
    bump_impressions(conn, [r["id"] for r in rows])
    return SearchOut(cards=[to_card(r) for r in rows], has_more=has_more, total=total)
