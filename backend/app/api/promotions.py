from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("")
def list_promotions() -> dict:
    return {"items": [], "message": "推广管理 · 待开发"}
