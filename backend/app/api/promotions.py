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
    fetch_plan_realtime,
    fetch_plan_reports,
    fetch_plan_snapshots,
    fetch_realtime,
    fetch_scene_daily,
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


def _store_realtime_rows(db, store_id: int, items: list[dict], now: str) -> int:
    today = date_cls.today().isoformat()
    for it in items:
        db.execute(
            "INSERT INTO promo_realtime (store_id, data_date, hour, impressions, clicks, ctr, spend, sales, roi, orders, conversion_rate, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(store_id, data_date, hour) DO UPDATE SET "
            "impressions = excluded.impressions, clicks = excluded.clicks, ctr = excluded.ctr, "
            "spend = excluded.spend, sales = excluded.sales, roi = excluded.roi, "
            "orders = excluded.orders, conversion_rate = excluded.conversion_rate",
            (
                store_id,
                today,
                it["hour"],
                it["impressions"],
                it["clicks"],
                it["ctr"],
                it["spend"],
                it["sales"],
                it["roi"],
                it["orders"],
                it["conversion_rate"],
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
            "SELECT * FROM promo_realtime WHERE data_date = ? ORDER BY hour ASC",
            (today.isoformat(),),
        ).fetchall()
        summary = {"impressions": 0, "clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0, "add_cart": 0}
        trend = []
        for r in rows:
            summary["impressions"] += r["impressions"] or 0
            summary["clicks"] += r["clicks"] or 0
            summary["spend"] += r["spend"] or 0
            summary["sales"] += r["sales"] or 0
            summary["orders"] += r["orders"] or 0
            trend.append(
                {
                    "label": r["hour"],
                    "impressions": r["impressions"] or 0,
                    "clicks": r["clicks"] or 0,
                    "spend": round(r["spend"] or 0, 2),
                    "sales": round(r["sales"] or 0, 2),
                    "orders": r["orders"] or 0,
                    "roi": round((r["sales"] or 0) / (r["spend"] or 0), 2) if r["spend"] else 0.0,
                }
            )
        return {
            "mode": mode,
            "summary": _finalize(summary),
            "scenes": [],
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
