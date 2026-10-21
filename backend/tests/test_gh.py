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


# ---------- N7:改名/迁移仓库的 301 处理(仅同可信宿主 api.github.com,手动逐跳) ----------
# F7 保持:客户端 follow_redirects=False;同宿重定向由下方手动逻辑逐跳判定,跨宿主绝不跟随。
# 旧测试 test_fetch_repo_context_never_follows_redirects(同宿 302 → 通用连接失败且不跟随)
# 钉住的正是 N7 要改的行为,由下列用例取代:同宿跟随、跨宿/缺 Location/打环显式收尾。


def _renamed_handler(request: httpx.Request) -> httpx.Response:
    """octocat/demo 的每条路径 301 到 octocat/renamed;新名路径正常出货。"""
    path = request.url.path
    old, new = "/repos/octocat/demo", "/repos/octocat/renamed"
    if path.startswith(old):
        return httpx.Response(301, headers={"Location": f"https://api.github.com{new}{path[len(old):]}"})
    if path == new:
        return httpx.Response(200, json={"default_branch": "main", "description": "renamed repo"})
    if path == f"{new}/readme":
        return httpx.Response(200, text="# Renamed\nnew home")
    if path == f"{new}/git/trees/main":
        return httpx.Response(200, json={"tree": [{"type": "blob", "path": "README.md"}]})
    if path == f"{new}/languages":
        return httpx.Response(200, json={"Python": 100})
    return httpx.Response(404)


async def test_fetch_repo_context_follows_same_host_rename_301():
    """N7(a):Location 指向 api.github.com 的 301 手动跟随,重命名仓库照常出理解包。"""
    repo = await gh.fetch_repo_context("octocat/demo", transport=httpx.MockTransport(_renamed_handler))
    assert repo["description"] == "renamed repo"
    assert repo["readme"].startswith("# Renamed")
    assert repo["tree_text"] == "README.md"
    assert repo["languages_text"] == "Python 100%"


async def test_fetch_repo_context_rejects_cross_host_redirect():
    """N7(b)/F7:跨宿主 Location 绝不跟随,固定文案收尾,不外泄 URL/主机(F6 同口径)。"""
    seen: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(301, headers={"Location": "https://evil.com/repos/octocat/renamed"})

    with pytest.raises(gh.GitHubFetchError) as excinfo:
        await gh.fetch_repo_context("octocat/demo", transport=httpx.MockTransport(_handler))
    assert str(excinfo.value) == "仓库已移动或改名"
    assert "evil.com" not in str(excinfo.value)
    assert seen and all("evil.com" not in u for u in seen)  # 重定向目标从未被请求


async def test_fetch_repo_context_redirect_loop_hits_hop_limit():
    """N7(c):api.github.com 上的 301 打环 → 跳数封顶后固定文案显式失败(不挂死/不无限跟随)。"""
    seen: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(301, headers={"Location": "https://api.github.com/repos/loop/next"})

    with pytest.raises(gh.GitHubFetchError) as excinfo:
        await gh.fetch_repo_context("octocat/demo", transport=httpx.MockTransport(_handler))
    assert str(excinfo.value) == "仓库已移动或改名"
    assert len(seen) <= gh.MAX_REDIRECT_HOPS + 1   # 手动跟随最多 MAX_REDIRECT_HOPS 跳


async def test_fetch_repo_context_3xx_without_location_is_explicit():
    """N7:3xx 缺 Location = 不可安全跟随 → 固定文案显式失败。"""
    no_location = httpx.MockTransport(lambda req: httpx.Response(301))
    with pytest.raises(gh.GitHubFetchError) as excinfo:
        await gh.fetch_repo_context("octocat/demo", transport=no_location)
    assert str(excinfo.value) == "仓库已移动或改名"


async def test_fetch_repo_context_client_keeps_auto_redirects_off(monkeypatch):
    """F7:客户端保持 follow_redirects=False;同宿重定向是 N7 手动逐跳判定,不交给 httpx 自动跟随。"""
    real_client = httpx.AsyncClient
    captured: dict = {}

    def _spy(*args, **kwargs):
        captured.update(kwargs)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(gh.httpx, "AsyncClient", _spy)
    await gh.fetch_repo_context("octocat/demo", transport=httpx.MockTransport(_handler))
    assert captured.get("follow_redirects") is False
