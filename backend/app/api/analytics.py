"""数据洞察：从礼品单数据聚合统计（今日/本周/本月、趋势、按店铺、状态分布）。"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta

from fastapi import APIRouter, Depends

from backend.app.api.auth import get_current_user
from backend.app.core.db import get_db

router = APIRouter()


def _day(raw: str) -> str:
    return raw[:10] if raw and len(raw) >= 10 else ""


def _day_date(raw: str) -> date_cls | None:
    d = _day(raw)
    if not d:
        return None
    try:
        return date_cls.fromisoformat(d)
    except ValueError:
        return None


def _store_name(row) -> str:
    if row["store_id"] != 0:
        return (row["linked_store_name"] or "") or "未关联店铺"
    return (row["store_name"] or "") or "未关联店铺"


def _sum(rows) -> dict:
    orders = 0
    amount = 0.0
    commission = 0.0
    for row in rows:
        orders += 1
        amount += row["price"] or 0
        commission += row["commission"] or 0
    return {
        "orders": orders,
        "amount": round(amount, 2),
        "commission": round(commission, 2),
    }


@router.get("/summary")
def analytics_summary(
    days: int = 14,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not (1 <= days <= 90):
        days = 14
    rows = db.execute(
        """
        SELECT g.*, COALESCE(s.name, '') AS linked_store_name
        FROM gifts g
        LEFT JOIN stores s ON s.id = g.store_id
        ORDER BY COALESCE(g.order_time, g.created_at) ASC, g.id ASC
        """
    ).fetchall()

    today = date_cls.today()
    today_str = today.isoformat()
    week_start = today - timedelta(days=6)
    month_prefix = today.strftime("%Y-%m")

    today_rows = [r for r in rows if _day(r["order_time"] or r["created_at"]) == today_str]
    week_rows = []
    month_rows = []
    for r in rows:
        d = _day_date(r["order_time"] or r["created_at"])
        if d is None:
            continue
        if week_start <= d <= today:
            week_rows.append(r)
        if d.strftime("%Y-%m") == month_prefix:
            month_rows.append(r)

    trend = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        day_rows = [r for r in rows if _day(r["order_time"] or r["created_at"]) == ds]
        agg = _sum(day_rows)
        trend.append({"date": d.strftime("%m-%d"), **agg})

    stores_map: dict[str, dict] = {}
    for r in rows:
        name = _store_name(r)
        item = stores_map.setdefault(
            name, {"store": name, "orders": 0, "amount": 0.0, "commission": 0.0}
        )
        item["orders"] += 1
        item["amount"] += r["price"] or 0
        item["commission"] += r["commission"] or 0
    by_store = sorted(stores_map.values(), key=lambda x: x["amount"], reverse=True)
    for item in by_store:
        item["amount"] = round(item["amount"], 2)
        item["commission"] = round(item["commission"], 2)

    reviewed = sum(1 for r in rows if r["review_status"] == "reviewed")
    settled = sum(1 for r in rows if r["settle_status"] == "settled")

    return {
        "today": _sum(today_rows),
        "week": _sum(week_rows),
        "month": _sum(month_rows),
        "total": _sum(rows),
        "trend": trend,
        "by_store": by_store,
        "status": {
            "reviewed": reviewed,
            "unreviewed": len(rows) - reviewed,
            "settled": settled,
            "unsettled": len(rows) - settled,
        },
    }
