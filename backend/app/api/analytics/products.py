"""数据洞察：商品分析。"""

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

from .insight import _lifecycle_of, _product_rank_days, _product_rank_realtime, _sum_product_rows
from .overview import analytics_alerts

router = APIRouter()

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
    # 净实际投产比：商品→计划映射 + 计划留存成交/花费聚合（复用计划表，无需新字段）
    plan_mode = "realtime" if promo_mode == "realtime" else "yesterday" if promo_mode == "yesterday" else "7d"
    plan_sf = sf.replace("store_id", "pi.store_id") if "store_id" in sf else sf
    plan_rows = db.execute(
        "SELECT pi.item_id, "
        "COALESCE(SUM(ps.spend), 0) AS spend, "
        "COALESCE(SUM(ps.retained_sales), 0) AS retained_sales "
        "FROM promo_plan_items pi "
        "JOIN promo_plan_stats ps ON ps.store_id = pi.store_id AND ps.campaign_id = pi.campaign_id AND ps.mode = ? "
        "WHERE 1=1" + plan_sf + " GROUP BY pi.item_id",
        [plan_mode] + sp,
    ).fetchall()
    net_map: dict[str, float] = {}
    for r in plan_rows:
        if r["spend"] and r["retained_sales"]:
            net_map[r["item_id"]] = round(r["retained_sales"] / r["spend"], 2)
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
        it["promo_net_roi"] = net_map.get(it["item_id"])


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
    sf, sp = _store_filter(store_id, user)
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
        sf, sp = _store_filter(store_id, user)
        items = _realtime_product_items(db, sf, sp)
        _attach_promo(db, items, "realtime", sf, sp)
        fetched = db.execute(
            "SELECT MAX(updated_at) AS m FROM store_item_realtime" + (" WHERE 1=1" + sf),
            sp,
        ).fetchone()
        for _it in items:
            _it["lifecycle"] = _lifecycle_of(_it)
        return {"items": items, "total": len(items), "days": 0, "mode": "realtime", "fetched_at": fetched["m"] if fetched and fetched["m"] else None}

    if mode == "yesterday":
        sf, sp = _store_filter(store_id, user)
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
        for _it in items:
            _it["lifecycle"] = _lifecycle_of(_it)
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
    sf, sp = _store_filter(store_id, user)
    rows = db.execute(
        "SELECT * FROM store_item_daily WHERE data_date >= ? AND data_date <= ?" + sf,
        [s.isoformat(), e.isoformat()] + sp,
    ).fetchall()
    items = _aggregate_item_rows(rows)
    if not items and s == e == date_cls.today():
        items = _realtime_product_items(db, sf, sp)
        _attach_promo(db, items, "realtime", sf, sp)
        for _it in items:
            _it["lifecycle"] = _lifecycle_of(_it)
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
    sf, sp = _store_filter(store_id, user)
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
    rsf, rsp = _store_filter(store_id, user)
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
    sf, sp = _store_filter(store_id, user)
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
    sf, sp = _store_filter(store_id, user)
    plan_sf = sf.replace("store_id", "pi.store_id") if "store_id" in sf else sf
    plan_rows = db.execute(
        "SELECT pi.store_id, pi.campaign_id, p.scene_name, p.plan_name, p.status, p.day_budget, p.bid_type, p.bid_value "
        "FROM promo_plan_items pi "
        "LEFT JOIN promo_plans p ON p.store_id = pi.store_id AND p.campaign_id = pi.campaign_id "
        "WHERE pi.item_id = ?" + plan_sf,
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
