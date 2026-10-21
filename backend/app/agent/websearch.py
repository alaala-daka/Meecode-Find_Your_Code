"""Tavily 联网搜索:httpx 直连 REST API(httpx 已由 openai 传递依赖,不另引 SDK)。"""
from __future__ import annotations

TAVILY_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "联网搜索公开网页资料,用于回答涉及最新动态、具体数据或不确定事实的问题。",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜索查询词,精炼为一句话或几个关键词"}},
            "required": ["query"],
        },
    },
}


async def web_search(query: str, api_key: str, max_results: int = 5) -> list[dict]:
    """返回 [{title, url, content}] 摘要列表;异常由调用方兜底成 error 结果。"""
    import httpx  # 懒加载:mock/无 key 场景不触发

    async with httpx.AsyncClient(follow_redirects=False, timeout=15) as c:
        resp = await c.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": max_results},
        )
    resp.raise_for_status()
    data = resp.json()
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": (r.get("content") or "")[:400]}
        for r in data.get("results", [])[:max_results]
    ]
