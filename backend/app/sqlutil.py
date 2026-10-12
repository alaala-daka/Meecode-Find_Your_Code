"""SQLite 查询文本工具：LIKE 模式包形（含通配符转义）与 FTS5 字面量转义；admin/feed 共用。"""
from __future__ import annotations

import re


def fts_escape(q: str) -> str:
    """FTS5 有自己的查询语法:AND/OR/NEAR/引号/星号都会被解析。
    这里只做字面量匹配,故整串加引号并转义内部引号。"""
    cleaned = re.sub(r'["]', '""', q.strip())
    return f'"{cleaned}"' if cleaned else ""


def like_pattern(q: str) -> str:
    return "%" + _escape_like(q) + "%"


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
