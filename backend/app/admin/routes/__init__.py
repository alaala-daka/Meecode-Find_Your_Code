"""管理台路由聚合：全部前置 require_admin（spec §4）。"""
from fastapi import APIRouter, Depends

from ..deps import require_admin
from . import users

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


@router.get("/me")
def me(admin=Depends(require_admin)) -> dict:
    return {"login": admin["login"], "avatar_url": admin["avatar_url"], "is_admin": True}


router.include_router(users.router)
