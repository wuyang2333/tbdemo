"""推广管理：万相台推广数据（自动抓取，复用店铺登录态）+ 推广计划管理（计划快照 + 本地备注/标记）。"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import get_current_user
from backend.app.core.alimama import (
    AlimamaError,
    check_access,
    fetch_plan_reports,
    fetch_plan_snapshots,
    fetch_scene_daily,
)
from backend.app.core.db import get_db
from backend.app.core.logs import log_op
from backend.app.core.sycm import has_profile

router = APIRouter()


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


def _range(days: int) -> tuple[date_cls, date_cls]:
    today = date_cls.today()
    return today - timedelta(days=days - 1), today


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
    days: int = 14,
    scene: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not (1 <= days <= 90):
        days = 14
    start, today = _range(days)
    query = "SELECT * FROM promo_daily_data WHERE data_date >= ? AND data_date <= ?"
    params: list = [start.isoformat(), today.isoformat()]
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

    def finalize(item: dict) -> dict:
        item["ctr"] = round(item["clicks"] / item["impressions"] * 100, 2) if item["impressions"] else 0.0
        item["roi"] = round(item["sales"] / item["spend"], 2) if item["spend"] else 0.0
        item["spend"] = round(item["spend"], 2)
        item["sales"] = round(item["sales"], 2)
        return item

    scenes = sorted((finalize(v) for v in scene_map.values()), key=lambda x: x["spend"], reverse=True)
    trend = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        row = date_map.get(d)
        if not row:
            trend.append({"date": (today - timedelta(days=i)).strftime("%m-%d"), "impressions": 0, "clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0, "roi": 0.0})
            continue
        trend.append(
            {
                "date": row["date"][5:],
                "impressions": row["impressions"],
                "clicks": row["clicks"],
                "spend": round(row["spend"], 2),
                "sales": round(row["sales"], 2),
                "orders": row["orders"],
                "roi": round(row["sales"] / row["spend"], 2) if row["spend"] else 0.0,
            }
        )

    summary = finalize(dict(totals))
    last = db.execute("SELECT value FROM meta WHERE key = 'promo_last_sync'").fetchone()
    return {
        "summary": summary,
        "scenes": scenes,
        "trend": trend,
        "days": days,
        "scene": scene,
        "bound_stores": len(_bound_stores(db)),
        "last_sync": last["value"] if last else None,
    }


@router.post("/sync")
def sync_promo(
    days: int = 7,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not (1 <= days <= 30):
        days = 7
    today = date_cls.today()
    start = today - timedelta(days=days - 1)
    end = today - timedelta(days=1)
    results = []
    for store in _bound_stores(db):
        try:
            items = fetch_scene_daily(store, start.isoformat(), end.isoformat())
            now = _now()
            for it in items:
                db.execute(
                    "INSERT INTO promo_daily_data (store_id, scene, scene_name, data_date, impressions, clicks, ctr, spend, sales, roi, orders, add_cart, conversion_rate, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(store_id, scene, data_date) DO UPDATE SET "
                    "impressions = excluded.impressions, clicks = excluded.clicks, ctr = excluded.ctr, "
                    "spend = excluded.spend, sales = excluded.sales, roi = excluded.roi, "
                    "orders = excluded.orders, add_cart = excluded.add_cart, conversion_rate = excluded.conversion_rate",
                    (
                        store["id"],
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
            results.append(
                {"store_id": store["id"], "store_name": store["name"], "ok": True, "days": len(items)}
            )
        except AlimamaError as exc:
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": str(exc)})
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('promo_last_sync', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_now(),),
    )
    _log(db, user, "同步万相台数据", "", f"成功 {sum(1 for r in results if r['ok'])} / {len(results)} 家")
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"])}


@router.get("/plans")
def list_plans(
    scene: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    query = "SELECT * FROM promo_plans"
    params: list = []
    if scene:
        query += " WHERE scene = ?"
        params.append(scene)
    query += " ORDER BY CASE status WHEN '在投' THEN 0 ELSE 1 END, spend DESC, id ASC"
    rows = db.execute(query, params).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("/sync-plans")
def sync_plans(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    today = date_cls.today()
    start = today - timedelta(days=6)
    end = today - timedelta(days=1)
    results = []
    for store in _bound_stores(db):
        try:
            snapshots = fetch_plan_snapshots(store)
            reports = fetch_plan_reports(store, start.isoformat(), end.isoformat())
            report_map = {r["campaign_id"]: r for r in reports}
            now = _now()
            for p in snapshots:
                rep = report_map.get(p["campaign_id"], {})
                db.execute(
                    "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, day_budget, bid_type, bid_value, status, gmt_create, spend, sales, roi, clicks, note, tag, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?) "
                    "ON CONFLICT(store_id, campaign_id) DO UPDATE SET "
                    "scene = excluded.scene, scene_name = excluded.scene_name, plan_name = excluded.plan_name, "
                    "day_budget = excluded.day_budget, bid_type = excluded.bid_type, bid_value = excluded.bid_value, "
                    "status = excluded.status, gmt_create = excluded.gmt_create, spend = excluded.spend, "
                    "sales = excluded.sales, roi = excluded.roi, clicks = excluded.clicks, updated_at = excluded.updated_at",
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
                        rep.get("spend", 0),
                        rep.get("sales", 0),
                        rep.get("roi", 0),
                        rep.get("clicks", 0),
                        now,
                    ),
                )
            results.append(
                {"store_id": store["id"], "store_name": store["name"], "ok": True, "plans": len(snapshots)}
            )
        except AlimamaError as exc:
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": str(exc)})
    _log(db, user, "同步推广计划", "", f"成功 {sum(1 for r in results if r['ok'])} / {len(results)} 家")
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
    _log(db, user, "编辑推广计划", row["plan_name"], f"备注/标记更新")
    return {"ok": True}
