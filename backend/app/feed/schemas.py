"""Pydantic 模型：LLM 结构化输出 + API 出入参。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ScreeningResult(BaseModel):
    """LLM 精筛输出。quality 1..5，由 screening 层夹紧。"""
    is_real_project: bool
    category: str = "其他"
    tagline_zh: str = ""
    why_zh: str = ""
    quality: int = Field(default=3)


class DraftResult(BaseModel):
    """「AI 帮我写」草稿：卖点 + 介绍 + AI 推荐分类。"""
    tagline_zh: str = ""
    intro_zh: str = ""
    suggested_category: str = "其他"


class UserOut(BaseModel):
    id: int
    login: str
    avatar_url: str = ""
    bio: str = ""


class RepoCardOut(BaseModel):
    """对齐前端 RepoCardData:见 spec 第 4 节映射表。"""
    id: int
    full_name: str
    title: str
    owner_login: str
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    stars: int = 0
    views: int = 0
    likes: int = 0
    source: str
    category: str = "其他"
    tagline_zh: str = ""
    published_at: str = ""     # ISO 8601
    cover_url: str | None = None


class FeedOut(BaseModel):
    cards: list[RepoCardOut]
    has_more: bool


class SearchOut(FeedOut):
    total: int


class RepoDetailOut(RepoCardOut):
    """仓库详情 = 卡片全字段 + 详情页补充；不再含 readme_md/giscus_*。"""
    intro_zh: str = ""
    github_url: str
    default_branch: str = "main"
    discussions_open: bool = False
    liked: bool = False       # 当前用户点赞态；未登录恒 false
    favorited: bool = False   # 当前用户收藏态；未登录恒 false


class TreeItem(BaseModel):
    """前端文件树节点：blob→file、tree→dir，children 组成嵌套。"""
    name: str
    path: str
    type: str  # 'file' | 'dir'
    children: list["TreeItem"] = Field(default_factory=list)


class RepoFileOut(BaseModel):
    path: str
    content: str


class MyGithubRepoOut(BaseModel):
    """投稿页候选仓库:github_id 即后续 ai-draft/submit 的定位键(status 表达三态徽标)。"""
    github_id: int
    full_name: str
    title: str
    language: str | None = None
    stars: int = 0
    status: str = ""  # '' 未投稿 | published | pending_claim


class UserProfileOut(BaseModel):
    login: str
    avatar_url: str = ""
    bio: str = ""
    repo_count: int = 0
    star_count: int = 0
    favorite_count: int = 0


class SubmitIn(BaseModel):
    full_name: str
    tagline_zh: str = Field(max_length=60)
    intro_zh: str = ""
    category: str = "其他"
    cover_url: str | None = ""

    @field_validator("cover_url")
    @classmethod
    def _check_cover_url(cls, v: str | None) -> str:
        """封面以 <img src> 直出,不校验就是存储型 XSS/钓鱼向量。

        None 归一为空串:前端 SubmitPayload.cover_url 恒发 null,后端向既有前端类型看齐。
        """
        if v is None:
            return ""
        v = v.strip()
        if not v:
            return ""
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("cover_url 必须是 http(s) 链接")
        if len(v) > 500:
            raise ValueError("cover_url 过长(上限 500 字符)")
        return v


class DraftIn(BaseModel):
    github_id: int


class BioIn(BaseModel):
    bio: str = Field(max_length=200)


class InteractionIn(BaseModel):
    repo_id: int
    kind: str    # 仅 like / favorite;visit 由服务端在详情接口写入
    active: bool
