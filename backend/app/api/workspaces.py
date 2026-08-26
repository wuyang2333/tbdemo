from __future__ import annotations

from fastapi import APIRouter, HTTPException


market_router = APIRouter()
growth_lab_router = APIRouter()
ops_knowledge_router = APIRouter()


WORKSPACES = {
    "market": {
        "name": "市场洞察",
        "message": "市场洞察框架已就绪",
        "sections": [
            {"id": "opportunities", "name": "选品与市场机会"},
            {"id": "keywords", "name": "关键词运营中心"},
            {"id": "radar", "name": "经营机会雷达"},
        ],
    },
    "growth-lab": {
        "name": "增长实验室",
        "message": "增长实验室框架已就绪",
        "sections": [
            {"id": "products", "name": "商品策略中心"},
            {"id": "pricing", "name": "价格与促销中心"},
            {"id": "simulator", "name": "经营沙盘"},
            {"id": "experiments", "name": "营销实验中心"},
            {"id": "creative", "name": "素材洞察中心"},
        ],
    },
    "ops-knowledge": {
        "name": "运营知识库",
        "message": "运营知识库框架已就绪",
        "sections": [
            {"id": "reviews", "name": "经营复盘中心"},
            {"id": "decisions", "name": "运营决策档案"},
            {"id": "knowledge", "name": "知识库与 SOP"},
            {"id": "automation", "name": "运营自动化中心"},
        ],
    },
}


def _overview(workspace_id: str) -> dict:
    return dict(WORKSPACES[workspace_id])


def _section(workspace_id: str, section_id: str) -> dict:
    workspace = WORKSPACES[workspace_id]
    section = next((item for item in workspace["sections"] if item["id"] == section_id), None)
    if section is None:
        raise HTTPException(status_code=404, detail="工作区页面不存在")
    return {"workspace": workspace["name"], "section": section, "status": "scaffolded"}


@market_router.get("")
def market_overview() -> dict:
    return _overview("market")


@market_router.get("/{section_id}")
def market_section(section_id: str) -> dict:
    return _section("market", section_id)


@growth_lab_router.get("")
def growth_lab_overview() -> dict:
    return _overview("growth-lab")


@growth_lab_router.get("/{section_id}")
def growth_lab_section(section_id: str) -> dict:
    return _section("growth-lab", section_id)


@ops_knowledge_router.get("")
def ops_knowledge_overview() -> dict:
    return _overview("ops-knowledge")


@ops_knowledge_router.get("/{section_id}")
def ops_knowledge_section(section_id: str) -> dict:
    return _section("ops-knowledge", section_id)
