"""筛选管道：规则粗筛（零成本，几万→几百）+ LLM 精筛（每仓库 1 次调用）。

粗筛门槛与黑名单全在 config，便于按实际噪声手调。
followers 上限只用于采集端 —— 投稿不跑粗筛（见 spec 第 4 节）。
"""
from __future__ import annotations

import re

from .. import config
from . import llm, mock
from .schemas import ScreeningResult

CODE_SUFFIXES = (
    ".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java", ".c", ".h",
    ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift", ".kt", ".zig", ".lua",
    ".scala", ".sh", ".vue", ".svelte", ".m", ".mm", ".dart", ".ex", ".jl",
)

SCREEN_SYSTEM = """你是开源项目审稿人。判断一个 GitHub 仓库是否为「真实的、有价值的原创项目」。

判为 false 的典型情况：课程作业、教程跟练、awesome 清单、个人配置/简历、
空壳仓库、仅换名的模板复制。

只输出 JSON，字段：
- is_real_project: 布尔
- category: 从这些里选一个：{categories}
- tagline_zh: 一句话卖点，简体中文，不超过 30 字，讲清它做什么、对谁有用
- why_zh: 推荐理由，简体中文，不超过 80 字
- quality: 1..5 的整数，5 为最佳

tagline_zh 与 why_zh 必须用简体中文，即使仓库本身是英文。"""

SCREEN_USER = """仓库：{full_name}

README（截断至 4000 字符）：
{readme}

文件树（部分）：
{tree}"""


def star_velocity(stars: int, created_at: int, now: int) -> float:
    """star 增速（个/周）。新仓库按至少 1 天计，避免除零。"""
    age_days = max(1.0, (now - created_at) / 86400)
    return stars / (age_days / 7)


def count_code_files(tree: list[dict]) -> int:
    return sum(
        1 for t in tree
        if t.get("type") == "blob" and t.get("path", "").lower().endswith(CODE_SUFFIXES)
    )


def _hits_blacklist(full_name: str, topics: list[str]) -> str:
    """按词边界匹配，避免 resume 误杀 resumable-upload。"""
    name = full_name.split("/")[-1].lower()
    words = set(re.split(r"[^a-z0-9]+", name)) | {t.lower() for t in topics}
    for bad in config.NAME_BLACKLIST:
        if bad in words or bad in {t.lower() for t in topics}:
            return bad
        # 处理 100-days 这类自带连字符的词
        if "-" in bad and bad in name:
            return bad
    return ""


def passes_rules(
    repo: dict, readme: str, tree: list[dict], followers: int, now: int
) -> tuple[bool, str]:
    """采集端粗筛。返回 (是否通过, 未通过原因)。"""
    if repo.get("archived"):
        return False, "已归档"
    if len(readme) < config.MIN_README_CHARS:
        return False, f"README 过短（{len(readme)} < {config.MIN_README_CHARS}）"
    n_code = count_code_files(tree)
    if n_code < config.MIN_CODE_FILES:
        return False, f"代码文件过少（{n_code} < {config.MIN_CODE_FILES}）"
    age_days = (now - repo.get("pushed_at", 0)) / 86400
    if age_days > config.MAX_PUSHED_AGE_DAYS:
        return False, f"近期无提交（{int(age_days)} 天前）"
    v = star_velocity(repo.get("stars", 0), repo.get("created_at", now), now)
    if v < config.MIN_STAR_VELOCITY:
        return False, f"star 增速不足（{v:.1f}/周 < {config.MIN_STAR_VELOCITY}）"
    if followers >= config.MAX_OWNER_FOLLOWERS:
        return False, f"作者 followers 过高（{followers}），不属于待发掘群体"
    bad = _hits_blacklist(repo.get("full_name", ""), repo.get("topics") or [])
    if bad:
        return False, f"命中黑名单词「{bad}」"
    return True, ""


def screen_repo(full_name: str, readme: str, tree: list[dict], *,
                route: str, repo_id: int | None = None) -> ScreeningResult:
    """LLM 精筛。越界 quality 夹到 1..5，未知分类回落「其他」。"""
    if config.LLM_MOCK:
        result = ScreeningResult.model_validate(mock.mock_screening(full_name))
    else:
        paths = "\n".join(t["path"] for t in tree[:60])
        result = llm.chat_json(
            system=SCREEN_SYSTEM.format(categories="、".join(config.CATEGORIES)),
            user=SCREEN_USER.format(full_name=full_name, readme=readme[:4000], tree=paths),
            model=ScreeningResult,
            route=route,
            repo_id=repo_id,
        )
    result.quality = max(1, min(5, result.quality))
    if result.category not in config.CATEGORIES:
        result.category = "其他"
    return result
