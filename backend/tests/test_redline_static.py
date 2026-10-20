"""红线静态门禁(§12③ 可执行形态):async/generator 可达路径内禁止同步阻塞 I/O。

红线(计划 Global Constraints,最高优先级):`async def`(含异步生成器)可达路径内
禁止同步阻塞 I/O —— 违反即单请求冻结整个事件循环(比旧线程池更糟),判缺陷。

扫描语义:
- 根(root):所有 `async def`(含异步生成器)—— 它们必然在事件循环上执行。
  同步生成器(`def` 含 yield)**不作无条件根**,而是按「可达即查」处理:只有被
  async 根直接调用/迭代(即真正在事件循环上执行)才展开其体。理由:红线危害模型
  是「跑在事件循环上」,而 FastAPI 依赖注入的 sync generator 跑在线程池
  (fastapi.concurrency.contextmanager_in_threadpool,实证于 0.139),
  `feed/deps.get_conn` 这类 sync-by-design 生成器若按无条件根扫描即误报 ——
  与决策 CRITICAL「sync-by-design 不得误报」冲突时,按危害模型收敛;判别力不减
  (被 async 迭代的同步生成器照抓,见自检)。纯同步函数同理不作根。
- 可达调用(interprocedural):根体内的**直接调用**逐层跟进 app 内部函数体。
  这覆盖 F1 回归类缺陷:async 路径调用了内部用 socket.getaddrinfo 的同步助手
  (违禁调用不在 async 体词法内,但跑在事件循环上)。
- 线程边界不跟进:`threading.Thread(target=f)`/`asyncio.to_thread(f, ...)` 里 f 以
  实参出现、非直接调用 —— 交给线程即离开事件循环,不算违禁。故
  llm_usage.record_usage / traffic.writer.record(内存缓冲 + 守护线程落库)与其
  flush 链天然不误报,与决策「sync-by-design 不得误报」一致。
- 解析保守:仅跟进能唯一解析的调用目标(同名多定义/局部变量/第三方一律跳过),
  宁漏报不误报;漏报面由 test_redline_runtime.py 的运行时探针补。

误报防线(决策 CRITICAL):
- 匹配限定根名:`socket.getaddrinfo` 只认 `socket.` 前缀或裸名,`loop.getaddrinfo`
  (async 正解)不误报;`time.sleep` 不误报 `asyncio.sleep`;`OpenAI` 不误报
  `AsyncOpenAI`;`httpx.Client` 不误报 `AsyncClient`;`invoke` 不误报 `ainvoke`。
- 每条规则都有下方 seeded 自检(判别力自证):该抓的必抓、不该抓的必不抓。
"""
from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"

# 启动期豁免(唯一一处,test_startup_exemption_is_minimal 钉死,防豁免名单悄悄长大):
# app.main.lifespan 在 uvicorn 开始接受请求**之前**执行,阻塞只发生在启动瞬间,
# 红线危害模型(「单请求冻结全站」)不成立;但其可达路径确含 db.connect/db.init_db/
# PolicyCache.maybe_refresh 的同步 sqlite I/O,按启动期语义豁免而非按代码语义放行。
# 根治建议(见任务报告):启动段挪入 asyncio.to_thread。
STARTUP_EXEMPT_ROOTS = frozenset({"app.main.lifespan"})


# ---------- 违禁匹配 ----------

# 裸名调用(含 from X import y 后直呼 y 的形态)
_BARE = {
    "getaddrinfo": "同步 DNS",
    "gethostbyname": "同步 DNS",
    "sleep": "同步睡眠",
    "OpenAI": "同步 OpenAI 客户端",
    "connect": "同步 sqlite3.connect",
    "invoke": "graph.invoke 同步",
    "open": "同步文件 I/O",
}

# 属性调用里无法从根名限定的(接收者类型不可静态判定,按属性名收口)
_ATTR_ONLY = {
    "execute": "同步 sqlite3 写",
    "executemany": "同步 sqlite3 写",
    "commit": "同步 sqlite3 写",
    "invoke": "graph.invoke 同步",
    "read": "同步文件 I/O",
    "write": "同步文件 I/O",
    "OpenAI": "同步 OpenAI 客户端",
}


