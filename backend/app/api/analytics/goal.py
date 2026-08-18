"""数据洞察：联动分析、目标、预测。"""

from __future__ import annotations

import io as _io
import json as _json
from datetime import date as date_cls
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel

from backend.app.api.auth import get_current_user, visible_store_ids
from backend.app.api.model_configs import get_default_config
from backend.app.core.ai_client import AIError, chat_completion
from backend.app.core.db import get_db
from backend.app.core.sycm import has_profile

from ._common import (
    AlertsConfigIn,
    _alerts_config,
    _buckets,
    _date_range,
    _derive,
    _store_filter,
    _sum_rows,
    _to_date,
)

router = APIRouter()

# ---------- 联动分析（推广 vs 销售） ----------

@router.get("/linkage")
def analytics_linkage(
    days: int = 14,
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not (1 <= days <= 90):
        days = 14
    start, today = _date_range(days)
    sf, sp = _store_filter(store_id, user)
    sd_rows = db.execute(
        "SELECT * FROM store_daily_data WHERE data_date >= ? AND data_date <= ?" + sf + " ORDER BY data_date",
        [start.isoformat(), today.isoformat()] + sp,
    ).fetchall()
    pd_rows = db.execute(
        "SELECT * FROM promo_daily_data WHERE data_date >= ? AND data_date <= ?" + sf + " ORDER BY data_date",
        [start.isoformat(), today.isoformat()] + sp,
    ).fetchall()
    sd_map: dict[str, dict] = {}
    pd_map: dict[str, dict] = {}
    for r in sd_rows:
        d = r["data_date"]
        item = sd_map.setdefault(d, {"sales": 0.0, "visitors": 0, "orders": 0})
        item["sales"] += r["sales"] or 0
        item["visitors"] += r["visitors"] or 0
        item["orders"] += r["orders"] or 0
    for r in pd_rows:
        d = r["data_date"]
        item = pd_map.setdefault(d, {"spend": 0.0, "sales": 0.0})
        item["spend"] += r["spend"] or 0
        item["sales"] += r["sales"] or 0

    items = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        sd = sd_map.get(d, {"sales": 0.0, "visitors": 0, "orders": 0})
        pd = pd_map.get(d, {"spend": 0.0, "sales": 0.0})
        total_sales = round(sd["sales"], 2)
        promo_spend = round(pd["spend"], 2)
        promo_sales = round(pd["sales"], 2)
        items.append(
            {
                "date": d,
                "label": d[5:],
                "total_sales": total_sales,
                "total_visitors": sd["visitors"],
                "total_orders": sd["orders"],
                "promo_spend": promo_spend,
                "promo_sales": promo_sales,
                "promo_roi": round(promo_sales / promo_spend, 2) if promo_spend else 0.0,
                "ad_share": round(min(promo_sales / total_sales * 100, 100.0), 1) if total_sales else 0.0,
                "overall_roi": round(total_sales / promo_spend, 2) if promo_spend else 0.0,
                "natural_sales": round(max(total_sales - promo_sales, 0), 2),
            }
        )
    ts = sum(x["total_sales"] for x in items)
    ps = sum(x["promo_spend"] for x in items)
    psa = sum(x["promo_sales"] for x in items)
    summary = {
        "total_sales": round(ts, 2),
        "promo_spend": round(ps, 2),
        "promo_sales": round(psa, 2),
        "natural_sales": round(max(ts - psa, 0), 2),
        "ad_share": round(min(psa / ts * 100, 100.0), 1) if ts else 0.0,
        "promo_roi": round(psa / ps, 2) if ps else 0.0,
        "overall_roi": round(ts / ps, 2) if ps else 0.0,
        "days": days,
    }
    return {"items": items, "summary": summary, "days": days}


# ---------- 区间对比 ----------

class GoalIn(BaseModel):
    goal: float = 0
    month: str = ""


def _current_month() -> str:
    return date_cls.today().strftime("%Y-%m")


def _goal_value(db) -> tuple[float, str]:
    row = db.execute("SELECT value FROM meta WHERE key = 'analytics_sales_goal'").fetchone()
    if not row or not row["value"]:
        return 0.0, _current_month()
    try:
        data = _json.loads(row["value"])
        return float(data.get("goal") or 0), str(data.get("month") or _current_month())
    except (ValueError, TypeError, AttributeError):
        return 0.0, _current_month()


@router.get("/goal")
def get_goal(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    goal, month = _goal_value(db)
    return {"goal": goal, "month": month}


@router.put("/goal")
def set_goal(
    body: GoalIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if body.goal < 0:
        raise HTTPException(status_code=400, detail="目标金额不能为负数")
    month = (body.month or _current_month()).strip()
    try:
        date_cls.fromisoformat(month + "-01")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="月份格式不正确（应为 YYYY-MM）") from exc
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('analytics_sales_goal', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_json.dumps({"month": month, "goal": float(body.goal)}, ensure_ascii=False),),
    )
    return {"ok": True, "goal": float(body.goal), "month": month}


@router.get("/goal/progress")
def goal_progress(
    month: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    month = (month or _current_month()).strip()
    try:
        date_cls.fromisoformat(month + "-01")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="月份格式不正确（应为 YYYY-MM）") from exc
    goal, _ = _goal_value(db)
    if month != _current_month():
        goal = 0.0
    sf, sp = _store_filter(store_id, user)
    rows = db.execute(
        "SELECT sales FROM store_daily_data WHERE data_date LIKE ?" + sf,
        [month + "%"] + sp,
    ).fetchall()
    sales = round(sum(r["sales"] or 0 for r in rows), 2)
    today = date_cls.today()
    if month == today.strftime("%Y-%m"):
        days_elapsed = today.day
        days_total = 31 if today.month == 12 else (date_cls(today.year, today.month + 1, 1) - timedelta(days=1)).day
    else:
        days_elapsed = 0
        days_total = 30
    avg_daily = round(sales / days_elapsed, 2) if days_elapsed else 0.0
    forecast = round(avg_daily * days_total, 2) if avg_daily else 0.0
    remaining = max(goal - sales, 0)
    remaining_days = max(days_total - days_elapsed, 0)
    remaining_daily = round(remaining / remaining_days, 2) if remaining_days else 0.0
    return {
        "month": month,
        "goal": goal,
        "sales": sales,
        "progress_pct": round(sales / goal * 100, 1) if goal else 0.0,
        "days_elapsed": days_elapsed,
        "days_total": days_total,
        "avg_daily": avg_daily,
        "forecast": forecast,
        "remaining": round(remaining, 2),
        "remaining_daily": remaining_daily,
    }


@router.get("/forecast")
def analytics_forecast(
    days: int = 7,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not (1 <= days <= 30):
        days = 7
    today = date_cls.today()
    sf, sp = _store_filter(None, user)
    rows = db.execute(
        "SELECT data_date, sales FROM store_daily_data WHERE data_date >= ?" + sf + " ORDER BY data_date",
        [(today - timedelta(days=13)).isoformat()] + sp,
    ).fetchall()
    by_date = {r["data_date"]: r["sales"] or 0 for r in rows}
    actual = []
    for i in range(13, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        actual.append({"date": d[5:], "sales": round(by_date.get(d, 0), 2)})
    xs = []
    ys = []
    for i, p in enumerate(actual):
        if p["sales"] > 0:
            xs.append(i)
            ys.append(p["sales"])
    predicted = []
    if len(xs) >= 2:
        n = len(xs)
        xm = sum(xs) / n
        ym = sum(ys) / n
        slope = sum((xs[i] - xm) * (ys[i] - ym) for i in range(n)) / sum((xs[i] - xm) ** 2 for i in range(n)) if sum((xs[i] - xm) ** 2 for i in range(n)) else 0
        intercept = ym - slope * xm
        last_idx = 13
        for k in range(1, days + 1):
            val = max(slope * (last_idx + k) + intercept, 0)
            predicted.append({"date": (today + timedelta(days=k)).strftime("%m-%d"), "sales": round(val, 2)})
    return {"actual": actual, "predicted": predicted, "days": days}
