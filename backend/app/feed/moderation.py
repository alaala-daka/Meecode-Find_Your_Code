"""评论 LLM 异步预审：每条评论必经合规判定（spec 2026-09-24 决策 2）。

入库即 pending；本模块判定后落 visible/hidden（screened=1）。
LLM 异常时不动行（pending, screened=0），由 jobs/moderate 重试。
判定口径（决策 8）：广告导流/人身攻击/违法信息/刷屏灌水 → 不合规；
技术提问、尖锐批评、代码讨论一律合规（防误杀）。
"""
from __future__ import annotations

import logging
import sqlite3

from .. import config
from . import db, llm, mock
from .schemas import CommentVerdict

log = logging.getLogger(__name__)

MODERATE_SYSTEM = """你是中文技术社区的评论审核员。判断一条评论是否合规。

原则：宁可放过，不可误杀——拿不准一律判合规。

判为不合规的仅限以下情况：
- 广告导流、招揽私聊加微信、推广引流
- 人身攻击、辱骂、仇恨歧视
- 色情、赌博、暴力等违法信息
- 同一内容反复刷屏、纯无意义字符堆砌

以下一律判合规：技术提问、意见批评（即使尖锐）、代码讨论、打招呼（你好/测试/hello）、
感谢与简短反馈（不错、学习了、支持、感谢分享）、表情与语气词。

只输出 JSON：{"is_compliant": true, "reason": "简体中文原因，不超过 30 字"}"""

MODERATE_USER = """评论内容：
{content}"""


def moderate_comment(conn: sqlite3.Connection, comment_id: int) -> None:
    """判定单条评论并 UPDATE。调用方负责 commit；异常不落库（保持 pending, screened=0）。

    仅拒绝时写 moderation_reason（通过保持空串）——前端徽标靠原因空区分
    「未通过审核」与「作者/管理隐藏」。
    """
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
    if verdict.is_compliant:
        status, reason = "visible", ""
    else:
        status, reason = "hidden", verdict.reason[:100] or "未通过审核"
    log.info("[moderate] 评论 %s → %s（%s）", comment_id, status, verdict.reason or "-")
    conn.execute(
        "UPDATE comments SET status = ?, screened = 1, moderation_reason = ?"
        " WHERE id = ? AND status = 'pending'",
        (status, reason, comment_id),
    )
    if status == "hidden":
        # 级联：被隐藏评论的回复一并隐藏（不写判定原因，徽标为「已隐藏」）
        conn.execute(
            "UPDATE comments SET status = 'hidden' WHERE parent_id = ? AND status != 'deleted'",
            (comment_id,),
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