def _dotted(func: ast.expr) -> str | None:
    """Name/Attribute 纯链的点分名;链中有 Call/Subscript 等则 None(asyncio.get_running_loop().getaddrinfo 属此类,不判违禁)。"""
    parts: list[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _forbidden_reason(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return _BARE.get(func.id)
    if not isinstance(func, ast.Attribute):
        return None
    dotted = _dotted(func)
    if dotted is not None:
        segs = dotted.split(".")
        root, last = segs[0], segs[-1]
        if dotted in ("socket.getaddrinfo", "socket.gethostbyname"):
            return "同步 DNS"
        if dotted == "time.sleep":
            return "同步睡眠"
        if dotted == "sqlite3.connect":
            return "同步 sqlite3.connect"
        if root == "httpx" and last in ("post", "get", "request"):
            return "同步 httpx 直发"
        if root == "httpx" and last == "Client":
            return "同步 httpx.Client"
        if root == "requests":
            return "同步 requests"
        return _ATTR_ONLY.get(last)
    return _ATTR_ONLY.get(func.attr)


# ---------- 索引与调用解析(只为「可达调用」服务;解析不出即跳过) ----------


@dataclass
class FuncInfo:
    module: str
    name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    cls: str | None          # 所属类(方法)
    parent: "FuncInfo | None"  # 所在外层函数(嵌套 def)
    qual: str


class _Module:
    def __init__(self, name: str, tree: ast.Module):
        self.name = name
        self.tree = tree
        self.funcs: list[FuncInfo] = []
        self.methods: dict[str, dict[str, FuncInfo]] = {}   # 类名 -> 方法名 -> fn
        self.imports: dict[str, tuple] = {}                  # 别名 -> ("module", m) | ("func", m, name)
        self.instances: dict[str, str] = {}                  # 模块级 x = Cls(...) -> 类名
        self.classes: set[str] = set()


class _Index:
    def __init__(self, sources: dict[str, str]):
        self.modules: dict[str, _Module] = {}
        self.trees: dict[str, ast.Module] = {}
        for mod, src in sources.items():
            tree = ast.parse(src)
            self.trees[mod] = tree
            self.modules[mod] = _Module(mod, tree)
        for mod, module in self.modules.items():
            self._build(module)

    def _build(self, module: _Module) -> None:
        def visit(node, cls: str | None, parent: FuncInfo | None) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        module.imports[alias.asname or alias.name.split(".")[0]] = (
                            "module", alias.name.split(".")[0])
                elif isinstance(child, ast.ImportFrom):
                    base = self._from_target(module.name, child)
                    for alias in child.names:
                        full = f"{base}.{alias.name}" if base else alias.name
                        if full in self.modules:   # 导入的其实是子模块(from .feed import db)
                            module.imports[alias.asname or alias.name] = ("module", full)
                        else:
                            module.imports[alias.asname or alias.name] = ("func", base, alias.name)
                elif isinstance(child, ast.ClassDef):
                    module.classes.add(child.name)
                    visit(child, child.name, parent)
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qual = f"{module.name}.{child.name}"
                    if cls:
                        qual = f"{module.name}.{cls}.{child.name}"
                    elif parent is not None:
                        qual = f"{parent.qual}.{child.name}"
                    info = FuncInfo(module.name, child.name, child, cls, parent, qual)
                    module.funcs.append(info)
                    if cls:
                        module.methods.setdefault(cls, {})[child.name] = info
                    visit(child, cls, info)
                elif isinstance(child, ast.Assign) and parent is None and cls is None:
                    for t in child.targets:
                        if isinstance(t, ast.Name) and isinstance(child.value, ast.Call):
                            fn = child.value.func
                            if isinstance(fn, ast.Name):
                                module.instances[t.id] = fn.id
                            elif isinstance(fn, ast.Attribute):
                                module.instances[t.id] = fn.attr
                else:
                    visit(child, cls, parent)

        visit(module.tree, None, None)

    @staticmethod
    def _from_target(current: str, node: ast.ImportFrom) -> str:
        if node.level == 0:
            return node.module or ""
        pkg = current.split(".")[:-1]
        base = pkg[: len(pkg) - (node.level - 1)]
        return ".".join(base + ([node.module] if node.module else []))

    def unique_func(self, module: str, name: str) -> FuncInfo | None:
        m = self.modules.get(module)
        if m is None:
            return None
        cands = [f for f in m.funcs if f.name == name and f.cls is None]
        return cands[0] if len(cands) == 1 else None

    def unique_method(self, module: str, cls: str, name: str) -> FuncInfo | None:
        m = self.modules.get(module)
        if m is None:
            return None
        return m.methods.get(cls, {}).get(name)

    def walk_attr(self, module: str, segs: list[str]) -> FuncInfo | None:
        """模块命名空间逐段走:子模块 → 模块级函数 → 类.方法 → 实例.方法。"""
        m = self.modules.get(module)
        if m is None or not segs:
            return None
        head, *tail = segs
        sub = f"{module}.{head}"
        if sub in self.modules:
            return self.walk_attr(sub, tail)
        if head in m.imports and m.imports[head][0] == "module":
            return self.walk_attr(m.imports[head][1], tail)
        if not tail:
            return self.unique_func(module, head)
        if head in m.classes:
            return self.unique_method(module, head, tail[0]) if len(tail) == 1 else None
        if head in m.instances:
            return self.unique_method(module, m.instances[head], tail[0]) if len(tail) == 1 else None
        return None

    def resolve(self, func: ast.expr, fi: FuncInfo) -> FuncInfo | None:
        if isinstance(func, ast.Name):
            scope: FuncInfo | None = fi
            while scope is not None:  # 内层嵌套 def 优先
                nested = [f for f in self.modules[fi.module].funcs
                          if f.parent is scope and f.name == func.id]
                if len(nested) == 1:
                    return nested[0]
                scope = scope.parent
            hit = self.unique_func(fi.module, func.id)
            if hit is not None:
                return hit
            imp = self.modules[fi.module].imports.get(func.id)
            if imp and imp[0] == "func":
                return self.unique_func(imp[1], imp[2])
            return None
        if isinstance(func, ast.Attribute):
            recv = func.value
            if isinstance(recv, ast.Name) and recv.id in ("self", "cls") and fi.cls:
                return self.unique_method(fi.module, fi.cls, func.attr)
            recv_dotted = _dotted(recv)
            if recv_dotted is None:
                return None
            segs = recv_dotted.split(".") + [func.attr]
            imp = self.modules[fi.module].imports.get(segs[0])
            if imp is not None and imp[0] == "module":
                return self.walk_attr(imp[1], segs[1:])
            return self.walk_attr(fi.module, segs)  # 同模块实例/类/函数
        return None


# ---------- 扫描 ----------


@dataclass(frozen=True)
class Finding:
    root: str
    site: str
    module: str
    lineno: int
    call: str
    reason: str

    def __str__(self) -> str:
        via = f"{self.root} -> {self.site}" if self.site != self.root else self.root
        return f"{self.module}:{self.lineno} {self.call} [{self.reason}] (root {via})"


def _is_root_fn(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """根 = async def(含异步生成器)。同步 def(含同步生成器)跑在线程池/守护线程,
    仅当被 async 根直接调用时经「可达调用」展开,不作无条件根(见模块 docstring)。"""
    return isinstance(node, ast.AsyncFunctionDef)


def _iter_own_calls(node: ast.FunctionDef | ast.AsyncFunctionDef):
    """体内的调用点;嵌套 def/lambda/class 是独立作用域(其体由各自扫描/跟进负责)。"""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(n, ast.Call):
            yield n
        stack.extend(ast.iter_child_nodes(n))


def _call_label(func: ast.expr) -> str:
    return _dotted(func) or (getattr(func, "attr", None) or getattr(func, "id", None) or "<?>")


def scan_modules(sources: dict[str, str]) -> list[Finding]:
    """扫描全部 app 模块;返回违禁清单(空 = 红线守住)。"""
    index = _Index(sources)
    findings: list[Finding] = []
    all_funcs = [f for m in index.modules.values() for f in m.funcs]
    for root in all_funcs:
        if not _is_root_fn(root.node):
            continue
        if root.qual in STARTUP_EXEMPT_ROOTS:
            continue
        visited: set[tuple[str, int]] = set()
        frontier: list[tuple[FuncInfo, str]] = [(root, root.qual)]
        while frontier:
            fi, root_qual = frontier.pop()
            key = (fi.module, id(fi.node))
            if key in visited:
                continue
            visited.add(key)
            for call in _iter_own_calls(fi.node):
                reason = _forbidden_reason(call.func)
                if reason is not None:
                    findings.append(Finding(
                        root=root_qual, site=fi.qual, module=fi.module,
                        lineno=getattr(call, "lineno", -1),
                        call=_call_label(call.func), reason=reason))
                callee = index.resolve(call.func, fi)
                if callee is not None:
                    frontier.append((callee, root_qual))
    return findings


def _app_sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        rel = path.relative_to(APP_DIR.parent)
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        sources[".".join(parts)] = path.read_text(encoding="utf-8")
    return sources


# ---------- 门禁本体 ----------


def test_no_forbidden_sync_calls_in_async_paths():
    findings = scan_modules(_app_sources())
    assert findings == [], "红线违禁(async/generator 可达路径内同步阻塞 I/O):\n" + "\n".join(
        f"  {f}" for f in findings)


def test_startup_exemption_is_minimal():
    """豁免名单必须一字不差:新增豁免 = 修改此测试 = 强制人审。"""
    assert STARTUP_EXEMPT_ROOTS == frozenset({"app.main.lifespan"})


# ---------- 判别力自检(seeded):该抓的必抓 ----------


def test_selfcheck_flags_direct_sleep_in_async_fn():
    findings = scan_modules({"seeded.a": "import time\nasync def boom():\n    time.sleep(0.1)\n"})
    assert [f.reason for f in findings] == ["同步睡眠"]


def test_selfcheck_flags_direct_dns_in_async_generator():
    src = "import socket\nasync def gen():\n    socket.getaddrinfo('x', 80)\n    yield 1\n"
    findings = scan_modules({"seeded.a": src})
    assert [f.reason for f in findings] == ["同步 DNS"]


def test_selfcheck_flags_blocking_sync_helper_reached_from_async():
    """F1 回归类:违禁在同步助手体内,但被 async 路径直接调用 → 必须经「可达调用」抓获。"""
    src = (
        "import time\n"
        "def helper():\n"
        "    time.sleep(1)\n"
        "async def boom():\n"
        "    helper()\n"
    )
    findings = scan_modules({"seeded.a": src})
    assert len(findings) == 1
    assert findings[0].reason == "同步睡眠"
    assert findings[0].site == "seeded.a.helper" and findings[0].root == "seeded.a.boom"


def test_selfcheck_flags_sync_generator_iterated_from_async():
    """同步生成器被 async 路径直接调用/迭代(跑在循环上)→ 必抓。"""
    src = (
        "import time\n"
        "def gen():\n"
        "    time.sleep(1)\n"
        "    yield 1\n"
        "async def boom():\n"
        "    for x in gen():\n"
        "        pass\n"
    )
    findings = scan_modules({"seeded.a": src})
    assert len(findings) == 1
    assert findings[0].reason == "同步睡眠" and findings[0].site == "seeded.a.gen"


def test_selfcheck_flags_forbidden_names_breadth():
    src = (
        "from openai import OpenAI\n"
        "import httpx, requests, sqlite3\n"
        "async def boom():\n"
        "    OpenAI()\n"
        "    httpx.post('https://x')\n"
        "    httpx.Client()\n"
        "    requests.get('https://x')\n"
        "    sqlite3.connect(':memory:')\n"
        "    open('f')\n"
        "    g.invoke({})\n"
    )
    reasons = {f.call: f.reason for f in scan_modules({"seeded.a": src})}
    assert reasons == {
        "OpenAI": "同步 OpenAI 客户端",
        "httpx.post": "同步 httpx 直发",
        "httpx.Client": "同步 httpx.Client",
        "requests.get": "同步 requests",
        "sqlite3.connect": "同步 sqlite3.connect",
        "open": "同步文件 I/O",
        "g.invoke": "graph.invoke 同步",
    }


def test_selfcheck_flags_sqlite_write_on_reached_helper():
    src = (
        "def writer(conn):\n"
        "    conn.execute('INSERT INTO t VALUES (1)')\n"
        "    conn.commit()\n"
        "async def boom():\n"
        "    writer(c)\n"
    )
    assert sorted(f.reason for f in scan_modules({"seeded.a": src})) == [
        "同步 sqlite3 写", "同步 sqlite3 写"]


# ---------- 判别力自检(seeded):不该抓的必不抓(误报防线) ----------


def test_selfcheck_allows_sync_by_design_functions_not_reached_from_async():
    """决策 CRITICAL:validate_base_url/record_usage/traffic flush 类 sync-by-design 不误报。"""
    src = (
        "import socket, threading\n"
        "def validate_base_url(url):\n"          # 同步 DNS,仅供测试/线程池路径
        "    return socket.getaddrinfo(url, 443)\n"
        "def flush(conn):\n"                      # 守护线程里写库
        "    conn.execute('INSERT INTO t VALUES (1)')\n"
        "def record_usage():\n"                   # 缓冲 + 起守护线程,自身不碰 I/O
        "    threading.Thread(target=flush, daemon=True).start()\n"
    )
    assert scan_modules({"seeded.a": src}) == []


def test_selfcheck_allows_async_dns_via_loop_and_asyncio_sleep():
    """async 正解(loop.getaddrinfo / asyncio.sleep / AsyncOpenAI / ainvoke)不误报。"""
    src = (
        "import asyncio, socket\n"
        "from openai import AsyncOpenAI\n"
        "async def boom():\n"
        "    loop = asyncio.get_running_loop()\n"
        "    await loop.getaddrinfo('x', 443)\n"
        "    await asyncio.get_running_loop().getaddrinfo('y', 443)\n"
        "    await asyncio.sleep(1)\n"
        "    socket.gethostbyname  # 引用不调用\n"
        "    AsyncOpenAI()\n"
        "    await graph.ainvoke({})\n"
    )
    assert scan_modules({"seeded.a": src}) == []


def test_selfcheck_allows_thread_offloaded_helper_reached_from_async():
    """async 调用的助手若把 I/O 交给守护线程(实参形式),不算违禁。"""
    src = (
        "import threading\n"
        "def flush(conn):\n"
        "    conn.execute('INSERT INTO t VALUES (1)')\n"
        "def record():\n"
        "    threading.Thread(target=flush, daemon=True).start()\n"
        "async def boom():\n"
        "    record()\n"
    )
    assert scan_modules({"seeded.a": src}) == []


def test_selfcheck_ignores_plain_sync_functions_as_roots():
    findings = scan_modules({"seeded.a": "import time\ndef sync_ok():\n    time.sleep(1)\n"})
    assert findings == []


def test_selfcheck_allows_framework_run_sync_generator_deps():
    """feed/deps.get_conn 形态:sync generator 依赖,线程池执行,无 async 调用方 → 不误报。"""
    src = (
        "import sqlite3\n"
        "def get_conn():\n"
        "    conn = sqlite3.connect(':memory:')\n"
        "    try:\n"
        "        yield conn\n"
        "    finally:\n"
        "        conn.close()\n"
    )
    assert scan_modules({"seeded.a": src}) == []
