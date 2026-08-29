"""推广管理通用工具与同步函数。"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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
    start = today - timedelta(days=days)
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
        except Exception as exc:  # noqa: BLE001 - 后台同步按店铺隔离
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": f"同步异常：{str(exc) or exc.__class__.__name__}"})
    result = {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"])}
    from .health import record_sync_result

    record_sync_result(db, "daily", result, source="alimama_scene_daily")
    return result

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
            "orders = excluded.orders, add_cart = excluded.add_cart, conversion_rate = excluded.conversion_rate, created_at = excluded.created_at",
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
            "orders = excluded.orders, conversion_rate = excluded.conversion_rate, created_at = excluded.created_at",
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
        except Exception as exc:  # noqa: BLE001 - 后台同步按店铺隔离
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": f"同步异常：{str(exc) or exc.__class__.__name__}"})
    result = {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"])}
    from .health import record_sync_result

    record_sync_result(db, "realtime", result, source="alimama_scene_realtime")
    return result

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
        except Exception as exc:  # noqa: BLE001 - 后台同步按店铺隔离
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": f"同步异常：{str(exc) or exc.__class__.__name__}"})
    result = {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"])}
    from .health import record_sync_result

    record_sync_result(db, "items_realtime", result, source="alimama_item_or_plan_attribution")
    return result


def _strategy_evidence_score(strategy: dict) -> int:
    if strategy.get("verification_status") == "pending":
        return 0
    confidence_points = {"high": 30, "medium": 20, "low": 8}.get(strategy.get("confidence") or "", 5)
    observed_days = int(strategy.get("baseline_days") or 0) + int(strategy.get("after_days") or 0)
    day_points = min(24, observed_days * 4)
    after_spend = float(strategy.get("after_spend") or 0)
    spend_points = 15 if after_spend >= 500 else 12 if after_spend >= 100 else 8 if after_spend >= 20 else 4
    verified_at = strategy.get("verified_at") or strategy.get("updated_at") or ""
    recency_points = 3
    if verified_at:
        try:
            age_days = max(0, (datetime.now().astimezone() - datetime.fromisoformat(verified_at.replace("Z", "+00:00"))).days)
            recency_points = 15 if age_days <= 30 else 10 if age_days <= 90 else 5
        except ValueError:
            recency_points = 3
    usage_points = min(10, int(strategy.get("use_count") or 0) * 2 + int(strategy.get("success_count") or 0) * 3)
    specificity_points = (3 if strategy.get("scene") else 0) + (3 if strategy.get("min_roi") is not None and strategy.get("max_roi") is not None else 0)
    return min(100, confidence_points + day_points + spend_points + recency_points + usage_points + specificity_points)


def _enrich_promo_strategies(db, rows) -> tuple[list[dict], list[dict]]:
    strategies: list[dict] = []
    for row in rows:
        item = dict(row)
        source = None
        if item.get("source_action_id"):
            source = db.execute(
                "SELECT confidence, baseline_days, after_days, after_spend, verified_at FROM promo_action_records WHERE id = ? AND COALESCE(lifecycle_status, 'active') = 'active'",
                (item["source_action_id"],),
            ).fetchone()
        if source:
            item.update(dict(source))
        item["evidence_score"] = _strategy_evidence_score(item)
        item["evidence_level"] = "high" if item["evidence_score"] >= 75 else "medium" if item["evidence_score"] >= 50 else "low"
        strategies.append(item)

    grouped: dict[tuple[str, str], list[dict]] = {}
    for strategy in strategies:
        if strategy.get("verification_status") == "pending":
            continue
        key = (strategy.get("action_type") or "未标注动作", strategy.get("scene") or "不限场景")
        grouped.setdefault(key, []).append(strategy)

    groups: list[dict] = []
    for (action_type, scene), members in grouped.items():
        success = sum(1 for member in members if member.get("outcome") == "success")
        partial = sum(1 for member in members if member.get("outcome") == "partial")
        failed = sum(1 for member in members if member.get("outcome") == "failed")
        conclusive = success + partial + failed
        group = {
            "group_id": f"{action_type}|{scene}",
            "action_type": action_type,
            "scene": scene,
            "sample_count": len(members),
            "success_count": success,
            "partial_count": partial,
            "failed_count": failed,
            "success_rate": round(success / conclusive * 100, 1) if conclusive else 0.0,
            "avg_evidence_score": round(sum(member["evidence_score"] for member in members) / len(members), 1),
            "latest_verified_at": max((member.get("verified_at") or member.get("updated_at") or "" for member in members), default=""),
            "strategy_ids": [member["id"] for member in members],
        }
        groups.append(group)
        for member in members:
            member.update({
                "sample_count": group["sample_count"],
                "group_success_count": group["success_count"],
                "group_partial_count": group["partial_count"],
                "group_failed_count": group["failed_count"],
                "group_success_rate": group["success_rate"],
                "group_evidence_score": group["avg_evidence_score"],
            })
    groups.sort(key=lambda item: (item["sample_count"], item["avg_evidence_score"], item["success_rate"]), reverse=True)
    strategies.sort(
        key=lambda item: (
            item.get("outcome") == "success",
            item.get("group_success_rate") or 0,
            item.get("evidence_score") or 0,
            item.get("use_count") or 0,
        ),
        reverse=True,
    )
    return strategies, groups

def _promo_insight_data(mode: str, db, user: dict, store_id: int | None = None, plan_id: int | None = None) -> dict:
    mode = _mode(mode)
    today = date_cls.today()
    visible = visible_store_ids(user)
    if store_id is not None:
        selected = {store_id} if visible is None or store_id in visible else set()
    else:
        selected = visible
    focus_scene = None
    if plan_id is not None:
        focus_row = db.execute("SELECT store_id, scene, scene_name FROM promo_plans WHERE id = ?", (int(plan_id),)).fetchone()
        if focus_row:
            focus_scene = focus_row["scene"] or focus_row["scene_name"]
    if selected is None:
        scope_frag = ""
        scope_params: list = []
    elif not selected:
        scope_frag = " AND 1=0"
        scope_params = []
    else:
        scope_frag = " AND store_id IN (%s)" % ",".join(str(i) for i in sorted(selected))
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
        start = (today - timedelta(days=7)).isoformat()
        end = (today - timedelta(days=1)).isoformat()
        scene_rows = db.execute(
            "SELECT scene, scene_name, SUM(spend) AS spend, SUM(sales) AS sales FROM promo_daily_data "
            "WHERE data_date >= ? AND data_date <= ?" + scope_frag + " GROUP BY scene ORDER BY spend DESC",
            [start, end] + scope_params,
        ).fetchall()
    scenes = []
    for r in scene_rows:
        spend = round(r["spend"] or 0, 2)
        sales = round(r["sales"] or 0, 2)
        scenes.append({"scene": r["scene"], "scene_name": r["scene_name"] or r["scene"], "spend": spend, "sales": sales, "roi": round(sales / spend, 2) if spend else 0.0})
    if focus_scene is not None:
        scenes = [scene for scene in scenes if scene.get("scene") == focus_scene or scene.get("scene_name") == focus_scene]
    if selected is None:
        plan_scope = ""
    elif not selected:
        plan_scope = " WHERE 1=0"
    else:
        plan_scope = " WHERE p.store_id IN (%s)" % ",".join(str(i) for i in sorted(selected))
    if plan_id is not None:
        plan_scope += (" AND" if plan_scope else " WHERE") + f" p.id = {int(plan_id)}"
    plans = db.execute(
        "SELECT p.id, p.store_id, p.scene, p.scene_name, p.campaign_id, p.plan_name, p.status, p.day_budget, p.bid_value, "
        "COALESCE(s.spend,0) AS spend, COALESCE(s.sales,0) AS sales, COALESCE(s.roi,0) AS roi, COALESCE(s.clicks,0) AS clicks, "
        "COALESCE(s.prev_spend,0) AS prev_spend, COALESCE(s.prev_sales,0) AS prev_sales, COALESCE(s.prev_roi,0) AS prev_roi, "
        "COALESCE(s.prev_clicks,0) AS prev_clicks, COALESCE(s.prev_scope,'unknown') AS prev_scope, COALESCE(s.updated_at,'') AS stats_updated_at "
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
                "id": int(r["id"]),
                "store_id": int(r["store_id"]),
                "campaign_id": r["campaign_id"] or "",
                "scene_name": r["scene_name"] or r["scene"] or "?",
                "plan_name": r["plan_name"] or "?",
                "status": r["status"],
                "day_budget": round(r["day_budget"] or 0, 2),
                "bid_value": round(r["bid_value"] or 0, 2),
                "spend": spend,
                "sales": sales,
                "roi": round(sales / spend, 2) if spend else 0.0,
                "clicks": int(r["clicks"] or 0),
                "prev_spend": round(r["prev_spend"] or 0, 2),
                "prev_sales": round(r["prev_sales"] or 0, 2),
                "prev_roi": round(r["prev_roi"] or 0, 2),
                "prev_clicks": int(r["prev_clicks"] or 0),
                "prev_scope": r["prev_scope"] or "unknown",
                "stats_updated_at": r["stats_updated_at"] or "",
                "decision_status": (
                    "insufficient" if spend <= 0 else "needs_decision" if (sales / spend if spend else 0.0) < 1 else "observe"
                ),
                "decision_status_label": (
                    "证据不足" if spend <= 0 else "需要处理" if (sales / spend if spend else 0.0) < 1 else "正常观察"
                ),
                "decision_reason": (
                    "当前没有有效花费样本，暂不形成调整建议"
                    if spend <= 0
                    else "当前 ROI 低于保本线，需要评估止损或收缩流量"
                    if (sales / spend if spend else 0.0) < 1
                    else "当前指标未发现需要立即调整的异常，保持现状并继续观察"
                ),
            }
        )
    total_spend = sum(p["spend"] for p in plan_list)
    total_sales = sum(p["sales"] for p in plan_list)
    active = [p for p in plan_list if p["status"] == "在投"]
    low = [p for p in active if p["spend"] > 0 and p["roi"] < 1]
    mid = [p for p in active if p["spend"] > 0 and 1 <= p["roi"] < 2]
    high = [p for p in active if p["spend"] > 0 and p["roi"] >= 2]
    if selected is None:
        strategy_scope = ""
        strategy_params: list = []
    elif not selected:
        strategy_scope = " AND 1=0"
        strategy_params = []
    else:
        strategy_scope = " AND store_id IN (%s)" % ",".join(str(i) for i in sorted(selected))
        strategy_params = []
    strategy_rows = db.execute(
        "SELECT id, source_action_id, name, action_type, conditions, evidence, success_count, use_count, outcome, scene, min_roi, max_roi, source_type, verification_status, updated_at "
        "FROM promo_strategies WHERE status = 'active'" + strategy_scope + " ORDER BY updated_at DESC LIMIT 100",
        strategy_params,
    ).fetchall()
    strategies, strategy_groups = _enrich_promo_strategies(db, strategy_rows)
    from .learning import learn_strategy_weights

    decision_learning_rows = db.execute(
        "SELECT strategy_id, feedback_status, created_at, updated_at FROM promo_decision_records "
        "WHERE strategy_id IS NOT NULL AND (action_record_id IS NULL OR action_record_id IN ("
        "SELECT id FROM promo_action_records WHERE COALESCE(lifecycle_status, 'active') = 'active'))"
        + strategy_scope + " ORDER BY updated_at DESC LIMIT 2000",
        strategy_params,
    ).fetchall()
    action_learning_rows = db.execute(
        "SELECT strategy_id, status, confidence, interference_notes, manual_conclusion, created_at, executed_at, verified_at "
        "FROM promo_action_records WHERE COALESCE(lifecycle_status, 'active') = 'active' AND strategy_id IS NOT NULL" + strategy_scope + " ORDER BY id DESC LIMIT 2000",
        strategy_params,
    ).fetchall()
    learning = learn_strategy_weights(decision_learning_rows, action_learning_rows)
    learning_by_strategy = {item["strategy_id"]: item for item in learning["strategy_weights"]}
    for strategy in strategies:
        learned = learning_by_strategy.get(int(strategy["id"]))
        strategy["learning_weight"] = learned["weight"] if learned else 1.0
        strategy["learning_sample_count"] = learned["sample_count"] if learned else 0
        strategy["learning_explanation"] = learned["explanation"] if learned else "暂无决策反馈与验证样本，学习权重保持中性"
        strategy["learned_score"] = round(float(strategy.get("evidence_score") or 0) * float(strategy["learning_weight"]), 1)
    strategies.sort(
        key=lambda item: (
            item.get("outcome") == "success",
            float(item.get("learning_weight") or 1),
            float(item.get("group_success_rate") or 0),
            float(item.get("learned_score") or 0),
        ),
        reverse=True,
    )

    constraint_rows = db.execute(
        "SELECT plan_id, feedback_reason, feedback_note, updated_at FROM promo_decision_records "
        "WHERE feedback_status = 'rejected'" + strategy_scope + " ORDER BY updated_at DESC LIMIT 1000",
        strategy_params,
    ).fetchall()
    decision_constraints: dict[str, dict] = {}
    for row in constraint_rows:
        plan = db.execute("SELECT scene_name, scene FROM promo_plans WHERE id = ?", (row["plan_id"],)).fetchone()
        scene_name = (plan["scene_name"] or plan["scene"] or "未标注场景") if plan else "未标注场景"
        reason = (row["feedback_reason"] or "未填写原因").strip()
        group = decision_constraints.setdefault(scene_name, {"scene_name": scene_name, "rejected_count": 0, "reasons": {}})
        group["rejected_count"] += 1
        group["reasons"][reason] = group["reasons"].get(reason, 0) + 1
    for group in decision_constraints.values():
        group["top_reasons"] = [
            {"reason": reason, "count": count}
            for reason, count in sorted(group["reasons"].items(), key=lambda entry: (-entry[1], entry[0]))[:3]
        ]
        del group["reasons"]
    return {
        "mode": mode,
        "focus_plan_id": plan_id,
        "scenes": scenes,
        "plans": plan_list,
        "total_spend": round(total_spend, 2),
        "total_sales": round(total_sales, 2),
        "total_roi": round(total_sales / total_spend, 2) if total_spend else 0.0,
        "active_count": len(active),
        "low_count": len(low),
        "mid_count": len(mid),
        "high_count": len(high),
        "decision_count": sum(1 for p in active if p.get("decision_status") == "needs_decision"),
        "observe_count": sum(1 for p in active if p.get("decision_status") == "observe"),
        "insufficient_count": sum(1 for p in active if p.get("decision_status") == "insufficient"),
        "strategies": strategies,
        "strategy_groups": strategy_groups,
        "learning": learning,
        "decision_constraints": decision_constraints,
    }


def _build_promo_drafts(data: dict, ai_decisions: dict[int, dict] | None = None) -> list[dict]:
    """Build evidence-guarded single-variable drafts.

    AI decides whether intervention is justified and identifies the likely
    cause. Deterministic rules then validate data quality, allowed variables,
    direction and maximum amplitude. This keeps model reasoning useful without
    allowing free-form text to become a platform write.
    """
    ai_decisions = ai_decisions or {}
    drafts: list[dict] = []
    focused_plan_id = int(data["focus_plan_id"]) if data.get("focus_plan_id") is not None else None
    active_plans = [
        plan for plan in data.get("plans", [])
        if plan.get("status") == "在投"
        and (float(plan.get("spend") or 0) > 0 or int(plan.get("id") or 0) == focused_plan_id)
    ]
    low_plans = sorted(
        (plan for plan in active_plans if plan.get("decision_status") == "needs_decision"),
        key=lambda plan: float(plan.get("spend") or 0),
        reverse=True,
    )[:4]
    selected_plans = (
        [plan for plan in active_plans if int(plan.get("id") or 0) == focused_plan_id]
        if focused_plan_id is not None
        else low_plans
    )
    for plan in selected_plans:
        spend = float(plan.get("spend") or 0)
        roi = float(plan.get("roi") or 0)
        findings = plan.get("diagnostic_findings") or []
        risk_findings = [item for item in findings if item.get("signal_type") == "risk"]
        risk_findings.sort(key=lambda item: ({"critical": 0, "high": 1, "medium": 2}.get(item.get("severity"), 9), -float(item.get("spend_at_risk") or 0)))
        primary = risk_findings[0] if risk_findings else (findings[0] if findings else {})
        rule_code = str(primary.get("rule_code") or "")
        ai = ai_decisions.get(int(plan.get("id") or 0), {})
        ai_decision = str(ai.get("decision") or "证据不足")
        ai_confidence = str(ai.get("confidence") or "低")
        diagnostic_confidence = str(primary.get("confidence") or "low")
        confidence_key = {"高": "high", "中": "medium", "低": "low"}.get(ai_confidence, "low")

        priority = "urgent" if primary.get("severity") in {"critical", "high"} else "efficiency"
        priority_label = "优先止损" if priority == "urgent" else "谨慎处理"
        field = "day_budget"
        direction = "降低"
        default_change = 10.0
        action_type = "降低预算/止损"
        risk = "调整只能验证一个投放变量，期间需避免叠加修改商品、素材或人群"
        rule_actionable = rule_code in {"spend_without_sales", "roi_drop", "roi_low", "budget_over", "spend_too_fast"}
        data_blockers: list[str] = []
        if not risk_findings:
            data_blockers.append("诊断中心没有发现风险异常")
        if rule_code in {"data_stale", "no_spend", "low_spend", "delivery_stopped", "delivery_slow"} or spend <= 0:
            data_blockers.append("当前问题应先排查数据或投放状态，不能直接修改投放参数")
        if diagnostic_confidence == "low":
            data_blockers.append("诊断置信度较低")
        if plan.get("prev_scope") not in {"same_hour", "full_day", "7d"} and rule_code in {"roi_drop", "delivery_slow", "delivery_stopped"}:
            data_blockers.append("缺少可比的历史基线")

        variable = str(ai.get("recommended_variable") or "")
        variable_aliases = {"预算": "day_budget", "日预算": "day_budget", "出价": "bid_value"}
        variable = variable_aliases.get(variable, variable)
        if "预算" in variable:
            variable = "day_budget"
        elif "出价" in variable:
            variable = "bid_value"
        allowed_fields = {"day_budget"}
        if rule_code in {"roi_drop", "roi_low"} and float(plan.get("bid_value") or 0) > 0:
            allowed_fields.add("bid_value")
        if variable in allowed_fields:
            field = variable
        elif variable not in {"", "不调整"}:
            data_blockers.append(f"AI 建议变量 {variable} 不在当前异常的安全调整范围")
        if field == "bid_value":
            action_type = "降低出价/控成本"
            risk = "出价降低可能导致展现和点击减少；观察期内不要同时调整预算"
        ai_direction = str(ai.get("recommended_direction") or "")
        if ai_direction in {"下调", "减少", "收缩"}:
            ai_direction = "降低"
        if ai_direction not in {"降低", "不调整", ""}:
            data_blockers.append("当前风险只允许保持或降低单一投放变量")
        if not rule_actionable:
            data_blockers.append("当前异常没有可直接执行的安全动作")
        if ai_decision != "建议干预":
            data_blockers.append("AI 未判断为需要立即干预")

        old_value = float(plan.get(field) or 0)
        if old_value <= 0:
            data_blockers.append("平台当前值未同步，无法计算目标值")
        actionable = not data_blockers
        max_change = 10.0 if confidence_key == "low" else 15.0 if confidence_key == "medium" else 20.0
        requested_change = float(ai.get("change_pct") or default_change)
        base_change = min(max_change, max(5.0, requested_change)) if actionable else 0.0
        observation_hours = int(ai.get("observation_hours") or 48)
        reason = str(ai.get("primary_cause") or primary.get("summary") or "当前证据不足，暂不形成调整结论")
        rollback_condition = str(ai.get("rollback_condition") or "调整后成交明显下降且效率没有改善时，恢复原值")
        if field == "day_budget":
            success_criteria = {"roi_change_min": 0.05, "spend_change_pct_max": -3}
        else:
            success_criteria = {"roi_change_min": 0.05, "spend_change_pct_max": 0}
        if actionable:
            factors = [("conservative", "稳健", 0.5), ("balanced", "平衡", 1.0), ("aggressive", "激进", 1.5)]
            option_configs = []
            for tier, label, factor in factors:
                magnitude = min(max_change, max(5.0, round(base_change * factor / 5) * 5))
                option_configs.append((tier, label, -magnitude, observation_hours, ai.get("next_step") or "单变量调整后观察效率与成交变化", success_criteria))
            recommended_tier = "balanced" if confidence_key in {"medium", "high"} else "conservative"
        else:
            option_configs = [("conservative", "观察", 0, observation_hours, ai.get("next_step") or "保持当前设置，先补齐证据", {"spend_change_pct_max": 0})]
            recommended_tier = "conservative"

        candidates = [
            strategy for strategy in data.get("strategies", [])
            if (not strategy.get("action_type") or strategy["action_type"] == action_type)
            and (not strategy.get("scene") or strategy["scene"] == plan.get("scene_name"))
            and (strategy.get("min_roi") is None or roi >= float(strategy["min_roi"]))
            and (strategy.get("max_roi") is None or roi <= float(strategy["max_roi"]))
        ]
        candidates.sort(
            key=lambda strategy: (
                strategy.get("verification_status") == "verified",
                strategy.get("outcome") == "success",
                float(strategy.get("learning_weight") or 1),
                float(strategy.get("group_success_rate") or 0),
                float(strategy.get("learned_score") or strategy.get("evidence_score") or 0),
                int(strategy.get("use_count") or 0),
            ),
            reverse=True,
        )
        matching = candidates[0] if candidates else None
        has_conflict = len({strategy.get("outcome") for strategy in candidates if int(strategy.get("evidence_score") or 0) >= 50}) > 1
        scene_constraint = data.get("decision_constraints", {}).get(plan.get("scene_name"), {})
        has_constraint_signal = int(scene_constraint.get("rejected_count") or 0) >= 2
        learning_weight = float(matching.get("learning_weight") or 1) if matching else 1.0
        learning_samples = int(matching.get("learning_sample_count") or 0) if matching else 0
        if has_constraint_signal or has_conflict or (learning_samples >= 3 and learning_weight < 0.9):
            recommended_tier = "conservative"
        if matching:
            if matching.get("verification_status") == "pending":
                evidence_summary = f"参考人工经验《{matching['name']}》：当前待验证，不计入历史证据分，也不能单独支持执行"
            else:
                evidence_summary = (
                    f"参考《{matching['name']}》：证据 {matching['evidence_score']} 分；"
                    f"同类 {matching.get('sample_count', 1)} 次，成功率 {matching.get('group_success_rate', 0)}%；"
                    f"学习权重 {learning_weight:.2f}（{learning_samples} 条反馈/验证证据）"
                )
        else:
            evidence_summary = "暂无完全匹配的历史策略，本次建议以当前计划数据为主并采用稳健方案"
        constraint_summary = ""
        if has_constraint_signal:
            reasons = "、".join(f"{item['reason']} {item['count']} 次" for item in scene_constraint.get("top_reasons", []))
            constraint_summary = f"该场景已有 {scene_constraint['rejected_count']} 次人工拒绝，主要约束：{reasons}"
            evidence_summary += f"；{constraint_summary}"
        options = []
        for tier, tier_label, change_pct, observation_hours, expected, success_criteria in option_configs:
            options.append({
                "tier": tier,
                "tier_label": tier_label,
                "recommended": tier == recommended_tier,
                "field": field,
                "change_pct": change_pct,
                "old_value": round(old_value, 2),
                "new_value": round(max(0, old_value * (1 + change_pct / 100)), 2),
                "expected": expected,
                "observation_hours": observation_hours,
                "risk": risk,
                "rollback_condition": rollback_condition,
                "success_criteria": success_criteria,
                "evidence_summary": evidence_summary,
            })
        recommended = next(option for option in options if option["recommended"])
        diagnostic_evidence = []
        for item in primary.get("evidence", []):
            if isinstance(item, dict):
                current = item.get("current")
                unit = item.get("unit") or ""
                baseline = item.get("baseline")
                text = f"{item.get('label') or '指标'}：{current}{unit}"
                if baseline is not None:
                    text += f"（对比 {baseline}{unit}）"
                diagnostic_evidence.append(text)
            elif str(item).strip():
                diagnostic_evidence.append(str(item).strip())
        drafts.append(
            {
                "plan_id": plan["id"],
                "store_id": plan.get("store_id"),
                "campaign_id": plan.get("campaign_id", ""),
                "plan_name": plan["plan_name"],
                "scene_name": plan["scene_name"],
                "action_type": action_type,
                "priority": priority,
                "priority_label": priority_label,
                "reason": reason,
                "recommended_tier": recommended_tier,
                "options": options,
                **recommended,
                "strategy_id": matching.get("id") if matching else None,
                "strategy_name": matching.get("name") if matching else None,
                "strategy_outcome": matching.get("outcome") if matching else None,
                "strategy_source_type": matching.get("source_type") if matching else None,
                "strategy_verification_status": matching.get("verification_status") if matching else None,
                "strategy_score": matching.get("evidence_score") if matching else None,
                "learning_weight": round(learning_weight, 4),
                "learning_sample_count": learning_samples,
                "learning_explanation": matching.get("learning_explanation") if matching else "暂无可学习的关联策略样本",
                "strategy_candidates": candidates[:5],
                "strategy_conflict": has_conflict,
                "conflict_reason": "高质量历史证据中同时存在成功与谨慎经验，默认采用稳健方案并等待人工选择" if has_conflict else "",
                "constraint_summary": constraint_summary,
                "engine_actionable": actionable,
                "decision_mode": "intervene" if actionable else "observe" if ai_decision == "建议观察" else "insufficient",
                "ai_decision": ai_decision,
                "primary_cause": str(ai.get("primary_cause") or ""),
                "affected_stage": str(ai.get("affected_stage") or ""),
                "diagnostic_rule": rule_code,
                "diagnostic_title": primary.get("title") or "未发现风险异常",
                "diagnostic_confidence": diagnostic_confidence,
                "decision_confidence": confidence_key,
                "decision_evidence": ai.get("evidence") or diagnostic_evidence,
                "missing_data": ai.get("missing_data") or primary.get("unknown_dimensions") or [],
                "ai_success_criteria_text": ai.get("success_criteria") or [],
                "next_step": ai.get("next_step") or ("进入调整预览" if actionable else "补齐证据后重新生成决策"),
                "guardrail_reasons": data_blockers,
                "not_recommended_reason": "；".join(dict.fromkeys(data_blockers)),
            }
        )
    return drafts

def _build_promo_prompt(d: dict) -> str:
    lines = [
        f"数据范围：{d['mode']}",
        f"分析范围：仅分析计划 ID {d['focus_plan_id']}" if d.get("focus_plan_id") is not None else "分析范围：当前可见店铺的推广计划",
        f"总花费 {d['total_spend']:.0f} 元，总成交 {d['total_sales']:.0f} 元，整体ROI {d['total_roi']}；在投计划 {d['active_count']} 个，其中待决策 {d.get('decision_count', d['low_count'])} 个、正常观察 {d.get('observe_count', 0)} 个、证据不足 {d.get('insufficient_count', 0)} 个",
        "决策口径：仅为待决策计划生成执行草案；正常观察计划保持现状，证据不足计划不形成调整建议。",
    ]
    if d["scenes"]:
        lines.append("分场景：" + "、".join(f"{s['scene_name']}花费{s['spend']:.0f}元成交{s['sales']:.0f}元ROI{s['roi']}" for s in d["scenes"]))
    if d["plans"]:
        top = sorted(d["plans"], key=lambda p: -p["spend"])[:6]
        lines.append("花费最高的计划：" + "；".join(f"{p['plan_name'][:20]}({p['scene_name']})花费{p['spend']:.0f}元ROI{p['roi']}" for p in top))
        lowplans = [p for p in d["plans"] if p.get("decision_status") == "needs_decision"]
        if lowplans:
            lines.append("诊断标记为风险异常的待处理计划：" + "；".join(f"{p['plan_name'][:20]}（ROI{p['roi']}）" for p in lowplans[:6]))
    if d.get("strategies"):
        verified_strategies = [s for s in d["strategies"] if s.get("verification_status") != "pending"]
        manual_strategies = [s for s in d["strategies"] if s.get("verification_status") == "pending"]
        if verified_strategies:
            lines.append("历史验证策略（证据分表示数据可靠程度，不等于建议方向）：" + "；".join(
            f"{s['name']}：{s['conditions']}（适用场景{s.get('scene') or '不限'}，ROI {s.get('min_roi') if s.get('min_roi') is not None else '-∞'}~{s.get('max_roi') if s.get('max_roi') is not None else '+∞'}，结果{s.get('outcome', 'success')}，证据分{s.get('evidence_score', 0)}，学习权重{s.get('learning_weight', 1)}，学习样本{s.get('learning_sample_count', 0)}条，同类样本{s.get('sample_count', 1)}次，同类成功率{s.get('group_success_rate', 0)}%，证据{s['evidence'][:80]}）"
                for s in verified_strategies[:6]
            ))
        if manual_strategies:
            lines.append("人工经验（仅供参考，待真实验证，不计入证据分且不能单独支持执行）：" + "；".join(
                f"{s['name']}：{s['conditions']}（动作{s['action_type']}，适用场景{s.get('scene') or '不限'}，人工依据{s['evidence'][:80]}）"
                for s in manual_strategies[:6]
            ))
    if d.get("strategy_groups"):
        lines.append("同类经验汇总：" + "；".join(
            f"{group['action_type']}@{group['scene']}：样本{group['sample_count']}，成功{group['success_count']}，部分有效{group['partial_count']}，失败{group['failed_count']}，平均证据分{group['avg_evidence_score']}"
            for group in d["strategy_groups"][:6]
        ))
    if d.get("decision_constraints"):
        lines.append("人工拒绝约束（达到重复样本后才影响档位） ：" + "；".join(
            f"{group['scene_name']}拒绝{group['rejected_count']}次，主要原因" + "、".join(f"{item['reason']}{item['count']}次" for item in group.get("top_reasons", []))
            for group in d["decision_constraints"].values()
        ))
    prompt = (
        "你是淘宝店铺的电商推广优化师。根据以下万相台推广数据输出推广诊断，严格按格式：\n"
        "【整体表现】2-3句话概括（总花费、成交、ROI、计划健康度）\n"
        "【亮点】\n- 高效计划/场景及原因（2-3条）\n"
        "【风险】\n- 低效计划、花费失控、预算风险等（3条）\n"
        "【建议】\n- 具体可执行：点名建议暂停/降价/加预算的计划名（4-5条）\n"
        "简体中文务实，金额≥1万用X.X万简化；只依据给定数据，不要编造。历史策略只能作为参考，不能替代当前计划数据；证据分代表可靠程度，学习权重由真实反馈和验证结果计算；失败但证据分高的策略应作为强风险证据；重复出现的人工拒绝原因应作为业务约束，单次拒绝不能直接推广到所有计划。\n\n"
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

class PlanBatchStatusIn(BaseModel):
    plan_ids: list[int]
    status: str = "pause"
    execute: bool = True

class PlanBatchAdjustIn(BaseModel):
    plan_ids: list[int]
    field: str = "day_budget"
    change_pct: float = 0
    # 单计划可直接指定最终目标值；存在时优先于 change_pct，避免百分比
    # 展示精度（如 3.3%）反算出 3099 而不是用户输入的 3100。
    target_value: float | None = Field(default=None, ge=0)
    execute: bool = False

class PlanAdjustIn(BaseModel):
    field: str
    value: float = Field(ge=0)
    execute: bool = False

class PlanCreateIn(BaseModel):
    biz_code: str
    solution_list: list[dict[str, Any]] = Field(default_factory=list)

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
