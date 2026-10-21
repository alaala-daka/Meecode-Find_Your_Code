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

名字解析(scope-aware,round 2 修订):
- import 别名(`import socket as s`、`from time import sleep as sl`)与简单赋值别名
  (`f = socket.getaddrinfo`)归一到真实符号再判违禁,封住换名逃逸
  (test_selfcheck_alias_evasion_*)。
- 归一**只认词法作用域内可见的绑定**:只沿「调用点所在函数 → 外层嵌套函数 → 模块」
  查;别的函数里的绑定不得漏进来(test_selfcheck_allows_scoped_alias_*)。
  同名局部绑定**遮蔽**外层 import/别名(`client = make_test_client()` 盖掉
  `import httpx as client` → 不误报 httpx.post)。
- 局部同名多次绑定(值不同)= 歧义,保守按局部变量处理(不误报方向)。
- 已知残留盲区(刻意保守):`global` 语句跨函数回填的绑定不追踪;接收者类型不可
  判的属性调用仍按属性名兜底(execute/commit/read/write/invoke)。

误报防线(决策 CRITICAL):
- 匹配限定根名:`socket.getaddrinfo` 只认 `socket.` 前缀或裸名,`loop.getaddrinfo`
  (async 正解)不误报;`time.sleep` 不误报 `asyncio.sleep`;`OpenAI` 不误报
  `AsyncOpenAI`;`httpx.Client` 不误报 `AsyncClient`;`invoke` 不误报 `ainvoke`。
