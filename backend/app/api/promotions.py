"""推广管理：万相台推广数据（自动抓取，复用店铺登录态）+ 推广计划管理（计划快照 + 本地备注/标记）。

数据模式：realtime（今日实时，按小时） / yesterday（昨天） / 7d（近七天，按天）。
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import get_current_user
from backend.app.core.alimama import (
    AlimamaError,
    check_access,
    fetch_item_promo_plan_based,
    fetch_item_report,
    fetch_plan_realtime,
    fetch_plan_reports,
    fetch_plan_snapshots,
    fetch_promo_item_fallback,
    fetch_realtime,
    fetch_scene_daily,
    fetch_scene_hourly,
)
from backend.app.core.db import get_db
from backend.app.core.logs import log_op
from backend.app.core.sycm import has_profile

router = APIRouter()

MODES = ("realtime", "yesterday", "7d")


class PlanNoteIn(BaseModel):
    note: str = ""
    tag: str = ""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _log(db, user: dict, action: str, target: str = "", detail: str = "") -> None:
    log_op(db, user, "promotions", action, target, detail)


def _bound_stores(db) -> list[dict]:
    return [
        dict(r)
        for r in db.execute("SELECT * FROM stores ORDER BY id ASC").fetchall()
        if has_profile(r["id"])
    ]


def _mode(value: str) -> str:
    return value if value in MODES else "realtime"


def _finalize(item: dict) -> dict:
    item["ctr"] = round(item["clicks"] / item["impressions"] * 100, 2) if item["impressions"] else 0.0
    item["roi"] = round(item["sales"] / item["spend"], 2) if item["spend"] else 0.0
    item["spend"] = round(item["spend"], 2)
    item["sales"] = round(item["sales"], 2)
    return item


def _store_daily_rows(db, store_id: int, items: list[dict], now: str) -> int:
    for it in items:
        db.execute(
            "INSERT INTO promo_daily_data (store_id, scene, scene_name, data_date, impressions, clicks, ctr, spend, sales, roi, orders, add_cart, conversion_rate, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(store_id, scene, data_date) DO UPDATE SET "
            "impressions = excluded.impressions, clicks = excluded.clicks, ctr = excluded.ctr, "
            "spend = excluded.spend, sales = excluded.sales, roi = excluded.roi, "
            "orders = excluded.orders, add_cart = excluded.add_cart, conversion_rate = excluded.conversion_rate",
            (
                store_id,
                it["scene"],
                it["scene_name"],
                it["date"],
                it["impressions"],
                it["clicks"],
                it["ctr"],
                it["spend"],
                it["sales"],
                it["roi"],
                it["orders"],
                it["add_cart"],
                it["conversion_rate"],
                now,
            ),
        )
    return len(items)


def _store_realtime_rows(db, store_id: int, items: list[dict], now: str, data_date: str | None = None) -> int:
    today = data_date or date_cls.today().isoformat()
    for it in items:
        imp = int(it.get("impressions") or 0)
        clicks = int(it.get("clicks") or 0)
        spend = round(it.get("spend") or 0, 2)
        sales = round(it.get("sales") or 0, 2)
        ctr = it.get("ctr") if it.get("ctr") is not None else (round(clicks / imp * 100, 2) if imp else 0.0)
        roi = it.get("roi") if it.get("roi") is not None else (round(sales / spend, 2) if spend else 0.0)
        conv = it.get("conversion_rate") if it.get("conversion_rate") is not None else 0.0
        db.execute(
            "INSERT INTO promo_realtime (store_id, scene, scene_name, data_date, hour, impressions, clicks, ctr, spend, sales, roi, orders, conversion_rate, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(store_id, scene, data_date, hour) DO UPDATE SET "
            "impressions = excluded.impressions, clicks = excluded.clicks, ctr = excluded.ctr, "
            "spend = excluded.spend, sales = excluded.sales, roi = excluded.roi, "
            "orders = excluded.orders, conversion_rate = excluded.conversion_rate",
            (
                store_id,
                it["scene"],
                it["scene_name"],
                today,
                it["hour"],
                imp,
                clicks,
                ctr,
                spend,
                sales,
                roi,
                int(it.get("orders") or 0),
                conv,
                now,
            ),
        )
    return len(items)


@router.get("")
def list_promotions() -> dict:
    return {"items": [], "message": "推广管理：使用推广数据与推广计划功能"}


@router.get("/account")
def promo_account(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    stores = _bound_stores(db)
    last = db.execute("SELECT value FROM meta WHERE key = 'promo_last_sync'").fetchone()
    return {
        "bound_stores": [{"id": s["id"], "name": s["name"]} for s in stores],
        "last_sync": last["value"] if last else None,
    }


@router.post("/test")
def test_promo(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    stores = _bound_stores(db)
    if not stores:
        raise HTTPException(status_code=400, detail="还没有绑定店铺，请先在店铺管理绑定生意参谋登录")
    results = []
    for store in stores:
        try:
            check_access(store)
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": True})
        except AlimamaError as exc:
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": str(exc)})
    return {"results": results}


@router.get("/data")
def promo_data(
    mode: str = "realtime",
    scene: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    mode = _mode(mode)
    today = date_cls.today()

    if mode == "realtime":
        rows = db.execute(
            "SELECT * FROM promo_realtime WHERE data_date = ? ORDER BY hour ASC, scene ASC",
            (today.isoformat(),),
        ).fetchall()
        summary = {"impressions": 0, "clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0, "add_cart": 0}
        scene_map: dict[str, dict] = {}
        hour_map: dict[str, dict] = {}
        for r in rows:
            for f in ("impressions", "clicks", "spend", "sales", "orders"):
                summary[f] += r[f] or 0
            key = r["scene"]
            item = scene_map.setdefault(
                key,
                {"scene": key, "scene_name": r["scene_name"], "impressions": 0, "clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0, "add_cart": 0},
            )
            for f in ("impressions", "clicks", "spend", "sales", "orders"):
                item[f] += r[f] or 0
            h = r["hour"]
            hrow = hour_map.setdefault(
                h,
                {"label": h, "impressions": 0, "clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0, "roi": 0.0},
            )
            for f in ("impressions", "clicks", "spend", "sales", "orders"):
                hrow[f] += r[f] or 0
        scenes = sorted((_finalize(v) for v in scene_map.values()), key=lambda x: x["spend"], reverse=True)
        trend = []
        for h in sorted(hour_map.keys()):
            row = hour_map[h]
            trend.append(
                {
                    "label": row["label"],
                    "impressions": row["impressions"],
                    "clicks": row["clicks"],
                    "spend": round(row["spend"], 2),
                    "sales": round(row["sales"], 2),
                    "orders": row["orders"],
                    "roi": round(row["sales"] / row["spend"], 2) if row["spend"] else 0.0,
                }
            )
        return {
            "mode": mode,
            "summary": _finalize(summary),
            "scenes": scenes,
            "trend": trend,
            "trend_unit": "hour",
            "last_sync": _last_sync(db),
            "bound_stores": len(_bound_stores(db)),
        }

    # yesterday / 7d：按天报表（分场景）
    if mode == "yesterday":
        start = today - timedelta(days=1)
        end = today - timedelta(days=1)
    else:
        start = today - timedelta(days=6)
        end = today - timedelta(days=1)
    query = "SELECT * FROM promo_daily_data WHERE data_date >= ? AND data_date <= ?"
    params: list = [start.isoformat(), end.isoformat()]
    if scene:
        query += " AND scene = ?"
        params.append(scene)
    rows = db.execute(query + " ORDER BY data_date ASC, scene ASC", params).fetchall()

    scene_map: dict[str, dict] = {}
    date_map: dict[str, dict] = {}
    totals = {"impressions": 0, "clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0, "add_cart": 0}
    for r in rows:
        key = r["scene"]
        item = scene_map.setdefault(
            key,
            {
                "scene": key,
                "scene_name": r["scene_name"],
                "impressions": 0,
                "clicks": 0,
                "spend": 0.0,
                "sales": 0.0,
                "orders": 0,
                "add_cart": 0,
            },
        )
        for f in totals:
            item[f] += r[f] or 0
            totals[f] += r[f] or 0
        d = r["data_date"]
        drow = date_map.setdefault(d, {"date": d, "impressions": 0, "clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0})
        for f in ("impressions", "clicks", "spend", "sales", "orders"):
            drow[f] += r[f] or 0

    scenes = sorted((_finalize(v) for v in scene_map.values()), key=lambda x: x["spend"], reverse=True)
    span = (end - start).days + 1
    trend = []
    for i in range(span - 1, -1, -1):
        d = (end - timedelta(days=i)).isoformat()
        row = date_map.get(d)
        label = (end - timedelta(days=i)).strftime("%m-%d")
        if not row:
            trend.append({"label": label, "impressions": 0, "clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0, "roi": 0.0})
            continue
        trend.append(
            {
                "label": label,
                "impressions": row["impressions"],
                "clicks": row["clicks"],
                "spend": round(row["spend"], 2),
                "sales": round(row["sales"], 2),
                "orders": row["orders"],
                "roi": round(row["sales"] / row["spend"], 2) if row["spend"] else 0.0,
            }
        )

    return {
        "mode": mode,
        "summary": _finalize(dict(totals)),
        "scenes": scenes,
        "trend": trend,
        "trend_unit": "day",
        "last_sync": _last_sync(db),
        "bound_stores": len(_bound_stores(db)),
    }


def _last_sync(db) -> str | None:
    row = db.execute("SELECT value FROM meta WHERE key = 'promo_last_sync'").fetchone()
    return row["value"] if row else None


@router.post("/sync")
def sync_promo(
    mode: str = "realtime",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    mode = _mode(mode)
    today = date_cls.today()
    results = []
    for store in _bound_stores(db):
        try:
            now = _now()
            if mode == "realtime":
                items = fetch_realtime(store)
                count = _store_realtime_rows(db, store["id"], items, now)
            elif mode == "yesterday":
                d = today - timedelta(days=1)
                items = fetch_scene_daily(store, d.isoformat(), d.isoformat())
                count = _store_daily_rows(db, store["id"], items, now)
            else:
                start = today - timedelta(days=6)
                end = today - timedelta(days=1)
                items = fetch_scene_daily(store, start.isoformat(), end.isoformat())
                count = _store_daily_rows(db, store["id"], items, now)
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": True, "rows": count})
        except AlimamaError as exc:
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": str(exc)})
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('promo_last_sync', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_now(),),
    )
    _log(db, user, "同步万相台数据", "", f"模式={mode} 成功 {sum(1 for r in results if r['ok'])} / {len(results)} 家")
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"])}


@router.get("/plans")
def list_plans(
    scene: str = "",
    mode: str = "realtime",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    mode = _mode(mode)
    query = (
        "SELECT p.*, COALESCE(s.spend, 0) AS stat_spend, COALESCE(s.sales, 0) AS stat_sales, "
        "COALESCE(s.roi, 0) AS stat_roi, COALESCE(s.clicks, 0) AS stat_clicks "
        "FROM promo_plans p "
        "LEFT JOIN promo_plan_stats s ON s.store_id = p.store_id AND s.campaign_id = p.campaign_id AND s.mode = ?"
    )
    params: list = [mode]
    if scene:
        query += " WHERE p.scene = ?"
        params.append(scene)
    query += " ORDER BY CASE p.status WHEN '在投' THEN 0 ELSE 1 END, stat_spend DESC, p.id ASC"
    rows = db.execute(query, params).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["spend"] = d.pop("stat_spend", 0) or 0
        d["sales"] = d.pop("stat_sales", 0) or 0
        d["roi"] = d.pop("stat_roi", 0) or 0
        d["clicks"] = d.pop("stat_clicks", 0) or 0
        d["mode"] = mode
        items.append(d)
    return {"items": items, "mode": mode}


@router.post("/sync-plans")
def sync_plans(
    mode: str = "realtime",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    mode = _mode(mode)
    today = date_cls.today()
    results = []
    for store in _bound_stores(db):
        try:
            snapshots = fetch_plan_snapshots(store)
            if mode == "realtime":
                stats_list = fetch_plan_realtime(store)
            elif mode == "yesterday":
                d = today - timedelta(days=1)
                stats_list = fetch_plan_reports(store, d.isoformat(), d.isoformat())
            else:
                start = today - timedelta(days=6)
                end = today - timedelta(days=1)
                stats_list = fetch_plan_reports(store, start.isoformat(), end.isoformat())
            stats_map = {r["campaign_id"]: r for r in stats_list}
            now = _now()
            for p in snapshots:
                db.execute(
                    "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, day_budget, bid_type, bid_value, status, gmt_create, spend, sales, roi, clicks, note, tag, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, '', '', ?) "
                    "ON CONFLICT(store_id, campaign_id) DO UPDATE SET "
                    "scene = excluded.scene, scene_name = excluded.scene_name, plan_name = excluded.plan_name, "
                    "day_budget = excluded.day_budget, bid_type = excluded.bid_type, bid_value = excluded.bid_value, "
                    "status = excluded.status, gmt_create = excluded.gmt_create, updated_at = excluded.updated_at",
                    (
                        store["id"],
                        p["scene"],
                        p["scene_name"],
                        p["campaign_id"],
                        p["plan_name"],
                        p["day_budget"],
                        p["bid_type"],
                        p["bid_value"],
                        p["status"],
                        p["gmt_create"],
                        now,
                    ),
                )
                st = stats_map.get(p["campaign_id"])
                if st:
                    db.execute(
                        "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(store_id, campaign_id, mode) DO UPDATE SET "
                        "spend = excluded.spend, sales = excluded.sales, roi = excluded.roi, "
                        "clicks = excluded.clicks, updated_at = excluded.updated_at",
                        (
                            store["id"],
                            p["campaign_id"],
                            mode,
                            st["spend"],
                            st["sales"],
                            st["roi"],
                            st["clicks"],
                            now,
                        ),
                    )
            results.append(
                {"store_id": store["id"], "store_name": store["name"], "ok": True, "plans": len(snapshots)}
            )
        except AlimamaError as exc:
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": str(exc)})
    _log(db, user, "同步推广计划", "", f"模式={mode} 成功 {sum(1 for r in results if r['ok'])} / {len(results)} 家")
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"])}


@router.post("/sync-items")
def sync_items(
    mode: str = "realtime",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """同步商品级推广数据到 promo_item_stats。

    优先方案A：万相台商品报表（report-item / report-realtime，按商品维度）；
    商品报表为空或失败时退回方案B：宝贝↔计划映射 + 计划花费归因（单商品计划全额，多商品均摊）。
    """
    today = date_cls.today()
    if mode == "realtime":
        start = end = today.isoformat()
        realtime = True
        db_mode = "realtime"
    elif mode == "yesterday":
        d = today - timedelta(days=1)
        start = end = d.isoformat()
        realtime = False
        db_mode = "yesterday"
    else:
        try:
            days = int(mode)
        except (TypeError, ValueError):
            days = 7
        if not (1 <= days <= 90):
            days = 7
        start = (today - timedelta(days=days - 1)).isoformat()
        end = today.isoformat()
        realtime = False
        db_mode = str(days)
    now = _now()
    results = []
    for store in _bound_stores(db):
        try:
            if realtime:
                # 实时：走推广「计划→商品」口径（全站推广+关键词+人群，不含内容营销），
                # 与万相台各推广模块一致；实时商品报表混入大量短视频条目，不能用作商品推广数据
                rows = fetch_item_promo_plan_based(store, start, end, realtime=True)
                source = "plan_scene"
                if not rows:
                    rows = fetch_promo_item_fallback(store, start, end, realtime=True)
                    source = "plan"
            else:
                rows = fetch_item_report(store, start, end, realtime=False)
                source = "report"
                if not rows:
                    rows = fetch_promo_item_fallback(store, start, end, realtime=False)
                    source = "plan"
            for it in rows:
                db.execute(
                    "INSERT INTO promo_item_stats (store_id, item_id, item_title, mode, spend, sales, roi, clicks, orders, impressions, source, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(store_id, item_id, mode) DO UPDATE SET "
                    "item_title = excluded.item_title, spend = excluded.spend, sales = excluded.sales, roi = excluded.roi, "
                    "clicks = excluded.clicks, orders = excluded.orders, impressions = excluded.impressions, "
                    "source = excluded.source, updated_at = excluded.updated_at",
                    (
                        store["id"], it["item_id"], it.get("item_title") or "", db_mode,
                        it.get("spend") or 0, it.get("sales") or 0, it.get("roi") or 0,
                        it.get("clicks") or 0, it.get("orders") or 0, it.get("impressions") or 0,
                        source, now,
                    ),
                )
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": True, "rows": len(rows), "source": source})
        except AlimamaError as exc:
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": str(exc)})
    _log(db, user, "同步商品推广数据", "", f"模式={db_mode} 成功 {sum(1 for r in results if r['ok'])} / {len(results)} 家")
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"]), "mode": db_mode}


def sync_promo_realtime_all(db) -> dict:
    """同步万相台今日实时分时数据到 promo_realtime（后台定时与接口共用）。"""
    from backend.app.core.alimama import AlimamaError, fetch_realtime

    now = _now()
    results = []
    for store in _bound_stores(db):
        try:
            items = fetch_realtime(store)
            count = _store_realtime_rows(db, store["id"], items, now)
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": True, "rows": count})
        except AlimamaError as exc:
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": str(exc)})
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"])}


def sync_promo_items_realtime_all(db) -> dict:
    """同步商品级实时推广数据到 promo_item_stats（后台定时与接口共用）。

    走「计划→商品」口径（全站推广+关键词+人群，不含内容营销）。
    """
    from backend.app.core.alimama import AlimamaError, fetch_item_promo_plan_based, fetch_promo_item_fallback

    today = date_cls.today().isoformat()
    now = _now()
    results = []
    for store in _bound_stores(db):
        try:
            rows = fetch_item_promo_plan_based(store, today, today, realtime=True)
            source = "plan_scene"
            if not rows:
                rows = fetch_promo_item_fallback(store, today, today, realtime=True)
                source = "plan"
            for it in rows:
                db.execute(
                    "INSERT INTO promo_item_stats (store_id, item_id, item_title, mode, spend, sales, roi, clicks, orders, impressions, source, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(store_id, item_id, mode) DO UPDATE SET "
                    "item_title = excluded.item_title, spend = excluded.spend, sales = excluded.sales, roi = excluded.roi, "
                    "clicks = excluded.clicks, orders = excluded.orders, impressions = excluded.impressions, "
                    "source = excluded.source, updated_at = excluded.updated_at",
                    (
                        store["id"], it["item_id"], it.get("item_title") or "", "realtime",
                        it.get("spend") or 0, it.get("sales") or 0, it.get("roi") or 0,
                        it.get("clicks") or 0, it.get("orders") or 0, it.get("impressions") or 0,
                        source, now,
                    ),
                )
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": True, "rows": len(rows)})
        except AlimamaError as exc:
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": str(exc)})
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"])}


@router.post("/sync-hourly")
def sync_promo_hourly(
    days: int = 7,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """补拉最近 N 天（不含今天）各推广场景的 24 小时分时数据到 promo_realtime。"""
    from backend.app.core.alimama import AlimamaError, fetch_scene_hourly

    if not (1 <= days <= 30):
        days = 7
    today = date_cls.today()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(1, days + 1)]
    now = _now()
    results = []
    for store in _bound_stores(db):
        total = 0
        err = None
        for d in dates:
            try:
                items = fetch_scene_hourly(store, d)
                total += _store_realtime_rows(db, store["id"], items, now, data_date=d)
            except AlimamaError as exc:
                err = str(exc)
                break
        results.append({"store_id": store["id"], "store_name": store["name"], "ok": err is None, "rows": total, "error": err})
    _log(db, user, "补推广分时", "", f"近 {days} 天 成功 {sum(1 for r in results if r['ok'])} / {len(results)} 家")
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"]), "days": len(dates)}


@router.put("/plans/{plan_id}")
def update_plan(
    plan_id: int,
    body: PlanNoteIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    row = db.execute("SELECT * FROM promo_plans WHERE id = ?", (plan_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="推广计划不存在")
    db.execute(
        "UPDATE promo_plans SET note = ?, tag = ?, updated_at = ? WHERE id = ?",
        (body.note.strip(), body.tag.strip(), _now(), plan_id),
    )
    _log(db, user, "编辑推广计划", row["plan_name"], "备注/标记更新")
    return {"ok": True}
