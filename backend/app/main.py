"""FastAPI 入口:会话管理(仅内存,不持久化)+ 根节点创建 + 节点展开 + 阅读器伴读。"""
from __future__ import annotations

import json
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import config, gh
from .agent import prompts
from .agent.graph import run_elaborate, run_expand, run_repo_topic, run_rewrite
from .agent.mock import mock_chat_events, mock_repo_context
from .feed import db
from .security import SecurityMiddleware
from .feed.routes import comments as comments_routes
from .feed.routes import feed as feed_routes
from .feed.routes import me as me_routes
from .feed.routes import repos as repos_routes
from .feed.routes import submit as submit_routes
from .feed.routes import users as users_routes
from .llm import chat_stream_events
from .schemas import (  # 解读域 schemas,原样
    ChatRequest, CreateRootRequest, CreateRootResponse, CreateSessionResponse,
    DetailRequest, DetailResponse, EdgePayload, ExpandRequest, ExpandResponse,
    NodePayload, RepoRootRequest, RepoRootResponse, Settings,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """进程启动时建表(fail-fast):DB 异常在启动期暴露,而不是第一个请求 500。"""
    config.ensure_prod_secrets()
    conn = db.connect()
    try:
        db.init_db(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="觅码 API", version="0.2.0", lifespan=lifespan)

# 层序红线：security 先加（内层），CORS 后加（外层）——429 出栈时经 CORS 补头
app.add_middleware(SecurityMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config.CORS_ORIGINS),
    allow_credentials=True,  # 登录态是 cookie,必须允许
    allow_methods=["*"],
    allow_headers=["*"],
)

# 信息流域路由(前缀 /api)
app.include_router(feed_routes.router, prefix="/api")
app.include_router(repos_routes.router, prefix="/api")
app.include_router(submit_routes.router, prefix="/api")
app.include_router(me_routes.router, prefix="/api")
app.include_router(users_routes.router, prefix="/api")
app.include_router(comments_routes.router, prefix="/api")

class _SessionStore:
    """进程内解读会话:滑动 TTL + 容量上限,满额拒新键(不淘汰既有,防洪水重置)。

    与 SlidingWindowLimiter 同一取舍;dict 写入加锁,同步路由跑在线程池里。
    """

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, now: float | None = None) -> str | None:
        ts = time.time() if now is None else now
        with self._lock:
            self._sweep(ts)
            if len(self._data) >= config.EXPLAIN_SESSION_MAX:
                return None
            sid = uuid.uuid4().hex
            self._data[sid] = {"last_seen": ts, "repo_context": None}
            return sid

    def get(self, session_id: str, now: float | None = None) -> dict | None:
        ts = time.time() if now is None else now
        with self._lock:
            item = self._data.get(session_id)
            if item is None:
                return None
            if ts - item["last_seen"] > config.EXPLAIN_SESSION_TTL:
                del self._data[session_id]
                return None
            item["last_seen"] = ts
            return item

    def _sweep(self, ts: float) -> None:
        cutoff = config.EXPLAIN_SESSION_TTL
        for k in [k for k, v in self._data.items() if ts - v["last_seen"] > cutoff]:
            del self._data[k]

    def reset(self) -> None:
        with self._lock:
            self._data.clear()


# 会话仅存活于进程内存(构思文档开放问题4默认:仅会话内有效);TTL/容量见 config.EXPLAIN_SESSION_*
_sessions = _SessionStore()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "time": int(time.time())}


@app.post("/api/sessions", response_model=CreateSessionResponse)
def create_session() -> CreateSessionResponse:
    session_id = _sessions.create()
    if session_id is None:
        raise HTTPException(status_code=429, detail="会话创建过多，请稍后再试",
                            headers={"Retry-After": "60"})
    return CreateSessionResponse(session_id=session_id)


@app.post("/api/roots", response_model=CreateRootResponse)
def create_root(req: CreateRootRequest) -> CreateRootResponse:
    _require_session(req.session_id)
    raw = req.raw_input.strip()
    if not raw:
        raise HTTPException(status_code=422, detail="输入不能为空")
    try:
        topic = run_rewrite(raw, llm=req.llm)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    node = NodePayload(id=uuid.uuid4().hex, title=topic, content=topic, relevance=1.0)
    return CreateRootResponse(node=node)


