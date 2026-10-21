"""gh.fetch_repo_context:GitHub 拉取与降级(MockTransport 兼作异步 transport,离线可跑)。"""
import httpx
import pytest

from app import config, gh


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/repos/octocat/demo":
        return httpx.Response(200, json={"default_branch": "main", "description": "demo repo"})
    if path == "/repos/octocat/demo/readme":
        return httpx.Response(200, text="# Demo\nhello world")
    if path == "/repos/octocat/demo/git/trees/main":
        return httpx.Response(200, json={"tree": [
            {"type": "blob", "path": "README.md"},
            {"type": "tree", "path": "src"},
            {"type": "blob", "path": "src/main.py"},
            {"type": "blob", "path": "src/agent.py"},
        ]})
    if path == "/repos/octocat/demo/languages":
        return httpx.Response(200, json={"Python": 8000, "TypeScript": 2000})
    return httpx.Response(404)


async def test_fetch_repo_context_assembles_package():
    repo = await gh.fetch_repo_context("octocat/demo", transport=httpx.MockTransport(_handler))
    assert repo["full_name"] == "octocat/demo"
    assert repo["default_branch"] == "main"
    assert repo["description"] == "demo repo"
    assert repo["readme"].startswith("# Demo")
    assert "src/" in repo["tree_text"]
    assert "Python" in repo["languages_text"] and "80%" in repo["languages_text"]


async def test_fetch_repo_context_missing_repo():
    with pytest.raises(gh.GitHubFetchError, match="仓库不存在"):
        await gh.fetch_repo_context("octocat/ghost", transport=httpx.MockTransport(_handler))


async def test_fetch_repo_context_rate_limited(monkeypatch):
    monkeypatch.setattr(config, "GITHUB_TOKEN", "")
    limited = httpx.MockTransport(lambda req: httpx.Response(403))
    with pytest.raises(gh.GitHubFetchError, match="限流"):
        await gh.fetch_repo_context("octocat/demo", transport=limited)


async def test_fetch_repo_context_connection_error_is_sanitized():
    """F6:连接失败文案必须通用;原始 httpx 异常(可能含 URL/主机/IP)不得外泄。"""
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect to 10.0.0.5:80 failed")

    failing = httpx.MockTransport(_boom)
    with pytest.raises(gh.GitHubFetchError) as excinfo:
        await gh.fetch_repo_context("octocat/demo", transport=failing)
    assert str(excinfo.value) == "GitHub 连接失败"
    assert "10.0.0.5" not in str(excinfo.value)


async def test_fetch_repo_context_never_follows_redirects():
    """F7:出站 GitHub 请求不跟随重定向;3xx 以通用连接失败收尾(重命名仓库处理见 backlog N7)。"""
    seen: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            302, json={"default_branch": "main", "description": ""},
            headers={"Location": "https://api.github.com/repos/octocat/renamed"},
        )

    with pytest.raises(gh.GitHubFetchError) as excinfo:
        await gh.fetch_repo_context("octocat/demo", transport=httpx.MockTransport(_handler))
    assert str(excinfo.value) == "GitHub 连接失败"
    assert seen and all("/renamed" not in u for u in seen)  # 重定向目标从未被请求