- 用户定义同名符号(def/class 同名 sleep/open/connect...)不算违禁内置。
- 每条规则都有下方 seeded 自检(判别力自证):该抓的必抓、不该抓的必不抓。
"""
from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass, field

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"

# 启动期豁免(唯一一处,test_startup_exemption_is_minimal 钉死,防豁免名单悄悄长大):
# app.main.lifespan 在 uvicorn 开始接受请求**之前**执行,阻塞只发生在启动瞬间,
# 红线危害模型(「单请求冻结全站」)不成立;但其可达路径确含 db.connect/db.init_db/
# PolicyCache.maybe_refresh 的同步 sqlite I/O,按启动期语义豁免而非按代码语义放行。
# 根治建议(见任务报告):启动段挪入 asyncio.to_thread。
STARTUP_EXEMPT_ROOTS = frozenset({"app.main.lifespan"})


# ---------- 违禁匹配(纯拼写规则,输入为归一后的名字) ----------

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


def _match_forbidden(canonical: str | None, attr: str | None) -> str | None:
    """纯拼写规则:输入为**归一后**的点分名(canonical),或非命名链的属性名兜底。

    归一由 _Index._canonical 负责(scope-aware,见模块 docstring);不做归一的裸拼写
    可被换名逃逸(见 test_selfcheck_alias_evasion_* 中「拼写规则单独不抓」断言)。
    """
    if canonical is not None:
        segs = canonical.split(".")
        if len(segs) == 1:
            return _BARE.get(segs[0])
        root, last = segs[0], segs[-1]
        if canonical in ("socket.getaddrinfo", "socket.gethostbyname"):
            return "同步 DNS"
        if canonical == "time.sleep":
            return "同步睡眠"
        if canonical == "sqlite3.connect":
            return "同步 sqlite3.connect"
        if root == "httpx" and last in ("post", "get", "request"):
            return "同步 httpx 直发"
        if root == "httpx" and last == "Client":
            return "同步 httpx.Client"
        if root == "requests":
            return "同步 requests"
        return _ATTR_ONLY.get(last)
    return _ATTR_ONLY.get(attr or "")


# ---------- 索引与名字/调用解析 ----------

# 作用域绑定值形状(元组首元=种类):
#   ("def", FuncInfo) | ("class", 类名) | ("module", 模块名) | ("func", 模块, 名)
#   | ("alias", 目标点分名) | ("instance", 类名) | ("var", None)  ← 普通局部绑定/歧义


@dataclass
class FuncInfo:
    module: str
    name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    cls: str | None          # 所属类(方法)
    parent: "FuncInfo | None"  # 所在外层函数(嵌套 def)
    qual: str
    bindings: dict[str, tuple] = field(default_factory=dict)   # 本函数作用域内绑定


class _Module:
    def __init__(self, name: str, tree: ast.Module):
        self.name = name
        self.tree = tree
        self.funcs: list[FuncInfo] = []
        self.methods: dict[str, dict[str, FuncInfo]] = {}   # 类名 -> 方法名 -> fn
        self.bindings: dict[str, tuple] = {}                 # 模块作用域内绑定
        self.instances: dict[str, str] = {}                  # 模块级 x = f(...) -> 被调名(walk_attr 兜底)
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
        def bind(scope, name: str, value: tuple) -> None:
            prev = scope.bindings.get(name)
            # 同一作用域内同名多次绑定且值不同 = 歧义(动态谁赢不可知),保守当普通局部绑定
            scope.bindings[name] = value if prev is None or prev == value else ("var", None)

        def target_names(node) -> list[str]:
            if isinstance(node, ast.Name):
                return [node.id]
            if isinstance(node, (ast.Tuple, ast.List)):
                return [n for e in node.elts for n in target_names(e)]
            if isinstance(node, ast.Starred):
                return target_names(node.value)
            return []

        def visit(node, cls: str | None, parent: FuncInfo | None) -> None:
            scope = parent if parent is not None else module
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        if alias.asname:   # import socket as s → s 归一到 socket
                            bind(scope, alias.asname, ("module", alias.name))
                        else:
                            root = alias.name.split(".")[0]
                            bind(scope, root, ("module", root))
                elif isinstance(child, ast.ImportFrom):
                    base = self._from_target(module.name, child)
                    for alias in child.names:
                        full = f"{base}.{alias.name}" if base else alias.name
                        key = alias.asname or alias.name
                        if full in self.modules:   # 导入的其实是子模块(from .feed import db)
                            bind(scope, key, ("module", full))
                        else:
                            bind(scope, key, ("func", base, alias.name))
                elif isinstance(child, ast.ClassDef):
                    module.classes.add(child.name) if scope is module else None
                    bind(scope, child.name, ("class", child.name))
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
                    bind(scope, child.name, ("def", info))
                    args = child.args
                    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs,
                                *[a for a in (args.vararg, args.kwarg) if a is not None]]:
                        bind(info, arg.arg, ("var", None))
                    visit(child, cls, info)
                elif isinstance(child, (ast.Assign, ast.AnnAssign)):
                    value = child.value
                    targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                    for t in targets:
                        for nm in target_names(t):
                            if (isinstance(t, ast.Name) and isinstance(value, (ast.Name, ast.Attribute))
                                    and _dotted(value) is not None):
                                bind(scope, nm, ("alias", _dotted(value)))   # f = socket.getaddrinfo
                            elif (isinstance(child, ast.Assign) and scope is module
                                  and isinstance(value, ast.Call)):
                                fn = value.func
                                cls_name = (fn.id if isinstance(fn, ast.Name)
                                            else fn.attr if isinstance(fn, ast.Attribute) else None)
                                if cls_name is not None:
                                    module.instances[nm] = cls_name
                                    bind(scope, nm, ("instance", cls_name))
                                else:
                                    bind(scope, nm, ("var", None))
                            else:
                                bind(scope, nm, ("var", None))
                    visit(child, cls, parent)
                elif isinstance(child, ast.AugAssign):
                    for nm in target_names(child.target):
                        bind(scope, nm, ("var", None))
                    visit(child, cls, parent)
                elif isinstance(child, (ast.For, ast.AsyncFor)):
                    for nm in target_names(child.target):
                        bind(scope, nm, ("var", None))
                    visit(child, cls, parent)
                elif isinstance(child, (ast.With, ast.AsyncWith)):
                    for item in child.items:
                        if item.optional_vars is not None:
                            for nm in target_names(item.optional_vars):
                                bind(scope, nm, ("var", None))
                    visit(child, cls, parent)
                elif isinstance(child, ast.ExceptHandler):
                    if child.name:
                        bind(scope, child.name, ("var", None))
                    visit(child, cls, parent)
                elif isinstance(child, ast.comprehension):
                    for nm in target_names(child.target):
                        bind(scope, nm, ("var", None))
                    visit(child, cls, parent)
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

    # ---- 词法作用域内名字解析(round 2:别的函数的绑定不得漏进来;局部遮蔽外层) ----

    def _resolve_binding(self, name: str, fi: FuncInfo) -> tuple | None:
        """沿词法链(本函数 → 外层嵌套函数 → 模块)找绑定;查不到 None(= 未绑定自由名)。"""
        scope: FuncInfo | None = fi
        while scope is not None:
            b = scope.bindings.get(name)
            if b is not None:
                return b
            scope = scope.parent
        return self.modules[fi.module].bindings.get(name)

    def _canonical(self, dotted: str, fi: FuncInfo, depth: int = 0) -> str | None:
        """点分名归一到真实符号;None = 明确不是违禁符号(用户 def/class 或被遮蔽的裸名)。"""
        if depth > 8:
            return dotted
        segs = dotted.split(".")
        head, tail = segs[0], segs[1:]
        b = self._resolve_binding(head, fi)
        if b is None:                       # 未绑定自由名:保留原拼写(属性名兜底照旧)
            return dotted
        kind = b[0]
        if kind in ("def", "class"):        # 用户定义同名符号:不是违禁内置
            return None
        if kind == "var":                   # 局部绑定遮蔽:裸调用不是内置;属性走原拼写
            return None if not tail else dotted
        if kind == "instance":              # 实例方法接收者类型不可判:按属性名兜底(同旧行为)
            return dotted
        if kind == "module":
            return ".".join([b[1]] + tail)
        if kind == "func":
            base = f"{b[1]}.{b[2]}" if b[1] else b[2]
            return ".".join([base] + tail)
        target = self._canonical(b[1], fi, depth + 1)   # ("alias", 目标点分名)
        return None if target is None else ".".join([target] + tail)

    def forbidden_reason(self, func: ast.expr, fi: FuncInfo) -> str | None:
        """违禁判定:名字先 scope-aware 归一到真实符号,再套拼写规则。"""
        dotted = _dotted(func)
        if dotted is None:
            attr = func.attr if isinstance(func, ast.Attribute) else None
            return _match_forbidden(None, attr)
        canonical = self._canonical(dotted, fi)
        if canonical is None:
            return None
        return _match_forbidden(canonical, None)

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
        """模块命名空间逐段走:子模块 → 模块作用域绑定(import/def/类/实例) → 兜底。"""
        m = self.modules.get(module)
        if m is None or not segs:
            return None
        head, *tail = segs
        sub = f"{module}.{head}"
        if sub in self.modules:
            return self.walk_attr(sub, tail)
        b = m.bindings.get(head)
        if b is not None:
            kind = b[0]
            if kind == "module":
                return self.walk_attr(b[1], tail)
            if kind == "func":
                return self.unique_func(b[1], b[2]) if not tail else None
            if kind == "def":
                return b[1] if not tail else None
            if kind == "instance":
                return self.unique_method(module, b[1], tail[0]) if len(tail) == 1 else None
            if kind == "class":
                return self.unique_method(module, b[1], tail[0]) if len(tail) == 1 else None
            return None
        if not tail:
            return self.unique_func(module, head)
        if head in m.classes:
            return self.unique_method(module, head, tail[0]) if len(tail) == 1 else None
        if head in m.instances:
            return self.unique_method(module, m.instances[head], tail[0]) if len(tail) == 1 else None
        return None

    def resolve(self, func: ast.expr, fi: FuncInfo) -> FuncInfo | None:
        if isinstance(func, ast.Name):
            b = self._resolve_binding(func.id, fi)
            if b is None:
                return None
            if b[0] == "def":
                return b[1]
            if b[0] == "func":
                return self.unique_func(b[1], b[2])
            return None   # var/alias/instance/class/module:不跟进(alias 保守不展开)
        if isinstance(func, ast.Attribute):
            recv = func.value
            if isinstance(recv, ast.Name) and recv.id in ("self", "cls") and fi.cls:
                return self.unique_method(fi.module, fi.cls, func.attr)
            recv_dotted = _dotted(recv)
            if recv_dotted is None:
                return None
            segs = recv_dotted.split(".") + [func.attr]
            b = self._resolve_binding(segs[0], fi)
            if b is None:
                return self.walk_attr(fi.module, segs)   # 未绑定自由名:模块命名空间兜底(旧行为)
            kind = b[0]
            if kind == "module":
                return self.walk_attr(b[1], segs[1:])
            if kind == "instance":
                return self.unique_method(fi.module, b[1], segs[1]) if len(segs) == 2 else None
            if kind == "class":
                return self.unique_method(fi.module, b[1], segs[1]) if len(segs) == 2 else None
            return None   # def/func/alias/var:局部遮蔽或不可解析,不跟进(round 2 修误报)
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
                reason = index.forbidden_reason(call.func, fi)
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


# ---------- 判别力自检(seeded):import/赋值别名换名逃逸必须被抓获(round 1) ----------


def test_selfcheck_alias_evasion_import_socket_as():
    """`import socket as s` + s.getaddrinfo:归一到 socket.getaddrinfo 后判违禁。"""
    src = (
        "import socket as s\n"
        "async def boom():\n"
        "    s.getaddrinfo('x', 80)\n"
    )
    assert _match_forbidden("s.getaddrinfo", None) is None   # 判别力:裸拼写规则单独不抓(修复前的逃逸)
    findings = scan_modules({"seeded.a": src})
    assert len(findings) == 1
    f = findings[0]
    assert (f.reason, f.site, f.root) == ("同步 DNS", "seeded.a.boom", "seeded.a.boom")


def test_selfcheck_alias_evasion_from_time_import_sleep_as():
    """`from time import sleep as sl` + sl(1):归一到 time.sleep 后判违禁。"""
    src = (
        "from time import sleep as sl\n"
        "async def boom():\n"
        "    sl(1)\n"
    )
    assert _match_forbidden("sl", None) is None   # 判别力:裸拼写规则单独不抓
    findings = scan_modules({"seeded.a": src})
    assert len(findings) == 1
    f = findings[0]
    assert (f.reason, f.site, f.root) == ("同步睡眠", "seeded.a.boom", "seeded.a.boom")


def test_selfcheck_alias_evasion_assignment_alias():
    """`f = socket.getaddrinfo` + f(...):赋值别名归一到 socket.getaddrinfo 后判违禁。"""
    src = (
        "import socket\n"
        "async def boom():\n"
        "    f = socket.getaddrinfo\n"
        "    f('x', 80)\n"
    )
    assert _match_forbidden("f", None) is None   # 判别力:裸拼写规则单独不抓
    findings = scan_modules({"seeded.a": src})
    assert len(findings) == 1
    fn = findings[0]
    assert (fn.reason, fn.site, fn.root) == ("同步 DNS", "seeded.a.boom", "seeded.a.boom")


def test_selfcheck_alias_evasion_through_reached_helper():
    """别名逃逸在「可达调用」链上同样抓得到:助手体内 sl(1) 归一判违禁,根在 async。"""
    src = (
        "from time import sleep as sl\n"
        "def helper():\n"
        "    sl(1)\n"
        "async def boom():\n"
        "    helper()\n"
    )
    findings = scan_modules({"seeded.a": src})
    assert len(findings) == 1
    f = findings[0]
    assert (f.reason, f.site, f.root) == ("同步睡眠", "seeded.a.helper", "seeded.a.boom")


# ---------- 判别力自检(seeded):不该抓的必不抓(误报防线,round 2:作用域) ----------


def test_selfcheck_allows_scoped_alias_poisoning_sync_fn():
    """round 2 误报复现形态①:别的(同步)函数里的 f = socket.getaddrinfo 不得漏进
    无关 async 函数的 f(1)(该 f 是局部 get_handler() 结果)。"""
    src = (
        "import socket\n"
        "def sync_setup():\n"
        "    f = socket.getaddrinfo\n"
        "async def boom():\n"
        "    f = get_handler()\n"
        "    f(1)\n"
    )
    assert scan_modules({"seeded.a": src}) == []


def test_selfcheck_allows_scoped_alias_poisoning_across_async_fns():
    """round 2 误报复现形态②:另一 async 函数里的别名绑定同样不得跨函数漏入。"""
    src = (
        "import socket\n"
        "async def other():\n"
        "    f = socket.getaddrinfo\n"
        "async def boom():\n"
        "    f = make_thing()\n"
        "    f(1)\n"
    )
    assert scan_modules({"seeded.a": src}) == []


def test_selfcheck_allows_local_shadow_of_module_import():
    """round 2 误报复现形态③:函数局部 client = make_test_client() 遮蔽
    模块级 import httpx as client → client.post 不得归一成 httpx.post。"""
    src = (
        "import httpx as client\n"
        "async def boom():\n"
        "    client = make_test_client()\n"
        "    client.post('https://x')\n"
    )
    assert scan_modules({"seeded.a": src}) == []


def test_selfcheck_allows_local_param_shadowing_builtin_name():
    """参数同名遮蔽:参数 open 不是内置 open,open(...) 不判同步文件 I/O。"""
    src = (
        "async def boom(open):\n"
        "    open('f')\n"
    )
    assert scan_modules({"seeded.a": src}) == []


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
