"""数据洞察通用工具：汇总、日期、店铺过滤、预警配置。"""

from __future__ import annotations

import json as _json
from datetime import date as date_cls
from datetime import timedelta

from pydantic import BaseModel

from backend.app.api.auth import visible_store_ids


def _sum_rows(rows) -> dict:
    visitors = 0
    pv = 0
    sales = 0.0
    orders = 0
    for r in rows:
        visitors += r["visitors"] or 0
        pv += r["pv"] or 0
        sales += r["sales"] or 0
        orders += r["orders"] or 0
    conversion = (orders / visitors * 100) if visitors else 0.0
    return {
        "visitors": visitors,
        "pv": pv,
        "sales": round(sales, 2),
        "orders": orders,
        "conversion_rate": round(conversion, 2),
    }


def _to_date(raw: str) -> date_cls | None:
    try:
        return date_cls.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _date_range(days: int) -> tuple[date_cls, date_cls]:
    today = date_cls.today()
    start = today - timedelta(days=days - 1)
    return start, today


def _derive(item: dict) -> dict:
    """补充客单价、单访客价值等派生指标。"""
    sales = item.get("sales") or 0
    orders = item.get("orders") or 0
    visitors = item.get("visitors") or 0
    item["avg_order_value"] = round(sales / orders, 2) if orders else 0.0
    item["value_per_visitor"] = round(sales / visitors, 2) if visitors else 0.0
    return item


def _buckets(rows) -> dict:
    today = date_cls.today()
    today_str = today.isoformat()
    week_start = today - timedelta(days=6)
    month_prefix = today.strftime("%Y-%m")

    today_rows = [r for r in rows if r["data_date"] == today_str]
    week_rows = []
    month_rows = []
    for r in rows:
        d = _to_date(r["data_date"])
        if d is None:
            continue
        if week_start <= d <= today:
            week_rows.append(r)
        if r["data_date"].startswith(month_prefix):
            month_rows.append(r)

    today_sum = _sum_rows(today_rows)
    if len(today_rows) == 1 and today_rows[0]["conversion_rate"]:
        today_sum["conversion_rate"] = round(today_rows[0]["conversion_rate"], 2)
    return {
        "today": today_sum,
        "week": _sum_rows(week_rows),
        "month": _sum_rows(month_rows),
        "total": _sum_rows(rows),
    }


def _store_filter(store_id: int | None, user: dict) -> tuple[str, list]:
    """店铺过滤：先按账号可见店铺（SaaS 隔离），再按请求的 store_id 参数。"""
    clauses: list[str] = []
    params: list = []
    visible = visible_store_ids(user)
    if visible is not None:
        if not visible:
            return " AND 1=0", []
        ids = ",".join(str(i) for i in visible)
        clauses.append(f" AND store_id IN ({ids})")
    if store_id:
        clauses.append(" AND store_id = ?")
        params.append(store_id)
    # 只统计店铺列表里真实存在的店铺，避免已删除店铺的残留数据混入汇总
    clauses.append(" AND store_id IN (SELECT id FROM stores)")
    return "".join(clauses), params


def _alerts_config(db) -> dict:
    row = db.execute("SELECT value FROM meta WHERE key = 'analytics_alerts_config'").fetchone()
    default = {
        "baseline_days": 7,
        "sales_down": -30,
        "sales_up": 60,
        "orders_down": -30,
        "visitors_down": -30,
        "conversion_down": -20,
    }
    if not row or not row["value"]:
        return default
    try:
        data = _json.loads(row["value"])
        for k in default:
            if k in data and isinstance(data[k], (int, float)):
                default[k] = data[k]
    except (ValueError, TypeError):
        pass
    return default


class AlertsConfigIn(BaseModel):
    baseline_days: int = 7
    sales_down: float = -30
    sales_up: float = 60
    orders_down: float = -30
    visitors_down: float = -30
    conversion_down: float = -20
