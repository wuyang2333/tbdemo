from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()

SECTIONS = [
    {"id": "overview", "name": "内容运营总览"},
    {"id": "topics", "name": "选题策划中心"},
    {"id": "calendar", "name": "内容日历"},
    {"id": "assets", "name": "内容素材库"},
    {"id": "studio", "name": "内容创作工作台"},
    {"id": "performance", "name": "发布与效果复盘"},
]


@router.get("")
def content_overview() -> dict:
    return {
        "name": "内容运营",
        "message": "内容运营框架已就绪",
        "sections": SECTIONS,
    }


@router.get("/{section_id}")
def content_section(section_id: str) -> dict:
    section = next((item for item in SECTIONS if item["id"] == section_id), None)
    if section is None:
        raise HTTPException(status_code=404, detail="内容运营页面不存在")
    return {"workspace": "内容运营", "section": section, "status": "scaffolded"}
