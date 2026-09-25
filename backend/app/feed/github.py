"""GitHub API 客户端：只读公开信息 + OAuth 换取一次性 token。

限流策略：403/429 且 X-RateLimit-Remaining=0 时按 Retry-After 退避重试；
超过 MAX_RETRIES 抛 GitHubError，由调用方决定跳过还是降级。
永不 clone，永不落地仓库文件（见 Global Constraints）。
"""
from __future__ import annotations

import base64
import time
from datetime import datetime, timedelta, timezone

import httpx

from .. import config
from . import mock

MAX_RETRIES = 3
DEFAULT_BACKOFF = 2.0
TIMEOUT = 20.0
INTERACTIVE_RETRIES = 1     # 交互路径:网页请求不该为 GitHub 事故挂起
_shared_client: httpx.Client | None = None


class GitHubError(RuntimeError):
    """GitHub 调用失败：调用方应跳过该仓库或降级展示，不中断整批。"""


def _client() -> httpx.Client:
    """进程级共享连接池:每请求新建客户端 = 每次重新 TLS 握手,爬取数百仓库时开销显著。
    测试直接 monkeypatch 本函数注入 MockTransport 客户端即可。"""
    global _shared_client
    if _shared_client is None:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "meecode"}
        if config.GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
        _shared_client = httpx.Client(headers=headers, timeout=TIMEOUT)
    return _shared_client


def _retry_after(headers: httpx.Headers, fallback: float) -> float:
    """Retry-After 规范允许 HTTP-date 形式,float() 会炸,一律兜回退避值。"""
    raw = headers.get("Retry-After")
    if not raw:
        return fallback
    try:
        return max(0.0, float(raw))
    except ValueError:
        return fallback


def _get(path: str, params: dict | None = None, *,
         allow_404: bool = False, interactive: bool = False) -> dict | list | None:
    """interactive=True 用于网页请求路径:限流立即抛错不等待,重试至多 1 次;
    批量路径(爬取)保持满配重试与退避。"""
    retries = INTERACTIVE_RETRIES if interactive else MAX_RETRIES
    last = ""
    for attempt in range(retries):
        try:
            resp = _client().get(f"{config.GITHUB_API}{path}", params=params)
        except httpx.HTTPError as exc:
            last = f"网络错误:{exc}"
            if interactive:
                break
            time.sleep(DEFAULT_BACKOFF * (attempt + 1))
            continue
        if resp.status_code == 404 and allow_404:
            return None
        if resp.status_code in (403, 429) and resp.headers.get("X-RateLimit-Remaining") == "0":
            wait = _retry_after(resp.headers, DEFAULT_BACKOFF * (attempt + 1))
            last = f"触发限流(剩余配额 0),需等待 {wait}s"
            if interactive:
                break
            time.sleep(wait)
            continue
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub {resp.status_code}:{resp.text[:200]}")
        return resp.json()
    raise GitHubError(f"GitHub 重试 {retries} 次仍失败:{last}")


def search_new_repos(language: str, *, now: int | None = None) -> list[dict]:
    """按语言分片查近期新仓库（Search API 单查询上限 1000，故分片）。"""
    if config.GITHUB_MOCK:
        fixtures = mock.mock_repos(now)
        return [r for r in fixtures if r["language"] == language]
    since = datetime.fromtimestamp(now or time.time(), timezone.utc) - timedelta(
        days=config.CRAWL_CREATED_WITHIN_DAYS
    )
    q = (
        f"created:>={since:%Y-%m-%d} "
        f"stars:>={config.CRAWL_MIN_STARS} fork:false language:{language}"
    )
    data = _get("/search/repositories",
                {"q": q, "sort": "stars", "order": "desc", "per_page": 100})
    return [_normalize(item) for item in (data or {}).get("items", [])]


