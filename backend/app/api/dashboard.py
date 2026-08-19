from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.app.api.auth import get_current_user, visible_store_ids
from backend.app.core.db import get_db

router = APIRouter()


ALLOWED_WIDGETS = {"kpis", "trend", "stores", "shortcuts", "system"}
DEFAULT_WIDGETS = ["kpis", "trend", "shortcuts", "system"]


class DashboardConfigIn(BaseModel):
    widgets: list[str]


@router.get("/config")
def get_dashboard_config(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """读取当前账号的自定义看板配置（未配置时返回默认）。"""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_configs (
            user_id INTEGER PRIMARY KEY,
            config TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    row = db.execute(
        "SELECT config FROM dashboard_configs WHERE user_id = ?", (user["id"],)
    ).fetchone()
    if not row:
        return {"widgets": DEFAULT_WIDGETS, "default": True}
    try:
        widgets = json.loads(row["config"])
    except (ValueError, TypeError):
        widgets = []
    return {"widgets": widgets, "default": False}


@router.put("/config")
def save_dashboard_config(
    body: DashboardConfigIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """保存当前账号的自定义看板配置（只允许白名单内的组件）。"""
    widgets = [w for w in body.widgets if w in ALLOWED_WIDGETS]
    seen: set[str] = set()
    deduped: list[str] = []
    for w in widgets:
        if w not in seen:
            seen.add(w)
            deduped.append(w)
    now = date.today().isoformat() + "T00:00:00"
    db.execute(
        """
        INSERT INTO dashboard_configs (user_id, config, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET config = excluded.config, updated_at = excluded.updated_at
        """,
        (user["id"], json.dumps(deduped), now),
    )
    return {"ok": True, "widgets": deduped}


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
    # 只统计店铺列表里真实存在的店铺，避免残留数据混入
    sf += " AND store_id IN (SELECT id FROM stores)"

    # 经营指标以 store_daily_data 为准（数据最实时），商品数单独取商品明细表的最新日
    latest = db.execute(
        "SELECT MAX(data_date) AS d FROM store_daily_data WHERE 1=1" + sf
    ).fetchone()["d"]
    if not latest:
        empty["store_count"] = store_count
        empty["message"] = "暂无经营数据，请先在店铺管理同步数据"
        return empty

    row = db.execute(
        """
        SELECT
            COALESCE(SUM(sales), 0) AS sales,
            COALESCE(SUM(orders), 0) AS orders,
            COALESCE(SUM(visitors), 0) AS visitors
        FROM store_daily_data
        WHERE data_date = ?
        """
        + sf,
        (latest,),
    ).fetchone()

    yesterday = (date.fromisoformat(latest) - timedelta(days=1)).isoformat()

    # 较昨日采用「同时段对比」：取今日分时数据里最后一个有数据的整点，
    # 今日与昨日都只累计到该小时，避免今日还没同步完就与昨日全天对比的不公平。
    hour_rows = db.execute(
        """
        SELECT data_date, hour,
               COALESCE(SUM(visitors), 0) AS visitors,
               COALESCE(SUM(sales), 0) AS sales,
               COALESCE(SUM(orders), 0) AS orders
        FROM store_hourly_data
        WHERE data_date IN (?, ?)
        """
        + sf
        + " GROUP BY data_date, hour",
        (latest, yesterday),
    ).fetchall()
    today_hours: dict[str, dict] = {}
    yesterday_hours: dict[str, dict] = {}
    for r in hour_rows:
        target = today_hours if r["data_date"] == latest else yesterday_hours
        target[r["hour"]] = {
            "visitors": r["visitors"],
            "sales": r["sales"],
            "orders": r["orders"],
        }

    # 推广花费分时（用于真实 ROI 的同时段对比）
    promo_rows = db.execute(
        """
        SELECT data_date, hour,
               COALESCE(SUM(spend), 0) AS spend
        FROM promo_realtime
        WHERE data_date IN (?, ?)
        """
        + sf
        + " GROUP BY data_date, hour",
        (latest, yesterday),
    ).fetchall()
    today_spend_hours: dict[str, float] = {}
    yesterday_spend_hours: dict[str, float] = {}
    for r in promo_rows:
        target_sp = today_spend_hours if r["data_date"] == latest else yesterday_spend_hours
        target_sp[r["hour"]] = target_sp.get(r["hour"], 0.0) + (r["spend"] or 0)

    active_hours = [
        h for h, v in today_hours.items() if v["visitors"] or v["sales"] or v["orders"]
    ]
    if active_hours:
        upto = max(active_hours)

        def _segment(hours_map: dict[str, dict]) -> dict:
            agg = {"visitors": 0, "sales": 0.0, "orders": 0}
            for h, v in hours_map.items():
                if h <= upto:
                    agg["visitors"] += v["visitors"]
                    agg["sales"] += v["sales"]
                    agg["orders"] += v["orders"]
            agg["sales"] = round(agg["sales"], 2)
            return agg

        today_row = _segment(today_hours)
        yrow = _segment(yesterday_hours)

        def _spend_segment(hours_map: dict[str, float]) -> float:
            return round(sum(v for h, v in hours_map.items() if h <= upto), 2)

        today_spend = _spend_segment(today_spend_hours)
        yesterday_spend = _spend_segment(yesterday_spend_hours)
        hour_until = upto
        compare_mode = "同时段"
    else:
        # 无分时数据时回退为全天对比
        today_row = row
        yrow = db.execute(
            """
            SELECT
                COALESCE(SUM(sales), 0) AS sales,
                COALESCE(SUM(orders), 0) AS orders,
                COALESCE(SUM(visitors), 0) AS visitors
            FROM store_daily_data
            WHERE data_date = ?
            """
            + sf,
            (yesterday,),
        ).fetchone()

        def _daily_spend(d: str) -> float:
            r = db.execute(
                "SELECT COALESCE(SUM(spend), 0) AS spend FROM promo_daily_data WHERE data_date = ?" + sf,
                (d,),
            ).fetchone()
            return round(r["spend"] or 0, 2)

        today_spend = _daily_spend(latest)
        yesterday_spend = _daily_spend(yesterday)
        hour_until = None
        compare_mode = "全天"

    # 真实 ROI = 总成交 / 推广花费（推广花费为 0 时不展示）
    today_real_roi = round(today_row["sales"] / today_spend, 2) if today_spend else None
    yesterday_real_roi = round(yrow["sales"] / yesterday_spend, 2) if yesterday_spend else None

    # 近 14 天趋势（缺日补 0，保证图表连续）
    start = date.fromisoformat(latest) - timedelta(days=13)
    trend_rows = db.execute(
        """
        SELECT data_date,
               COALESCE(SUM(sales), 0) AS sales,
               COALESCE(SUM(orders), 0) AS orders,
               COALESCE(SUM(visitors), 0) AS visitors
        FROM store_daily_data
        WHERE data_date >= ?
        """
        + sf
        + " GROUP BY data_date ORDER BY data_date ASC",
        (start.isoformat(),),
    ).fetchall()
    trend_map = {r["data_date"]: r for r in trend_rows}
    trend = []
    for i in range(14):
        d = start + timedelta(days=i)
        ds = d.isoformat()
        r = trend_map.get(ds)
        trend.append(
            {
                "date": d.strftime("%m-%d"),
                "sales": round(r["sales"], 2) if r else 0,
                "orders": r["orders"] if r else 0,
                "visitors": r["visitors"] if r else 0,
            }
        )

    product_latest = db.execute(
        "SELECT MAX(data_date) AS d FROM store_item_daily WHERE 1=1" + sf
    ).fetchone()["d"]
    product_count = 0
    if product_latest:
        product_count = db.execute(
            "SELECT COUNT(DISTINCT item_id) AS c FROM store_item_daily WHERE data_date = ?"
            + sf,
            (product_latest,),
        ).fetchone()["c"]

    pending = db.execute(
        "SELECT COUNT(*) AS c FROM gifts WHERE status = 'pending'" + sf
    ).fetchone()["c"]
    return {
        "store_count": store_count,
        "product_count": product_count,
        "today_orders": today_row["orders"],
        "today_sales": today_row["sales"],
        "today_visitors": today_row["visitors"],
        "yesterday_orders": yrow["orders"],
        "yesterday_sales": yrow["sales"],
        "yesterday_visitors": yrow["visitors"],
        "today_real_roi": today_real_roi,
        "yesterday_real_roi": yesterday_real_roi,
        "pending_shipments": pending,
        "data_date": latest,
        "hour_until": hour_until,
        "compare_mode": compare_mode,
        "product_date": product_latest,
        "trend": trend,
        "message": f"真实数据（较昨日为{compare_mode}对比，截至 {latest} {hour_until or '全天'}）",
    }

