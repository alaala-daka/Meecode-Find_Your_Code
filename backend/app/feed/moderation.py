"""评论 LLM 异步预审：每条评论必经合规判定（spec 2026-09-24 决策 2）。

入库即 pending；本模块判定后落 visible/hidden（screened=1）。
LLM 异常时不动行（pending, screened=0），由 jobs/moderate 重试。
判定口径（决策 8）：广告导流/人身攻击/违法信息/刷屏灌水 → 不合规；
技术提问、尖锐批评、代码讨论一律合规（防误杀）。
"""
from __future__ import annotations

import sqlite3

from .. import config
from . import db, llm, mock
from .schemas import CommentVerdict

MODERATE_SYSTEM = """你是中文技术社区的评论审核员。判断一条评论是否合规。

判为不合规的典型情况：广告导流、人身攻击、辱骂仇恨、色情赌博等违法信息、
无意义刷屏灌水、与技术讨论完全无关的内容。

技术提问、意见批评、代码相关讨论（即使尖锐）一律判合规。

只输出 JSON：{"is_compliant": 布尔, "reason": "简体中文原因，不超过 30 字"}"""

MODERATE_USER = """评论内容：
{content}"""


def moderate_comment(conn: sqlite3.Connection, comment_id: int) -> None:
    """判定单条评论并 UPDATE。调用方负责 commit；异常不落库（保持 pending, screened=0）。"""
    row = conn.execute(
        "SELECT id, content, status FROM comments WHERE id = ?", (comment_id,)
    ).fetchone()
    if row is None or row["status"] == "deleted":
        return
    if config.LLM_MOCK:
        verdict = CommentVerdict.model_validate(mock.mock_comment_verdict(row["content"]))
    else:
        verdict = llm.chat_json(
            system=MODERATE_SYSTEM,
            user=MODERATE_USER.format(content=row["content"][:2000]),
            model=CommentVerdict,
        )
    status = "visible" if verdict.is_compliant else "hidden"
    conn.execute(
        "UPDATE comments SET status = ?, screened = 1 WHERE id = ? AND status = 'pending'",
        (status, comment_id),
    )


def moderate_comment_bg(comment_id: int) -> None:
    """BackgroundTasks 入口：自开连接（请求级 conn 已随响应关闭）。异常上抛，
    行保持 pending 待 jobs/moderate 重试。"""
    conn = db.connect()
    try:
        moderate_comment(conn, comment_id)
        conn.commit()
    finally:
        conn.close()
