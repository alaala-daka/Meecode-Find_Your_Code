"""模拟数据生成器:LLM_MOCK=true 时替代真实 LLM,用于离线开发/前端联调。

输出形态与真实 Agent 一致(主题陈述、相关度递减、类型轮换、双向关系描述),
但内容为模板化演示文本,不代表真实拆解质量。
"""
from __future__ import annotations

from typing import AsyncIterator

from ..schemas import ChildSpec, EdgeDescription, NodeType, Settings

_ASPECTS = ["核心定义", "历史背景", "关键要素", "运行机制", "应用场景", "常见误区", "相关领域", "度量方法"]
_TYPES = [NodeType.CONCEPT, NodeType.CATEGORY, NodeType.DIMENSION]


def mock_rewrite(raw_input: str) -> str:
    t = raw_input.strip().rstrip("?？").strip()
    if t.endswith("是什么"):
        return f"{t[:-3]}的概念"
    if t.startswith("什么是"):
        return f"{t[3:]}的概念"
    if t.startswith(("如何", "怎么")):
        return f"{t[2:]}的方法"
    if t.startswith("为什么"):
        return f"{t[3:]}的原因"
    return t if len(t) <= 10 else t[:10]


def mock_decompose(parent_title: str, settings: Settings) -> list[ChildSpec]:
    n = max(1, settings.max_children)
    children: list[ChildSpec] = []
    for i in range(n):
        aspect = _ASPECTS[i % len(_ASPECTS)]
        title = f"{parent_title}的{aspect}"
        children.append(
            ChildSpec(
                title=title,
                node_type=_TYPES[i % len(_TYPES)],
                relevance=round(0.95 - i * 0.12, 2),
                content=f"{title}:这是「{parent_title}」语境下关于{aspect}的要点概述(模拟数据)。",
            )
        )
    return children


def mock_relate(parent_title: str, children: list[ChildSpec]) -> list[EdgeDescription]:
    edges: list[EdgeDescription] = []
    for c in children:
        edges.append(
            EdgeDescription(
                child_title=c.title,
                forward=f"{c.title}是{parent_title}向该方向延伸出的子主题,侧重它在{parent_title}框架内的定位(模拟数据)。",
                backward=f"{parent_title}借由{c.title}被进一步拆解,二者是整体与部分的关系(模拟数据)。",
            )
        )
    return edges


def mock_elaborate(node_title: str, path: list[str], brief: str = "") -> str:
    """模拟详细阐述:确定性 markdown(离线演示用)。"""
    crumb = " → ".join(path) if path else node_title
    return (
        f"{node_title}是这一探索分支上的关键概念。在「{crumb}」的语境下,它承担着承上启下的作用。\n\n"
        f"## 核心阐释\n\n"
        f"这是关于「{node_title}」的模拟详细阐述:真实模式下,这里会由大模型生成 300-500 字的深入讲解,"
        f"包含机制剖析、背景脉络与易混点辨析。\n\n"
        f"## 一个具体例子\n\n"
        f"- 示例要点一:帮助建立直觉\n"
        f"- 示例要点二:连接已有知识\n\n"
        f"## 与路径的关系\n\n"
        f"沿着「{crumb}」继续深入,下一个节点将在此基础上展开。(模拟数据)"
    )


async def mock_chat_events(node_title: str, messages: list[dict]) -> AsyncIterator[dict]:
    """模拟伴读回答:确定性分块流式文本(离线演示用),永不触发工具。"""
    question = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    answer = (
        f"关于「{node_title}」,你问的是“{question[:24]}”。这是伴读助手的模拟回答:"
        f"真实模式下,我会结合该节点的精读内容简洁作答,必要时联网搜索资料补充。"
    )
    for i in range(0, len(answer), 12):
        yield {"type": "delta", "text": answer[i : i + 12]}
    yield {"type": "done"}


def mock_repo_context(full_name: str) -> dict:
    """mock 模式的仓库理解包:离线开发/联调用,不触 GitHub。"""
    return {
        "full_name": full_name,
        "default_branch": "main",
        "description": "演示用仓库:离线 mock 模式",
        "readme": "# Demo\n这是一个演示仓库,用于离线开发与前端联调。",
        "tree_text": "README.md\nsrc/\n  main.py\n  agent.py",
        "languages_text": "Python 100%",
    }
