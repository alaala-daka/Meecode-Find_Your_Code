"""GitHub 客户端：mock 模式、限流退避、错误降级。不打真实网络。"""
import httpx
import pytest

from app.feed import github


def test_mock_mode_returns_fixtures(monkeypatch):
    monkeypatch.setattr(github.config, "GITHUB_MOCK", True)
    repos = github.search_new_repos("Python")
    assert repos and all("full_name" in r for r in repos)
    assert github.get_readme(repos[0]["full_name"]).strip()


def test_mock_tree_has_code_files(monkeypatch):
    monkeypatch.setattr(github.config, "GITHUB_MOCK", True)
    tree = github.get_tree("demo/agent-runtime", "main")
    assert sum(1 for t in tree if t["type"] == "blob") >= 5


def test_rate_limit_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(github.config, "GITHUB_MOCK", False)
    monkeypatch.setattr(github.config, "GITHUB_TOKEN", "t")
    monkeypatch.setattr(github.time, "sleep", lambda _s: None)  # 测试不真睡
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "Retry-After": "1"})
        return httpx.Response(200, json={"followers": 12})

    monkeypatch.setattr(github, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert github.get_user("someone")["followers"] == 12
    assert calls["n"] == 2


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(github.config, "GITHUB_MOCK", False)
    monkeypatch.setattr(github.config, "GITHUB_TOKEN", "t")
    monkeypatch.setattr(github.time, "sleep", lambda _s: None)
    handler = lambda r: httpx.Response(403, headers={"X-RateLimit-Remaining": "0"})
    monkeypatch.setattr(github, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(github.GitHubError):
        github.get_user("someone")


def test_missing_readme_returns_empty_not_raise(monkeypatch):
    monkeypatch.setattr(github.config, "GITHUB_MOCK", False)
    monkeypatch.setattr(github.config, "GITHUB_TOKEN", "t")
    handler = lambda r: httpx.Response(404, json={"message": "Not Found"})
    monkeypatch.setattr(github, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert github.get_readme("a/b") == ""


def test_readme_base64_is_decoded(monkeypatch):
    monkeypatch.setattr(github.config, "GITHUB_MOCK", False)
    monkeypatch.setattr(github.config, "GITHUB_TOKEN", "t")
    import base64
    body = {"content": base64.b64encode("# 标题\n正文".encode()).decode(), "encoding": "base64"}
    monkeypatch.setattr(github, "_client",
                        lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))))
    assert github.get_readme("a/b") == "# 标题\n正文"


def test_search_query_carries_spec_filters(monkeypatch):
    monkeypatch.setattr(github.config, "GITHUB_MOCK", False)
    monkeypatch.setattr(github.config, "GITHUB_TOKEN", "t")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["q"] = request.url.params.get("q")
        return httpx.Response(200, json={"items": []})

    monkeypatch.setattr(github, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    github.search_new_repos("Rust")
    assert "language:Rust" in seen["q"]
    assert "fork:false" in seen["q"]
    assert f"stars:>={github.config.CRAWL_MIN_STARS}" in seen["q"]
    assert "created:>=" in seen["q"]


def test_retry_after_non_numeric_falls_back():
    headers = httpx.Headers({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert github._retry_after(headers, 2.0) == 2.0
    assert github._retry_after(httpx.Headers({"Retry-After": "7"}), 2.0) == 7.0
    assert github._retry_after(httpx.Headers({}), 2.0) == 2.0


def test_shared_client_is_reused(monkeypatch):
    monkeypatch.setattr(github.config, "GITHUB_TOKEN", "", raising=False)
    github._shared_client = None
    assert github._client() is github._client()


def test_interactive_path_no_sleep_on_rate_limit(monkeypatch):
    """交互路径限流立即抛错,不 sleep(否则线程池被 GitHub 事故拖死)。"""
    monkeypatch.setattr(github.config, "GITHUB_MOCK", False)
    sleeps: list[float] = []
    monkeypatch.setattr(github.time, "sleep", sleeps.append)
    resp = httpx.Response(429, headers={"X-RateLimit-Remaining": "0", "Retry-After": "60"},
                          request=httpx.Request("GET", "https://x"))
    monkeypatch.setattr(github, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(lambda req: resp)))
    with pytest.raises(github.GitHubError):
        github.get_file("a/b", "README.md", interactive=True)
    assert sleeps == []


def test_batch_path_sleeps_then_gives_up(monkeypatch):
    monkeypatch.setattr(github.config, "GITHUB_MOCK", False)
    sleeps: list[float] = []
    monkeypatch.setattr(github.time, "sleep", sleeps.append)
    resp = httpx.Response(429, headers={"X-RateLimit-Remaining": "0", "Retry-After": "60"},
                          request=httpx.Request("GET", "https://x"))
    monkeypatch.setattr(github, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(lambda req: resp)))
    with pytest.raises(github.GitHubError):
        github.get_readme("a/b")
    assert len(sleeps) >= 1


def test_list_user_repos_paginates(monkeypatch):
    def make_items(start: int, n: int) -> list[dict]:
        return [{"id": start + i, "full_name": f"o/r{start + i}", "owner": {"login": "o"},
                 "language": "Python", "topics": [], "stargazers_count": 1,
                 "created_at": "2026-08-01T00:00:00Z", "pushed_at": "2026-08-01T00:00:00Z",
                 "license": None, "default_branch": "main", "archived": False}
                for i in range(n)]

    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        calls.append(page)
        return httpx.Response(200, json=make_items(1000 * page, 100 if page == 1 else 30))

    monkeypatch.setattr(github.config, "GITHUB_MOCK", False, raising=False)
    monkeypatch.setattr(github, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler)))
    repos = github.list_user_repos("o")
    assert calls == [1, 2]
    assert len(repos) == 130


def test_exchange_oauth_code_non_json(monkeypatch):
    monkeypatch.setattr(github.config, "GITHUB_MOCK", False, raising=False)
    resp = httpx.Response(502, text="<html>bad gateway</html>",
                          request=httpx.Request("POST", "https://x"))
    monkeypatch.setattr(github.httpx, "post", lambda *a, **k: resp)
    with pytest.raises(github.GitHubError, match="非 JSON"):
        github.exchange_oauth_code("code")


def test_batch_network_error_backoff_not_capped(monkeypatch):
    """批量路径网络错误退避保持 2/4/6s 递进,不被 2.0s 封顶(task3 review 裁决)。"""
    sleeps: list[float] = []
    monkeypatch.setattr(github.time, "sleep", sleeps.append)
    monkeypatch.setattr(github.config, "GITHUB_MOCK", False, raising=False)
    monkeypatch.setattr(github.config, "GITHUB_TOKEN", "t", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    monkeypatch.setattr(github, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler)))
    with pytest.raises(github.GitHubError):
        github.get_readme("a/b")
    assert sleeps == [2.0, 4.0, 6.0]


def test_interactive_readme_no_sleep_on_rate_limit(monkeypatch):
    """get_readme 透传 interactive:投稿/ai-draft 网页路径限流立即抛错(task3 review 裁决)。"""
    sleeps: list[float] = []
    monkeypatch.setattr(github.time, "sleep", sleeps.append)
    monkeypatch.setattr(github.config, "GITHUB_MOCK", False, raising=False)
    resp = httpx.Response(429, headers={"X-RateLimit-Remaining": "0", "Retry-After": "60"},
                          request=httpx.Request("GET", "https://x"))
    monkeypatch.setattr(github, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(lambda req: resp)))
    with pytest.raises(github.GitHubError):
        github.get_readme("a/b", interactive=True)
    assert sleeps == []
