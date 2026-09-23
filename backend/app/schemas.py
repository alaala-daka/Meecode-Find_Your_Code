"""Pydantic 模型:API 请求/响应 + Agent 结构化输出校验。"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------- 领域模型 ----------


class NodeType(str, Enum):
    """节点类型:概念 / 分类方法 / 维度(构思文档 F4)。"""

    CONCEPT = "concept"
    CATEGORY = "category"
    DIMENSION = "dimension"


class Settings(BaseModel):
    """设置区配置(3.3):单次最多展开数 + 最高发散层数(None=不限)。"""

    max_children: int = Field(default=3, ge=1, le=12)
    max_depth: Optional[int] = Field(default=None, ge=1, le=20)


class LLMOverride(BaseModel):
    """请求级 LLM 覆盖(设置区自定义模型):空/缺省字段回落到后端环境变量。"""

    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return v
        from .urlguard import validate_base_url
        return validate_base_url(v)


class ChildSpec(BaseModel):
    """decompose 输出的单个子节点。"""

    title: str
    node_type: NodeType = NodeType.CONCEPT
    relevance: float = Field(default=0.5, ge=0.0, le=1.0)
    content: str = ""


class DecomposeResult(BaseModel):
    children: list[ChildSpec] = Field(default_factory=list)


class EdgeDescription(BaseModel):
    """relate 输出的单条边双向描述:forward=父→子(重点叙述子节点),
    backward=子→父(重点叙述父节点),内容只讲两者区别与关系(F6)。"""

    child_title: str
    forward: str = ""
    backward: str = ""


class RelateResult(BaseModel):
    edges: list[EdgeDescription] = Field(default_factory=list)


class RewriteResult(BaseModel):
    """rewrite 输出:以主题为核心的名词性陈述(F1)。"""

    topic: str


# ---------- API 请求/响应 ----------


class CreateSessionResponse(BaseModel):
    session_id: str


class CreateRootRequest(BaseModel):
    session_id: str
    raw_input: str = Field(min_length=1, max_length=500)
    llm: Optional[LLMOverride] = None


class NodePayload(BaseModel):
    """返回给前端的节点(前端自行维护图结构)。"""
    id: str
    title: str
    content: str = ""
    node_type: NodeType = NodeType.CONCEPT
    relevance: float = 1.0


class EdgePayload(BaseModel):
    id: str
    parent_id: str
    child_id: str
    forward: str = ""
    backward: str = ""


class CreateRootResponse(BaseModel):
    node: NodePayload


class ExpandRequest(BaseModel):
    session_id: str
    node_id: str
    node_title: str
    path: list[str] = Field(default_factory=list, description="从根到当前节点的标题路径")
    depth: int = Field(ge=0)
    settings: Settings = Field(default_factory=Settings)
    llm: Optional[LLMOverride] = None


class ExpandResponse(BaseModel):
    children: list[NodePayload] = Field(default_factory=list)
    edges: list[EdgePayload] = Field(default_factory=list)
    refused: Optional[str] = None  # "max_depth" 等


class ElaborateResult(BaseModel):
    """elaborate 输出:节点的详细阐述(markdown)。"""

    detail: str


class DetailRequest(BaseModel):
    session_id: str
    node_id: str
    node_title: str
    path: list[str] = Field(default_factory=list)
    brief: str = ""
    llm: Optional[LLMOverride] = None


class DetailResponse(BaseModel):
    node_id: str
    detail: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    session_id: str
    node_id: str
    node_title: str
    path: list[str] = Field(default_factory=list)
    detail: str = ""
    messages: list[ChatMessage] = Field(default_factory=list)
    llm: Optional[LLMOverride] = None
    tavily_api_key: Optional[str] = None


class RepoRootRequest(BaseModel):
    """以仓库为根建图(觅码仓库解读)。"""

    session_id: str
    full_name: str = Field(min_length=1, max_length=200, description="owner/repo")
    default_branch: Optional[str] = None
    llm: Optional[LLMOverride] = None


class RepoRootResponse(BaseModel):
    """根节点 + 首层子节点 + 双向边(后端已替前端完成首层展开)。"""

    node: NodePayload
    children: list[NodePayload] = Field(default_factory=list)
    edges: list[EdgePayload] = Field(default_factory=list)
