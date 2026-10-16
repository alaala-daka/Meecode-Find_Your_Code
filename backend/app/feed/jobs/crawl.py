"""采集日跑任务：搜索 → 规则粗筛 → top-K LLM 精筛 → 按分数取前 N 入库 → 补筛遗留。

与 Web 请求完全解耦：本任务挂掉不影响首页出内容。
日配额（CRAWL_DAILY_QUOTA）是防止采集冲淡投稿的第一道闸；
LLM 花销是第二道闸：规则通过者只对启发式预分 top-K（配额 + 缓冲）精筛。
单仓库失败一律跳过并计入 skipped，绝不中断整批（见 spec 第 9 节）。

手动触发：python -m app.feed.jobs.crawl
"""
from __future__ import annotations

import logging
import sqlite3
import time

from ... import config, llm_usage
from .. import db, github, ranking, screening
from ..schemas import ScreeningResult

log = logging.getLogger(__name__)


def crawl_once(conn: sqlite3.Connection, *, now: int | None = None) -> dict:
    now = int(now or time.time())
    stats = {"scanned": 0, "passed_rules": 0, "screened_in": 0, "inserted": 0, "skipped": 0}
    rule_passed: list[tuple[float, dict, str, list[dict]]] = []

    known = {r["github_id"] for r in conn.execute("SELECT github_id FROM repos")}

    for language in config.CRAWL_LANGUAGES:
        try:
            found = github.search_new_repos(language, now=now)
        except github.GitHubError as exc:
            log.warning("搜索 %s 失败,跳过该语言:%s", language, exc)
            continue

        for repo in found:
            stats["scanned"] += 1
            if repo["id"] in known:
                continue  # 已入库:不重复、不覆盖作者文案
            try:
                readme = github.get_readme(repo["full_name"])
                tree = github.get_tree(repo["full_name"], repo.get("default_branch", "main"))
                followers = github.get_user(repo["owner_login"]).get("followers", 0)
            except github.GitHubError as exc:
                stats["skipped"] += 1
                log.warning("取 %s 元数据失败,跳过:%s", repo["full_name"], exc)
                continue

            ok, why = screening.passes_rules(repo, readme, tree, followers, now)
            if not ok:
                continue
            stats["passed_rules"] += 1

            repo["star_velocity"] = screening.star_velocity(
                repo.get("stars", 0), repo.get("created_at", now), now
            )
            preview = {
                "quality": config.NEUTRAL_QUALITY, "published_at": now,
                "source": "crawled", "impression_count": 0, "repo_view_count": 0,
            }
            rule_passed.append((ranking.score(preview, now), repo, readme, tree))

    # LLM 花销封顶:规则通过者先按启发式预分排序,只对 top-K 精筛(K = 配额 + 缓冲)
    rule_passed.sort(key=lambda c: c[0], reverse=True)
    topk = rule_passed[: config.CRAWL_DAILY_QUOTA + config.CRAWL_SCREEN_BUFFER]

    candidates: list[tuple[float, dict, str, ScreeningResult]] = []
    for _score, repo, readme, tree in topk:
        try:
            result = screening.screen_repo(repo["full_name"], readme, tree,
                                           route=llm_usage.ROUTE_CRAWL_SCREEN)
        except Exception as exc:  # LLM 故障:跳过,下轮重试
            stats["skipped"] += 1
            log.warning("%s 精筛失败,跳过:%s", repo["full_name"], exc)
            continue
        if not result.is_real_project:
            continue  # 采集端:精筛不达标即丢弃
        stats["screened_in"] += 1
        preview = {
            "quality": result.quality, "published_at": now,
            "source": "crawled", "impression_count": 0, "repo_view_count": 0,
        }
        candidates.append((ranking.score(preview, now), repo, readme, result))

    # 日配额:只取分数最高的 N 条,防止采集冲淡投稿
    candidates.sort(key=lambda c: c[0], reverse=True)
    for _score, repo, readme, result in candidates[: config.CRAWL_DAILY_QUOTA]:
        upsert_crawled(conn, repo, readme, result, now)
        stats["inserted"] += 1

    rescreen_pending(conn, now=now)
    conn.commit()
    return stats


def rescreen_pending(
    conn: sqlite3.Connection, *, now: int | None = None, limit: int | None = None
) -> int:
    """补筛 screened=0(投稿降级/精筛失败遗留):只补质量分,绝不覆盖作者文案。

    投稿不受准入约束,故 is_real_project=False 也只是继续挂中性分,不下架。
    """
    limit = limit if limit is not None else config.CRAWL_RESCREEN_LIMIT
    rows = conn.execute(
        "SELECT id, full_name, readme_md, default_branch, source FROM repos"
        " WHERE screened = 0 AND status != 'delisted' LIMIT ?", (limit,)
    ).fetchall()
    done = 0
    for row in rows:
        try:
            tree = github.get_tree(row["full_name"], row["default_branch"])
            result = screening.screen_repo(row["full_name"], row["readme_md"], tree,
                                           route=llm_usage.ROUTE_CRAWL_SCREEN,
                                           repo_id=row["id"])
        except Exception as exc:
            log.warning("[rescreen] %s 失败,下轮重试:%s", row["full_name"], exc)
            continue
        if not result.is_real_project:
            continue
        conn.execute(
            "UPDATE repos SET quality = ?, screened = 1,"
            " category = CASE WHEN source = 'crawled' THEN ? ELSE category END"
            " WHERE id = ?",
            (result.quality, result.category, row["id"]),
        )
        done += 1
    return done


def upsert_crawled(
    conn: sqlite3.Connection, repo: dict, readme: str, result: ScreeningResult, now: int
) -> int:
    """插入采集仓库。github_id 冲突时只刷新 GitHub 侧字段，绝不动觅码侧文案。"""
    cur = conn.execute(
        """
        INSERT INTO repos (
            github_id, full_name, owner_login, language, topics, stars, star_velocity,
            pushed_at, license, readme_md, default_branch,
            source, status, tagline_zh, intro_zh, category, quality, screened, published_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'crawled', 'pending_claim', ?,?,?,?,1,?)
        ON CONFLICT(github_id) DO UPDATE SET
            stars = excluded.stars,
            star_velocity = excluded.star_velocity,
            pushed_at = excluded.pushed_at,
            readme_md = excluded.readme_md
        """,
        (
            repo["id"], repo["full_name"], repo["owner_login"], repo.get("language", ""),
            ",".join(repo.get("topics") or []), repo.get("stars", 0),
            repo.get("star_velocity", 0.0), repo.get("pushed_at", 0),
            repo.get("license", ""), readme, repo.get("default_branch", "main"),
            result.tagline_zh, result.why_zh, result.category, result.quality, now,
        ),
    )
    return cur.lastrowid


def main() -> None:
    conn = db.connect()
    db.init_db(conn)
    stats = crawl_once(conn)
    log.info("采集完成:%s", stats)
    conn.close()


if __name__ == "__main__":
    main()
