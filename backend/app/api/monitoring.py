from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("")
def monitoring_overview() -> dict:
    return {"items": [], "message": "竞品监控 · 待开发"}
