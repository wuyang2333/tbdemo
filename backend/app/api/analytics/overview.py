"""数据洞察：总览、每日、异常波动、退款。"""

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

@router.get("/summary")
def analytics_summary(
    days: int = 14,
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not (1 <= days <= 90):
        days = 14
    sf, sp = _store_filter(store_id, user)
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

    visible = visible_store_ids(user)
    if visible is None:
        store_ids = [s["id"] for s in db.execute("SELECT id FROM stores").fetchall()]
        configured = sum(1 for sid in store_ids if has_profile(sid))
    else:
        configured = sum(1 for sid in visible if has_profile(sid))
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


@router.get("/refund-analysis")
def refund_analysis(
    days: int = 14,
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """退款分析：区间退款总额/率、TOP 退款商品、退款趋势。"""
    days = max(1, min(days, 90))
    sf, sp = _store_filter(store_id, user)
    today = date_cls.today()
    start = today - timedelta(days=days - 1)
    rows = db.execute(
        "SELECT * FROM store_item_daily WHERE data_date >= ? AND data_date <= ?" + sf,
        [start.isoformat(), today.isoformat()] + sp,
    ).fetchall()
    total_sales = sum(r["sales"] or 0 for r in rows)
    total_refund = sum(r["refund_amount"] or 0 for r in rows)
    item_map: dict[str, dict] = {}
    for r in rows:
        it = item_map.setdefault(r["item_id"], {"item_id": r["item_id"], "item_title": r["item_title"], "refund": 0.0, "sales": 0.0, "orders": 0})
        it["refund"] += r["refund_amount"] or 0
        it["sales"] += r["sales"] or 0
        it["orders"] += r["orders"] or 0
    top_refund = sorted(item_map.values(), key=lambda x: x["refund"], reverse=True)[:10]
    for it in top_refund:
        it["refund_rate"] = round(it["refund"] / it["sales"] * 100, 1) if it["sales"] else 0.0
        it["refund"] = round(it["refund"], 2)
        it["sales"] = round(it["sales"], 2)
    date_map: dict[str, dict] = {}
    for r in rows:
        d = date_map.setdefault(r["data_date"], {"date": r["data_date"], "refund": 0.0, "sales": 0.0})
        d["refund"] += r["refund_amount"] or 0
        d["sales"] += r["sales"] or 0
    trend = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        row = date_map.get(d)
        trend.append({
            "date": d[5:],
            "refund": round(row["refund"], 2) if row else 0,
            "rate": round(row["refund"] / row["sales"] * 100, 1) if row and row["sales"] else 0,
        })
    return {
        "days": days,
        "total_refund": round(total_refund, 2),
        "refund_rate": round(total_refund / total_sales * 100, 1) if total_sales else 0.0,
        "top_refund": top_refund,
        "trend": trend,
    }


@router.get("/summary/today")
def summary_today(
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """今日总览：今日实时 KPI（较昨日同时段）、推广、转化漏斗、流量结构、退款、爆款/暴跌。"""
    sf, sp = _store_filter(store_id, user)
    today = date_cls.today()
    yesterday = today - timedelta(days=1)
    now = datetime.now()
    cur_hour = f"{now.hour:02d}:00"

    def _pct(cur, prev):
        if prev and prev > 0:
            return round((cur - prev) / prev * 100, 1)
        return None

    # ---- 1. 今日 KPI + 较昨日同时段（分时表口径一致）----
    today_rows = db.execute(
        "SELECT * FROM store_hourly_data WHERE data_date = ? AND hour <= ?" + sf,
        [today.isoformat(), cur_hour] + sp,
    ).fetchall()
    yest_rows = db.execute(
        "SELECT * FROM store_hourly_data WHERE data_date = ? AND hour <= ?" + sf,
        [yesterday.isoformat(), cur_hour] + sp,
    ).fetchall()
    t = _sum_rows(today_rows)
    y = _sum_rows(yest_rows)
    kpi = {
        "sales": round(t["sales"], 2),
        "orders": t["orders"],
        "visitors": t["visitors"],
        "conversion_rate": round(t["conversion_rate"], 2),
        "avg_order_value": round(t["sales"] / t["orders"], 2) if t["orders"] else 0,
        "compare": {
            "sales": _pct(t["sales"], y["sales"]),
            "orders": _pct(t["orders"], y["orders"]),
            "visitors": _pct(t["visitors"], y["visitors"]),
            "conversion": round(t["conversion_rate"] - y["conversion_rate"], 2) if y["visitors"] else None,
        },
    }

    # ---- 2. 今日推广 + 较昨日同时段 ----
    pt = db.execute(
        "SELECT * FROM promo_realtime WHERE data_date = ? AND hour <= ?" + sf,
        [today.isoformat(), cur_hour] + sp,
    ).fetchall()
    py = db.execute(
        "SELECT * FROM promo_realtime WHERE data_date = ? AND hour <= ?" + sf,
        [yesterday.isoformat(), cur_hour] + sp,
    ).fetchall()

    def _ps(rows):
        return {
            "spend": round(sum(r["spend"] or 0 for r in rows), 2),
            "sales": round(sum(r["sales"] or 0 for r in rows), 2),
        }

    pts, pys = _ps(pt), _ps(py)
    scenes: dict[str, dict] = {}
    for r in pt:
        s = scenes.setdefault(r["scene"], {"scene": r["scene"], "scene_name": r["scene_name"], "spend": 0.0, "sales": 0.0, "roi": 0.0})
        s["spend"] += r["spend"] or 0
        s["sales"] += r["sales"] or 0
    for s in scenes.values():
        s["spend"] = round(s["spend"], 2)
        s["sales"] = round(s["sales"], 2)
        s["roi"] = round(s["sales"] / s["spend"], 2) if s["spend"] else 0
    promo = {
        "spend": pts["spend"],
        "sales": pts["sales"],
        "roi": round(pts["sales"] / pts["spend"], 2) if pts["spend"] else 0,
        "compare": {"spend": _pct(pts["spend"], pys["spend"]), "sales": _pct(pts["sales"], pys["sales"])},
        "scenes": sorted(scenes.values(), key=lambda x: x["spend"], reverse=True),
    }

    # ---- 3. 转化漏斗 / 流量结构 / 退款（基于商品实时榜汇总）----
    rt_rows = db.execute("SELECT * FROM store_item_realtime WHERE 1=1" + sf, sp).fetchall()
    rv = sum(r["visitors"] or 0 for r in rt_rows)
    funnel = {
        "visitors": rv,
        "collect": sum(r["item_clt_byr_cnt"] or 0 for r in rt_rows),
        "add_cart": sum(r["add_cart"] or 0 for r in rt_rows),
        "buyers": sum(r["buyers"] or 0 for r in rt_rows),
        "collect_rate": round(sum(r["item_clt_byr_cnt"] or 0 for r in rt_rows) / (rv or 1) * 100, 1),
        "cart_rate": round(sum(r["add_cart"] or 0 for r in rt_rows) / (rv or 1) * 100, 1),
        "pay_rate": round(sum(r["buyers"] or 0 for r in rt_rows) / (rv or 1) * 100, 1),
    }
    # 流量结构：今日实时流量来源排行（flow_source_top，生意参谋 流量看板-流量来源）
    fs_rows = db.execute(
        "SELECT * FROM flow_source_top WHERE data_date = ? AND 1=1" + sf,
        [today.isoformat()] + sp,
    ).fetchall()
    fs_total = sum(r["uv"] or 0 for r in fs_rows)
    fs_search = sum(r["uv"] or 0 for r in fs_rows if "搜索" in (r["source_name"] or ""))
    sources = [
        {"source": r["source_name"], "uv": r["uv"] or 0, "rank": r["rank"]}
        for r in sorted(fs_rows, key=lambda x: x["rank"] or 0)[:10]
    ]
    flow = {
        "search_uv": fs_search,
        "search_share": round(fs_search / fs_total * 100, 1) if fs_total else None,
        "other_share": round((fs_total - fs_search) / fs_total * 100, 1) if fs_total else None,
        "has_data": fs_total > 0,
        "data_date": today.isoformat(),
        "sources": sources,
    }
    # 退款：今日实时（生意参谋 首页-数据概括 退款金额-完结时间）
    rf_rows = db.execute(
        "SELECT * FROM refund_today WHERE data_date = ?" + sf,
        [today.isoformat()] + sp,
    ).fetchall()
    rf_amount = sum(r["amount"] or 0 for r in rf_rows)
    rf_pay_amt = sum(r["pay_amt"] or 0 for r in rf_rows)
    rf_yest_amount = sum(r["yest_amount"] or 0 for r in rf_rows)
    rf_yest_pay_amt = sum(r["yest_pay_amt"] or 0 for r in rf_rows)
    # 退款率用生意参谋官方口径（payAmtRfdRate），多店按支付金额加权；不直接用 amount/pay_amt（完结时间 vs 付款时间口径不同）
    if rf_rows:
        w = sum(r["pay_amt"] or 0 for r in rf_rows)
        rf_rate = round(sum((r["rate"] or 0) * (r["pay_amt"] or 0) for r in rf_rows) / w, 2) if w else round(sum(r["rate"] or 0 for r in rf_rows) / len(rf_rows), 2)
        wy = sum(r["yest_pay_amt"] or 0 for r in rf_rows)
        rf_yest_rate = round(sum((r["yest_rate"] or 0) * (r["yest_pay_amt"] or 0) for r in rf_rows) / wy, 2) if wy else round(sum(r["yest_rate"] or 0 for r in rf_rows) / len(rf_rows), 2)
    else:
        rf_rate = 0.0
        rf_yest_rate = 0.0
    cycles = [r["cycle"] for r in rf_rows if r["cycle"] is not None]
    rf_cycle = None
    if len(rf_rows) == 1:
        rf_cycle = rf_rows[0]["cycle"]
    elif cycles:
        rf_cycle = round(sum(cycles) / len(cycles), 1)
    refund = {
        "amount": round(rf_amount, 2),
        "pay_amt": round(rf_pay_amt, 2),
        "rate": rf_rate,
        "ord_rate": round(sum(r["ord_rate"] or 0 for r in rf_rows) / len(rf_rows), 2) if rf_rows else 0.0,
        "cycle": rf_cycle,
        "yest_amount": round(rf_yest_amount, 2),
        "yest_rate": rf_yest_rate,
        "data_date": today.isoformat(),
        "updated_at": max((r["updated_at"] or "" for r in rf_rows), default=""),
    }

    # ---- 4. 今日爆款 / 暴跌（较昨日同时段环比）----
    def _movers(desc: bool):
        rows = [r for r in rt_rows if r["sales_cycle"] is not None and abs(r["sales_cycle"]) > 0 and (r["sales"] or 0) > 0]
        rows.sort(key=lambda r: r["sales_cycle"] or 0, reverse=desc)
        return [
            {"item_id": r["item_id"], "item_title": r["item_title"], "sales": round(r["sales"] or 0, 2), "cycle": round(r["sales_cycle"] or 0, 1)}
            for r in rows[:3]
        ]

    return {
        "kpi": kpi,
        "promo": promo,
        "funnel": funnel,
        "flow": flow,
        "refund": refund,
        "movers": {"risers": _movers(True), "fallers": _movers(False)},
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
    sf, sp = _store_filter(store_id, user)
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
    sf, sp = _store_filter(store_id, user)
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
