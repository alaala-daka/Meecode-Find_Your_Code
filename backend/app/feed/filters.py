"""精确筛选：过滤参数白名单校验 + 共用 WHERE 片段（spec §3.1 契约表）。

白名单是硬约束：URL 参数一旦放出即被外链固化、无法回收，与第六批
canonical / sitemap 直接耦合。任何新过滤维度必须先改 spec §3.1 再实现。
"""
from __future__ import annotations

import calendar
import re
import time
from dataclasses import dataclass

from fastapi import HTTPException

from ..sqlutil import like_pattern

SINCE_CHOICES: tuple[str, ...] = ("7d", "30d", "90d", "ytd")
_LANG_RE = re.compile(r"^[A-Za-z0-9+#.\- ]{1,30}$")
_TOPIC_RE = re.compile(r"^[a-z0-9-]{1,50}$")
MAX_TOPICS = 5
MAX_STARS = 10_000_000


@dataclass(frozen=True)
class FeedFilters:
    lang: str | None = None
    stars: int | None = None
    stars_max: int | None = None
    since: str | None = None
    topics: tuple[str, ...] = ()


def parse_filters(
    lang: str | None,
    stars: int | None,
    stars_max: int | None,
    since: str | None,
    topics: list[str] | tuple[str, ...] | None,
) -> FeedFilters:
    """值域校验（spec §3.1）；非法值 422，与现有 category 校验风格一致。"""
    if lang is not None:
        lang = lang.strip()
        if not _LANG_RE.match(lang):
            raise HTTPException(status_code=422, detail=f"非法语言参数：{lang}")
        if not lang:
            lang = None
    for name, v in (("stars", stars), ("stars_max", stars_max)):
        if v is not None and not (0 <= v <= MAX_STARS):
            raise HTTPException(status_code=422, detail=f"非法星数参数：{v}")
    if stars is not None and stars_max is not None and stars_max < stars:
        raise HTTPException(status_code=422, detail="stars_max 不能小于 stars")
    if since is not None and since not in SINCE_CHOICES:
        raise HTTPException(status_code=422, detail=f"非法时间范围：{since}")

    norm: list[str] = []
    for t in topics or ():
        t = t.strip().lower()
        if not _TOPIC_RE.match(t):
            raise HTTPException(status_code=422, detail=f"非法 topic 参数：{t}")
        if t not in norm:
            norm.append(t)
    if len(norm) > MAX_TOPICS:
        raise HTTPException(status_code=422, detail=f"topic 最多 {MAX_TOPICS} 个")
    return FeedFilters(
        lang=lang or None, stars=stars, stars_max=stars_max,
        since=since, topics=tuple(norm),
    )


def since_cutoff(since: str | None, now: int | None = None) -> int | None:
    """把 since 换算成 pushed_at 下限（epoch 秒）；ytd = 当年 1 月 1 日 UTC。"""
    if not since:
        return None
    now = int(time.time()) if now is None else now
    if since == "ytd":
        return calendar.timegm((time.gmtime(now).tm_year, 1, 1, 0, 0, 0))
    return now - {"7d": 7, "30d": 30, "90d": 90}[since] * 86400


def filter_sql(f: FeedFilters) -> tuple[str, list]:
    """返回 (" AND …", params)，调用方拼进带 r. 前缀的 WHERE。"""
    cond = ""
    params: list = []
    if f.lang:
        cond += " AND LOWER(r.language) = LOWER(?)"
        params.append(f.lang)
    if f.stars is not None:
        cond += " AND r.stars >= ?"
        params.append(f.stars)
    if f.stars_max is not None:
        cond += " AND r.stars <= ?"
        params.append(f.stars_max)
    if f.since:
        cond += " AND r.pushed_at >= ?"
        params.append(since_cutoff(f.since))
    for t in f.topics:  # AND 语义：每 topic 一条（spec 决策 #3）
        cond += " AND (',' || r.topics || ',') LIKE ? ESCAPE '\\'"
        params.append(like_pattern(f",{t},"))
    return cond, params
