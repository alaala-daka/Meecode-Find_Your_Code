"""「AI 帮我写」推广草稿生成：客观但正面，与质量精筛（screening）彻底分离。

精筛提示词（SCREEN_SYSTEM）要客观定分，会指出不足；推广文案要正面、避开负面。
二者意图相反，故各用各的提示词——本模块只服务投稿页「AI 帮我写」。
"""
from __future__ import annotations

from .. import config
from . import llm, mock
from .schemas import DraftGen, DraftResult

DRAFT_SYSTEM = """你是开源项目文案编辑，为作者的 GitHub 仓库写「推广页」文案：一句话卖点 + 详细介绍 + AI 推荐分类。

写作要求（务必遵守）：
- 只写正面：突出它做什么、核心能力与亮点、技术栈特色、适用对象与使用场景。
- 完全不写任何负面或未完成内容：缺陷、bug、局限、限制、不足、
  尚未接入/待完善/计划中的功能、已知问题、与竞品的差距等一概不提。
- 客观但正面：只依据 README 的真实信息，不夸大、不编造不存在的功能。
- 语气自然可信，不要营销腔或感叹号堆砌。
- 一律简体中文，即使仓库本身是英文。

只输出 JSON，字段：
- tagline_zh: 一句话卖点，不超过 30 字，讲清它做什么、对谁有用
- intro_zh: 详细介绍，2 到 4 句、约 60 到 160 字，概览它做什么、核心能力/亮点、技术与适用对象
- category: 从这些里选一个：{categories}"""

DRAFT_USER = """仓库：{full_name}

README（截断至 4000 字符）：
{readme}

文件树（部分）：
{tree}"""

TAGLINE_MAX = 40  # 对齐前端 SubmitPage TAGLINE_MAX


def draft_repo(full_name: str, readme: str, tree: list[dict], *,
               route: str, repo_id: int | None = None) -> DraftResult:
    """「AI 帮我写」：生成客观但正面的推广草稿。未知分类回落「其他」。"""
    if config.LLM_MOCK:
        gen = DraftGen.model_validate(mock.mock_draft(full_name))
    else:
        paths = "\n".join(t["path"] for t in tree[:60])
        gen = llm.chat_json(
            system=DRAFT_SYSTEM.format(categories="、".join(config.CATEGORIES)),
            user=DRAFT_USER.format(full_name=full_name, readme=readme[:4000], tree=paths),
            model=DraftGen,
            route=route,
            repo_id=repo_id,
        )
    if gen.category not in config.CATEGORIES:
        gen.category = "其他"
    return DraftResult(tagline_zh=gen.tagline_zh[:TAGLINE_MAX],
                       intro_zh=gen.intro_zh,
                       suggested_category=gen.category)
