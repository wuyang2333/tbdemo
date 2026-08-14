from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("")
def analytics() -> dict:
    return {"items": [], "message": "数据洞察 · 待开发"}
