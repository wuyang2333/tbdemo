from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("")
def list_customers() -> dict:
    return {"items": [], "message": "客户管理 · 待开发"}