def _normalize(item: dict) -> dict:
    """把 Search API 的仓库对象收敛成入库需要的字段。"""
    return {
        "id": item["id"],
        "full_name": item["full_name"],
        "owner_login": (item.get("owner") or {}).get("login", ""),
        "language": item.get("language") or "",
        "topics": item.get("topics") or [],
        "stars": item.get("stargazers_count", 0),
        "created_at": _ts(item.get("created_at")),
        "pushed_at": _ts(item.get("pushed_at")),
        "license": ((item.get("license") or {}) or {}).get("spdx_id") or "",
        "default_branch": item.get("default_branch") or "main",
        "archived": bool(item.get("archived")),
    }


def _ts(value: str | None) -> int:
    if not value:
        return 0
    return int(datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
               .replace(tzinfo=timezone.utc).timestamp())


def get_readme(full_name: str, *, interactive: bool = False) -> str:
    """README 缺失返回空串（由粗筛判定淘汰），不抛异常。"""
    if config.GITHUB_MOCK:
        return mock.mock_readme(full_name)
    data = _get(f"/repos/{full_name}/readme", allow_404=True, interactive=interactive)
    if not data:
        return ""
    if data.get("encoding") == "base64":
        return base64.b64decode(data.get("content", "")).decode("utf-8", "replace")
    return data.get("content", "")


def get_tree(full_name: str, branch: str = "main", *,
             interactive: bool = False) -> list[dict]:
    if config.GITHUB_MOCK:
        return mock.mock_tree(full_name)
    data = _get(f"/repos/{full_name}/git/trees/{branch}",
                {"recursive": "1"}, allow_404=True, interactive=interactive)
    if not data:
        return []
    return [
        {"path": t["path"], "type": t["type"], "size": t.get("size", 0)}
        for t in data.get("tree", [])
    ]


def get_file(full_name: str, path: str, branch: str = "main", *,
             interactive: bool = False) -> str:
    """按需取单个文件内容 —— 代替 clone，见 Global Constraints。"""
    if config.GITHUB_MOCK:
        return mock.mock_file(full_name, path)
    data = _get(f"/repos/{full_name}/contents/{path}", {"ref": branch},
                allow_404=True, interactive=interactive)
    if not data or data.get("encoding") != "base64":
        return ""
    return base64.b64decode(data.get("content", "")).decode("utf-8", "replace")


def get_user(login: str) -> dict:
    if config.GITHUB_MOCK:
        return mock.mock_user(login)
    return _get(f"/users/{login}") or {}


def list_user_repos(login: str) -> list[dict]:
    """列出用户自己拥有的公开仓库,供投稿页勾选;翻页拉全(>100 仓库的作者也要能投稿)。"""
    if config.GITHUB_MOCK:
        return mock.mock_repos()
    out: list[dict] = []
    page = 1
    while True:
        data = _get(f"/users/{login}/repos",
                    {"type": "owner", "sort": "updated", "per_page": 100, "page": page})
        items = data or []
        out.extend(_normalize(item) for item in items)
        if len(items) < 100 or page >= 10:  # 10 页 = 1000 仓库,投稿场景足够
            break
        page += 1
    return out


def exchange_oauth_code(code: str) -> str:
    """用 code 换 access_token；用完即弃，绝不入库（见 Global Constraints）。"""
    if config.GITHUB_MOCK:
        return "mock-token"
    try:
        resp = httpx.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": config.GITHUB_CLIENT_ID,
                "client_secret": config.GITHUB_CLIENT_SECRET,
                "code": code,
            },
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise GitHubError(f"OAuth 换取 token 失败：{exc}") from exc
    try:
        payload = resp.json()
    except ValueError as exc:
        raise GitHubError(f"OAuth 响应非 JSON:{resp.text[:200]}") from exc
    token = payload.get("access_token", "")
    if not token:
        raise GitHubError("OAuth 未返回 access_token，请检查 client 配置")
    return token


def get_authenticated_user(token: str) -> dict:
    """用一次性 token 读当前登录者身份，随后 token 即丢弃。"""
    if config.GITHUB_MOCK:
        return mock.mock_user("demo")
    try:
        resp = httpx.get(
            f"{config.GITHUB_API}/user",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise GitHubError(f"读取 GitHub 用户失败：{exc}") from exc
    if resp.status_code >= 400:
        raise GitHubError(f"读取 GitHub 用户失败：{resp.status_code}")
    return resp.json()
