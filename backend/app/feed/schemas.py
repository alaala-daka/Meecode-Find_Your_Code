"""Pydantic 模型：LLM 结构化输出 + API 出入参。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    gh_star_authed: bool = False   # 是否已授权点星同步（users.gh_token_enc 非空）


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
    total: int = 0   # 同 WHERE 的 COUNT(*)；已选条件行「共 N 个仓库」用


class SearchOut(FeedOut):
    """搜索响应与 feed 同形（total 已由 FeedOut 提供）。"""


class RepoDetailOut(RepoCardOut):
    """仓库详情 = 卡片全字段 + 详情页补充；不再含 readme_md/giscus_*。"""
    intro_zh: str = ""
    github_url: str
    default_branch: str = "main"
    liked: bool = False       # 当前用户点赞态；未登录恒 false
    favorited: bool = False   # 当前用户收藏态；未登录恒 false
    is_owner: bool = False   # 当前用户是否为作者/认领者（canModerate 依据）


class TreeItem(BaseModel):
    """前端文件树节点：blob→file、tree→dir，children 组成嵌套。"""
    name: str
    path: str
    type: str  # 'file' | 'dir'
    children: list["TreeItem"] = Field(default_factory=list)
    size: int = 0  # 文件字节数；dir 恒 0（图片大小护栏用）


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
    gh_sync: bool = True   # 仅 favorite-off 有效：False=只删本地，不动 GitHub（弹窗第二选项）


class InteractionOut(BaseModel):
    """互动响应。sync：favorite 为 SyncState——need_auth=待授权 / synced=已点星 /
    pending=待重试 / kept=仅取消本地（星保留）/ unstarred=已撤星 /
    skipped=仓库消失等不可点星终态（前端 Toast 提醒）；like 恒空串。"""
    active: bool
    sync: Literal["", "need_auth", "synced", "pending", "kept", "unstarred", "skipped"] = ""


class CommentOut(BaseModel):
    """单条评论：两层平铺（parent_id 恒指顶层）。status 供前端渲染「审核中/未通过/已隐藏」标记。

    moderation_reason 仅 LLM 拒绝时非空：前端以此区分「未通过审核」与「作者/管理隐藏」。
    """
    id: int
    repo_id: int
    user_id: int
    user_login: str
    user_avatar: str = ""
    parent_id: int | None = None
    content: str
    status: str
    moderation_reason: str = ""
    created_at: int
    created_at_iso: str = ""


class CommentsOut(BaseModel):
    """平铺列表：items 每顶层线程后跟其可见回复；total 为顶层线程数。"""
    items: list[CommentOut]
    total: int


class CommentIn(BaseModel):
    """发表评论/回复。content 校验带中文错误，前端可直出（同 SubmitIn 风格）。"""
    repo_id: int
    content: str
    parent_id: int | None = None

    @field_validator("content")
    @classmethod
    def _check_content(cls, v: str) -> str:
        from .. import config
        v = v.strip()
        if not v:
            raise ValueError("评论内容不能为空")
        if len(v) > config.COMMENT_MAX_LEN:
            raise ValueError(f"评论内容过长（上限 {config.COMMENT_MAX_LEN} 字符）")
        return v


class CommentVerdict(BaseModel):
    """LLM 评论合规判定输出（spec 决策 8）。"""
    is_compliant: bool
    reason: str = ""


class FeedbackIn(BaseModel):
    """提交反馈。body/contact 一律先 strip 再判空与计长，纯空白视为非法（spec §3.2）。"""
    model_config = ConfigDict(extra="forbid")
    category: Literal["bug", "suggest", "other"]
    body: str
    contact: str | None = None

    @field_validator("body")
    @classmethod
    def _check_body(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("反馈内容不能为空")
        if len(v) > 500:
            raise ValueError("反馈内容过长（上限 500 字符）")
        return v

    @field_validator("contact")
    @classmethod
    def _check_contact(cls, v: str | None) -> str | None:
        """spec §3.2：strip 后纯空白视为非法；「没填」请直接不传该键（主站表单即如此）。"""
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("联系方式不能留空（不填请省略该字段）")
        if len(v) > 100:
            raise ValueError("联系方式过长（上限 100 字符）")
        return v


class FeedbackOut(BaseModel):
    id: int


class FeedbackReply(BaseModel):
    """用户可见回复。不含 read_at（用户侧不需要「是否已读」语义）。"""
    id: int
    body: str
    author_login: str
    created_at: int


class FeedbackDetailOut(BaseModel):
    """我的反馈详情。刻意不含 contact/note——仅管理台可见（spec §3.1）。"""
    id: int
    category: str
    body: str
    status: str
    created_at: int
    updated_at: int
    replies: list[FeedbackReply]


class MyFeedbackItem(BaseModel):
    id: int
    category: str
    body_preview: str
    status: str
    created_at: int
    updated_at: int
    last_reply_preview: str | None = None
    last_reply_at: int | None = None
    unread_count: int = 0


class MyFeedbackOut(BaseModel):
    items: list[MyFeedbackItem]
    total: int


class ReplyNotification(BaseModel):
    feedback_id: int
    feedback_body_preview: str
    reply_id: int
    reply_body_preview: str
    created_at: int


class ReplyNotificationsOut(BaseModel):
    items: list[ReplyNotification]
    total: int
