from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("")
def list_settings() -> dict:
    return {"items": [], "message": "设置 · 待开发"}
