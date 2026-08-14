from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("")
def content_overview() -> dict:
    return {"items": [], "message": "内容运营 · 待开发"}
