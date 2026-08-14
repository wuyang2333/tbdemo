from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("")
def list_products() -> dict:
    return {"items": [], "message": "商品管理 · 待开发"}
