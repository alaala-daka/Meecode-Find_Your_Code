"""确定性假数据：GITHUB_MOCK / LLM_MOCK 下替代真实 API，供离线开发与测试。"""
from __future__ import annotations

import time

_FIXTURES: list[dict] = [
    {
        "id": 90001, "full_name": "demo/agent-runtime", "owner_login": "demo",
        "language": "TypeScript", "topics": ["agent", "llm"], "stars": 34,
        "license": "MIT", "default_branch": "main",
    },
    {
        "id": 90002, "full_name": "kenji/tiny-vm", "owner_login": "kenji",
        "language": "Rust", "topics": ["wasm", "vm"], "stars": 12,
        "license": "Apache-2.0", "default_branch": "main",
    },
    {
        "id": 90003, "full_name": "mira/flowlens", "owner_login": "mira",
        "language": "Python", "topics": ["visualization"], "stars": 61,
        "license": "MIT", "default_branch": "main",
    },
]


def mock_repos(now: int | None = None) -> list[dict]:
    """时间戳相对当前时间生成 —— 写死 2023 年的话粗筛会以「近期无提交」全部淘汰，
    离线模式就永远采不到东西。created 设 7 天前保证 star 增速达标。"""
    ref = int(now or time.time())
    return [
        {**r, "created_at": ref - 7 * 86400, "pushed_at": ref - 86400, "archived": False}
        for r in _FIXTURES
    ]

_MOCK_README = (
    "# {name}\n\n这是一个用于离线开发的模拟仓库说明。" + "它刻意写得足够长，"
    "以便通过规则粗筛对 README 长度的要求，从而让整条采集管道在没有网络的情况下也能跑通。" * 10
)

_MOCK_TREE = [
    {"path": "README.md", "type": "blob", "size": 2048},
    {"path": "src", "type": "tree", "size": 0},
    {"path": "src/main.ts", "type": "blob", "size": 1200},
    {"path": "src/agent.ts", "type": "blob", "size": 3400},
    {"path": "src/tools.ts", "type": "blob", "size": 900},
    {"path": "src/config.ts", "type": "blob", "size": 400},
    {"path": "tests/agent.test.ts", "type": "blob", "size": 800},
    {"path": "package.json", "type": "blob", "size": 300},
]


def mock_readme(full_name: str) -> str:
    return _MOCK_README.format(name=full_name.split("/")[-1])


def mock_tree(full_name: str) -> list[dict]:
    return [dict(t) for t in _MOCK_TREE]


def mock_file(full_name: str, path: str) -> str:
    return f"// {full_name} :: {path}\n// 模拟文件内容（GITHUB_MOCK=true）\nexport const demo = true;\n"


def mock_user(login: str) -> dict:
    return {"login": login, "id": abs(hash(login)) % 100000, "followers": 42,
            "avatar_url": f"https://avatars.githubusercontent.com/{login}"}


def mock_screening(full_name: str) -> dict:
    """LLM 精筛的确定性输出。"""
    name = full_name.split("/")[-1]
    return {
        "is_real_project": True,
        "category": "开发工具",
        "tagline_zh": f"{name}：一个可离线演示的模拟项目卖点",
        "why_zh": f"{name} 的模拟推荐理由，用于前端联调与离线开发。",
        "quality": 4,
    }


def mock_comment_verdict(content: str) -> dict:
    """LLM 合规判定的确定性输出：命中关键词判不合规，便于测试与离线演示。"""
    hit = next((w for w in ("垃圾", "广告", "刷屏") if w in content), "")
    return {
        "is_compliant": not hit,
        "reason": f"命中「{hit}」" if hit else "正常技术讨论",
    }
