from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.core.db import get_db

router = APIRouter()


@router.get("")
def overview(db=Depends(get_db)) -> dict:
    """总览：从真实数据表聚合核心指标。

    商品/访客等按天指标取 store_item_daily 最近有数据的日期（今日数据未生成时自动回退到最近一天）。
    """
    store_count = db.execute("SELECT COUNT(*) AS c FROM stores").fetchone()["c"]
    latest = db.execute("SELECT MAX(data_date) AS d FROM store_item_daily").fetchone()["d"]
    if not latest:
        return {
            "store_count": store_count,
            "product_count": 0,
            "today_orders": 0,
            "today_sales": 0,
            "today_visitors": 0,
            "pending_shipments": 0,
            "data_date": None,
            "message": "暂无商品数据，请先在店铺管理同步数据",
        }

    row = db.execute(
        """
        SELECT
            COUNT(DISTINCT item_id) AS product_count,
            COALESCE(SUM(sales), 0) AS sales,
            COALESCE(SUM(orders), 0) AS orders,
            COALESCE(SUM(visitors), 0) AS visitors
        FROM store_item_daily
        WHERE data_date = ?
        """,
        (latest,),
    ).fetchone()
    pending = db.execute(
        "SELECT COUNT(*) AS c FROM gifts WHERE status = 'pending'"
    ).fetchone()["c"]
    return {
        "store_count": store_count,
        "product_count": row["product_count"],
        "today_orders": row["orders"],
        "today_sales": round(row["sales"], 2),
        "today_visitors": row["visitors"],
        "pending_shipments": pending,
        "data_date": latest,
        "message": "真实数据（自动回退到最近有数据的日期）",
    }
