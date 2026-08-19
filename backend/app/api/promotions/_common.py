"""推广管理通用工具与同步函数。"""

from __future__ import annotations

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
MODES = ("realtime", "yesterday", "7d")

class PlanNoteIn(BaseModel):
    note: str = ""
    tag: str = ""

def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

def _log(db, user: dict | None, action: str, target: str = "", detail: str = "") -> None:
    if user is None:
        return
    log_op(db, user, "promotions", action, target, detail)

def _scope_filter(store_id, user: dict) -> tuple[str, list]:
    """按当前账号可见店铺生成 SQL 过滤片段；store_id 非空时再叠加指定店铺条件。"""
    visible = visible_store_ids(user)
    if visible is None:
        fragment = ""
        params: list = []
    elif not visible:
        return (" AND 1=0", [])
    else:
        fragment = " AND store_id IN (%s)" % ",".join(str(i) for i in sorted(visible))
        params = []
    if store_id:
        fragment += " AND store_id = ?"
        params.append(store_id)
    return fragment, params

def _bound_stores(db) -> list[dict]:
    return [
        dict(r)
        for r in db.execute("SELECT * FROM stores ORDER BY id ASC").fetchall()
        if has_profile(r["id"])
    ]

def _all_stores(db) -> list[dict]:
    """全部店铺（含未配置档案的），供同步函数显式标记失败原因。"""
    return [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY id ASC").fetchall()]

def sync_promo_daily_all(db, days: int = 7) -> dict:
    """同步近 N 天推广按天数据到 promo_daily_data（经营日报推广数据来源）。

    后台每日定时调用（勿加路由装饰器），单店容错。返回 {"results", "total", "ok"}。
    """
    today = date_cls.today()
    start = today - timedelta(days=days - 1)
    end = today - timedelta(days=1)
    results = []
    for store in _all_stores(db):
        if not has_profile(store["id"]):
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": PROFILE_MISSING_MSG})
            continue
        try:
            items = fetch_scene_daily(store, start.isoformat(), end.isoformat())
            count = _store_daily_rows(db, store["id"], items, _now())
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": True, "rows": count})
        except AlimamaError as exc:
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": str(exc)})
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"])}

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

def _last_sync(db) -> str | None:
    row = db.execute("SELECT value FROM meta WHERE key = 'promo_last_sync'").fetchone()
    return row["value"] if row else None

def sync_promo_realtime_all(db) -> dict:
    """同步万相台今日实时分时数据到 promo_realtime（后台定时与接口共用）。"""
    from backend.app.core.alimama import AlimamaError, fetch_realtime

    now = _now()
    results = []
    for store in _all_stores(db):
        if not has_profile(store["id"]):
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": PROFILE_MISSING_MSG})
            continue
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
    for store in _all_stores(db):
        if not has_profile(store["id"]):
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": PROFILE_MISSING_MSG})
            continue
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

def _promo_insight_data(mode: str, db, user: dict) -> dict:
    mode = _mode(mode)
    today = date_cls.today()
    visible = visible_store_ids(user)
    if visible is None:
        scope_frag = ""
        scope_params: list = []
    elif not visible:
        scope_frag = " AND 1=0"
        scope_params = []
    else:
        scope_frag = " AND store_id IN (%s)" % ",".join(str(i) for i in sorted(visible))
        scope_params = []
    if mode == "realtime":
        scene_rows = db.execute(
            "SELECT scene, scene_name, SUM(spend) AS spend, SUM(sales) AS sales FROM promo_realtime "
            "WHERE data_date = ?" + scope_frag + " GROUP BY scene ORDER BY spend DESC",
            [today.isoformat()] + scope_params,
        ).fetchall()
    elif mode == "yesterday":
        d = (today - timedelta(days=1)).isoformat()
        scene_rows = db.execute(
            "SELECT scene, scene_name, SUM(spend) AS spend, SUM(sales) AS sales FROM promo_daily_data "
            "WHERE data_date = ?" + scope_frag + " GROUP BY scene ORDER BY spend DESC",
            [d] + scope_params,
        ).fetchall()
    else:
        start = (today - timedelta(days=6)).isoformat()
        scene_rows = db.execute(
            "SELECT scene, scene_name, SUM(spend) AS spend, SUM(sales) AS sales FROM promo_daily_data "
            "WHERE data_date >= ? AND data_date <= ?" + scope_frag + " GROUP BY scene ORDER BY spend DESC",
            [start, today.isoformat()] + scope_params,
        ).fetchall()
    scenes = []
    for r in scene_rows:
        spend = round(r["spend"] or 0, 2)
        sales = round(r["sales"] or 0, 2)
        scenes.append({"scene": r["scene"], "scene_name": r["scene_name"] or r["scene"], "spend": spend, "sales": sales, "roi": round(sales / spend, 2) if spend else 0.0})
    if visible is None:
        plan_scope = ""
    elif not visible:
        plan_scope = " WHERE 1=0"
    else:
        plan_scope = " WHERE p.store_id IN (%s)" % ",".join(str(i) for i in sorted(visible))
    plans = db.execute(
        "SELECT p.scene, p.scene_name, p.plan_name, p.status, p.day_budget, "
        "COALESCE(s.spend,0) AS spend, COALESCE(s.sales,0) AS sales, COALESCE(s.roi,0) AS roi, COALESCE(s.clicks,0) AS clicks "
        "FROM promo_plans p LEFT JOIN promo_plan_stats s ON s.store_id = p.store_id AND s.campaign_id = p.campaign_id AND s.mode = ?"
        + plan_scope
        + " ORDER BY COALESCE(s.spend,0) DESC",
        (mode,),
    ).fetchall()
    plan_list = []
    for r in plans:
        spend = round(r["spend"] or 0, 2)
        sales = round(r["sales"] or 0, 2)
        plan_list.append(
            {
                "scene_name": r["scene_name"] or r["scene"] or "?",
                "plan_name": r["plan_name"] or "?",
                "status": r["status"],
                "day_budget": round(r["day_budget"] or 0, 2),
                "spend": spend,
                "sales": sales,
                "roi": round(sales / spend, 2) if spend else 0.0,
                "clicks": int(r["clicks"] or 0),
            }
        )
    total_spend = sum(p["spend"] for p in plan_list)
    total_sales = sum(p["sales"] for p in plan_list)
    active = [p for p in plan_list if p["status"] == "在投"]
    low = [p for p in plan_list if p["spend"] > 0 and p["roi"] < 1]
    mid = [p for p in plan_list if p["spend"] > 0 and 1 <= p["roi"] < 2]
    high = [p for p in plan_list if p["spend"] > 0 and p["roi"] >= 2]
    return {
        "mode": mode,
        "scenes": scenes,
        "plans": plan_list,
        "total_spend": round(total_spend, 2),
        "total_sales": round(total_sales, 2),
        "total_roi": round(total_sales / total_spend, 2) if total_spend else 0.0,
        "active_count": len(active),
        "low_count": len(low),
        "mid_count": len(mid),
        "high_count": len(high),
    }

def _build_promo_prompt(d: dict) -> str:
    lines = [
        f"数据范围：{d['mode']}",
        f"总花费 {d['total_spend']:.0f} 元，总成交 {d['total_sales']:.0f} 元，整体ROI {d['total_roi']}；在投计划 {d['active_count']} 个，其中ROI≥2有{d['high_count']}个、ROI1~2有{d['mid_count']}个、ROI<1有{d['low_count']}个",
    ]
    if d["scenes"]:
        lines.append("分场景：" + "、".join(f"{s['scene_name']}花费{s['spend']:.0f}元成交{s['sales']:.0f}元ROI{s['roi']}" for s in d["scenes"]))
    if d["plans"]:
        top = sorted(d["plans"], key=lambda p: -p["spend"])[:6]
        lines.append("花费最高的计划：" + "；".join(f"{p['plan_name'][:20]}({p['scene_name']})花费{p['spend']:.0f}元ROI{p['roi']}" for p in top))
        lowplans = [p for p in d["plans"] if p["spend"] > 0 and p["roi"] < 1]
        if lowplans:
            lines.append("ROI<1的计划：" + "；".join(f"{p['plan_name'][:20]}ROI{p['roi']}" for p in lowplans[:6]))
    prompt = (
        "你是淘宝店铺的电商推广优化师。根据以下万相台推广数据输出推广诊断，严格按格式：\n"
        "【整体表现】2-3句话概括（总花费、成交、ROI、计划健康度）\n"
        "【亮点】\n- 高效计划/场景及原因（2-3条）\n"
        "【风险】\n- 低效计划、花费失控、预算风险等（3条）\n"
        "【建议】\n- 具体可执行：点名建议暂停/降价/加预算的计划名（4-5条）\n"
        "简体中文务实，金额≥1万用X.X万简化；只依据给定数据，不要编造。\n\n"
        + "\n".join(lines)
    )
    return prompt

def _lookup_item_image(db, store_id: int, item_id: str) -> str:
    """从商品表反查图片（先实时后按天）。"""
    _r = db.execute(
        "SELECT image FROM store_item_realtime WHERE store_id = ? AND item_id = ? AND image != '' LIMIT 1",
        (store_id, item_id),
    ).fetchone()
    if _r:
        return _r["image"]
    _r = db.execute(
        "SELECT image FROM store_item_daily WHERE store_id = ? AND item_id = ? AND image != '' LIMIT 1",
        (store_id, item_id),
    ).fetchone()
    return _r["image"] if _r else ""

def _refresh_plan_items(db, store: dict) -> None:
    """抓取店铺的计划↔商品映射并写入缓存表（慢操作，仅在需要时调用）。"""
    from backend.app.core.alimama import _promo_item_map

    m = _promo_item_map(store)
    now = _now()
    for cid, items in m.items():
        if not items:
            continue
        first = items[0]
        img = _lookup_item_image(db, store["id"], first.get("item_id") or "") if first.get("item_id") else ""
        db.execute(
            "INSERT INTO promo_plan_items (store_id, campaign_id, item_id, item_title, image, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(store_id, campaign_id) DO UPDATE SET "
            "item_id = excluded.item_id, item_title = excluded.item_title, "
            "image = excluded.image, updated_at = excluded.updated_at",
            (store["id"], cid, first.get("item_id") or "", first.get("item_title") or "", img, now),
        )

class PlanStatusIn(BaseModel):
    status: str = "pause"
    execute: bool = False

class PlanChatIn(BaseModel):
    role: str
    content: str

class PlanChatBody(BaseModel):
    messages: list[PlanChatIn] = []

def _ensure_plan_daily(db, store: dict, start, end, user: dict) -> None:
    """懒加载：把 [start,end] 区间内缺失的按天计划报表补齐到 promo_plan_daily。"""
    from backend.app.core.alimama import AlimamaError

    visible = visible_store_ids(user)
    if visible is not None and store["id"] not in visible:
        return
    cur = start
    while cur <= end:
        d = cur.isoformat()
        exists = db.execute(
            "SELECT COUNT(*) AS c FROM promo_plan_daily WHERE store_id = ? AND data_date = ?",
            (store["id"], d),
        ).fetchone()["c"]
        if not exists:
            try:
                rows = fetch_plan_reports(store, d, d)
            except AlimamaError:
                rows = []
            now = _now()
            if not rows:
                rows = [{"campaign_id": "", "spend": 0.0, "sales": 0.0, "roi": 0.0, "clicks": 0}]
            for r in rows:
                db.execute(
                    "INSERT INTO promo_plan_daily (store_id, campaign_id, data_date, spend, sales, roi, clicks, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(store_id, campaign_id, data_date) DO UPDATE SET "
                    "spend = excluded.spend, sales = excluded.sales, roi = excluded.roi, "
                    "clicks = excluded.clicks, updated_at = excluded.updated_at",
                    (store["id"], r["campaign_id"], d, r["spend"], r["sales"], r["roi"], r["clicks"], now),
                )
        cur += timedelta(days=1)

def _collect_plan_data(db, store: dict, plan: dict, user: dict) -> dict:
    """汇总单个计划的静态信息 + 三个模式统计 + 环比 + 最近趋势。"""
    scope_frag, scope_params = _scope_filter(store["id"], user)
    modes: dict[str, dict] = {}
    for r in db.execute(
        "SELECT * FROM promo_plan_stats WHERE store_id = ? AND campaign_id = ?" + scope_frag,
        [store["id"], plan["campaign_id"]] + scope_params,
    ).fetchall():
        modes[r["mode"]] = dict(r)

    def _line(mode: str, label: str) -> str:
        st = modes.get(mode)
        if not st:
            return label + "：暂无数据"
        cyc = ""
        if st.get("prev_spend"):
            chg = (st["spend"] - st["prev_spend"]) / st["prev_spend"] * 100
            cyc = "（花费较上期 %+.1f%%）" % chg
        return "%s：花费 ¥%.2f，成交 ¥%.2f，ROI %.2f，点击 %d%s" % (
            label, st["spend"], st["sales"], st["roi"], int(st["clicks"]), cyc)

    trend = []
    for r in db.execute(
        "SELECT data_date, spend, sales, roi FROM promo_plan_daily "
        "WHERE store_id = ? AND campaign_id = ? AND data_date >= ?" + scope_frag + " ORDER BY data_date ASC",
        [store["id"], plan["campaign_id"], (date_cls.today() - timedelta(days=6)).isoformat()] + scope_params,
    ).fetchall():
        trend.append("%s:花费%.0f/成交%.0f/ROI%.2f" % (r["data_date"][5:], r["spend"], r["sales"], r["roi"]))

    return {
        "plan": plan,
        "store_name": store["name"],
        "lines": [_line("realtime", "实时"), _line("yesterday", "昨天"), _line("7d", "近7天")],
        "trend": trend,
    }

def _build_plan_prompt(data: dict) -> str:
    p = data["plan"]
    parts = [
        "你是淘宝万相台推广运营专家。请针对下面这一个推广计划做深入分析，输出结构化解读，严格按格式，每部分独占一段，条目用“- ”开头：",
        "计划：%s（ID %s）｜店铺：%s" % (p["plan_name"], p["campaign_id"], data["store_name"]),
        "场景：%s｜状态：%s｜日预算：¥%.2f｜出价：%s" % (
            p["scene_name"], p["status"], round(p["day_budget"] or 0, 2), p["bid_type"] or "—"),
    ]
    parts.extend(data["lines"])
    if data["trend"]:
        parts.append("近7天逐日：" + "；".join(data["trend"]))
    parts.extend(
        [
            "【整体表现】2-3句话评价该计划（含花费/成交/ROI关键数字）",
            "【亮点】\n- 投放亮点（2-3条，确实没有就写“本期暂无突出亮点”）",
            "【风险】\n- 风险点（如ROI偏低、花费超预算、环比下滑等，2-3条，没有就写“暂无重大风险”）",
            "【建议】\n- 下一步优化建议（加/减预算、调出价、暂停等，3-4条，要具体可执行）",
        ]
    )
    return "\n".join(parts)
