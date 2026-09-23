"""登录、个人数据、互动显式 on/off。

登录仅 GitHub OAuth：觅码账号即 GitHub 账号，无独立注册。
OAuth scope 只要 read:user —— 不申请 repo（不读私有代码，见 spec 账号边界）。
"""
from __future__ import annotations

import secrets
import sqlite3
import time
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from ... import config
from .. import auth, github
from ..cards import to_card, _card_select
from ..deps import get_conn
from ..schemas import BioIn, InteractionIn, RepoCardOut, UserOut

router = APIRouter()

TOGGLEABLE = ("like", "favorite")
OAUTH_STATE_COOKIE = "oauth_state"


@router.get("/auth/github")
def oauth_entry() -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    params = urllib.parse.urlencode({
        "client_id": config.GITHUB_CLIENT_ID,
        "scope": "read:user",  # 只读身份，不要 repo 权限
        "state": state,
    })
    resp = RedirectResponse(f"https://github.com/login/oauth/authorize?{params}")
    resp.set_cookie(
        OAUTH_STATE_COOKIE, state,
        max_age=600, httponly=True, samesite="lax",
        secure=not config.GITHUB_MOCK,  # 生产(HTTPS)强制安全 cookie
    )
    return resp


@router.get("/auth/callback")
def oauth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    conn: sqlite3.Connection = Depends(get_conn),
) -> RedirectResponse:
    """用 code 换一次性 token 读身份，随即丢弃 token（不入库）。"""
    saved_state = request.cookies.get(OAUTH_STATE_COOKIE, "")
    if not state or not saved_state or not secrets.compare_digest(state, saved_state):
        raise HTTPException(status_code=400, detail="OAuth state 不匹配，请重新登录")

    try:
        token = github.exchange_oauth_code(code)
        gh_user = github.get_authenticated_user(token)
    except github.GitHubError as exc:
        raise HTTPException(status_code=502, detail=f"GitHub 登录失败：{exc}") from exc

    user_id = auth.upsert_user(conn, gh_user)
    resp = RedirectResponse(config.FRONTEND_ORIGIN)
    resp.delete_cookie(OAUTH_STATE_COOKIE)
    resp.set_cookie(
        config.SESSION_COOKIE, auth.issue_token(conn, user_id),
        max_age=config.SESSION_MAX_AGE, httponly=True, samesite="lax",
        secure=not config.GITHUB_MOCK,
    )
    return resp


@router.post("/auth/logout")
def logout(request: Request, response: Response,
           conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """退出登录 = 吊销该账号全部登录态并清 cookie。

    无服务端 token 存储,单端精确吊销做不到;安全优先,退出即全端下线。
    """
    user = auth.current_user(request, conn)
    if user is not None:
        auth.revoke_all(conn, user["id"])
    response.delete_cookie(config.SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def get_me(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> UserOut | None:
    user = auth.current_user(request, conn)
    if user is None:
        return None
    return UserOut(id=user["id"], login=user["login"],
                   avatar_url=user["avatar_url"], bio=user["bio"])


@router.put("/me/bio", response_model=UserOut)
def update_bio(
    body: BioIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> UserOut:
    user = auth.require_user(request, conn)
    conn.execute("UPDATE users SET bio = ? WHERE id = ?", (body.bio.strip(), user["id"]))
    conn.commit()
    return UserOut(id=user["id"], login=user["login"],
                   avatar_url=user["avatar_url"], bio=body.bio.strip())


def _set_interaction_row(
    conn: sqlite3.Connection, user_id: int, repo_id: int, kind: str, active: bool
) -> None:
    """显式 on/off(幂等)替代读改写 toggle:并发下无竞态、无 IntegrityError。"""
    if active:
        conn.execute(
            "INSERT INTO interactions (user_id, repo_id, kind, updated_at) VALUES (?,?,?,?)"
            " ON CONFLICT(user_id, repo_id, kind) DO UPDATE SET updated_at = excluded.updated_at",
            (user_id, repo_id, kind, int(time.time())),
        )
    else:
        conn.execute(
            "DELETE FROM interactions WHERE user_id = ? AND repo_id = ? AND kind = ?",
            (user_id, repo_id, kind),
        )


@router.post("/interactions")
def set_interaction(
    body: InteractionIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    """点赞/收藏显式切换(前端传目标状态)。visit 不走这里 —— 它由详情接口写入。"""
    user = auth.require_user(request, conn)
    if body.kind not in TOGGLEABLE:
        raise HTTPException(status_code=422, detail="kind 只能是 like 或 favorite")
    exists = conn.execute(
        "SELECT id FROM repos WHERE id = ? AND status != 'delisted'", (body.repo_id,)
    ).fetchone()
    if exists is None:
        raise HTTPException(status_code=404, detail="仓库不存在或已下架")
    _set_interaction_row(conn, user["id"], body.repo_id, body.kind, body.active)
    conn.commit()
    return {"active": body.active}


@router.get("/me/interaction-ids", response_model=list[int])
def interaction_ids(
    request: Request,
    kind: str = Query(...),
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[int]:
    """前端拉点赞/收藏 id 列表用于心形/星标回显。"""
    user = auth.require_user(request, conn)
    if kind not in ("like", "favorite", "visit"):
        raise HTTPException(status_code=422, detail="kind 只能是 like/favorite/visit")
    rows = conn.execute(
        "SELECT repo_id FROM interactions WHERE user_id = ? AND kind = ?", (user["id"], kind)
    ).fetchall()
    return [r["repo_id"] for r in rows]


@router.get("/me/repos", response_model=list[RepoCardOut])
def my_repos(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> list[RepoCardOut]:
    """我的仓库：只展示当前可见/可管理的仓库，已下架的不再出现在个人主页。"""
    user = auth.require_user(request, conn)
    rows = conn.execute(
        _card_select(
            "FROM repos r WHERE (r.owner_login = ? OR r.claimed_by = ?)"
            " AND r.status != 'delisted' ORDER BY r.published_at DESC"
        ),
        (user["login"], user["id"]),
    ).fetchall()
    return [to_card(r) for r in rows]


def _by_kind(conn: sqlite3.Connection, user_id: int, kind: str) -> list[RepoCardOut]:
    """it.id DESC 是必要的兜底：同一秒内的多次访问 updated_at 相同，
    只按 updated_at 排序结果不确定，浏览历史顺序会飘。
    外层别名用 it：_card_select 的 like_count 子查询里已有 i，避免遮蔽混淆。"""
    rows = conn.execute(
        _card_select(
            "FROM interactions it JOIN repos r ON r.id = it.repo_id"
            " WHERE it.user_id = ? AND it.kind = ? AND r.status != 'delisted'"
            " ORDER BY it.updated_at DESC, it.id DESC"
        ),
        (user_id, kind),
    ).fetchall()
    return [to_card(r) for r in rows]


@router.get("/me/favorites", response_model=list[RepoCardOut])
def my_favorites(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> list[RepoCardOut]:
    user = auth.require_user(request, conn)
    return _by_kind(conn, user["id"], "favorite")


@router.get("/me/history", response_model=list[RepoCardOut])
def my_history(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> list[RepoCardOut]:
    user = auth.require_user(request, conn)
    return _by_kind(conn, user["id"], "visit")
