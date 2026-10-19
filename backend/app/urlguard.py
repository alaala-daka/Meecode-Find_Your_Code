"""LLM base_url SSRF 防护：仅放行解析到公网地址的 http(s) 端点。

设置区自定义模型是产品功能（BYOK），不能一刀切白名单主机名；改为协议限制 +
解析后 IP 落点校验。已知残余风险：DNS rebinding（校验与实际请求之间二次解析），
彻底解需在连接时钉住 IP，超出本批范围。

校验分两层：
- 语法层（_parse_and_check_syntax）：scheme/凭据/主机名/端口，纯解析不碰 DNS，
  供 schemas 请求体校验在 parse 期快速拒绝；
- 解析层（validate_base_url 同步 / validate_base_url_async 异步）：DNS 解析后
  每个 IP 必须公网。异步版用 loop.getaddrinfo + 独立信号量 + 超时，不阻塞事件循环。
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

# 拒绝环回/内网/链路本地/组播/保留段/CGNAT（含 IPv6 对应段）
_PRIVATE_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
        "172.16.0.0/12", "192.168.0.0/16", "224.0.0.0/4", "240.0.0.0/4",
        "::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8",
    )
]


def _is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if ip.is_unspecified:
        return False
    # IPv4-mapped(::ffff:x.x.x.x)/6to4(2002::)/IPv4-compatible(::x.x.x.x) 壳地址先拆出内嵌 IPv4 再判段
    mapped = getattr(ip, "ipv4_mapped", None) or getattr(ip, "sixtofour", None)
    if mapped is not None:
        ip = mapped
    elif ip.version == 6 and int(ip) < 2**32:
        ip = ipaddress.IPv4Address(int(ip))
    return not any(ip in net for net in _PRIVATE_NETWORKS)


def _parse_and_check_syntax(url: str) -> tuple[str, int | None]:
    """纯语法校验：scheme/凭据/主机名/端口；不触碰 DNS。返回 (host, port)。"""
    cleaned = (url or "").strip()
    try:
        parsed = urlparse(cleaned)
    except ValueError as exc:      # 如未闭合 '['：stdlib 抛英文 "Invalid IPv6 URL"
        raise ValueError("模型接口地址格式非法") from exc
    if parsed.scheme not in ("http", "https"):
        raise ValueError("模型接口地址仅支持 http/https")
    if parsed.username or parsed.password:
        raise ValueError("模型接口地址不允许携带账号信息")
    host = parsed.hostname
    if not host:
        raise ValueError("模型接口地址缺少主机名")
    try:
        port = parsed.port         # 非法/超范围端口：stdlib 抛英文 ValueError
    except ValueError as exc:
        raise ValueError("模型接口地址端口非法") from exc
    return host, port


def _check_resolved_ips(infos, host: str) -> None:
    """解析结果落点校验：任一 IP 非公网即拒绝（SSRF）。"""
    if not infos:
        raise ValueError(f"模型接口地址无法解析：{host}")
    for info in infos:
        addr = (info[4] or [""])[0]
        if not _is_public_ip(addr):
            raise ValueError("模型接口地址不允许指向内网或本机，请填写公网 API 地址")


def validate_base_url(url: str) -> str:
    """校验请求级 LLM base_url；通过返回 strip 后的 url，否则 raise ValueError。"""
    cleaned = (url or "").strip()
    host, port = _parse_and_check_syntax(cleaned)
    try:
        infos = socket.getaddrinfo(host, port)
    except socket.gaierror as exc:
        raise ValueError(f"模型接口地址无法解析：{host}") from exc
    _check_resolved_ips(infos, host)
    return cleaned


# ---------- 异步非阻塞版 ----------

_resolve_sem: asyncio.Semaphore | None = None


def _get_resolve_sem() -> asyncio.Semaphore:
    """惰性创建独立信号量（限 DNS 校验并发；import 时无运行中事件循环，不能提前建）。"""
    global _resolve_sem
    if _resolve_sem is None:
        from . import config
        _resolve_sem = asyncio.Semaphore(config.URL_RESOLVE_MAX_CONCURRENCY)
    return _resolve_sem


async def validate_base_url_async(url: str) -> str:
    """异步非阻塞校验：语法 + 解析后 IP 必须公网；DNS 走 loop.getaddrinfo +
    独立信号量限并发 + 超时保护。失败 raise ValueError，通过返回 url。"""
    from . import config
    host, port = _parse_and_check_syntax(url)
    try:
        async with _get_resolve_sem():
            infos = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(host, port),
                timeout=config.URL_RESOLVE_TIMEOUT,
            )
    except asyncio.TimeoutError as exc:
        raise ValueError("模型接口地址解析超时") from exc
    except socket.gaierror as exc:
        raise ValueError(f"模型接口地址无法解析：{host}") from exc
    _check_resolved_ips(infos, host)
    return (url or "").strip()
