"""LLM base_url SSRF 校验：非 http(s)、内网/环回/链路本地一律拒绝。"""
from __future__ import annotations

import socket

import pytest

from app import urlguard


def _fake_getaddrinfo(ips: list[str]):
    def _gai(host, port, *a, **k):
        out = []
        for ip in ips:
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            out.append((family, socket.SOCK_STREAM, 6, "", (ip, port or 0)))
        return out
    return _gai


def test_rejects_non_http_schemes():
    for url in ("file:///etc/passwd", "gopher://x", "ftp://x", "data:text/html,x"):
        with pytest.raises(ValueError):
            urlguard.validate_base_url(url)


def test_rejects_ip_literals_in_private_ranges():
    for url in (
        "http://127.0.0.1:11434/v1",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/v1",
        "http://100.64.0.1/v1",
        "http://192.168.1.1/v1",
        "http://172.16.0.1/v1",
        "http://[::1]/v1",
        "http://[::]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:169.254.169.254]/",
        "http://[::127.0.0.1]/",
    ):
        with pytest.raises(ValueError):
            urlguard.validate_base_url(url)


def test_rejects_hostname_resolving_to_private(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(["127.0.0.1"]))
    with pytest.raises(ValueError):
        urlguard.validate_base_url("http://localhost:11434/v1")


def test_rejects_unresolvable_host(monkeypatch):
    def _boom(host, port, *a, **k):
        raise socket.gaierror("no such host")
    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    with pytest.raises(ValueError):
        urlguard.validate_base_url("http://nope.invalid/v1")


def test_rejects_userinfo_in_url():
    with pytest.raises(ValueError):
        urlguard.validate_base_url("http://user:pass@example.com/v1")


def test_rejects_missing_host():
    with pytest.raises(ValueError):
        urlguard.validate_base_url("http:///v1")


def test_rejects_unclosed_ipv6_bracket_with_chinese_message():
    # urlparse 抛英文 stdlib ValueError("Invalid IPv6 URL")，须包成中文
    with pytest.raises(ValueError, match="模型接口地址格式非法"):
        urlguard.validate_base_url("http://[::1")


def test_rejects_invalid_port_with_chinese_message():
    # parsed.port 抛英文 stdlib ValueError，须包成中文（非法端口/超范围）
    for url in ("http://example.com:abc", "http://example.com:65536"):
        with pytest.raises(ValueError, match="模型接口地址端口非法"):
            urlguard.validate_base_url(url)


def test_allows_public_https(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(["203.0.113.10"]))
    assert urlguard.validate_base_url("https://api.deepseek.com") == "https://api.deepseek.com"


def test_strips_whitespace(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(["203.0.113.10"]))
    assert urlguard.validate_base_url("  https://api.deepseek.com  ") == "https://api.deepseek.com"


def test_llm_override_rejects_private_base_url(monkeypatch):
    from app.schemas import LLMOverride

    with pytest.raises(ValueError):
        LLMOverride(base_url="http://169.254.169.254/")
