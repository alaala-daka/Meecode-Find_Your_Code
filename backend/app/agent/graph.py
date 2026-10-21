"""LangGraph 工作流:① 输入改写 → ② 概念拆解 → ③ 关系描述 → ④ 停机控制。

对应构思文档"系统架构总览"的四步。两个入口:
- run_rewrite:创建根节点(只做改写);
- run_expand:展开节点(stop_check → decompose → relate)。
"""
from __future__ import annotations

from typing import Any, Optional, TypedDict

from langgraph.graph import END, StateGraph

from .. import config, llm_usage
from ..llm import chat_json
from ..schemas import (
    ChildSpec,
    DecomposeResult,
    EdgeDescription,
    ElaborateResult,
    LLMOverride,
    RelateResult,
    RewriteResult,
    Settings,
)
from . import mock, prompts


class AgentState(TypedDict, total=False):
    # 输入
    raw_input: str
    parent_title: str
    path: list[str]
    depth: int
    settings: Settings
    llm: LLMOverride
    route: str
    # 中间/输出
    topic: str
    children: list[ChildSpec]
    edges: list[EdgeDescription]
    refused: Optional[str]
    repo_context: Optional[dict]


# ---------------------------------------------------------------- nodes


async def rewrite_node(state: AgentState) -> dict[str, Any]:
    """① 输入改写:任意句式 → 以主题为核心的名词性陈述(F1)。"""
    if config.LLM_MOCK:
        return {"topic": mock.mock_rewrite(state["raw_input"])}
    result = await chat_json(
        prompts.REWRITE_SYSTEM,
        prompts.REWRITE_USER.format(raw_input=state["raw_input"]),
        RewriteResult,
        route=llm_usage.ROUTE_ROOTS,
        llm=state.get("llm"),
    )
    return {"topic": result.topic.strip()}


def stop_check_node(state: AgentState) -> dict[str, Any]:
    """④ 停机控制第一层:用户预设的最高发散层数(F3)。None 表示不限。"""
    max_depth = state["settings"].max_depth
    if max_depth is not None and state["depth"] >= max_depth:
        return {"refused": "max_depth"}
    return {"refused": None}


async def decompose_node(state: AgentState) -> dict[str, Any]:
    """② 概念拆解:生成 ≤max_children 个子节点,按相关度排序、标注类型(F2/F4)。

    已探索路径作为"Agent 推断层"的上下文传入提示词(F3 第二层)。
    """
    settings = state["settings"]
    if config.LLM_MOCK:
        return {"children": mock.mock_decompose(state["parent_title"], settings)}
    result = await chat_json(
        prompts.DECOMPOSE_SYSTEM,
        prompts.DECOMPOSE_USER.format(
            parent_title=state["parent_title"],
            path=" → ".join(state["path"]) or state["parent_title"],
            max_children=settings.max_children,
        )
        + prompts.repo_block(state.get("repo_context")),
        DecomposeResult,
        route=state["route"],
        llm=state.get("llm"),
    )
    children = sorted(result.children, key=lambda c: c.relevance, reverse=True)
    children = children[: settings.max_children]
    return {"children": children}


async def relate_node(state: AgentState) -> dict[str, Any]:
    """③ 关系描述:为每条边生成双向描述,聚焦两者区别(F6)。"""
    children = state.get("children") or []
    if not children:
        return {"edges": []}
    if config.LLM_MOCK:
        return {"edges": mock.mock_relate(state["parent_title"], children)}
    titles = "\n".join(f"- {c.title}" for c in children)
    result = await chat_json(
        prompts.RELATE_SYSTEM,
        prompts.RELATE_USER.format(
            parent_title=state["parent_title"],
            path=" → ".join(state["path"]) or state["parent_title"],
            children_titles=titles,
        )
        + prompts.repo_block(state.get("repo_context")),
        RelateResult,
        route=state["route"],
        llm=state.get("llm"),
    )
    return {"edges": result.edges}


# ---------------------------------------------------------------- graph 装配


def _route_after_stop(state: AgentState) -> str:
    return "refused" if state.get("refused") else "proceed"


_expand_graph = (
    StateGraph(AgentState)
    .add_node("stop_check", stop_check_node)
    .add_node("decompose", decompose_node)
    .add_node("relate", relate_node)
    .set_entry_point("stop_check")
    .add_conditional_edges("stop_check", _route_after_stop, {"refused": END, "proceed": "decompose"})
    .add_edge("decompose", "relate")
    .add_edge("relate", END)
    .compile()
)


async def run_rewrite(raw_input: str, llm: LLMOverride | None = None) -> str:
    state = await _rewrite_graph.ainvoke({"raw_input": raw_input, "llm": llm})
    return state["topic"]


async def run_expand(
    parent_title: str,
    path: list[str],
    depth: int,
    settings: Settings,
    llm: LLMOverride | None = None,
    repo_context: Optional[dict] = None,
    route: str = llm_usage.ROUTE_EXPAND,
) -> tuple[list[ChildSpec], list[EdgeDescription], Optional[str]]:
    state = await _expand_graph.ainvoke(
        {
            "parent_title": parent_title,
            "path": path,
            "depth": depth,
            "settings": settings,
            "llm": llm,
            "repo_context": repo_context,
            "route": route,
        }
    )
    return state.get("children") or [], state.get("edges") or [], state.get("refused")


async def run_elaborate(
    node_title: str,
    path: list[str],
    brief: str,
    llm: LLMOverride | None = None,
    repo_context: Optional[dict] = None,
) -> str:
    """详细展开:为已展开节点生成更丰富的 markdown 阐述(不产生新子节点)。"""
    if config.LLM_MOCK:
        return mock.mock_elaborate(node_title, path, brief)
    result = await chat_json(
        prompts.ELABORATE_SYSTEM,
        prompts.ELABORATE_USER.format(
            node_title=node_title,
            path=" → ".join(path) or node_title,
            brief=brief or node_title,
        )
        + prompts.repo_block(repo_context),
        ElaborateResult,
        route=llm_usage.ROUTE_NODES_DETAIL,
        llm=llm,
    )
    return result.detail.strip()


async def run_repo_topic(
    full_name: str, description: str, readme: str, llm: LLMOverride | None = None
) -> str:
    """仓库解读根主题:按仓库实情生成"XX 的解读"式名词性陈述。"""
    if config.LLM_MOCK:
        return f"{full_name} 仓库的解读"
    result = await chat_json(
        prompts.REPO_TOPIC_SYSTEM,
        prompts.REPO_TOPIC_USER.format(
            full_name=full_name, description=description or "(无)", readme=readme or "(无)"
        ),
        RewriteResult,
        route=llm_usage.ROUTE_REPO_ROOT,
        llm=llm,
    )
    return result.topic.strip()


# rewrite 是单节点小图,放在函数定义之后装配
_rewrite_graph = (
    StateGraph(AgentState)
    .add_node("rewrite", rewrite_node)
    .set_entry_point("rewrite")
    .add_edge("rewrite", END)
    .compile()
)
