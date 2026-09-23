"""LLM base_url SSRF 防护：仅放行解析到公网地址的 http(s) 端点。

设置区自定义模型是产品功能（BYOK），不能一刀切白名单主机名；改为协议限制 +
解析后 IP 落点校验。已知残余风险：DNS rebinding（校验与实际请求之间二次解析），
彻底解需在连接时钉住 IP，超出本批范围。
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# 拒绝环回/内网/链路本地/组播/保留段（含 IPv6 对应段）
_PRIVATE_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8", "10.0.0.0/8", "127.0.0.0/8", "169.254.0.0/16",
        "172.16.0.0/12", "192.168.0.0/16", "224.0.0.0/4", "240.0.0.0/4",
        "::1/128", "fc00::/7", "fe80::/10", "ff00::/8",
    )
]


def _ip_is_public(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not any(ip in net for net in _PRIVATE_NETWORKS)


def validate_base_url(url: str) -> str:
    """校验请求级 LLM base_url；通过返回 strip 后的 url，否则 raise ValueError。"""
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("模型接口地址仅支持 http/https")
    if parsed.username or parsed.password:
        raise ValueError("模型接口地址不允许携带账号信息")
    host = parsed.hostname
    if not host:
        raise ValueError("模型接口地址缺少主机名")
    try:
        infos = socket.getaddrinfo(host, parsed.port)
    except socket.gaierror as exc:
        raise ValueError(f"模型接口地址无法解析：{host}") from exc
    if not infos:
        raise ValueError(f"模型接口地址无法解析：{host}")
    for info in infos:
        addr = (info[4] or [""])[0]
        if not _ip_is_public(addr):
            raise ValueError("模型接口地址不允许指向内网或本机，请填写公网 API 地址")
    return cleaned
