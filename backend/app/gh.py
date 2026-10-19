"""GitHub 仓库理解包拉取:仅官方只读 API(元信息/README/文件树/语言统计)。
觅码仓库解读专用;失败一律抛 GitHubFetchError(message 面向用户直接展示)。"""
from __future__ import annotations

import httpx

from . import config

GITHUB_API = "https://api.github.com"
README_MAX_CHARS = 4000
TREE_MAX_LINES = 60
TIMEOUT_SECONDS = 10.0


class GitHubFetchError(RuntimeError):
    """GitHub 拉取失败;message 直接展示给用户。"""


def _headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "meecode-explain",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…(已截断)"


def _summarize_tree(entries: list[dict]) -> str:
    """文件树摘要:仅顶层文件与一级目录,超 TREE_MAX_LINES 行截断。"""
    lines: list[str] = []
    for entry in entries:
        path = str(entry.get("path", "")).strip("/")
        if not path or "/" in path:
            continue
        lines.append(f"{path}/" if entry.get("type") == "tree" else path)
    lines = sorted(set(lines))
    if len(lines) > TREE_MAX_LINES:
        lines = lines[:TREE_MAX_LINES] + [f"…(已截断,共 {len(lines)} 项)"]
    return "\n".join(lines)


def _summarize_languages(languages: dict[str, int]) -> str:
    total = sum(languages.values())
    if total <= 0:
        return ""
    ranked = sorted(languages.items(), key=lambda kv: kv[1], reverse=True)
    return "、".join(f"{name} {round(count * 100 / total)}%" for name, count in ranked)


async def fetch_repo_context(
    full_name: str,
    default_branch: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """拉取仓库理解包;transport 参数仅供测试注入(httpx.MockTransport 兼作异步 transport)。"""
    full_name = full_name.strip().strip("/")
    headers = _headers(config.GITHUB_TOKEN)
    try:
        async with httpx.AsyncClient(
            base_url=GITHUB_API,
            headers=headers,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            transport=transport,
        ) as client:
            meta_resp = await client.get(f"/repos/{full_name}")
            if meta_resp.status_code == 404:
                raise GitHubFetchError("GitHub 仓库不存在或已私有")
            if meta_resp.status_code == 403:
                raise GitHubFetchError("GitHub API 限流:请稍后重试,或在 backend/.env 配置 GITHUB_TOKEN")
            meta_resp.raise_for_status()
            meta = meta_resp.json()
            branch = default_branch or meta.get("default_branch") or "HEAD"

            readme = ""
            readme_resp = await client.get(
                f"/repos/{full_name}/readme",
                headers={**headers, "Accept": "application/vnd.github.raw"},
            )
            if readme_resp.status_code == 200:
                readme = _truncate(readme_resp.text, README_MAX_CHARS)

            tree_text = ""
            tree_resp = await client.get(f"/repos/{full_name}/git/trees/{branch}", params={"recursive": "1"})
            if tree_resp.status_code == 200:
                tree_text = _summarize_tree(tree_resp.json().get("tree", []))

            languages_text = ""
            lang_resp = await client.get(f"/repos/{full_name}/languages")
            if lang_resp.status_code == 200:
                languages_text = _summarize_languages(lang_resp.json())
    except httpx.HTTPError as exc:
        raise GitHubFetchError(f"GitHub 连接失败:{exc}") from exc

    return {
        "full_name": full_name,
        "default_branch": branch,
        "description": meta.get("description") or "",
        "readme": readme,
        "tree_text": tree_text,
        "languages_text": languages_text,
    }
