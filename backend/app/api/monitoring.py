from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()

SECTIONS = [
    {"id": "overview", "name": "竞品监控总览"},
    {"id": "shops", "name": "竞品店铺库"},
    {"id": "products", "name": "竞品商品追踪"},
    {"id": "pricing", "name": "价格与活动追踪"},
    {"id": "radar", "name": "竞品动作雷达"},
    {"id": "reports", "name": "竞品分析报告"},
]


@router.get("")
def monitoring_overview() -> dict:
    return {
        "name": "竞品监控",
        "message": "竞品监控框架已就绪",
        "sections": SECTIONS,
    }


@router.get("/{section_id}")
def monitoring_section(section_id: str) -> dict:
    section = next((item for item in SECTIONS if item["id"] == section_id), None)
    if section is None:
        raise HTTPException(status_code=404, detail="竞品监控页面不存在")
    return {"workspace": "竞品监控", "section": section, "status": "scaffolded"}
