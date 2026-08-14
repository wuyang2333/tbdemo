from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("")
def overview() -> dict:
    """总览：示例数据，后续替换为真实统计。"""
    return {
        "store_count": 0,
        "product_count": 0,
        "today_orders": 0,
        "today_sales": 0,
        "today_visitors": 0,
        "pending_shipments": 0,
        "message": "框架占位数据，功能待开发",
    }
