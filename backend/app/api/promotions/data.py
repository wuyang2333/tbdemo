"""推广管理：数据、计划、同步、导出、关键词。"""

from __future__ import annotations

import json

from datetime import date as date_cls
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import get_current_user, visible_store_ids
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
from backend.app.core.sycm import PROFILE_MISSING_MSG, has_profile

from ._common import (
    MODES,
    PlanNoteIn,
    _now,
    _log,
    _scope_filter,
    _bound_stores,
    _all_stores,
    sync_promo_daily_all,
    _mode,
    _finalize,
    _store_daily_rows,
    _store_realtime_rows,
    _last_sync,
    sync_promo_realtime_all,
    sync_promo_items_realtime_all,
    _promo_insight_data,
    _build_promo_prompt,
    _lookup_item_image,
    _refresh_plan_items,
    PlanStatusIn,
    PlanChatIn,
    PlanChatBody,
    _ensure_plan_daily,
    _collect_plan_data,
    _build_plan_prompt,
)

router = APIRouter()

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
    start: str = "",
    end: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    mode = _mode(mode)
    today = date_cls.today()
    scope_frag, scope_params = _scope_filter(None, user)
    visible = visible_store_ids(user)
    if visible is None:
        bound_store_count = len(_bound_stores(db))
    else:
        bound_store_count = sum(1 for s in _bound_stores(db) if s["id"] in visible)

    # 自定义时间区间
    use_range = bool(start.strip() and end.strip())
    range_start = range_end = None
    if use_range:
        try:
            range_start = date_cls.fromisoformat(start.strip())
            range_end = date_cls.fromisoformat(end.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式不正确（应为 YYYY-MM-DD）")
        if range_start > range_end:
            range_start, range_end = range_end, range_start
        mode = "range"

    def _pct(cur, prev):
        if prev and prev > 0:
            return round((cur - prev) / prev * 100, 1)
        return None

    def _store_sales(cur_hour: str | None = None) -> float:
        """店铺销售额（真实ROI/广告占比用）。实时档用分时今日累计，历史档用日数据区间。"""
        if cur_hour is not None:
            row = db.execute(
                "SELECT COALESCE(SUM(sales),0) AS s FROM store_hourly_data WHERE data_date = ? AND hour <= ?" + scope_frag,
                [today.isoformat(), cur_hour] + scope_params,
            ).fetchone()
        else:
            if mode == "yesterday":
                sd = ed = today - timedelta(days=1)
            elif mode == "range":
                sd, ed = range_start, range_end
            else:
                sd, ed = today - timedelta(days=6), today - timedelta(days=1)
            row = db.execute(
                "SELECT COALESCE(SUM(sales),0) AS s FROM store_daily_data WHERE data_date >= ? AND data_date <= ?" + scope_frag,
                [sd.isoformat(), ed.isoformat()] + scope_params,
            ).fetchone()
        return float(row["s"] or 0.0)

    def _final_summary(raw: dict, store_sales: float) -> dict:
        s = _finalize(raw)
        s["real_roi"] = round(store_sales / s["spend"], 2) if s["spend"] else 0.0
        s["ad_share"] = round(s["spend"] / store_sales * 100, 1) if store_sales else 0.0
        s["cost_per_order"] = round(s["spend"] / s["orders"], 2) if s["orders"] else 0.0
        return s

    def _alerts(scenes: list[dict]) -> list[dict]:
        out = []
        for s in scenes:
            if s["roi"] > 0 and s["roi"] < 2:
                out.append({"type": "warn", "message": f"「{s['scene_name']}」ROI {s['roi']:.2f} 偏低（低于 2）"})
        return out

    if mode == "realtime":
        cur_hour = datetime.now().strftime("%H:00")
        rows = db.execute(
            "SELECT * FROM promo_realtime WHERE data_date = ?" + scope_frag + " ORDER BY hour ASC, scene ASC",
            [today.isoformat()] + scope_params,
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
            hrow = hour_map.setdefault(h, {"label": h, "impressions": 0, "clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0, "roi": 0.0})
            for f in ("impressions", "clicks", "spend", "sales", "orders"):
                hrow[f] += r[f] or 0
        scenes = sorted((_finalize(v) for v in scene_map.values()), key=lambda x: x["spend"], reverse=True)
        trend = []
        for h in sorted(hour_map.keys()):
            row = hour_map[h]
            trend.append(
                {
                    "label": row["label"], "impressions": row["impressions"], "clicks": row["clicks"],
                    "spend": round(row["spend"], 2), "sales": round(row["sales"], 2), "orders": row["orders"],
                    "roi": round(row["sales"] / row["spend"], 2) if row["spend"] else 0.0,
                }
            )
        # 较昨日同时段
        yest_rows = db.execute(
            "SELECT * FROM promo_realtime WHERE data_date = ? AND hour <= ?" + scope_frag,
            [(today - timedelta(days=1)).isoformat(), cur_hour] + scope_params,
        ).fetchall()
        y_sum = {"spend": 0.0, "sales": 0.0}
        for r in yest_rows:
            y_sum["spend"] += r["spend"] or 0
            y_sum["sales"] += r["sales"] or 0
        store_sales = _store_sales(cur_hour=cur_hour)
        summary = _final_summary(summary, store_sales)
        return {
            "mode": mode,
            "summary": summary,
            "compare": {"spend": _pct(summary["spend"], y_sum["spend"]), "sales": _pct(summary["sales"], y_sum["sales"])},
            "scenes": scenes,
            "alerts": _alerts(scenes),
            "trend": trend,
            "trend_unit": "hour",
            "last_sync": _last_sync(db),
            "bound_stores": bound_store_count,
        }

    # yesterday / 7d / range：按天报表（分场景）
    if mode == "yesterday":
        start_d = end_d = today - timedelta(days=1)
    elif mode == "range":
        start_d, end_d = range_start, range_end
    else:
        start_d, end_d = today - timedelta(days=6), today - timedelta(days=1)
    query = "SELECT * FROM promo_daily_data WHERE data_date >= ? AND data_date <= ?" + scope_frag
    params: list = [start_d.isoformat(), end_d.isoformat()] + scope_params
    if scene:
        query += " AND scene = ?"
        params.append(scene)
    rows = db.execute(query + " ORDER BY data_date ASC, scene ASC", params).fetchall()

    scene_map = {}
    date_map = {}
    totals = {"impressions": 0, "clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0, "add_cart": 0}
    for r in rows:
        key = r["scene"]
        item = scene_map.setdefault(
            key,
            {"scene": key, "scene_name": r["scene_name"], "impressions": 0, "clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0, "add_cart": 0},
        )
        for f in totals:
            item[f] += r[f] or 0
            totals[f] += r[f] or 0
        d = r["data_date"]
        drow = date_map.setdefault(d, {"date": d, "impressions": 0, "clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0})
        for f in ("impressions", "clicks", "spend", "sales", "orders"):
            drow[f] += r[f] or 0

    scenes = sorted((_finalize(v) for v in scene_map.values()), key=lambda x: x["spend"], reverse=True)
    span = (end_d - start_d).days + 1
    trend = []
    for i in range(span - 1, -1, -1):
        d = (end_d - timedelta(days=i)).isoformat()
        row = date_map.get(d)
        label = (end_d - timedelta(days=i)).strftime("%m-%d")
        if not row:
            trend.append({"label": label, "impressions": 0, "clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0, "roi": 0.0})
            continue
        trend.append(
            {
                "label": label, "impressions": row["impressions"], "clicks": row["clicks"],
                "spend": round(row["spend"], 2), "sales": round(row["sales"], 2), "orders": row["orders"],
                "roi": round(row["sales"] / row["spend"], 2) if row["spend"] else 0.0,
            }
        )

    # 较上周同期
    prev_end = start_d - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    prev_totals = {"spend": 0.0, "sales": 0.0}
    if prev_start >= date_cls(2000, 1, 1):
        prev_rows = db.execute(
            "SELECT * FROM promo_daily_data WHERE data_date >= ? AND data_date <= ?" + scope_frag,
            [prev_start.isoformat(), prev_end.isoformat()] + scope_params,
        ).fetchall()
        for r in prev_rows:
            prev_totals["spend"] += r["spend"] or 0
            prev_totals["sales"] += r["sales"] or 0

    store_sales = _store_sales()
    summary = _final_summary(totals, store_sales)
    return {
        "mode": mode,
        "summary": summary,
        "compare": {"spend": _pct(summary["spend"], prev_totals["spend"]), "sales": _pct(summary["sales"], prev_totals["sales"])},
        "scenes": scenes,
        "alerts": _alerts(scenes),
        "trend": trend,
        "trend_unit": "day",
        "last_sync": _last_sync(db),
        "bound_stores": bound_store_count,
    }

@router.post("/sync")
def sync_promo(
    mode: str = "realtime",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    mode = _mode(mode)
    today = date_cls.today()
    results = []
    for store in _all_stores(db):
        if not has_profile(store["id"]):
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": PROFILE_MISSING_MSG})
            continue
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
        "COALESCE(s.roi, 0) AS stat_roi, COALESCE(s.clicks, 0) AS stat_clicks, "
        "COALESCE(s.prev_spend, 0) AS prev_spend, COALESCE(s.prev_sales, 0) AS prev_sales, "
        "COALESCE(s.prev_roi, 0) AS prev_roi, COALESCE(s.prev_clicks, 0) AS prev_clicks, "
        "COALESCE(s.alipay_dir, 0) AS stat_alipay_dir, COALESCE(s.alipay_indir, 0) AS stat_alipay_indir, "
        "COALESCE(s.retained_sales, 0) AS stat_retained_sales, COALESCE(s.retained_roi, 0) AS stat_retained_roi, "
        "COALESCE(s.refund_amt, 0) AS stat_refund_amt, COALESCE(s.extra_json, '') AS stat_extra "
        "FROM promo_plans p "
        "LEFT JOIN promo_plan_stats s ON s.store_id = p.store_id AND s.campaign_id = p.campaign_id AND s.mode = ?"
    )
    params: list = [mode]
    where_parts: list[str] = []
    visible = visible_store_ids(user)
    if visible is None:
        pass
    elif not visible:
        where_parts.append("1=0")
    else:
        where_parts.append("p.store_id IN (%s)" % ",".join(str(i) for i in sorted(visible)))
    if scene:
        where_parts.append("p.scene = ?")
        params.append(scene)
    if where_parts:
        query += " WHERE " + " AND ".join(where_parts)
    query += " ORDER BY CASE p.status WHEN '在投' THEN 0 ELSE 1 END, stat_spend DESC, p.id ASC"
    rows = db.execute(query, params).fetchall()
    items = []
    def _cycle(cur, prev):
        if prev:
            return round((cur - prev) / prev * 100, 2)
        return None

    for r in rows:
        d = dict(r)
        d["spend"] = d.pop("stat_spend", 0) or 0
        d["sales"] = d.pop("stat_sales", 0) or 0
        d["roi"] = d.pop("stat_roi", 0) or 0
        d["clicks"] = d.pop("stat_clicks", 0) or 0
        d["alipay_dir"] = d.pop("stat_alipay_dir", 0) or 0
        d["alipay_indir"] = d.pop("stat_alipay_indir", 0) or 0
        d["retained_sales"] = d.pop("stat_retained_sales", 0) or 0
        d["retained_roi"] = d.pop("stat_retained_roi", 0) or 0
        d["refund_amt"] = d.pop("stat_refund_amt", 0) or 0
        _extra = d.pop("stat_extra", "") or ""
        try:
            d["extra"] = json.loads(_extra) if _extra else {}
        except (ValueError, TypeError):
            d["extra"] = {}
        if mode == "realtime" and d["retained_roi"]:
            d["roi"] = d["retained_roi"]
        d["prev_spend"] = d.pop("prev_spend", 0) or 0
        d["prev_sales"] = d.pop("prev_sales", 0) or 0
        d["prev_roi"] = d.pop("prev_roi", 0) or 0
        d["prev_clicks"] = d.pop("prev_clicks", 0) or 0
        d["spend_cycle"] = _cycle(d["spend"], d["prev_spend"])
        d["sales_cycle"] = _cycle(d["sales"], d["prev_sales"])
        d["roi_cycle"] = _cycle(d["roi"], d["prev_roi"])
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
    for store in _all_stores(db):
        if not has_profile(store["id"]):
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": PROFILE_MISSING_MSG})
            continue
        try:
            snapshots = fetch_plan_snapshots(store)
            if mode == "realtime":
                stats_list = fetch_plan_realtime(store)
                _pd = today - timedelta(days=1)
                prev_list = fetch_plan_reports(store, _pd.isoformat(), _pd.isoformat())
            elif mode == "yesterday":
                d = today - timedelta(days=1)
                stats_list = fetch_plan_reports(store, d.isoformat(), d.isoformat())
                _pd = today - timedelta(days=2)
                prev_list = fetch_plan_reports(store, _pd.isoformat(), _pd.isoformat())
            else:
                start = today - timedelta(days=6)
                end = today - timedelta(days=1)
                stats_list = fetch_plan_reports(store, start.isoformat(), end.isoformat())
                _ps = today - timedelta(days=13)
                _pe = today - timedelta(days=7)
                prev_list = fetch_plan_reports(store, _ps.isoformat(), _pe.isoformat())
            stats_map = {r["campaign_id"]: r for r in stats_list}
            prev_map = {r["campaign_id"]: r for r in prev_list}
            now = _now()
            try:
                _refresh_plan_items(db, store)
            except Exception:  # noqa: BLE001
                pass
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
                    _pv = prev_map.get(p["campaign_id"]) or {}
                    _extra_json = json.dumps({k: v for k, v in st.items() if k != "campaign_id"}, ensure_ascii=False)
                    db.execute(
                        "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, prev_spend, prev_sales, prev_roi, prev_clicks, alipay_dir, alipay_indir, retained_sales, retained_roi, refund_amt, extra_json, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(store_id, campaign_id, mode) DO UPDATE SET "
                        "spend = excluded.spend, sales = excluded.sales, roi = excluded.roi, "
                        "clicks = excluded.clicks, prev_spend = excluded.prev_spend, prev_sales = excluded.prev_sales, "
                        "prev_roi = excluded.prev_roi, prev_clicks = excluded.prev_clicks, "
                        "alipay_dir = excluded.alipay_dir, alipay_indir = excluded.alipay_indir, "
                        "retained_sales = excluded.retained_sales, retained_roi = excluded.retained_roi, "
                        "refund_amt = excluded.refund_amt, extra_json = excluded.extra_json, updated_at = excluded.updated_at",
                        (
                            store["id"],
                            p["campaign_id"],
                            mode,
                            st["spend"],
                            st["sales"],
                            st["roi"],
                            st["clicks"],
                            _pv.get("spend") or 0,
                            _pv.get("sales") or 0,
                            _pv.get("roi") or 0,
                            _pv.get("clicks") or 0,
                            st.get("alipay_dir") or 0,
                            st.get("alipay_indir") or 0,
                            st.get("retained_sales") or 0,
                            st.get("retained_roi") or 0,
                            st.get("refund_amt") or 0,
                            _extra_json,
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
    for store in _all_stores(db):
        if not has_profile(store["id"]):
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": PROFILE_MISSING_MSG})
            continue
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
    for store in _all_stores(db):
        if not has_profile(store["id"]):
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "rows": 0, "error": PROFILE_MISSING_MSG})
            continue
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

@router.get("/alerts")
def promo_alerts(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """推广预警：预算超限/接近预算、ROI较昨日明显下滑（阈值取统一预警配置）。"""
    from backend.app.api.alerts import get_alert_config

    pcfg = (get_alert_config(db) or {}).get("plan") or {}
    budget_over = float(pcfg.get("budget_over") or 1.0)
    budget_warn = float(pcfg.get("budget_warn") or 0.8)
    roi_drop_ratio = float(pcfg.get("roi_drop_ratio") or 0.6)
    roi_low = float(pcfg.get("roi_low") or 1.0)
    alerts = []
    visible = visible_store_ids(user)
    if visible is None:
        store_scope = "1=1"
    elif not visible:
        store_scope = "1=0"
    else:
        store_scope = "p.store_id IN (%s)" % ",".join(str(i) for i in sorted(visible))
    rows = db.execute(
        "SELECT p.plan_name, p.scene_name, p.status, p.day_budget, "
        "COALESCE(rt.spend,0) AS rt_spend, COALESCE(rt.roi,0) AS rt_roi, "
        "COALESCE(ye.spend,0) AS ye_spend, COALESCE(ye.roi,0) AS ye_roi "
        "FROM promo_plans p "
        "LEFT JOIN promo_plan_stats rt ON rt.store_id=p.store_id AND rt.campaign_id=p.campaign_id AND rt.mode='realtime' "
        "LEFT JOIN promo_plan_stats ye ON ye.store_id=p.store_id AND ye.campaign_id=p.campaign_id AND ye.mode='yesterday' "
        "WHERE p.status='在投' AND " + store_scope
    ).fetchall()
    for r in rows:
        name = r["plan_name"] or "未命名计划"
        budget = round(r["day_budget"] or 0, 2)
        rt_spend = round(r["rt_spend"] or 0, 2)
        rt_roi = r["rt_roi"] or 0
        ye_roi = r["ye_roi"] or 0
        if budget > 0 and rt_spend > 0:
            ratio = rt_spend / budget
            if ratio >= budget_over:
                alerts.append({"level": "error", "type": "预算超限", "message": f"「{name}」今日花费 {rt_spend:.0f} 元已超日预算 {budget:.0f} 元，建议调整"})
            elif ratio >= budget_warn:
                alerts.append({"level": "warn", "type": "接近预算", "message": f"「{name}」今日花费已达日预算 {ratio * 100:.0f}%（{rt_spend:.0f}/{budget:.0f} 元）"})
        if rt_spend > 0 and ye_roi > 0 and 0 < rt_roi < ye_roi * roi_drop_ratio:
            alerts.append({"level": "warn", "type": "ROI下滑", "message": f"「{name}」今日ROI {rt_roi:.2f} 较昨日 {ye_roi:.2f} 明显下滑"})
        if rt_spend > 0 and 0 < rt_roi < roi_low:
            alerts.append({"level": "warn", "type": "ROI偏低", "message": f"「{name}」今日ROI {rt_roi:.2f} 低于 {roi_low:.2f}，建议关注"})
    alerts.sort(key=lambda a: 0 if a["level"] == "error" else 1)
    return {"items": alerts[:50], "count": len(alerts)}

@router.get("/export")
def export_promo(
    mode: str = "7d",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """导出推广数据 Excel（实时/昨天=场景明细；近7天=逐日分场景）。"""
    from io import BytesIO
    from urllib.parse import quote

    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook

    mode = _mode(mode)
    today = date_cls.today()
    scope_frag, scope_params = _scope_filter(None, user)
    wb = Workbook()
    ws = wb.active
    if mode in ("realtime", "yesterday"):
        d = today if mode == "realtime" else today - timedelta(days=1)
        table = "promo_realtime" if mode == "realtime" else "promo_daily_data"
        rows = db.execute(
            f"SELECT scene, scene_name, SUM(impressions) AS imp, SUM(clicks) AS clicks, SUM(spend) AS spend, SUM(sales) AS sales, SUM(orders) AS orders FROM {table} WHERE data_date=?" + scope_frag + " GROUP BY scene ORDER BY spend DESC",
            [d.isoformat()] + scope_params,
        ).fetchall()
        ws.append(["场景", "展现", "点击", "花费", "成交", "订单", "ROI"])
        for r in rows:
            spend = r["spend"] or 0
            sales = r["sales"] or 0
            ws.append([r["scene_name"] or r["scene"], r["imp"] or 0, r["clicks"] or 0, round(spend, 2), round(sales, 2), r["orders"] or 0, round(sales / spend, 2) if spend else 0])
        title = "推广数据_实时" if mode == "realtime" else "推广数据_昨天"
    else:
        start = today - timedelta(days=6)
        rows = db.execute(
            "SELECT data_date, scene, scene_name, SUM(spend) AS spend, SUM(sales) AS sales, SUM(orders) AS orders "
            "FROM promo_daily_data WHERE data_date>=? AND data_date<=?" + scope_frag + " GROUP BY data_date, scene ORDER BY data_date, spend DESC",
            [start.isoformat(), today.isoformat()] + scope_params,
        ).fetchall()
        scene_names = {}
        by_date = {}
        for r in rows:
            scene_names[r["scene"]] = r["scene_name"] or r["scene"]
            by_date.setdefault(r["data_date"], {})[r["scene"]] = {"spend": r["spend"] or 0, "sales": r["sales"] or 0}
        dates = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
        scenes = list(scene_names.keys())
        ws.append(["日期"] + [f"{scene_names[s]}花费" for s in scenes] + [f"{scene_names[s]}成交" for s in scenes] + ["合计花费", "合计成交", "合计ROI"])
        for d in dates:
            dd = by_date.get(d, {})
            spend_row = [round(dd.get(s, {}).get("spend", 0), 2) for s in scenes]
            sales_row = [round(dd.get(s, {}).get("sales", 0), 2) for s in scenes]
            ts = sum(spend_row)
            tsa = sum(sales_row)
            ws.append([d] + spend_row + sales_row + [round(ts, 2), round(tsa, 2), round(tsa / ts, 2) if ts else 0])
        title = "推广数据_近七天"
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"推广数据_{mode}_{today.strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )

@router.get("/plans/export")
def export_plans(
    mode: str = "realtime",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """导出推广计划 Excel。"""
    from io import BytesIO
    from urllib.parse import quote

    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook

    mode = _mode(mode)
    visible = visible_store_ids(user)
    if visible is None:
        plan_scope = ""
    elif not visible:
        plan_scope = " WHERE 1=0"
    else:
        plan_scope = " WHERE p.store_id IN (%s)" % ",".join(str(i) for i in sorted(visible))
    rows = db.execute(
        "SELECT p.scene_name, p.plan_name, p.status, p.day_budget, p.bid_type, p.bid_value, "
        "COALESCE(s.spend,0) AS spend, COALESCE(s.sales,0) AS sales, COALESCE(s.roi,0) AS roi, COALESCE(s.clicks,0) AS clicks, "
        "p.note, p.tag "
        "FROM promo_plans p LEFT JOIN promo_plan_stats s ON s.store_id=p.store_id AND s.campaign_id=p.campaign_id AND s.mode=?"
        + plan_scope
        + " ORDER BY COALESCE(s.spend,0) DESC",
        (mode,),
    ).fetchall()
    wb = Workbook()
    ws = wb.active
    ws.append(["场景", "计划名", "状态", "日预算", "出价", "花费", "成交", "ROI", "点击", "备注", "标记"])
    for r in rows:
        spend = r["spend"] or 0
        sales = r["sales"] or 0
        bid = f"{r['bid_value']} {r['bid_type']}" if r["bid_value"] else (r["bid_type"] or "")
        ws.append([r["scene_name"] or r["scene"], r["plan_name"], r["status"], r["day_budget"] or 0, bid.strip(), round(spend, 2), round(sales, 2), round(sales / spend, 2) if spend else 0, r["clicks"] or 0, r["note"] or "", r["tag"] or ""])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"推广计划_{mode}_{date_cls.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )

@router.get("/plan-items")
def plan_items(
    refresh: int = 0,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """计划 ↔ 商品映射（缓存优先，默认 6 小时刷新一次，refresh=1 强制刷新）。"""
    from backend.app.core.sycm import has_profile

    all_stores = [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY id").fetchall() if has_profile(r["id"])]
    visible = visible_store_ids(user)
    if visible is None:
        stores = all_stores
    else:
        stores = [s for s in all_stores if s["id"] in visible]
    stale_cutoff = (datetime.now() - timedelta(hours=6)).isoformat()
    need: list[dict] = []
    for st in stores:
        row = db.execute("SELECT updated_at FROM promo_plan_items WHERE store_id = ? LIMIT 1", (st["id"],)).fetchone()
        if refresh or not row or (row["updated_at"] or "") < stale_cutoff:
            need.append(st)
    for st in need:
        try:
            _refresh_plan_items(db, st)
        except Exception:  # noqa: BLE001
            continue
    result: dict[str, dict] = {}
    scope_frag, scope_params = _scope_filter(None, user)
    for r in db.execute("SELECT * FROM promo_plan_items WHERE 1=1" + scope_frag + " ORDER BY store_id", scope_params).fetchall():
        result[r["campaign_id"]] = {
            "item_id": r["item_id"],
            "item_title": r["item_title"],
            "image": r["image"],
        }
    return {"items": result, "from_cache": not need}

@router.get("/keywords")
def promo_keywords(
    mode: str = "yesterday",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """万相台关键词报表（实时/昨天/近7天，实时可能无数据）。"""
    from backend.app.core.alimama import AlimamaError, _num, _run_json
    from backend.app.core.sycm import has_profile

    today = date_cls.today()
    if mode == "realtime":
        start = end = today.isoformat()
    elif mode == "yesterday":
        d = today - timedelta(days=1)
        start = end = d.isoformat()
    else:
        start = (today - timedelta(days=6)).isoformat()
        end = today.isoformat()
    stores = [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY id").fetchall() if has_profile(r["id"])]
    rows: list[dict] = []
    for store in stores:
        try:
            payload = _run_json(store, ["report-keyword", "--date", start, "--end-date", end, "--limit", "100", "--raw"])
        except AlimamaError:
            continue
        for r in (payload.get("data") or {}).get("list") or []:
            if not isinstance(r, dict):
                continue
            word = r.get("originalWord") or r.get("word") or r.get("bidword") or "（智能匹配）"
            spend = _num(r.get("charge"))
            sales = _num(r.get("alipayInshopAmt"))
            rows.append(
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
    rows.sort(key=lambda x: -x["spend"])
    return {"items": rows[:100], "count": len(rows), "mode": mode}

@router.put("/plans/{plan_id}")
def update_plan(
    plan_id: int,
    body: PlanNoteIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    scope_frag, scope_params = _scope_filter(None, user)
    row = db.execute(
        "SELECT * FROM promo_plans WHERE id = ?" + scope_frag,
        [plan_id] + scope_params,
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="推广计划不存在")
    db.execute(
        "UPDATE promo_plans SET note = ?, tag = ?, updated_at = ? WHERE id = ?" + scope_frag,
        [body.note.strip(), body.tag.strip(), _now(), plan_id] + scope_params,
    )
    _log(db, user, "编辑推广计划", row["plan_name"], "备注/标记更新")
    return {"ok": True}

@router.post("/plans/{plan_id}/status")
def set_plan_status(
    plan_id: int,
    body: PlanStatusIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """暂停/开启某个万相台推广计划（写操作：前端必须二次确认后调用）。

    - execute=False：只预检（列出命中的投放单元），不写万相台。
    - execute=True：真正暂停/开启，并把本地计划状态同步过来。
    """
    from backend.app.core.alimama import _run_json

    if body.status not in ("pause", "start"):
        raise HTTPException(status_code=400, detail="仅支持 pause（暂停）/ start（开启）")
    scope_frag, scope_params = _scope_filter(None, user)
    row = db.execute(
        "SELECT * FROM promo_plans WHERE id = ?" + scope_frag,
        [plan_id] + scope_params,
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="推广计划不存在")
    store = db.execute("SELECT * FROM stores WHERE id = ?", (row["store_id"],)).fetchone()
    if not store or not has_profile(store["id"]):
        raise HTTPException(status_code=400, detail="该店铺未绑定万相台登录，无法操作")
    if row["scene"] not in ("wholesite", "keyword", "crowd"):
        raise HTTPException(status_code=400, detail="该计划场景暂不支持暂停/开启（内容营销除外）")
    store = dict(store)
    target = "暂停" if body.status == "pause" else "开启"
    label = f"{row['plan_name']}（{row['campaign_id']}）"
    try:
        # 先预检：列出命中单元（不写万相台）
        pre = _run_json(
            store,
            ["plan-status", "--campaign", str(row["campaign_id"]), "--scene", row["scene"], "--status", body.status, "--raw"],
        )
        count = int(pre.get("count") or 0)
        if body.execute and count == 0:
            raise HTTPException(status_code=400, detail="未找到该计划的投放单元，无法操作（可能已暂停或数据未同步）")
        if not body.execute:
            _log(db, user, "计划操作(预检)", label, f"{target}，命中 {count} 个单元（未执行）")
            return {"ok": True, "execute": False, "count": count, "units": pre.get("units", [])}
        resp = _run_json(
            store,
            ["plan-status", "--campaign", str(row["campaign_id"]), "--scene", row["scene"], "--status", body.status, "--execute", "--raw"],
        )
    except HTTPException:
        raise
    except AlimamaError as exc:
        raise HTTPException(status_code=502, detail=f"万相台操作失败：{exc}") from exc
    new_status = "暂停" if body.status == "pause" else "在投"
    db.execute(
        "UPDATE promo_plans SET status = ?, updated_at = ? WHERE id = ?" + scope_frag,
        [new_status, _now(), plan_id] + scope_params,
    )
    _log(db, user, "计划操作", label, f"{target}（万相台已执行，命中 {count} 个单元）")
    return {"ok": True, "execute": True, "count": count, "response": str(resp)[:300]}

@router.get("/plans/{plan_id}/trend")
def plan_trend(
    plan_id: int,
    days: int = 7,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """单个计划的每日趋势（花费/成交/ROI/点击），懒加载按天缓存。"""
    days = max(1, min(int(days), 30))
    scope_frag, scope_params = _scope_filter(None, user)
    row = db.execute(
        "SELECT * FROM promo_plans WHERE id = ?" + scope_frag,
        [plan_id] + scope_params,
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="推广计划不存在")
    store = db.execute("SELECT * FROM stores WHERE id = ?", (row["store_id"],)).fetchone()
    if not store or not has_profile(store["id"]):
        raise HTTPException(status_code=400, detail="该店铺未绑定万相台登录")
    store = dict(store)
    today = date_cls.today()
    start = today - timedelta(days=days - 1)
    try:
        _ensure_plan_daily(db, store, start, today, user)
    except Exception:  # noqa: BLE001
        pass
    rows = db.execute(
        "SELECT data_date, spend, sales, roi, clicks FROM promo_plan_daily "
        "WHERE store_id = ? AND campaign_id = ? AND data_date >= ? AND data_date <= ? ORDER BY data_date ASC",
        (store["id"], row["campaign_id"], start.isoformat(), today.isoformat()),
    ).fetchall()
    by_date = {r["data_date"]: dict(r) for r in rows}
    out = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        v = by_date.get(d) or {}
        out.append(
            {
                "date": d,
                "spend": round(v.get("spend") or 0, 2),
                "sales": round(v.get("sales") or 0, 2),
                "roi": round(v.get("roi") or 0, 2),
                "clicks": int(v.get("clicks") or 0),
            }
        )
    return {
        "plan": {"id": row["id"], "plan_name": row["plan_name"], "campaign_id": row["campaign_id"], "scene_name": row["scene_name"]},
        "items": out,
        "days": days,
    }
