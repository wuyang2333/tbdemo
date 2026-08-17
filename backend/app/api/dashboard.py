from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.auth import get_current_user, visible_store_ids
from backend.app.core.db import get_db

router = APIRouter()


@router.get("")
def overview(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """总览：从真实数据表聚合核心指标（SaaS：按账号可见店铺隔离）。"""
    visible = visible_store_ids(user)
    empty = {
        "store_count": 0,
        "product_count": 0,
        "today_orders": 0,
        "today_sales": 0,
        "today_visitors": 0,
        "pending_shipments": 0,
        "data_date": None,
        "message": "暂无店铺权限，请联系管理员分配店铺",
    }
    if visible is not None and not visible:
        return empty

    if visible is not None:
        sf = " AND store_id IN (" + ",".join(str(i) for i in visible) + ")"
        store_count = len(visible)
    else:
        sf = ""
        store_count = db.execute("SELECT COUNT(*) AS c FROM stores").fetchone()["c"]

    latest = db.execute("SELECT MAX(data_date) AS d FROM store_item_daily WHERE 1=1" + sf).fetchone()["d"]
    if not latest:
        empty["store_count"] = store_count
        empty["message"] = "暂无商品数据，请先在店铺管理同步数据"
        return empty

    row = db.execute(
        """
        SELECT
            COUNT(DISTINCT item_id) AS product_count,
            COALESCE(SUM(sales), 0) AS sales,
            COALESCE(SUM(orders), 0) AS orders,
            COALESCE(SUM(visitors), 0) AS visitors
        FROM store_item_daily
        WHERE data_date = ?
        """
        + sf,
        (latest,),
    ).fetchone()
    pending = db.execute(
        "SELECT COUNT(*) AS c FROM gifts WHERE status = 'pending'" + sf
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