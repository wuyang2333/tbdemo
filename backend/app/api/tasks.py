from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("")
def list_tasks() -> dict:
    return {"items": [], "message": "任务中心 · 待开发"}
