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

@router.get("/report")
def daily_report(
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    today = date_cls.today()
    yesterday = today - timedelta(days=1)
    ts = today.isoformat()
    ys = yesterday.isoformat()
    sf, sp = _store_filter(store_id)

    def sd_sum(d: str) -> dict:
        rows = db.execute("SELECT * FROM store_daily_data WHERE data_date = ?" + sf, [d] + sp).fetchall()
        s = _sum_rows(rows)
        if len(rows) == 1 and rows[0]["conversion_rate"]:
            s["conversion_rate"] = round(rows[0]["conversion_rate"], 2)
        return s

    td = sd_sum(ts)
    yd = sd_sum(ys)
    pr = db.execute(
        "SELECT COALESCE(SUM(spend),0) AS spend, COALESCE(SUM(sales),0) AS sales FROM promo_realtime WHERE data_date = ?",
        (ts,),
    ).fetchone()
    py = db.execute(
        "SELECT COALESCE(SUM(spend),0) AS spend, COALESCE(SUM(sales),0) AS sales FROM promo_daily_data WHERE data_date = ?",
        (ys,),
    ).fetchone()
    goal, _ = _goal_value(db)
    month = _current_month()
    month_rows = db.execute("SELECT sales FROM store_daily_data WHERE data_date LIKE ?", (month + "%",)).fetchall()
    month_sales = round(sum(r["sales"] or 0 for r in month_rows), 2)
    return {
        "date": ts,
        "today": td,
        "yesterday": yd,
        "promo_today": {"spend": round(pr["spend"] or 0, 2), "sales": round(pr["sales"] or 0, 2), "roi": round((pr["sales"] or 0) / (pr["spend"] or 0), 2) if pr["spend"] else 0.0},
        "promo_yesterday": {"spend": round(py["spend"] or 0, 2), "sales": round(py["sales"] or 0, 2), "roi": round((py["sales"] or 0) / (py["spend"] or 0), 2) if py["spend"] else 0.0},
        "goal": goal,
        "month_sales": month_sales,
        "month": month,
    }


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

@router.post("/insight")
def ai_insight(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    today = date_cls.today()
    rows = db.execute("SELECT * FROM store_daily_data ORDER BY data_date ASC").fetchall()
    link = analytics_linkage(days=14, user=user, db=db)
    summary = link["summary"]
    trend = "、".join(f"{x['label']}:¥{x['total_sales']:.0f}" for x in link["items"][-7:])
    anomalies = db.execute("SELECT data_date, message FROM (SELECT data_date, message FROM analytics_alert_probe) LIMIT 0").fetchall() if False else []
    prompt = (
        "你是淘宝店铺的运营数据分析师。请根据以下数据，用简体中文写一段不超过 180 字的经营解读，"
        "分 2-3 点：1) 整体表现 2) 推广效率 3) 一个具体建议。语气务实，数字用万元/万级简化。\n"
        f"近14天：总销售额 {summary['total_sales']:.0f} 元，推广花费 {summary['promo_spend']:.0f} 元，"
        f"广告成交占比 {summary['ad_share']}%，推广ROI {summary['promo_roi']}，整体ROI（总销售/推广花费）{summary['overall_roi']}。\n"
        f"近7天逐日销售额：{trend}。"
    )
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": prompt}], timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"reply": reply, "date": today.isoformat()}
# ---------- 通用：单店筛选 ----------

def _store_filter(store_id: int | None) -> tuple[str, list]:
    if store_id:
        return " AND store_id = ?", [store_id]
    return "", []


# ---------- 客群分析（新老客/复购） ----------

@router.get("/hours")
def analytics_hours(
    date: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    d = _to_date(date) or date_cls.today()
    ds = d.isoformat()
    sf, sp = _store_filter(store_id)
    rows = db.execute(
        "SELECT * FROM store_hourly_data WHERE data_date = ?" + sf + " ORDER BY hour",
        [ds] + sp,
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
    items = []
    for h in range(24):
        key = f"{h:02d}:00"
        row = hour_map.get(key)
        if row:
            row["conversion_rate"] = round(row["buyers"] / row["visitors"] * 100, 2) if row["visitors"] else 0.0
            row["sales"] = round(row["sales"], 2)
            items.append(row)
        else:
            items.append({"hour": key, "visitors": 0, "pv": 0, "sales": 0.0, "orders": 0, "buyers": 0, "conversion_rate": 0.0})
    summary = {"visitors": sum(i["visitors"] for i in items), "pv": sum(i["pv"] for i in items), "sales": round(sum(i["sales"] for i in items), 2), "orders": sum(i["orders"] for i in items)}
    peak = max(items, key=lambda x: x["sales"]) if items else {"hour": "", "sales": 0}
    return {"date": ds, "items": items, "summary": summary, "peak_hour": peak["hour"], "peak_sales": peak["sales"]}


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

@router.get("/products")
def analytics_products(
    days: int = 14,
    mode: str = "days",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if mode == "realtime":
        sf, sp = _store_filter(store_id)
        rows = db.execute(
            "SELECT * FROM store_item_realtime WHERE 1=1" + sf,
            sp,
        ).fetchall()
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
                    "days": 1,
                    "latest_date": date_cls.today().isoformat(),
                }
            )
        items.sort(key=lambda x: x["sales"], reverse=True)
        total_sales = sum(x["sales"] for x in items) or 1
        for item in items[:20]:
            item["sales_share"] = round(item["sales"] / total_sales * 100, 1)
        return {"items": items[:50], "total": len(items), "days": 0, "mode": "realtime"}

    if not (1 <= days <= 90):
        days = 14
    start, today = _date_range(days)
    sf, sp = _store_filter(store_id)
    rows = db.execute(
        "SELECT * FROM store_item_daily WHERE data_date >= ? AND data_date <= ?" + sf,
        [start.isoformat(), today.isoformat()] + sp,
    ).fetchall()
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
    items.sort(key=lambda x: x["sales"], reverse=True)
    total_sales = sum(x["sales"] for x in items) or 1
    for item in items[:20]:
        item["sales_share"] = round(item["sales"] / total_sales * 100, 1)
    return {"items": items[:50], "total": len(items), "days": days, "mode": "days"}


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
