"""系统状态：后台循环运行情况查询。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.auth import get_current_user
from backend.app.core import loops

router = APIRouter()


@router.get("/loops")
def loops_status(user: dict = Depends(get_current_user)) -> dict:
    """返回全部后台循环的运行状态（最后运行/成功时间、失败次数、错误信息）。"""
    return {"items": loops.get_all_status()}