@app.post("/api/repos/root", response_model=RepoRootResponse)
def create_repo_root(req: RepoRootRequest) -> RepoRootResponse:
    """以仓库为根建图:拉取理解包 → 主题陈述 → 自动首层展开。"""
    _require_session(req.session_id)
    if config.LLM_MOCK:
        repo = mock_repo_context(req.full_name.strip().strip("/"))
    else:
        try:
            repo = gh.fetch_repo_context(req.full_name, req.default_branch)
        except gh.GitHubFetchError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    _require_session(req.session_id)["repo_context"] = repo

    try:
        topic = run_repo_topic(repo["full_name"], repo["description"], repo["readme"], llm=req.llm)
        children, edges, _refused = run_expand(
            parent_title=topic,
            path=[topic],
            depth=0,
            settings=Settings(),
            llm=req.llm,
            repo_context=repo,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    node = NodePayload(id=uuid.uuid4().hex, title=topic, content=topic, relevance=1.0)
    edge_by_title = {e.child_title: e for e in edges}
    child_payloads = [
        NodePayload(
            id=uuid.uuid4().hex,
            title=c.title,
            content=c.content,
            node_type=c.node_type,
            relevance=c.relevance,
        )
        for c in children
    ]
    edge_payloads = [
        EdgePayload(
            id=uuid.uuid4().hex,
            parent_id=node.id,
            child_id=p.id,
            forward=edge_by_title[p.title].forward if p.title in edge_by_title else "",
            backward=edge_by_title[p.title].backward if p.title in edge_by_title else "",
        )
        for p in child_payloads
    ]
    return RepoRootResponse(node=node, children=child_payloads, edges=edge_payloads)


@app.post("/api/expand", response_model=ExpandResponse)
def expand(req: ExpandRequest) -> ExpandResponse:
    _require_session(req.session_id)
    try:
        children, edges, refused = run_expand(
            parent_title=req.node_title,
            path=req.path,
            depth=req.depth,
            settings=req.settings,
            llm=req.llm,
            repo_context=_require_session(req.session_id).get("repo_context"),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if refused:
        return ExpandResponse(refused=refused)

    child_payloads: list[NodePayload] = []
    edge_payloads: list[EdgePayload] = []
    edge_by_title = {e.child_title: e for e in edges}

    for child in children:
        child_id = uuid.uuid4().hex
        child_payloads.append(
            NodePayload(
                id=child_id,
                title=child.title,
                content=child.content,
                node_type=child.node_type,
                relevance=child.relevance,
            )
        )
        desc = edge_by_title.get(child.title)
        edge_payloads.append(
            EdgePayload(
                id=uuid.uuid4().hex,
                parent_id=req.node_id,
                child_id=child_id,
                forward=desc.forward if desc else "",
                backward=desc.backward if desc else "",
            )
        )

    return ExpandResponse(children=child_payloads, edges=edge_payloads)


@app.post("/api/nodes/detail", response_model=DetailResponse)
def node_detail(req: DetailRequest) -> DetailResponse:
    """详细展开(双击已展开节点):生成更丰富的 markdown 阐述,不产生新子节点。"""
    _require_session(req.session_id)
    try:
        detail = run_elaborate(
            req.node_title,
            req.path,
            req.brief,
            llm=req.llm,
            repo_context=_require_session(req.session_id).get("repo_context"),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return DetailResponse(node_id=req.node_id, detail=detail)


def _ndjson_stream(events: Iterator[dict]) -> Iterator[str]:
    """统一 NDJSON 输出;流中途异常以 error 事件收尾(此时 HTTP 状态已提交 200)。"""
    try:
        for ev in events:
            yield json.dumps(ev, ensure_ascii=False) + "\n"
    except Exception as exc:
        yield json.dumps({"type": "error", "message": f"生成中断:{exc}"}, ensure_ascii=False) + "\n"


@app.post("/api/reader/chat")
def reader_chat(req: ChatRequest) -> StreamingResponse:
    """阅读器伴读问答:NDJSON 流式;mock 模式输出确定性模拟回答。"""
    _require_session(req.session_id)
    history = [{"role": m.role, "content": m.content} for m in req.messages[-20:]]
    if config.LLM_MOCK:
        events = mock_chat_events(node_title=req.node_title, messages=history)
    else:
        if not (config.llm_configured() or (req.llm and (req.llm.api_key or "").strip())):
            raise HTTPException(status_code=502, detail="LLM 未配置:请在设置区填写伴读模型,或配置后端环境变量")
        tavily_key = ((req.tavily_api_key or "").strip() or config.TAVILY_API_KEY) or None
        # 用 replace 填充占位符,避免 detail 中的字面量花括号被 str.format 解析
        context = (
            prompts.READER_CONTEXT_USER
            .replace("{node_title}", req.node_title)
            .replace("{path}", " → ".join(req.path) or req.node_title)
            .replace("{detail}", req.detail or "(暂无精读内容)")
        )
        context += prompts.repo_block(_require_session(req.session_id).get("repo_context"))
        events = chat_stream_events(
            system=prompts.READER_CHAT_SYSTEM,
            messages=[{"role": "user", "content": context}, *history],
            llm=req.llm,
            tavily_key=tavily_key,
        )
    return StreamingResponse(_ndjson_stream(events), media_type="application/x-ndjson")


def _require_session(session_id: str) -> dict:
    item = _sessions.get(session_id)
    if item is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期,请重新开始")
    return item
