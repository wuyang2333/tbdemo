"""数据洞察：从生意参谋抓取的店铺每日数据（store_daily_data）聚合统计。"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta

from fastapi import APIRouter, Depends

from backend.app.api.auth import get_current_user
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
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not (1 <= days <= 90):
        days = 14
    rows = db.execute(
        "SELECT * FROM store_daily_data ORDER BY data_date ASC, store_id ASC"
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
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """每日明细：访客/浏览/销售额/订单/转化率/客单价/单访客价值（全部店铺合计）。"""
    if not (1 <= days <= 90):
        days = 30
    start, today = _date_range(days)
    rows = db.execute(
        "SELECT * FROM store_daily_data WHERE data_date >= ? AND data_date <= ? ORDER BY data_date ASC",
        (start.isoformat(), today.isoformat()),
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


@router.get("/stores")
def analytics_stores(
    days: int = 14,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """店铺对比：区间内各店铺合计指标（含客单价、单访客价值）。"""
    if not (1 <= days <= 90):
        days = 14
    start, today = _date_range(days)
    rows = db.execute(
        "SELECT * FROM store_daily_data WHERE data_date >= ? AND data_date <= ? ORDER BY data_date ASC",
        (start.isoformat(), today.isoformat()),
    ).fetchall()

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
    items = []
    for sid, item in stores_map.items():
        item["store_name"] = name_map.get(sid, f"店铺 {sid}")
        conv = (item["orders"] / item["visitors"] * 100) if item["visitors"] else 0.0
        item["conversion_rate"] = round(conv, 2)
        item["sales"] = round(item["sales"], 2)
        items.append(_derive(item))
    items.sort(key=lambda x: x["sales"], reverse=True)
    return {"items": items, "days": days}
# ---------- 同比环比 ----------

_METRIC_META = [
    ("sales", "销售额", "money"),
    ("orders", "订单", "int"),
    ("visitors", "访客", "int"),
    ("conversion_rate", "转化率", "pct"),
]


def _sum_range(rows, start: date_cls, end: date_cls) -> dict | None:
    in_range = [r for r in rows if start <= _to_date(r["data_date"]) <= end]
    if not in_range:
        return None
    return _sum_rows(in_range)


def _day_sum(rows, d: date_cls) -> dict | None:
    ds = d.isoformat()
    day_rows = [r for r in rows if r["data_date"] == ds]
    if not day_rows:
        return None
    s = _sum_rows(day_rows)
    if len(day_rows) == 1 and day_rows[0]["conversion_rate"]:
        s["conversion_rate"] = round(day_rows[0]["conversion_rate"], 2)
    return s


def _rel_change(current: float, previous: float) -> float | None:
    if previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _cmp_pair(current: float | None, previous: float | None) -> dict:
    return {
        "change_pct": _rel_change(current or 0, previous) if previous is not None else None,
        "prev": round(previous, 2) if isinstance(previous, float) and previous is not None else previous,
    }


@router.get("/compare")
def analytics_compare(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """同比环比：今日 vs 昨日 / 近7天 vs 前7天 / 本月 vs 上月同期 / 今日 vs 去年今日。"""
    today = date_cls.today()
    rows = db.execute("SELECT * FROM store_daily_data ORDER BY data_date ASC").fetchall()

    t = _day_sum(rows, today)
    if t is None:
        t = {"visitors": 0, "pv": 0, "sales": 0.0, "orders": 0, "conversion_rate": 0.0}
    yesterday = _day_sum(rows, today - timedelta(days=1))
    yoy_day = _day_sum(rows, today.replace(year=today.year - 1)) if today.year > 2000 else None

    week_cur = _sum_range(rows, today - timedelta(days=6), today)
    week_prev = _sum_range(rows, today - timedelta(days=13), today - timedelta(days=7))

    month_start = today.replace(day=1)
    prev_month_end = month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    month_cur = _sum_range(rows, month_start, today)
    month_prev_end = min(prev_month_end, prev_month_start.replace(day=today.day))
    month_prev = _sum_range(rows, prev_month_start, month_prev_end)

    ytd_cur = _sum_range(rows, today.replace(month=1, day=1), today)
    ytd_ly = None
    if today.year > 2000:
        last_year = today.replace(year=today.year - 1)
        ytd_ly = _sum_range(rows, last_year.replace(month=1, day=1), last_year)

    def pick(s: dict | None, key: str):
        return None if s is None else s.get(key)

    metrics = []
    for key, name, fmt in _METRIC_META:
        metrics.append(
            {
                "key": key,
                "name": name,
                "fmt": fmt,
                "today": pick(t, key),
                "dod": _cmp_pair(pick(t, key), pick(yesterday, key)),
                "wow": _cmp_pair(pick(week_cur, key), pick(week_prev, key)),
                "mom": _cmp_pair(pick(month_cur, key), pick(month_prev, key)),
                "yoy": _cmp_pair(pick(t, key), pick(yoy_day, key)),
            }
        )
    return {"today_date": today.isoformat(), "metrics": metrics}


# ---------- 异常波动提醒 ----------

@router.get("/alerts")
def analytics_alerts(
    days: int = 30,
    baseline: int = 7,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """异常波动：按店铺对比每天指标与前 baseline 日均值，超过阈值生成提醒。"""
    if not (1 <= days <= 90):
        days = 30
    if not (2 <= baseline <= 30):
        baseline = 7
    today = date_cls.today()
    start = today - timedelta(days=days - 1)
    rows = db.execute(
        "SELECT * FROM store_daily_data WHERE data_date >= ? ORDER BY data_date ASC",
        (start.isoformat(),),
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
                ("sales", "销售额", base_avg("sales"), cur["sales"] or 0, -30, 60, "money"),
                ("orders", "订单数", base_avg("orders"), cur["orders"] or 0, -30, None, "int"),
                ("visitors", "访客数", base_avg("visitors"), cur["visitors"] or 0, -30, 60, "int"),
                ("conversion_rate", "转化率", base_avg("conversion_rate"), cur["conversion_rate"] or 0, -20, None, "pct"),
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
