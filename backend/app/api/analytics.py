"""数据洞察：从生意参谋抓取的店铺每日数据（store_daily_data）聚合统计。"""

from __future__ import annotations

import io as _io
import json as _json
from datetime import date as date_cls
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel

from backend.app.api.auth import get_current_user
from backend.app.api.model_configs import get_default_config
from backend.app.core.ai_client import AIError, chat_completion
from backend.app.core.db import get_db
from backend.app.core.sycm import has_profile

router = APIRouter()


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


@router.get("/summary")
def analytics_summary(
    days: int = 14,
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not (1 <= days <= 90):
        days = 14
    sf, sp = _store_filter(store_id)
    rows = db.execute(
        "SELECT * FROM store_daily_data" + (" WHERE 1=1" + sf) + " ORDER BY data_date ASC, store_id ASC",
        sp,
    ).fetchall()

    start, today = _date_range(days)
    trend = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        point = {"date": d.strftime("%m-%d"), **(_sum_rows([r for r in rows if r["data_date"] == ds]))}
        single = [r for r in rows if r["data_date"] == ds]
        if len(single) == 1 and single[0]["conversion_rate"]:
            point["conversion_rate"] = round(single[0]["conversion_rate"], 2)
        trend.append(point)

    stores_map: dict[int, dict] = {}
    for r in rows:
        sid = r["store_id"]
        item = stores_map.setdefault(
            sid,
            {
                "store_id": sid,
                "store_name": "",
                "visitors": 0,
                "pv": 0,
                "sales": 0.0,
                "orders": 0,
                "days": 0,
                "latest_date": "",
            },
        )
        item["visitors"] += r["visitors"] or 0
        item["pv"] += r["pv"] or 0
        item["sales"] += r["sales"] or 0
        item["orders"] += r["orders"] or 0
        item["days"] += 1
        if r["data_date"] > item["latest_date"]:
            item["latest_date"] = r["data_date"]

    name_map = {s["id"]: s["name"] for s in db.execute("SELECT id, name FROM stores").fetchall()}
    by_store = []
    for sid, item in stores_map.items():
        item["store_name"] = name_map.get(sid, f"店铺 {sid}")
        conv = (item["orders"] / item["visitors"] * 100) if item["visitors"] else 0.0
        item["conversion_rate"] = round(conv, 2)
        item["sales"] = round(item["sales"], 2)
        by_store.append(_derive(item))
    by_store.sort(key=lambda x: x["sales"], reverse=True)

    store_ids = [s["id"] for s in db.execute("SELECT id FROM stores").fetchall()]
    configured = sum(1 for sid in store_ids if has_profile(sid))
    last = db.execute(
        "SELECT MAX(created_at) AS m FROM store_daily_data"
    ).fetchone()["m"]

    return {
        **_buckets(rows),
        "trend": trend,
        "by_store": by_store,
        "store_count": configured,
        "last_sync": last,
    }


@router.get("/daily")
def analytics_daily(
    days: int = 30,
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """每日明细：访客/浏览/销售额/订单/转化率/客单价/单访客价值（全部店铺合计）。"""
    if not (1 <= days <= 90):
        days = 30
    start, today = _date_range(days)
    sf, sp = _store_filter(store_id)
    rows = db.execute(
        "SELECT * FROM store_daily_data WHERE data_date >= ? AND data_date <= ?" + sf + " ORDER BY data_date ASC",
        [start.isoformat(), today.isoformat()] + sp,
    ).fetchall()

    items = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        day_rows = [r for r in rows if r["data_date"] == ds]
        point = {"date": ds, "date_label": d.strftime("%m-%d"), **_sum_rows(day_rows)}
        if len(day_rows) == 1 and day_rows[0]["conversion_rate"]:
            point["conversion_rate"] = round(day_rows[0]["conversion_rate"], 2)
        items.append(_derive(point))
    return {"items": items, "days": days}


@router.get("/alerts")
def analytics_alerts(
    days: int = 30,
    baseline: int = 7,
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """异常波动：按店铺对比每天指标与前 baseline 日均值，超过阈值生成提醒。"""
    if not (1 <= days <= 90):
        days = 30
    cfg = _alerts_config(db)
    baseline = int(cfg["baseline_days"])
    today = date_cls.today()
    start = today - timedelta(days=days - 1)
    sf, sp = _store_filter(store_id)
    rows = db.execute(
        "SELECT * FROM store_daily_data WHERE data_date >= ?" + sf + " ORDER BY data_date ASC",
        [start.isoformat()] + sp,
    ).fetchall()
    name_map = {s["id"]: s["name"] for s in db.execute("SELECT id, name FROM stores").fetchall()}

    by_store: dict[int, list] = {}
    for r in rows:
        by_store.setdefault(r["store_id"], []).append(r)

    min_base_days = 2
    items: list[dict] = []
    for sid, srows in by_store.items():
        srows.sort(key=lambda r: r["data_date"])
        store_name = name_map.get(sid, f"店铺 {sid}")
        for i in range(baseline, len(srows)):
            base_rows = [r for r in srows[i - baseline:i] if (r["sales"] or 0) > 0 or (r["visitors"] or 0) > 0]
            if len(base_rows) < min_base_days:
                continue
            cur = srows[i]
            date_label = cur["data_date"][5:]

            def base_avg(field: str) -> float:
                vals = [r[field] or 0 for r in base_rows]
                return sum(vals) / len(vals)

            checks = [
                ("sales", "销售额", base_avg("sales"), cur["sales"] or 0, cfg["sales_down"], cfg["sales_up"], "money"),
                ("orders", "订单数", base_avg("orders"), cur["orders"] or 0, cfg["orders_down"], None, "int"),
                ("visitors", "访客数", base_avg("visitors"), cur["visitors"] or 0, cfg["visitors_down"], 60, "int"),
                ("conversion_rate", "转化率", base_avg("conversion_rate"), cur["conversion_rate"] or 0, cfg["conversion_down"], None, "pct"),
            ]
            for key, mname, base, val, down_th, up_th, _fmt in checks:
                if base <= 0:
                    continue
                chg = (val - base) / base * 100
                if chg <= down_th:
                    level = "error" if key == "sales" else "warn"
                    items.append(
                        {
                            "date": cur["data_date"],
                            "date_label": date_label,
                            "store_id": sid,
                            "store_name": store_name,
                            "metric": mname,
                            "level": level,
                            "change_pct": round(chg, 1),
                            "message": f"「{store_name}」{date_label} {mname}较前 {baseline} 日均值下降 {abs(chg):.1f}%，建议核查原因",
                        }
                    )
                elif up_th is not None and chg >= up_th:
                    items.append(
                        {
                            "date": cur["data_date"],
                            "date_label": date_label,
                            "store_id": sid,
                            "store_name": store_name,
                            "metric": mname,
                            "level": "info",
                            "change_pct": round(chg, 1),
                            "message": f"「{store_name}」{date_label} {mname}较前 {baseline} 日均值上涨 {chg:.1f}%，留意是否异常冲量",
                        }
                    )

    items.sort(key=lambda x: (x["date"], {"error": 0, "warn": 1, "info": 2}[x["level"]]))
    items.reverse()
    return {
        "items": items,
        "baseline_days": baseline,
        "min_baseline_days": min_base_days,
        "checked_days": len(rows),
        "checked_stores": len(by_store),
    }
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
    sf, sp = _store_filter(store_id)
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
    sf, sp = _store_filter(store_id)
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
    rows = db.execute(
        "SELECT data_date, sales FROM store_daily_data WHERE data_date >= ? ORDER BY data_date",
        ((today - timedelta(days=13)).isoformat(),),
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


# ---------- 经营日报 ----------

def _report_day_summary(db, d: str, sf: str, sp: list) -> dict:
    rows = db.execute("SELECT * FROM store_daily_data WHERE data_date = ?" + sf, [d] + sp).fetchall()
    s = _sum_rows(rows)
    if len(rows) == 1 and rows[0]["conversion_rate"]:
        s["conversion_rate"] = round(rows[0]["conversion_rate"], 2)
    if rows:
        s["repeat_rate"] = round(rows[0]["repeat_rate"] or 0, 2)
        s["old_buyer_cnt"] = int(rows[0]["old_buyer_cnt"] or 0)
    s["avg_order_value"] = round(s["sales"] / s["orders"], 2) if s["orders"] else 0.0
    return s


def _report_top_items(db, d: str, sf: str, sp: list, realtime: bool, limit: int = 5) -> list[dict]:
    if realtime:
        rows = db.execute(
            "SELECT item_id, item_title, sales, orders, image FROM store_item_realtime WHERE 1=1"
            + sf + " ORDER BY sales DESC LIMIT " + str(limit),
            sp,
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT item_id, item_title, SUM(sales) AS sales, SUM(orders) AS orders, image FROM store_item_daily "
            "WHERE data_date = ?" + sf + " GROUP BY item_id ORDER BY sales DESC LIMIT " + str(limit),
            [d] + sp,
        ).fetchall()
    return [
        {
            "item_id": r["item_id"],
            "item_title": r["item_title"] or "",
            "image": r["image"] or "",
            "sales": round(r["sales"] or 0, 2),
            "orders": int(r["orders"] or 0),
        }
        for r in rows
    ]


def _report_scenes(db, d: str, sf: str, sp: list, realtime: bool) -> list[dict]:
    table = "promo_realtime" if realtime else "promo_daily_data"
    rows = db.execute(
        f"SELECT scene, scene_name, SUM(spend) AS spend, SUM(sales) AS sales FROM {table} "
        "WHERE data_date = ?" + sf + " GROUP BY scene ORDER BY spend DESC",
        [d] + sp,
    ).fetchall()
    return [
        {
            "scene": r["scene"],
            "scene_name": r["scene_name"] or r["scene"],
            "spend": round(r["spend"] or 0, 2),
            "sales": round(r["sales"] or 0, 2),
            "roi": round((r["sales"] or 0) / (r["spend"] or 0), 2) if r["spend"] else 0.0,
        }
        for r in rows
    ]


def _report_add_cart_refund(db, d: str, sf: str, sp: list, realtime: bool) -> dict:
    table = "store_item_realtime" if realtime else "store_item_daily"
    cond = ("WHERE 1=1" + sf) if realtime else ("WHERE data_date = ?" + sf)
    params = sp if realtime else [d] + sp
    r = db.execute(
        f"SELECT COALESCE(SUM(add_cart),0) AS ac, COALESCE(SUM(refund_amount),0) AS rf FROM {table} {cond}",
        params,
    ).fetchone()
    return {"add_cart": int(r["ac"] or 0), "refund_amount": round(r["rf"] or 0, 2)}


def _report_alerts(db, d: str, sf: str, sp: list, realtime: bool) -> list[dict]:
    """日报预警：销售额骤降商品（最多3）+ 推广ROI偏低计划（最多2）。"""
    alerts: list[dict] = []
    if realtime:
        rows = db.execute(
            "SELECT item_title, sales_cycle FROM store_item_realtime "
            "WHERE sales_cycle IS NOT NULL AND sales_cycle < -30 AND sales > 0" + sf + " ORDER BY sales_cycle ASC LIMIT 3",
            sp,
        ).fetchall()
        for r in rows:
            alerts.append({"level": "error", "type": "商品骤降", "message": f"{r['item_title']} 销售额环比 {r['sales_cycle']:.0f}%"})
    else:
        cur_rows = db.execute(
            "SELECT item_id, item_title, sales FROM store_item_daily WHERE data_date = ?" + sf,
            [d] + sp,
        ).fetchall()
        prev_rows = db.execute(
            "SELECT item_id, sales FROM store_item_daily WHERE data_date = ?" + sf,
            [(date_cls.fromisoformat(d) - timedelta(days=1)).isoformat()] + sp,
        ).fetchall()
        prev_map = {r["item_id"]: r["sales"] or 0 for r in prev_rows}
        drops = []
        for r in cur_rows:
            pv = prev_map.get(r["item_id"])
            if pv:
                cyc = (r["sales"] - pv) / pv * 100 if pv else 0
                if cyc < -30:
                    drops.append((cyc, r["item_title"]))
        for cyc, title in sorted(drops)[:3]:
            alerts.append({"level": "error", "type": "商品骤降", "message": f"{title} 销售额环比 {cyc:.0f}%"})
    mode = "realtime" if realtime else "yesterday"
    plan_rows = db.execute(
        "SELECT p.plan_name, s.roi, s.spend FROM promo_plan_stats s "
        "JOIN promo_plans p ON p.store_id = s.store_id AND p.campaign_id = s.campaign_id "
        "WHERE s.mode = ? AND s.roi > 0 AND s.roi < 1 AND s.spend > 0"
        + sf + " ORDER BY s.roi ASC LIMIT 2",
        [mode] + sp,
    ).fetchall()
    for r in plan_rows:
        alerts.append({"level": "warn", "type": "ROI偏低", "message": f"「{r['plan_name']}」推广ROI {r['roi']:.2f}"})
    return alerts


@router.get("/report")
def daily_report(
    date: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """经营日报：支持查看历史日期（date=YYYY-MM-DD），含完整指标/TOP商品/推广分场景/上周同期/预警。"""
    real_today = date_cls.today()
    # 经营日报默认分析昨天（前一天数据完整后再看），date 参数可指定任意日期
    if date:
        try:
            today = date_cls.fromisoformat(date)
        except ValueError:
            today = real_today - timedelta(days=1)
    else:
        today = real_today - timedelta(days=1)
    yesterday = today - timedelta(days=1)
    last_week = today - timedelta(days=7)
    ts, ys, ws = today.isoformat(), yesterday.isoformat(), last_week.isoformat()
    is_realtime = ts == real_today.isoformat()
    sf, sp = _store_filter(store_id)

    td = _report_day_summary(db, ts, sf, sp)
    yd = _report_day_summary(db, ys, sf, sp)
    wd = _report_day_summary(db, ws, sf, sp)

    if is_realtime:
        pr = db.execute(
            "SELECT COALESCE(SUM(spend),0) AS spend, COALESCE(SUM(sales),0) AS sales FROM promo_realtime WHERE data_date = ?" + sf,
            [ts] + sp,
        ).fetchone()
    else:
        pr = db.execute(
            "SELECT COALESCE(SUM(spend),0) AS spend, COALESCE(SUM(sales),0) AS sales FROM promo_daily_data WHERE data_date = ?" + sf,
            [ts] + sp,
        ).fetchone()
    py = db.execute(
        "SELECT COALESCE(SUM(spend),0) AS spend, COALESCE(SUM(sales),0) AS sales FROM promo_daily_data WHERE data_date = ?" + sf,
        [ys] + sp,
    ).fetchone()

    goal, _ = _goal_value(db)
    month = today.strftime("%Y-%m")
    month_rows = db.execute("SELECT sales FROM store_daily_data WHERE data_date LIKE ?", (month + "%",)).fetchall()
    month_sales = round(sum(r["sales"] or 0 for r in month_rows), 2)

    ac = _report_add_cart_refund(db, ts, sf, sp, is_realtime)

    return {
        "date": ts,
        "is_today": is_realtime,
        "today": td,
        "yesterday": yd,
        "last_week": wd,
        "promo_today": {"spend": round(pr["spend"] or 0, 2), "sales": round(pr["sales"] or 0, 2), "roi": round((pr["sales"] or 0) / (pr["spend"] or 0), 2) if pr["spend"] else 0.0},
        "promo_yesterday": {"spend": round(py["spend"] or 0, 2), "sales": round(py["sales"] or 0, 2), "roi": round((py["sales"] or 0) / (py["spend"] or 0), 2) if py["spend"] else 0.0},
        "promo_today_scenes": _report_scenes(db, ts, sf, sp, is_realtime),
        "promo_yesterday_scenes": _report_scenes(db, ys, sf, sp, False),
        "top_today": _report_top_items(db, ts, sf, sp, is_realtime),
        "top_yesterday": _report_top_items(db, ys, sf, sp, False),
        "add_cart": ac["add_cart"],
        "refund_amount": ac["refund_amount"],
        "report_alerts": _report_alerts(db, ts, sf, sp, is_realtime),
        "goal": goal,
        "month_sales": month_sales,
        "month": month,
    }


def _report_text_lines(r: dict) -> list[str]:
    t = r["today"]
    pt = r["promo_today"]
    lines = [f"【经营日报 {r['date']}】"]
    lines.append(
        f"访客 {t['visitors']}｜销售额 ¥{t['sales']:,.0f}｜订单 {t['orders']}｜转化率 {t['conversion_rate']}%"
        f"｜客单价 ¥{t['avg_order_value']:,.0f}"
    )
    if r.get("add_cart"):
        lines.append(f"加购 {r['add_cart']}")
    lines.append(f"推广：花费 ¥{pt['spend']:,.0f}，成交 ¥{pt['sales']:,.0f}，ROI {pt['roi']:.2f}")
    if r["promo_today_scenes"]:
        sc = "；".join(f"{x['scene_name']}花¥{x['spend']:,.0f}/ROI{x['roi']:.2f}" for x in r["promo_today_scenes"])
        lines.append("分场景：" + sc)
    if r["top_today"]:
        top = "、".join(f"{x['item_title'][:14]}¥{x['sales']:,.0f}" for x in r["top_today"][:3])
        lines.append("TOP商品：" + top)
    return lines


@router.get("/report/text")
def report_text(
    date: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """经营日报纯文本（供复制/推送）。"""
    report = daily_report(date=date, store_id=store_id, user=user, db=db)
    return {"text": "\n".join(_report_text_lines(report)), "date": report["date"]}


@router.post("/report/ai")
def report_ai(
    date: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """AI 生成今日经营总结（可复制发群）。"""
    from backend.app.api.model_configs import get_default_config
    from backend.app.core.ai_client import AIError, chat_completion

    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    report = daily_report(date=date, store_id=store_id, user=user, db=db)
    context = "\n".join(_report_text_lines(report))
    prompt = (
        "你是淘宝店铺的运营分析师。根据下面这份经营日报（默认是昨日数据），写一段120字以内的日报总结，口语化、适合直接发到工作群。"
        "包含：整体表现一句话、今天最值得注意的亮点或问题、一句明天建议。不要编造数据。\n\n" + context
    )
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": prompt}], timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"reply": reply, "date": report["date"], "report": report}


def _report_push_config(db) -> dict:
    default = {"enabled": False, "webhook": "", "hour": 9, "minute": 0}
    row = db.execute("SELECT value FROM meta WHERE key = 'daily_report_push'").fetchone()
    if row and row["value"]:
        try:
            data = _json.loads(row["value"])
            for k in default:
                if k in data and isinstance(data[k], (int, float, str, bool)):
                    default[k] = data[k]
        except (ValueError, TypeError):
            pass
    return default


class ReportPushIn(BaseModel):
    enabled: bool = False
    webhook: str = ""
    hour: int = 21
    minute: int = 0


@router.get("/report/push-config")
def get_push_config(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    return _report_push_config(db)


@router.put("/report/push-config")
def set_push_config(
    body: ReportPushIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = {
        "enabled": bool(body.enabled),
        "webhook": (body.webhook or "").strip(),
        "hour": max(0, min(23, int(body.hour))),
        "minute": max(0, min(59, int(body.minute))),
    }
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('daily_report_push', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_json.dumps(cfg, ensure_ascii=False),),
    )
    return {"ok": True, **cfg}


def send_report_webhook(webhook: str, text: str) -> None:
    """推送日报文本到群机器人（钉钉/企业微信 通用格式）。"""
    import urllib.request

    body = _json.dumps({"msgtype": "text", "text": {"content": text}}).encode("utf-8")
    req = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


@router.post("/report/push")
def push_report_now(
    date: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """手动触发一次日报推送（测试）。"""
    cfg = _report_push_config(db)
    if not cfg["webhook"]:
        raise HTTPException(status_code=400, detail="还没有配置推送 webhook，请先到「推送设置」填写")
    report = daily_report(date=date, store_id=store_id, user=user, db=db)
    text = "\n".join(_report_text_lines(report))
    try:
        send_report_webhook(cfg["webhook"], text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"推送失败：{exc}") from exc
    return {"ok": True}


def _build_analysis_context(r: dict) -> str:
    t, y = r["today"], r["yesterday"]
    pt, py = r["promo_today"], r["promo_yesterday"]
    real_roi = t["sales"] / pt["spend"] if pt["spend"] else 0.0
    prev_real_roi = y["sales"] / py["spend"] if py["spend"] else 0.0
    lines = [
        f"日期：{r['date']}",
        f"访客 {t['visitors']}（前日 {y['visitors']}）｜销售额 ¥{t['sales']:,.0f}（前日 ¥{y['sales']:,.0f}）｜订单 {t['orders']}｜转化率 {t['conversion_rate']}%｜客单价 ¥{t['avg_order_value']:,.0f}｜真实ROI {real_roi:.2f}（前日 {prev_real_roi:.2f}）",
    ]
    if r.get("add_cart"):
        lines.append(f"加购 {r['add_cart']} 次")
    lines.append(f"推广：花费 ¥{pt['spend']:,.0f}，成交 ¥{pt['sales']:,.0f}，推广ROI {pt['roi']:.2f}，真实ROI {real_roi:.2f}")
    for x in r["promo_today_scenes"]:
        lines.append(f"场景 {x['scene_name']}：花费 ¥{x['spend']:,.0f}，成交 ¥{x['sales']:,.0f}，ROI {x['roi']:.2f}")
    if r["top_today"]:
        lines.append("TOP商品：" + "；".join(f"{x['item_title'][:14]} ¥{x['sales']:,.0f}" for x in r["top_today"][:3]))
    if r["report_alerts"]:
        lines.append("异常：" + "；".join(a["message"] for a in r["report_alerts"]))
    return "\n".join(lines)


_ANALYSIS_KEYS = ["经营分析", "推广分析", "异常分析", "总结", "今日行动建议"]


def _parse_analysis_sections(reply: str) -> dict:
    import re as _re

    sections = {k: "" for k in _ANALYSIS_KEYS}
    matches = list(_re.finditer(r"【(.+?)】", reply))
    for i, m in enumerate(matches):
        key = m.group(1)
        if key in sections:
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(reply)
            sections[key] = reply[start:end].strip()
    return sections


@router.post("/report/analysis")
def report_analysis(
    date: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """AI 详细经营分析：经营分析/推广分析/异常分析/总结/今日行动建议。"""
    from backend.app.api.model_configs import get_default_config
    from backend.app.core.ai_client import AIError, chat_completion

    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    report = daily_report(date=date, store_id=store_id, user=user, db=db)
    context = _build_analysis_context(report)
    prompt = (
        "你是淘宝店铺的资深运营专家。基于下面这份昨日真实经营数据，输出一份详细的经营分析报告。"
        "严格按格式，每部分独占一段，条目用“- ”开头，务实用数据说话、可执行，不要编造：\n"
        "【经营分析】2-4句话：整体经营状况（销售额、访客、转化、客单价、真实ROI 及环比），指出趋势和问题\n"
        "【推广分析】2-4句话：付费推广表现（总花费/成交/ROI/真实ROI、各场景优劣、哪些场景在浪费钱、推广ROI与真实ROI的差异）\n"
        "【异常分析】逐条列出数据里的异常（商品骤降、ROI偏低计划、转化异常等），说明可能影响\n"
        "【总结】2-3句话：今天整体状况一句话总结\n"
        "【今日行动建议】3-5条具体可执行的建议（调预算、停投/加投场景、优化哪些商品、补货/定价等），落到具体场景或商品\n\n"
        + context
    )
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": prompt}], timeout=180.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"sections": _parse_analysis_sections(reply), "reply": reply, "date": report["date"]}


@router.get("/export")
def export_analytics(
    days: int = 14,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> StreamingResponse:
    if not (1 <= days <= 90):
        days = 14
    start, today = _date_range(days)
    linkage = analytics_linkage(days=days, user=user, db=db)
    wb = Workbook()
    ws = wb.active
    ws.title = "经营数据"
    ws.append(["日期", "总销售额", "总访客", "总订单", "推广花费", "推广成交", "推广ROI", "广告成交占比", "整体ROI", "自然销售额"])
    for item in linkage["items"]:
        ws.append(
            [
                item["date"],
                item["total_sales"],
                item["total_visitors"],
                item["total_orders"],
                item["promo_spend"],
                item["promo_sales"],
                item["promo_roi"],
                f"{item['ad_share']}%",
                item["overall_roi"],
                item["natural_sales"],
            ]
        )
    widths = [12, 12, 10, 10, 12, 12, 10, 14, 10, 12]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + idx)].width = width
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"经营数据_{today.strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


# ---------- 健康分 ----------

@router.get("/health")
def analytics_health(
    days: int = 14,
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not (1 <= days <= 90):
        days = 14
    start, today = _date_range(days)
    sf, sp = _store_filter(store_id)
    rows = db.execute(
        "SELECT * FROM store_daily_data WHERE data_date >= ? AND data_date <= ?" + sf + " ORDER BY data_date",
        [start.isoformat(), today.isoformat()] + sp,
    ).fetchall()
    if not rows:
        return {"score": 0, "items": [], "days": days}

    def agg(rs):
        s = _sum_rows(rs)
        if len(rs) == 1 and rs[0]["conversion_rate"]:
            s["conversion_rate"] = round(rs[0]["conversion_rate"], 2)
        return s

    today_s = agg([r for r in rows if r["data_date"] == today.isoformat()])
    prev_rows = [r for r in rows if r["data_date"] != today.isoformat()]
    base = agg(prev_rows) if prev_rows else None

    items = []
    # 1) 销售额趋势
    if base and base["sales"]:
        chg = (today_s["sales"] - base["sales"]) / base["sales"] * 100
    else:
        chg = 0.0
    score = min(max(50 + chg * 2, 0), 100)
    items.append({"key": "sales", "name": "销售额", "score": round(score), "detail": f"今日 ¥{today_s['sales']:.2f}" + (f"，较前日均值 {chg:+.1f}%" if base and base["sales"] else "，暂无对比基准")})

    # 2) 转化率
    if base and base["conversion_rate"]:
        chg = today_s["conversion_rate"] - base["conversion_rate"]
    else:
        chg = 0.0
    score = min(max(60 + chg * 5, 0), 100)
    items.append({"key": "conv", "name": "转化率", "score": round(score), "detail": f"今日 {today_s['conversion_rate']:.2f}%" + (f"，较前日均值 {chg:+.2f} 个百分点" if base else "")})

    # 3) 访客
    if base and base["visitors"]:
        chg = (today_s["visitors"] - base["visitors"]) / base["visitors"] * 100
    else:
        chg = 0.0
    score = min(max(50 + chg, 0), 100)
    items.append({"key": "uv", "name": "访客", "score": round(score), "detail": f"今日 {today_s['visitors']}" + (f"，较前日均值 {chg:+.1f}%" if base and base["visitors"] else "")})

    # 4) 推广 ROI（区间平均）
    promo_rows = db.execute(
        "SELECT * FROM promo_daily_data WHERE data_date >= ? AND data_date <= ?",
        (start.isoformat(), today.isoformat()),
    ).fetchall()
    pspend = sum(r["spend"] or 0 for r in promo_rows)
    psales = sum(r["sales"] or 0 for r in promo_rows)
    roi = psales / pspend if pspend else 0.0
    score = min(max(roi / 2.0 * 100, 0), 100) if pspend else 0
    items.append({"key": "roi", "name": "推广 ROI", "score": round(score), "detail": f"区间 ROI {roi:.2f}" + ("（目标 2.0）" if pspend else "，暂无推广数据")})

    total = sum(i["score"] for i in items) / len(items)
    return {"score": round(total), "items": items, "days": days}


# ---------- AI 解读 ----------

def _pct_chg(cur: float, prev: float) -> float | None:
    return round((cur - prev) / prev * 100, 1) if prev else None


def _insight_sum(db, sf, sp, start: date_cls, end: date_cls) -> dict:
    """某时间段内销售汇总（全部店铺或单店）。"""
    rows = db.execute(
        "SELECT * FROM store_daily_data WHERE data_date >= ? AND data_date <= ?" + sf,
        [start.isoformat(), end.isoformat()] + sp,
    ).fetchall()
    s = _sum_rows(rows)
    if len(rows) == 1 and rows[0]["conversion_rate"]:
        s["conversion_rate"] = round(rows[0]["conversion_rate"], 2)
    return s


def _insight_promo(db, sf, sp, start: date_cls, end: date_cls) -> dict:
    """某时间段内推广汇总（万相台按天数据）。"""
    row = db.execute(
        "SELECT COALESCE(SUM(spend),0) AS spend, COALESCE(SUM(sales),0) AS sales "
        "FROM promo_daily_data WHERE data_date >= ? AND data_date <= ?" + sf,
        [start.isoformat(), end.isoformat()] + sp,
    ).fetchone()
    spend = round(row["spend"] or 0, 2)
    sales = round(row["sales"] or 0, 2)
    return {"spend": spend, "sales": sales, "roi": round(sales / spend, 2) if spend else 0.0}


def _insight_peak(db, sf, sp, start: date_cls, end: date_cls) -> list[dict]:
    """统计区间内销售额最高的 2 个时段。"""
    rows = db.execute(
        "SELECT hour, SUM(sales) AS sales FROM store_hourly_data "
        "WHERE data_date >= ? AND data_date <= ?" + sf + " GROUP BY hour ORDER BY sales DESC LIMIT 2",
        [start.isoformat(), end.isoformat()] + sp,
    ).fetchall()
    return [{"hour": r["hour"], "sales": round(r["sales"] or 0, 2)} for r in rows]


def _collect_insight(mode: str, store_id: int | None, db) -> dict:
    """按模式汇总 AI 解读所需数据：销售额、推广、趋势、TOP商品、高峰时段、异常。"""
    today = date_cls.today()
    sf, sp = _store_filter(store_id)
    anomalies: list[str] = []
    if mode == "realtime":
        ts = today.isoformat()
        cur = _insight_sum(db, sf, sp, today, today)
        if not cur["sales"] and not cur["visitors"]:
            hrows = db.execute(
                "SELECT visitors, pv, sales, orders FROM store_hourly_data WHERE data_date = ?" + sf,
                [ts] + sp,
            ).fetchall()
            cur = _sum_rows(hrows)
        prev = _insight_sum(db, sf, sp, today - timedelta(days=1), today - timedelta(days=1))
        pr = db.execute(
            "SELECT COALESCE(SUM(spend),0) AS spend, COALESCE(SUM(sales),0) AS sales "
            "FROM promo_realtime WHERE data_date = ?" + sf,
            [ts] + sp,
        ).fetchone()
        promo = {"spend": round(pr["spend"] or 0, 2), "sales": round(pr["sales"] or 0, 2)}
        promo["roi"] = round(promo["sales"] / promo["spend"], 2) if promo["spend"] else 0.0
        promo_prev = _insight_promo(db, sf, sp, today - timedelta(days=1), today - timedelta(days=1))
        prods = db.execute(
            "SELECT item_title, sales FROM store_item_realtime WHERE 1=1" + sf + " ORDER BY sales DESC LIMIT 3",
            sp,
        ).fetchall()
        top_products = [{"item_title": r["item_title"], "sales": round(r["sales"] or 0, 2)} for r in prods]
        peak = _insight_peak(db, sf, sp, today, today)
        trend = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            s = _insight_sum(db, sf, sp, d, d)
            trend.append(f"{d.strftime('%m-%d')}:¥{s['sales']:.0f}")
        range_label = f"今日实时（{ts[5:]}）"
    else:
        if mode == "yesterday":
            end = today - timedelta(days=1)
            days = 1
        else:
            try:
                days = int(mode)
            except (TypeError, ValueError):
                days = 14
            if not (1 <= days <= 90):
                days = 14
            end = today
        start = end - timedelta(days=days - 1)
        cur = _insight_sum(db, sf, sp, start, end)
        prev = _insight_sum(db, sf, sp, start - timedelta(days=days), end - timedelta(days=days))
        promo = _insight_promo(db, sf, sp, start, end)
        promo_prev = _insight_promo(db, sf, sp, start - timedelta(days=days), end - timedelta(days=days))
        prods = db.execute(
            "SELECT item_title, SUM(sales) AS sales FROM store_item_daily "
            "WHERE data_date >= ? AND data_date <= ?" + sf + " GROUP BY item_id ORDER BY sales DESC LIMIT 3",
            [start.isoformat(), end.isoformat()] + sp,
        ).fetchall()
        top_products = [{"item_title": r["item_title"], "sales": round(r["sales"] or 0, 2)} for r in prods]
        peak = _insight_peak(db, sf, sp, start, end)
        n = min(days, 7)
        trend = []
        for i in range(n - 1, -1, -1):
            d = end - timedelta(days=i)
            s = _insight_sum(db, sf, sp, d, d)
            trend.append(f"{d.strftime('%m-%d')}:¥{s['sales']:.0f}")
        range_label = f"近 {days} 天（{start.strftime('%m-%d')}~{end.strftime('%m-%d')}）" if days > 1 else f"昨日（{end.strftime('%m-%d')}）"
        try:
            alerts = analytics_alerts(days=30, store_id=store_id, user=None, db=db)
            anomalies = [a["message"] for a in alerts["items"][:3]]
        except Exception:  # noqa: BLE001
            anomalies = []
    ad_share = round(min(promo["sales"] / cur["sales"] * 100, 100.0), 1) if cur["sales"] else 0.0
    if mode == "realtime":
        scene_rows = db.execute(
            "SELECT scene, scene_name, SUM(spend) AS spend, SUM(sales) AS sales FROM promo_realtime "
            "WHERE data_date = ?" + sf + " GROUP BY scene ORDER BY spend DESC",
            [ts] + sp,
        ).fetchall()
    else:
        scene_rows = db.execute(
            "SELECT scene, scene_name, SUM(spend) AS spend, SUM(sales) AS sales FROM promo_daily_data "
            "WHERE data_date >= ? AND data_date <= ?" + sf + " GROUP BY scene ORDER BY spend DESC",
            [start.isoformat(), end.isoformat()] + sp,
        ).fetchall()
    promo_scenes = []
    for r in scene_rows:
        spend = round(r["spend"] or 0, 2)
        sales = round(r["sales"] or 0, 2)
        promo_scenes.append(
            {
                "scene": r["scene"],
                "scene_name": r["scene_name"] or r["scene"],
                "spend": spend,
                "sales": sales,
                "roi": round(sales / spend, 2) if spend else 0.0,
            }
        )
    avg_order_value = round(cur["sales"] / cur["orders"], 2) if cur["orders"] else 0.0
    value_per_visitor = round(cur["sales"] / cur["visitors"], 2) if cur["visitors"] else 0.0
    return {
        "range_label": range_label,
        "cur": cur,
        "prev": prev,
        "avg_order_value": avg_order_value,
        "value_per_visitor": value_per_visitor,
        "promo_scenes": promo_scenes,
        "chg": {
            "sales": _pct_chg(cur["sales"], prev["sales"]),
            "orders": _pct_chg(cur["orders"], prev["orders"]),
            "visitors": _pct_chg(cur["visitors"], prev["visitors"]),
            "conversion": round(cur["conversion_rate"] - prev["conversion_rate"], 2) if prev["conversion_rate"] else None,
        },
        "promo": {**promo, "ad_share": ad_share},
        "promo_chg": {
            "spend": _pct_chg(promo["spend"], promo_prev["spend"]),
            "roi": round(promo["roi"] - promo_prev["roi"], 2) if promo_prev["spend"] else None,
        },
        "trend": trend,
        "top_products": top_products,
        "peak": peak,
        "anomalies": anomalies,
    }


def _data_lines(d: dict) -> list[str]:
    """把采集到的经营数据整理成给模型看的数据行（解读与追问共用）。"""
    cur = d["cur"]
    chg = d["chg"]
    promo = d["promo"]
    pchg = d["promo_chg"]
    fmt_pct = lambda x: f"{x:+.1f}%" if x is not None else "—"
    fmt_pp = lambda x: f"{x:+.2f} 个百分点" if x is not None else "—"
    lines = [
        f"数据范围：{d['range_label']}",
        (
            f"销售额 {cur['sales']:.0f} 元（环比 {fmt_pct(chg['sales'])}），订单 {cur['orders']}（环比 {fmt_pct(chg['orders'])}），"
            f"访客 {cur['visitors']}（环比 {fmt_pct(chg['visitors'])}），转化率 {cur['conversion_rate']}%（较上期 {fmt_pp(chg['conversion'])}）"
        ),
        (
            f"推广花费 {promo['spend']:.0f} 元（环比 {fmt_pct(pchg['spend'])}），推广成交 {promo['sales']:.0f} 元，"
            f"推广ROI {promo['roi']}（较上期 {fmt_pp(pchg['roi'])}），广告成交占比 {promo['ad_share']}%"
        ),
    ]
    if d.get("avg_order_value") is not None:
        lines.append(f"客单价 {d['avg_order_value']:.2f} 元，单访客价值 {d['value_per_visitor']:.2f} 元")
    if d.get("promo_scenes"):
        lines.append("推广分场景：" + "、".join(f"{s['scene_name']}花费{s['spend']:.0f}元成交{s['sales']:.0f}元ROI{s['roi']}" for s in d["promo_scenes"]))
    if d["trend"]:
        lines.append("逐日销售额：" + "、".join(d["trend"]))
    if d["top_products"]:
        lines.append("TOP商品：" + "；".join(f"{p['item_title'][:24]} ¥{p['sales']:.0f}" for p in d["top_products"]))
    if d["peak"]:
        lines.append("高峰时段：" + "、".join(f"{p['hour']}（¥{p['sales']:.0f}）" for p in d["peak"]))
    if d["anomalies"]:
        lines.append("异常提醒：" + "；".join(d["anomalies"]))
    if any(x.endswith(":¥0") for x in d["trend"]):
        lines.append("注：部分日期销售额为0可能是数据未同步，解读时以有数据的日期为准，不要解读为经营异常。")
    return lines


def _build_insight_prompt(d: dict) -> str:
    prompt = (
        "你是淘宝店铺的运营数据分析师。请根据下面数据输出详细经营解读，严格按格式，每部分独占一段，条目用“- ”开头：\n"
        "【整体表现】2-3句话概括本期经营（含销售额、订单、访客、转化率、推广ROI关键数字，并说明同比/环比趋势）\n"
        "【亮点】\n- 销售/流量/转化/推广方面的亮点（3-4条，确实没有就写“本期暂无突出亮点”）\n"
        "【推广表现】\n- 分场景说明投放效果，点出ROI高/低的场景与原因（2-3条）\n"
        "【风险】\n- 数据异常、低效投放、转化下滑等（3条，没有就写“暂无明显风险”）\n"
        "【建议】\n- 具体可执行的运营/投放建议（4-5条，明确到动作或时段）\n"
        "简体中文务实，金额≥1万用X.X万简化；只依据给定数据，不要编造。\n\n"
        + "\n".join(_data_lines(d))
    )
    return prompt


def _parse_insight_sections(reply: str) -> dict:
    """解析【...】标记输出为结构化 sections（支持 5 段时段解读与通用 4 段）。"""
    import re as _re
    sections = {"overall": "", "highlights": [], "conversion": [], "promo": [], "risks": [], "suggestions": []}
    key_map = {
        "整体表现": "overall",
        "销售时段规律": "highlights",
        "亮点": "highlights",
        "流量与转化": "conversion",
        "推广表现": "promo",
        "风险提醒": "risks",
        "风险": "risks",
        "投放建议": "suggestions",
        "建议": "suggestions",
    }
    found = False
    for m in _re.finditer(r"【([^】]+)】\s*(.*?)(?=【[^】]+】|$)", reply, _re.S):
        title = m.group(1).strip()
        key = key_map.get(title)
        if key is None:
            continue
        found = True
        body = m.group(2).strip()
        if key == "overall":
            sections[key] = _re.sub(r"\s+", " ", body).strip()
        else:
            items = []
            for line in body.splitlines():
                line = line.strip()
                if not line:
                    continue
                line = _re.sub(r"^[-•*]\s*", "", line)
                line = _re.sub(r"^\d+[.、)]\s*", "", line)
                if line:
                    items.append(line)
            if not items and body:
                items = [_re.sub(r"^[-•*]\s*", "", body)]
            sections[key] = items[:4]
    if not found:
        sections["overall"] = _re.sub(r"\s+", " ", reply).strip()
    return sections


def _insight_metrics(d: dict) -> list[dict]:
    chg = d["chg"]
    promo = d["promo"]
    pchg = d["promo_chg"]
    return [
        {"label": "销售额", "value": f"¥{d['cur']['sales']:,.0f}", "change": chg["sales"], "unit": "%"},
        {"label": "订单", "value": f"{d['cur']['orders']}", "change": chg["orders"], "unit": "%"},
        {"label": "访客", "value": f"{d['cur']['visitors']}", "change": chg["visitors"], "unit": "%"},
        {"label": "转化率", "value": f"{d['cur']['conversion_rate']}%", "change": chg["conversion"], "unit": "pp"},
        {"label": "推广花费", "value": f"¥{promo['spend']:,.0f}", "change": pchg["spend"], "unit": "%"},
        {"label": "推广ROI", "value": f"{promo['roi']}", "change": pchg["roi"], "unit": "val"},
    ]


@router.post("/insight")
def ai_insight(
    mode: str = "14",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    data = _collect_insight(mode, store_id, db)
    prompt = _build_insight_prompt(data)
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": prompt}], timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "sections": _parse_insight_sections(reply),
        "reply": reply,
        "metrics": _insight_metrics(data),
        "range": data["range_label"],
        "date": date_cls.today().isoformat(),
    }

class InsightMsgIn(BaseModel):
    role: str
    content: str


class InsightChatIn(BaseModel):
    mode: str = "14"
    store_id: int | None = None
    messages: list[InsightMsgIn] = []


@router.post("/insight/chat")
def ai_insight_chat(
    body: InsightChatIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    data = _collect_insight(body.mode, body.store_id, db)
    context = (
        "你是淘宝店铺的运营数据分析师。以下是当前数据上下文：\n"
        + "\n".join(_data_lines(data))
        + "\n用户会围绕这份数据追问，请结合数据回答，简洁务实，不要编造；数据里没有的信息要如实说明。"
    )
    msgs: list[dict] = [{"role": "system", "content": context}]
    for m in body.messages[-12:]:
        if m.role in ("user", "assistant") and (m.content or "").strip():
            msgs.append({"role": m.role, "content": m.content})
    try:
        reply = chat_completion(cfg, msgs, timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"reply": reply}


def _sum_product_rows(rows) -> dict:
    """商品每日明细汇总（销售额/订单/买家/访客/浏览/转化/加购/退款）。"""
    sales = 0.0
    orders = 0
    buyers = 0
    visitors = 0
    pv = 0
    add_cart = 0
    refund = 0.0
    for r in rows:
        sales += r["sales"] or 0
        orders += r["orders"] or 0
        buyers += r["buyers"] or 0
        visitors += r["visitors"] or 0
        pv += r["pv"] or 0
        add_cart += r["add_cart"] or 0
        refund += r["refund_amount"] or 0
    return {
        "sales": round(sales, 2),
        "orders": orders,
        "buyers": buyers,
        "visitors": visitors,
        "pv": pv,
        "conversion_rate": round(buyers / visitors * 100, 2) if visitors else 0.0,
        "add_cart": add_cart,
        "refund_amount": round(refund, 2),
    }


def _product_rank_realtime(item_id: str, store_id: int | None, db) -> tuple[int, float, float]:
    """商品在店铺实时榜中的排名、销售占比与全店实时销售额。"""
    sf, sp = _store_filter(store_id)
    rows = db.execute("SELECT item_id, sales FROM store_item_realtime WHERE 1=1" + sf, sp).fetchall()
    items = sorted(rows, key=lambda r: r["sales"] or 0, reverse=True)
    store_total = sum(r["sales"] or 0 for r in items)
    rank = None
    sales = 0.0
    for i, r in enumerate(items):
        if r["item_id"] == item_id:
            rank = i + 1
            sales = r["sales"] or 0
            break
    share = round(sales / store_total * 100, 1) if store_total else 0.0
    return (rank or len(items) + 1), share, round(store_total, 2)


def _product_rank_days(item_id: str, store_id: int | None, days: int, db) -> tuple[int, float, float]:
    """商品在店铺区间销售榜中的排名、占比与全店区间销售额。"""
    sf, sp = _store_filter(store_id)
    today = date_cls.today()
    start = today - timedelta(days=days - 1)
    rows = db.execute(
        "SELECT item_id, SUM(sales) AS sales FROM store_item_daily "
        "WHERE data_date >= ? AND data_date <= ?" + sf + " GROUP BY item_id",
        [start.isoformat(), today.isoformat()] + sp,
    ).fetchall()
    items = sorted(rows, key=lambda r: r["sales"] or 0, reverse=True)
    store_total = sum(r["sales"] or 0 for r in items)
    rank = None
    sales = 0.0
    for i, r in enumerate(items):
        if r["item_id"] == item_id:
            rank = i + 1
            sales = r["sales"] or 0
            break
    share = round(sales / store_total * 100, 1) if store_total else 0.0
    return (rank or len(items) + 1), share, round(store_total, 2)


def _product_trend_daily(item_id: str, store_id: int | None, days: int, db) -> list[str]:
    """商品近 N 天逐日销售额（最多 7 个点）。"""
    sf, sp = _store_filter(store_id)
    today = date_cls.today()
    start = today - timedelta(days=days - 1)
    rows = db.execute(
        "SELECT data_date, sales FROM store_item_daily WHERE item_id = ? AND data_date >= ?" + sf + " ORDER BY data_date",
        [item_id, start.isoformat()] + sp,
    ).fetchall()
    return [f"{r['data_date'][5:]}:¥{r['sales'] or 0:.0f}" for r in rows[-7:]]


def _collect_product_data(item_id: str, store_id: int | None, mode: str, db, start: str = "", end: str = "") -> dict:
    """按模式汇总单个商品的诊断数据。"""
    today = date_cls.today()
    ts = today.isoformat()
    sf, sp = _store_filter(store_id)
    rt = db.execute("SELECT * FROM store_item_realtime WHERE item_id = ?" + sf, [item_id] + sp).fetchone()
    title = (rt["item_title"] or "") if rt else ""
    image = (rt["image"] or "") if rt else ""

    if mode == "realtime":
        if rt:
            cur = {
                "sales": round(rt["sales"] or 0, 2),
                "orders": rt["orders"] or 0,
                "buyers": rt["buyers"] or 0,
                "visitors": rt["visitors"] or 0,
                "pv": rt["pv"] or 0,
                "conversion_rate": round(rt["conversion_rate"] or 0, 2),
                "add_cart": rt["add_cart"] or 0,
                "refund_amount": round(rt["refund_amount"] or 0, 2),
            }
            chg = {
                "sales": round(rt["sales_cycle"] or 0, 1) if rt["sales_cycle"] is not None else None,
                "orders": round(rt["orders_cycle"] or 0, 1) if rt["orders_cycle"] is not None else None,
                "visitors": round(rt["visitors_cycle"] or 0, 1) if rt["visitors_cycle"] is not None else None,
                "conversion": round(rt["conversion_cycle"] or 0, 2) if rt["conversion_cycle"] is not None else None,
                "add_cart": round(rt["add_cart_cycle"] or 0, 1) if rt["add_cart_cycle"] is not None else None,
            }
        else:
            cur = {"sales": 0.0, "orders": 0, "buyers": 0, "visitors": 0, "pv": 0, "conversion_rate": 0.0, "add_cart": 0, "refund_amount": 0.0}
            chg = {"sales": None, "orders": None, "visitors": None, "conversion": None, "add_cart": None}
        rank, share, store_total = _product_rank_realtime(item_id, store_id, db)
        range_label = f"今日实时（{ts[5:]}）"
        trend = _product_trend_daily(item_id, store_id, 7, db)
    else:
        if start and end:
            try:
                s = date_cls.fromisoformat(start)
                e = date_cls.fromisoformat(end)
            except ValueError:
                s = e = None
            if not (s and e and s <= e):
                s, e = _date_range(int(mode) if str(mode).isdigit() else 14)
        else:
            try:
                days = int(mode)
            except (TypeError, ValueError):
                days = 14
            if not (1 <= days <= 90):
                days = 14
            e = today
            s = today - timedelta(days=days - 1)
        prev_end = s - timedelta(days=1)
        prev_start = prev_end - timedelta(days=(e - s).days)
        rows = db.execute(
            "SELECT * FROM store_item_daily WHERE item_id = ? AND data_date >= ? AND data_date <= ?" + sf + " ORDER BY data_date",
            [item_id, s.isoformat(), e.isoformat()] + sp,
        ).fetchall()
        prev_rows = db.execute(
            "SELECT * FROM store_item_daily WHERE item_id = ? AND data_date >= ? AND data_date <= ?" + sf,
            [item_id, prev_start.isoformat(), prev_end.isoformat()] + sp,
        ).fetchall()
        cur = _sum_product_rows(rows)
        prev = _sum_product_rows(prev_rows)
        if rows and not title:
            title = rows[-1]["item_title"] or ""
        prev_active_days = sum(1 for r in prev_rows if (r["sales"] or 0) > 0)
        if prev_active_days < 2:
            chg = {"sales": None, "orders": None, "visitors": None, "conversion": None, "add_cart": None}
        else:
            chg = {
                "sales": _pct_chg(cur["sales"], prev["sales"]),
                "orders": _pct_chg(cur["orders"], prev["orders"]),
                "visitors": _pct_chg(cur["visitors"], prev["visitors"]),
                "conversion": round(cur["conversion_rate"] - prev["conversion_rate"], 2) if prev["visitors"] else None,
                "add_cart": _pct_chg(cur["add_cart"], prev["add_cart"]),
            }
        if start and end:
            rank, share, store_total = _product_rank_range(item_id, store_id, s, e, db)
            range_label = f"{s.strftime('%m-%d')} ~ {e.strftime('%m-%d')}"
        else:
            rank, share, store_total = _product_rank_days(item_id, store_id, days, db)
            range_label = f"近 {days} 天（{s.strftime('%m-%d')}~{e.strftime('%m-%d')}）"
        trend = [f"{r['data_date'][5:]}:¥{r['sales'] or 0:.0f}" for r in rows[-7:]]

    if mode == "realtime":
        promo_mode = "realtime"
    elif mode == "yesterday":
        promo_mode = "yesterday"
    else:
        promo_mode = _range_promo_mode(s, e)
    prow = db.execute(
        "SELECT * FROM promo_item_stats WHERE item_id = ? AND mode = ?" + sf,
        [item_id, promo_mode] + sp,
    ).fetchone()
    promo = (
        {
            "spend": round(prow["spend"] or 0, 2),
            "sales": round(prow["sales"] or 0, 2),
            "roi": round(prow["roi"] or 0, 2),
            "clicks": int(prow["clicks"] or 0),
        }
        if prow
        else None
    )
    return {
        "item_id": item_id,
        "title": title or item_id,
        "image": image,
        "range_label": range_label,
        "cur": cur,
        "chg": chg,
        "trend": trend,
        "rank": rank,
        "share": share,
        "store_total_sales": store_total,
        "promo": promo,
    }


def _product_data_lines(d: dict) -> list[str]:
    """单品诊断数据行（解读与追问共用）。"""
    cur = d["cur"]
    chg = d["chg"]
    fmt_pct = lambda x: f"{x:+.1f}%" if x is not None else "—"
    fmt_pp = lambda x: f"{x:+.2f} 个百分点" if x is not None else "—"
    lines = [
        f"商品：{d['title']}（ID {d['item_id']}）",
        f"数据范围：{d['range_label']}",
        (
            f"销售额 {cur['sales']:.0f} 元（环比 {fmt_pct(chg['sales'])}），订单 {cur['orders']}（环比 {fmt_pct(chg['orders'])}），"
            f"访客 {cur['visitors']}（环比 {fmt_pct(chg['visitors'])}），转化率 {cur['conversion_rate']}%（较上期 {fmt_pp(chg['conversion'])}），"
            f"加购 {cur['add_cart']}（环比 {fmt_pct(chg['add_cart'])}），退款 {cur['refund_amount']:.0f} 元"
        ),
        f"店铺内排名第 {d['rank']} 名，占全店销售额 {d['share']}%（全店同期销售额 {d['store_total_sales']:.0f} 元）",
    ]
    if d.get("promo"):
        promo = d["promo"]
        share = round(min(promo["sales"] / (d["cur"]["sales"] or 1) * 100, 100.0), 1)
        lines.append(f"推广：花费 {promo['spend']:.0f} 元，广告成交 {promo['sales']:.0f} 元，推广ROI {promo['roi']}，广告成交占该商品销售额 {share}%")
    if d["trend"]:
        lines.append("逐日销售额：" + "、".join(d["trend"]))
    return lines


def _build_product_prompt(d: dict) -> str:
    prompt = (
        "你是淘宝店铺的运营数据分析师。请针对下面这个单品输出诊断，要求严格按以下格式：\n"
        "【整体表现】一句话概括该商品本期表现并给出关键数字（销售额、订单、转化率）。\n"
        "【亮点】\n- 亮点1\n- 亮点2\n- 亮点3（最多3条，确实没有就写“本期暂无突出亮点”）\n"
        "【风险】\n- 风险1\n- 风险2（最多2条，没有就写“暂无明显风险”）\n"
        "【建议】\n- 建议1\n- 建议2\n- 建议3（最多3条，具体可执行，可从标题/主图/价格/加购催付/退款处理等方向给）\n"
        "简体中文、语气务实，不客套；金额≥1万用“X.X万”简化；只依据给定数据，不要编造。\n\n"
        + "\n".join(_product_data_lines(d))
    )
    return prompt


def _product_metrics(d: dict) -> list[dict]:
    cur = d["cur"]
    chg = d["chg"]
    metrics = [
        {"label": "销售额", "value": f"¥{cur['sales']:,.0f}", "change": chg["sales"], "unit": "%"},
        {"label": "订单", "value": f"{cur['orders']}", "change": chg["orders"], "unit": "%"},
        {"label": "转化率", "value": f"{cur['conversion_rate']}%", "change": chg["conversion"], "unit": "pp"},
        {"label": "加购", "value": f"{cur['add_cart']}", "change": chg["add_cart"], "unit": "%"},
        {"label": "退款", "value": f"¥{cur['refund_amount']:,.0f}", "change": None, "unit": "val"},
    ]
    if d.get("promo"):
        promo = d["promo"]
        share = round(min(promo["sales"] / (cur["sales"] or 1) * 100, 100.0), 1)
        metrics.extend(
            [
                {"label": "推广花费", "value": f"¥{promo['spend']:,.0f}", "change": None, "unit": "val"},
                {"label": "推广ROI", "value": f"{promo['roi']}", "change": None, "unit": "val"},
                {"label": "广告占比", "value": f"{share}%", "change": None, "unit": "val"},
            ]
        )
    metrics.append({"label": "店铺排名", "value": f"第{d['rank']}名", "change": None, "unit": "val"})
    return metrics


class ProductMsgIn(BaseModel):
    role: str
    content: str


class ProductChatIn(BaseModel):
    mode: str = "realtime"
    store_id: int | None = None
    messages: list[ProductMsgIn] = []


@router.post("/products/{item_id}/insight")
def product_ai_insight(
    item_id: str,
    mode: str = "realtime",
    store_id: int | None = None,
    start: str = "",
    end: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    data = _collect_product_data(item_id, store_id, mode, db, start=start, end=end)
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": _build_product_prompt(data)}], timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "sections": _parse_insight_sections(reply),
        "reply": reply,
        "metrics": _product_metrics(data),
        "range": data["range_label"],
        "product": {"item_id": data["item_id"], "item_title": data["title"], "image": data["image"]},
        "date": date_cls.today().isoformat(),
    }


@router.post("/products/{item_id}/insight/chat")
def product_ai_insight_chat(
    item_id: str,
    body: ProductChatIn,
    start: str = "",
    end: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    data = _collect_product_data(item_id, body.store_id, body.mode, db, start=start, end=end)
    context = (
        "你是淘宝店铺的运营数据分析师。以下是该商品的数据上下文：\n"
        + "\n".join(_product_data_lines(data))
        + "\n用户会围绕这个商品追问，请结合数据回答，简洁务实，不要编造；数据里没有的信息要如实说明。"
    )
    msgs: list[dict] = [{"role": "system", "content": context}]
    for m in body.messages[-12:]:
        if m.role in ("user", "assistant") and (m.content or "").strip():
            msgs.append({"role": m.role, "content": m.content})
    try:
        reply = chat_completion(cfg, msgs, timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"reply": reply}


# ---------- 通用：单店筛选 ----------

def _store_filter(store_id: int | None) -> tuple[str, list]:
    if store_id:
        return " AND store_id = ?", [store_id]
    return "", []


# ---------- 客群分析（新老客/复购） ----------

HOUR_SEGMENTS = [
    ("凌晨", range(0, 6)),
    ("上午", range(6, 12)),
    ("下午", range(12, 18)),
    ("晚间", range(18, 22)),
    ("深夜", range(22, 24)),
]


def _hours_agg(db, sf, sp, start: date_cls, end: date_cls) -> dict[str, dict]:
    """某日期区间内按小时聚合店铺分时数据。"""
    rows = db.execute(
        "SELECT hour, visitors, pv, sales, orders, buyers FROM store_hourly_data "
        "WHERE data_date >= ? AND data_date <= ?" + sf,
        [start.isoformat(), end.isoformat()] + sp,
    ).fetchall()
    hour_map: dict[str, dict] = {}
    for r in rows:
        item = hour_map.setdefault(
            r["hour"],
            {"hour": r["hour"], "visitors": 0, "pv": 0, "sales": 0.0, "orders": 0, "buyers": 0},
        )
        item["visitors"] += r["visitors"] or 0
        item["pv"] += r["pv"] or 0
        item["sales"] += r["sales"] or 0
        item["orders"] += r["orders"] or 0
        item["buyers"] += r["buyers"] or 0
    return hour_map


def _promo_hours_agg(db, sf, sp, start: date_cls, end: date_cls) -> dict[str, dict]:
    """某日期区间内按小时聚合万相台推广花费/成交。"""
    rows = db.execute(
        "SELECT hour, SUM(spend) AS spend, SUM(sales) AS sales FROM promo_realtime "
        "WHERE data_date >= ? AND data_date <= ?" + sf + " GROUP BY hour",
        [start.isoformat(), end.isoformat()] + sp,
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        out[r["hour"]] = {"spend": round(r["spend"] or 0, 2), "sales": round(r["sales"] or 0, 2)}
    return out


def _resolve_hours_range(date: str, start: str, end: str) -> tuple[date_cls, date_cls]:
    today = date_cls.today()
    if start and end:
        try:
            s = date_cls.fromisoformat(start)
            e = date_cls.fromisoformat(end)
        except ValueError:
            s = e = None
        if not (s and e and s <= e):
            s = e = today
    elif date:
        d = _to_date(date) or today
        s = e = d
    else:
        s = e = today
    return s, e


def _hours_dataset(db, sf, sp, s: date_cls, e: date_cls) -> dict:
    """聚合某日期区间的时段数据：24h指标 + 推广分时 + 环比 + 分段占比 + 按场景。"""
    today = date_cls.today()
    hour_map = _hours_agg(db, sf, sp, s, e)
    promo_map = _promo_hours_agg(db, sf, sp, s, e)
    prev_end = s - timedelta(days=1)
    prev_start = prev_end - timedelta(days=(e - s).days)
    prev_hour_map = _hours_agg(db, sf, sp, prev_start, prev_end)
    prev_promo_map = _promo_hours_agg(db, sf, sp, prev_start, prev_end)

    scene_rows = db.execute(
        "SELECT scene, scene_name, hour, SUM(spend) AS spend, SUM(sales) AS sales FROM promo_realtime "
        "WHERE data_date >= ? AND data_date <= ?" + sf + " GROUP BY scene, hour",
        [s.isoformat(), e.isoformat()] + sp,
    ).fetchall()
    promo_by_scene: dict[str, dict] = {}
    for r in scene_rows:
        sc = promo_by_scene.setdefault(r["scene"], {"scene": r["scene"], "scene_name": r["scene_name"] or r["scene"], "items": {}})
        sc["items"][r["hour"]] = {"spend": round(r["spend"] or 0, 2), "sales": round(r["sales"] or 0, 2)}
    for sc in promo_by_scene.values():
        for h in range(24):
            it = sc["items"].setdefault(f"{h:02d}:00", {"spend": 0.0, "sales": 0.0})
            it["roi"] = round(it["sales"] / it["spend"], 2) if it["spend"] else 0.0

    items: list[dict] = []
    for h in range(24):
        key = f"{h:02d}:00"
        row = hour_map.get(key)
        if row:
            row["conversion_rate"] = round(row["buyers"] / row["visitors"] * 100, 2) if row["visitors"] else 0.0
            row["sales"] = round(row["sales"], 2)
        else:
            row = {"hour": key, "visitors": 0, "pv": 0, "sales": 0.0, "orders": 0, "buyers": 0, "conversion_rate": 0.0}
        p = promo_map.get(key)
        row["promo_spend"] = p["spend"] if p else 0.0
        row["promo_sales"] = p["sales"] if p else 0.0
        row["promo_roi"] = round(p["sales"] / p["spend"], 2) if p and p["spend"] else 0.0
        prev = prev_hour_map.get(key)
        row["visitors_cycle"] = round((row["visitors"] - prev["visitors"]) / prev["visitors"] * 100, 1) if prev and prev["visitors"] else None
        row["sales_cycle"] = round((row["sales"] - prev["sales"]) / prev["sales"] * 100, 1) if prev and prev["sales"] else None
        row["orders_cycle"] = round((row["orders"] - prev["orders"]) / prev["orders"] * 100, 1) if prev and prev["orders"] else None
        row["conversion_cycle"] = round(row["conversion_rate"] - (round(prev["buyers"] / prev["visitors"] * 100, 2) if prev and prev["visitors"] else 0.0), 2) if prev and prev["visitors"] else None
        items.append(row)

    total_visitors = sum(i["visitors"] for i in items)
    total_sales = sum(i["sales"] for i in items)
    summary = {
        "visitors": total_visitors,
        "pv": sum(i["pv"] for i in items),
        "sales": round(total_sales, 2),
        "orders": sum(i["orders"] for i in items),
        "promo_spend": round(sum(i["promo_spend"] for i in items), 2),
        "promo_sales": round(sum(i["promo_sales"] for i in items), 2),
    }
    summary["promo_roi"] = round(summary["promo_sales"] / summary["promo_spend"], 2) if summary["promo_spend"] else 0.0

    def _prev_point(h: int) -> dict:
        key = f"{h:02d}:00"
        pm = prev_hour_map.get(key)
        if not pm:
            return {"hour": key, "visitors": 0, "sales": 0.0, "orders": 0, "conversion_rate": 0.0}
        return {
            "hour": key,
            "visitors": pm["visitors"],
            "sales": pm["sales"],
            "orders": pm["orders"],
            "conversion_rate": round(pm["buyers"] / pm["visitors"] * 100, 2) if pm["visitors"] else 0.0,
        }

    prev_items = [_prev_point(h) for h in range(24)]
    prev_promo_items = [
        {"hour": f"{h:02d}:00", "spend": (prev_promo_map.get(f"{h:02d}:00") or {}).get("spend", 0), "sales": (prev_promo_map.get(f"{h:02d}:00") or {}).get("sales", 0)}
        for h in range(24)
    ]

    segments: list[dict] = []
    for name, hrs in HOUR_SEGMENTS:
        seg = {"name": name, "hours": f"{hrs.start:02d}:00-{hrs.stop - 1:02d}:00", "visitors": 0, "sales": 0.0, "orders": 0, "promo_spend": 0.0, "promo_sales": 0.0}
        for h in hrs:
            it = items[h]
            seg["visitors"] += it["visitors"]
            seg["sales"] += it["sales"]
            seg["orders"] += it["orders"]
            seg["promo_spend"] += it["promo_spend"]
            seg["promo_sales"] += it["promo_sales"]
        seg["sales"] = round(seg["sales"], 2)
        seg["promo_spend"] = round(seg["promo_spend"], 2)
        seg["promo_sales"] = round(seg["promo_sales"], 2)
        seg["promo_roi"] = round(seg["promo_sales"] / seg["promo_spend"], 2) if seg["promo_spend"] else 0.0
        seg["sales_pct"] = round(seg["sales"] / total_sales * 100, 1) if total_sales else 0.0
        seg["visitors_pct"] = round(seg["visitors"] / total_visitors * 100, 1) if total_visitors else 0.0
        segments.append(seg)

    peak = max(items, key=lambda x: x["sales"]) if items else {"hour": "", "sales": 0}
    recommended_hours = [it["hour"] for it in items if it["promo_spend"] > 0 and it["promo_roi"] >= 2]

    if s == e == today:
        label = "今日"
    elif s == e == today - timedelta(days=1):
        label = "昨日"
    else:
        label = f"{s.strftime('%m-%d')} ~ {e.strftime('%m-%d')}"

    return {
        "date": s.isoformat(),
        "start": s.isoformat(),
        "end": e.isoformat(),
        "label": label,
        "items": items,
        "prev_items": prev_items,
        "prev_promo_items": prev_promo_items,
        "summary": summary,
        "segments": segments,
        "promo_by_scene": promo_by_scene,
        "recommended_hours": recommended_hours,
        "peak_hour": peak["hour"],
        "peak_sales": peak["sales"],
    }


@router.get("/hours")
def analytics_hours(
    date: str = "",
    start: str = "",
    end: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """时段分析：支持单日或日期区间，叠加推广分时、环比与时段分组。"""
    s, e = _resolve_hours_range(date, start, end)
    sf, sp = _store_filter(store_id)
    return _hours_dataset(db, sf, sp, s, e)


def _build_hours_prompt(d: dict) -> str:
    summary = d["summary"]
    conv_rate = round(summary["orders"] / max(summary["visitors"], 1) * 100, 2)
    lines = [
        f"数据范围：{d['label']}",
        f"访客 {summary['visitors']}，销售额 {summary['sales']:.0f} 元，订单 {summary['orders']}，转化率 {conv_rate}%，推广花费 {summary['promo_spend']:.0f} 元，推广成交 {summary['promo_sales']:.0f} 元，推广ROI {summary['promo_roi']}",
        "逐小时(访客/销售额/订单/转化率%/推广花费/ROI)：" + "、".join(
            f"{it['hour']}:{it['visitors']}/{it['sales']:.0f}/{it['orders']}/{it['conversion_rate']}/{it['promo_spend']:.0f}/{it['promo_roi']}"
            for it in d["items"]
        ),
    ]
    conv_peak = sorted([it for it in d["items"] if it["visitors"] > 0], key=lambda x: x["conversion_rate"], reverse=True)[:3]
    if conv_peak:
        lines.append("转化率最高时段：" + "、".join(f"{it['hour']}（{it['conversion_rate']}%）" for it in conv_peak))
    anomalies = []
    for it in d["items"]:
        for name, val in (("访客", it["visitors_cycle"]), ("销售额", it["sales_cycle"])):
            if val is not None and abs(val) >= 30:
                anomalies.append(f"{it['hour']}{name}{val:+.0f}%")
    if anomalies:
        lines.append("较上一周期涨跌≥30%的时段：" + "、".join(anomalies[:8]))
    for sc in d.get("promo_by_scene", {}).values():
        active = []
        for h in range(24):
            it = sc["items"].get(f"{h:02d}:00") or {"spend": 0.0, "sales": 0.0, "roi": 0.0}
            if it["spend"] > 0:
                active.append((f"{h:02d}:00", it))
        if not active:
            continue
        total_spend = sum(it["spend"] for _, it in active)
        total_sales = sum(it["sales"] for _, it in active)
        roi = round(total_sales / total_spend, 2) if total_spend else 0
        top = sorted(active, key=lambda x: x[1]["roi"], reverse=True)[:3]
        bottom = sorted(active, key=lambda x: x[1]["roi"])[:2]
        lines.append(
            f"场景{sc['scene_name']}：总花费{total_spend:.0f}元，ROI{roi}；ROI最高时段 "
            + "、".join(f"{h}({it['roi']})" for h, it in top)
            + "；ROI最低时段 "
            + "、".join(f"{h}({it['roi']})" for h, it in bottom)
        )
    if d["recommended_hours"]:
        lines.append("推广ROI≥2 的时段：" + "、".join(d["recommended_hours"]))
    prompt = (
        "你是淘宝店铺的运营数据分析师。根据以下分时数据输出详细时段经营解读，严格按格式，每部分独占一段，条目用“- ”开头：\n"
        "【整体表现】2-3句话概括本期（含销售额、访客、转化率、推广ROI关键数字）\n"
        "【销售时段规律】\n- 销售高峰/次高峰/低谷时段及特征（3-4条）\n"
        "【流量与转化】\n- 访客高峰、转化率特征（2-3条）\n"
        "【投放建议】\n- 按场景按时段的具体建议，明确“几点到几点投/停投”（4-5条）\n"
        "【风险提醒】\n- 低ROI时段、异常波动等（2-3条）\n"
        "简体中文务实，金额≥1万用X.X万简化；只依据给定数据，不要编造。\n\n"
        + "\n".join(lines)
    )
    return prompt


@router.post("/hours/insight")
def hours_ai_insight(
    start: str = "",
    end: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    s, e = _resolve_hours_range("", start, end)
    sf, sp = _store_filter(store_id)
    d = _hours_dataset(db, sf, sp, s, e)
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": _build_hours_prompt(d)}], timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "sections": _parse_insight_sections(reply),
        "reply": reply,
        "range": d["label"],
        "recommended_hours": d["recommended_hours"],
        "summary": d["summary"],
    }


# ---------- 预警阈值配置 ----------

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


@router.get("/alerts/config")
def get_alerts_config(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    return _alerts_config(db)


@router.put("/alerts/config")
def set_alerts_config(
    body: AlertsConfigIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = {
        "baseline_days": max(2, min(int(body.baseline_days), 30)),
        "sales_down": float(body.sales_down),
        "sales_up": float(body.sales_up),
        "orders_down": float(body.orders_down),
        "visitors_down": float(body.visitors_down),
        "conversion_down": float(body.conversion_down),
    }
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('analytics_alerts_config', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_json.dumps(cfg, ensure_ascii=False),),
    )
    return {"ok": True, **cfg}
# ---------- 商品分析 ----------

def _aggregate_item_rows(rows) -> list[dict]:
    """把商品每日明细按商品聚合（销售额/订单/买家/访客/转化/加购/退款）。"""
    prod_map: dict[str, dict] = {}
    for r in rows:
        key = r["item_id"]
        item = prod_map.setdefault(
            key,
            {"item_id": key, "item_title": r["item_title"], "image": r["image"] or "", "sales": 0.0, "orders": 0, "buyers": 0, "visitors": 0, "pv": 0, "add_cart": 0, "refund_amount": 0.0, "conversion_rate": 0.0, "days": 0, "latest_date": ""},
        )
        item["sales"] += r["sales"] or 0
        item["orders"] += r["orders"] or 0
        item["buyers"] += r["buyers"] or 0
        item["visitors"] += r["visitors"] or 0
        item["pv"] += r["pv"] or 0
        item["add_cart"] += r["add_cart"] or 0
        item["refund_amount"] += r["refund_amount"] or 0
        if r["conversion_rate"]:
            item["conversion_rate"] = r["conversion_rate"]
        if r["image"]:
            item["image"] = r["image"]
        item["days"] += 1
        if r["data_date"] > item["latest_date"]:
            item["latest_date"] = r["data_date"]
    items = []
    for item in prod_map.values():
        item["sales"] = round(item["sales"], 2)
        item["refund_amount"] = round(item["refund_amount"], 2)
        item["conversion_rate"] = round(item["buyers"] / item["visitors"] * 100, 2) if item["visitors"] else 0.0
        items.append(item)
    return items


def _attach_promo(db, items, promo_mode: str, sf, sp) -> None:
    """给商品列表附加推广数据（promo_spend/promo_sales/promo_roi/promo_share）。"""
    rows = db.execute(
        "SELECT item_id, spend, sales, roi FROM promo_item_stats WHERE mode = ?" + sf,
        [promo_mode] + sp,
    ).fetchall()
    p_map = {r["item_id"]: r for r in rows}
    for it in items:
        p = p_map.get(it["item_id"])
        if p:
            spend = round(p["spend"] or 0, 2)
            sales = round(p["sales"] or 0, 2)
            it["promo_spend"] = spend
            it["promo_sales"] = sales
            it["promo_roi"] = round(p["roi"] or 0, 2)
            it["promo_share"] = round(min(sales / (it["sales"] or 1) * 100, 100.0), 1)
        else:
            it["promo_spend"] = None
            it["promo_sales"] = None
            it["promo_roi"] = None
            it["promo_share"] = None


def _realtime_product_items(db, sf, sp) -> list[dict]:
    """今日实时商品列表（实时快照，按销售额排序并算占比）。"""
    rows = db.execute("SELECT * FROM store_item_realtime WHERE 1=1" + sf, sp).fetchall()
    items = []
    for r in rows:
        items.append(
            {
                "item_id": r["item_id"],
                "item_title": r["item_title"],
                "image": r["image"],
                "visitors": r["visitors"] or 0,
                "pv": r["pv"] or 0,
                "buyers": r["buyers"] or 0,
                "orders": r["orders"] or 0,
                "sales": round(r["sales"] or 0, 2),
                "conversion_rate": round(r["conversion_rate"] or 0, 2),
                "add_cart": r["add_cart"] or 0,
                "refund_amount": round(r["refund_amount"] or 0, 2),
                "visitors_cycle": round(r["visitors_cycle"] or 0, 2),
                "pv_cycle": round(r["pv_cycle"] or 0, 2),
                "buyers_cycle": round(r["buyers_cycle"] or 0, 2),
                "orders_cycle": round(r["orders_cycle"] or 0, 2),
                "sales_cycle": round(r["sales_cycle"] or 0, 2),
                "conversion_cycle": round(r["conversion_cycle"] or 0, 2),
                "add_cart_cycle": round(r["add_cart_cycle"] or 0, 2),
                "live": True,
                "date_label": "今日",
                "days": 1,
                "latest_date": date_cls.today().isoformat(),
            }
        )
    items.sort(key=lambda x: x["sales"], reverse=True)
    total_sales = sum(x["sales"] for x in items) or 1
    for item in items[:20]:
        item["sales_share"] = round(item["sales"] / total_sales * 100, 1)
    return items


def _range_promo_mode(s: date_cls, e: date_cls) -> str | None:
    """按日期范围匹配已有的商品推广数据档位（realtime/yesterday/7/14/30），无匹配返回 None。"""
    today = date_cls.today()
    if s == e == today:
        return "realtime"
    if s == e == today - timedelta(days=1):
        return "yesterday"
    length = (e - s).days + 1
    if length in (7, 14, 30):
        return str(length)
    return None


def _product_rank_range(item_id: str, store_id: int | None, s: date_cls, e: date_cls, db) -> tuple[int, float, float]:
    """商品在区间销售榜中的排名、占比与全店区间销售额。"""
    sf, sp = _store_filter(store_id)
    rows = db.execute(
        "SELECT item_id, SUM(sales) AS sales FROM store_item_daily "
        "WHERE data_date >= ? AND data_date <= ?" + sf + " GROUP BY item_id",
        [s.isoformat(), e.isoformat()] + sp,
    ).fetchall()
    items = sorted(rows, key=lambda r: r["sales"] or 0, reverse=True)
    store_total = sum(r["sales"] or 0 for r in items)
    rank = None
    sales = 0.0
    for i, r in enumerate(items):
        if r["item_id"] == item_id:
            rank = i + 1
            sales = r["sales"] or 0
            break
    share = round(sales / store_total * 100, 1) if store_total else 0.0
    return (rank or len(items) + 1), share, round(store_total, 2)


@router.get("/products")
def analytics_products(
    days: int = 14,
    mode: str = "days",
    store_id: int | None = None,
    start: str = "",
    end: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if mode == "realtime":
        sf, sp = _store_filter(store_id)
        items = _realtime_product_items(db, sf, sp)
        _attach_promo(db, items, "realtime", sf, sp)
        fetched = db.execute(
            "SELECT MAX(updated_at) AS m FROM store_item_realtime" + (" WHERE 1=1" + sf),
            sp,
        ).fetchone()
        return {"items": items, "total": len(items), "days": 0, "mode": "realtime", "fetched_at": fetched["m"] if fetched and fetched["m"] else None}

    if mode == "yesterday":
        sf, sp = _store_filter(store_id)
        ys = (date_cls.today() - timedelta(days=1)).isoformat()
        rows = db.execute(
            "SELECT * FROM store_item_daily WHERE data_date = ?" + sf,
            [ys] + sp,
        ).fetchall()
        items = _aggregate_item_rows(rows)
        prev_rows = db.execute(
            "SELECT * FROM store_item_daily WHERE data_date = ?" + sf,
            [(date_cls.today() - timedelta(days=2)).isoformat()] + sp,
        ).fetchall()
        prev_map = {it["item_id"]: it for it in _aggregate_item_rows(prev_rows)}
        for item in items:
            p = prev_map.get(item["item_id"])
            if p:
                item["sales_cycle"] = round((item["sales"] - p["sales"]) / p["sales"] * 100, 1) if p["sales"] else None
                item["orders_cycle"] = round((item["orders"] - p["orders"]) / p["orders"] * 100, 1) if p["orders"] else None
                item["buyers_cycle"] = round((item["buyers"] - p["buyers"]) / p["buyers"] * 100, 1) if p["buyers"] else None
                item["visitors_cycle"] = round((item["visitors"] - p["visitors"]) / p["visitors"] * 100, 1) if p["visitors"] else None
                item["conversion_cycle"] = round(item["conversion_rate"] - p["conversion_rate"], 2) if p["visitors"] else None
                item["add_cart_cycle"] = round((item["add_cart"] - p["add_cart"]) / p["add_cart"] * 100, 1) if p["add_cart"] else None
            else:
                item["sales_cycle"] = None
                item["orders_cycle"] = None
                item["buyers_cycle"] = None
                item["visitors_cycle"] = None
                item["conversion_cycle"] = None
                item["add_cart_cycle"] = None
        items.sort(key=lambda x: x["sales"], reverse=True)
        total_sales = sum(x["sales"] for x in items) or 1
        for item in items[:20]:
            item["sales_share"] = round(item["sales"] / total_sales * 100, 1)
        _attach_promo(db, items, "yesterday", sf, sp)
        return {"items": items[:50], "total": len(items), "days": 1, "mode": "yesterday"}

    if not (1 <= days <= 90):
        days = 14
    if start and end:
        try:
            s = date_cls.fromisoformat(start)
            e = date_cls.fromisoformat(end)
        except ValueError:
            s = e = None
        if not (s and e and s <= e):
            s, e = _date_range(days)
    else:
        s, e = _date_range(days)
    sf, sp = _store_filter(store_id)
    rows = db.execute(
        "SELECT * FROM store_item_daily WHERE data_date >= ? AND data_date <= ?" + sf,
        [s.isoformat(), e.isoformat()] + sp,
    ).fetchall()
    items = _aggregate_item_rows(rows)
    if not items and s == e == date_cls.today():
        items = _realtime_product_items(db, sf, sp)
        _attach_promo(db, items, "realtime", sf, sp)
        return {"items": items[:50], "total": len(items), "days": 1, "mode": "days", "range": f"{s.isoformat()}~{e.isoformat()}", "today_fallback": True}
    # 涨跌幅：与上一相同长度周期对比（昨日=较前日，7天=较前7天……）
    prev_rows = db.execute(
        "SELECT * FROM store_item_daily WHERE data_date >= ? AND data_date <= ?" + sf,
        [(s - timedelta(days=(e - s).days)).isoformat(), (s - timedelta(days=1)).isoformat()] + sp,
    ).fetchall()
    prev_map = {it["item_id"]: it for it in _aggregate_item_rows(prev_rows)}
    for item in items:
        p = prev_map.get(item["item_id"])
        if p:
            item["sales_cycle"] = round((item["sales"] - p["sales"]) / p["sales"] * 100, 1) if p["sales"] else None
            item["orders_cycle"] = round((item["orders"] - p["orders"]) / p["orders"] * 100, 1) if p["orders"] else None
            item["buyers_cycle"] = round((item["buyers"] - p["buyers"]) / p["buyers"] * 100, 1) if p["buyers"] else None
            item["visitors_cycle"] = round((item["visitors"] - p["visitors"]) / p["visitors"] * 100, 1) if p["visitors"] else None
            item["conversion_cycle"] = round(item["conversion_rate"] - p["conversion_rate"], 2) if p["visitors"] else None
            item["add_cart_cycle"] = round((item["add_cart"] - p["add_cart"]) / p["add_cart"] * 100, 1) if p["add_cart"] else None
        else:
            item["sales_cycle"] = None
            item["orders_cycle"] = None
            item["buyers_cycle"] = None
            item["visitors_cycle"] = None
            item["conversion_cycle"] = None
            item["add_cart_cycle"] = None
    items.sort(key=lambda x: x["sales"], reverse=True)
    total_sales = sum(x["sales"] for x in items) or 1
    for item in items[:20]:
        item["sales_share"] = round(item["sales"] / total_sales * 100, 1)
    _attach_promo(db, items, _range_promo_mode(s, e), sf, sp)
    return {"items": items[:50], "total": len(items), "days": (e - s).days + 1, "mode": "days", "range": f"{s.isoformat()}~{e.isoformat()}"}


@router.get("/products/{item_id}")
def analytics_product_detail(
    item_id: str,
    days: int = 14,
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not (1 <= days <= 90):
        days = 14
    start, today = _date_range(days)
    sf, sp = _store_filter(store_id)
    rows = db.execute(
        "SELECT * FROM store_item_daily WHERE item_id = ? AND data_date >= ? AND data_date <= ?" + sf + " ORDER BY data_date",
        [item_id, start.isoformat(), today.isoformat()] + sp,
    ).fetchall()
    by_date: dict[str, dict] = {}
    title = ""
    for r in rows:
        title = r["item_title"] or title
        d = r["data_date"]
        item = by_date.setdefault(d, {"date": d[5:], "sales": 0.0, "orders": 0, "buyers": 0, "visitors": 0, "pv": 0})
        item["sales"] += r["sales"] or 0
        item["orders"] += r["orders"] or 0
        item["buyers"] += r["buyers"] or 0
        item["visitors"] += r["visitors"] or 0
        item["pv"] += r["pv"] or 0
    # 今天用实时快照补充
    rsf, rsp = _store_filter(store_id)
    rt = db.execute(
        "SELECT * FROM store_item_realtime WHERE item_id = ?" + rsf,
        [item_id] + rsp,
    ).fetchone()
    if rt:
        today_key = date_cls.today().isoformat()
        item = by_date.setdefault(today_key, {"date": today_key[5:], "sales": 0.0, "orders": 0, "buyers": 0, "visitors": 0, "pv": 0})
        item["sales"] = round(rt["sales"] or 0, 2)
        item["orders"] = rt["orders"] or 0
        item["buyers"] = rt["buyers"] or 0
        item["visitors"] = rt["visitors"] or 0
        item["pv"] = rt["pv"] or 0
        title = title or rt["item_title"]
    series = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        row = by_date.get(d)
        if row:
            row["sales"] = round(row["sales"], 2)
            series.append(row)
        else:
            series.append({"date": d[5:], "sales": 0.0, "orders": 0, "buyers": 0, "visitors": 0, "pv": 0})
    return {"item_id": item_id, "item_title": title, "series": series}


# ---------- 异常通知汇总（顶部铃铛） ----------

@router.get("/alerts/summary")
def alerts_summary(
    days: int = 3,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not (1 <= days <= 30):
        days = 3
    result = analytics_alerts(days=days, user=user, db=db)
    items = result["items"]
    return {"count": len(items), "items": items[:10], "checked_at": date_cls.today().isoformat()}



@router.get("/products/{item_id}/trend")
def product_trend(
    item_id: str,
    days: int = 7,
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """单个商品每日趋势（销售额/订单/访客/转化），从 store_item_daily 读取，缺日期补 0。"""
    if not (1 <= days <= 90):
        days = 7
    sf, sp = _store_filter(store_id)
    today = date_cls.today()
    start = today - timedelta(days=days - 1)
    rows = db.execute(
        "SELECT data_date, sales, orders, visitors, pv, buyers, conversion_rate, add_cart, item_title, image "
        "FROM store_item_daily WHERE item_id = ? AND data_date >= ? AND data_date <= ?" + sf + " ORDER BY data_date",
        [item_id, start.isoformat(), today.isoformat()] + sp,
    ).fetchall()
    by_date = {r["data_date"]: dict(r) for r in rows}
    title = ""
    image = ""
    if rows:
        title = rows[-1]["item_title"] or ""
        image = rows[-1]["image"] or ""
    out = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        v = by_date.get(d) or {}
        out.append(
            {
                "date": d,
                "sales": round(v.get("sales") or 0, 2),
                "orders": int(v.get("orders") or 0),
                "visitors": int(v.get("visitors") or 0),
                "pv": int(v.get("pv") or 0),
                "buyers": int(v.get("buyers") or 0),
                "conversion_rate": round(v.get("conversion_rate") or 0, 2),
                "add_cart": int(v.get("add_cart") or 0),
            }
        )
    return {"item": {"item_id": item_id, "item_title": title, "image": image}, "items": out, "days": days}


@router.get("/products/{item_id}/promo")
def product_promo(
    item_id: str,
    mode: str = "realtime",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """商品 ↔ 推广联动：这个商品挂在哪些推广计划（含计划表现）+ 这些计划的关键词表现。"""
    mode = mode if mode in ("realtime", "yesterday", "7d") else "realtime"
    sf, sp = _store_filter(store_id)
    plan_rows = db.execute(
        "SELECT pi.store_id, pi.campaign_id, p.scene_name, p.plan_name, p.status, p.day_budget, p.bid_type, p.bid_value "
        "FROM promo_plan_items pi "
        "LEFT JOIN promo_plans p ON p.store_id = pi.store_id AND p.campaign_id = pi.campaign_id "
        "WHERE pi.item_id = ?" + sf,
        [item_id] + sp,
    ).fetchall()
    plans: list[dict] = []
    cids: list[str] = []
    for r in plan_rows:
        d = dict(r)
        cids.append(d["campaign_id"])
        d["spend"] = 0.0
        d["sales"] = 0.0
        d["roi"] = 0.0
        d["clicks"] = 0
        plans.append(d)
    if cids:
        ph = ",".join("?" for _ in cids)
        s_map = {
            r["campaign_id"]: r
            for r in db.execute(
                "SELECT campaign_id, spend, sales, roi, clicks FROM promo_plan_stats "
                "WHERE mode = ? AND campaign_id IN (" + ph + ")",
                [mode] + cids,
            ).fetchall()
        }
        for p in plans:
            s = s_map.get(p["campaign_id"])
            if s:
                p["spend"] = round(s["spend"] or 0, 2)
                p["sales"] = round(s["sales"] or 0, 2)
                p["roi"] = round(s["roi"] or 0, 2)
                p["clicks"] = int(s["clicks"] or 0)
    # 关键词（best-effort：抓全量关键词报表，按该商品的计划名过滤）
    keywords: list[dict] = []
    names = {p["plan_name"] for p in plans if p["plan_name"]}
    store_ids = {p["store_id"] for p in plans}
    if names:
        try:
            from backend.app.core.alimama import AlimamaError, _num, _run_json
            from backend.app.core.sycm import has_profile as _has_profile

            today = date_cls.today()
            if mode == "realtime":
                start = end = today.isoformat()
            elif mode == "yesterday":
                d = today - timedelta(days=1)
                start = end = d.isoformat()
            else:
                start = (today - timedelta(days=6)).isoformat()
                end = today.isoformat()
            for st in [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY id").fetchall() if _has_profile(r["id"])]:
                if st["id"] not in store_ids:
                    continue
                try:
                    payload = _run_json(st, ["report-keyword", "--date", start, "--end-date", end, "--limit", "100", "--raw"])
                except AlimamaError:
                    continue
                for r in (payload.get("data") or {}).get("list") or []:
                    if not isinstance(r, dict):
                        continue
                    if (r.get("promotionName") or "") not in names:
                        continue
                    word = r.get("originalWord") or r.get("word") or r.get("bidword") or "（智能匹配）"
                    spend = _num(r.get("charge"))
                    sales = _num(r.get("alipayInshopAmt"))
                    keywords.append(
                        {
                            "word": word,
                            "promotion": r.get("promotionName") or "",
                            "spend": round(spend, 2),
                            "sales": round(sales, 2),
                            "roi": round(sales / spend, 2) if spend else 0.0,
                            "clicks": int(_num(r.get("click"))),
                            "orders": int(_num(r.get("alipayInshopNum"))),
                        }
                    )
        except Exception:  # noqa: BLE001
            pass
    keywords.sort(key=lambda x: -x["spend"])
    return {"item_id": item_id, "mode": mode, "plans": plans, "keywords": keywords[:50]}
