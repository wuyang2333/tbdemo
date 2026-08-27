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


def _strategy_evidence_score(strategy: dict) -> int:
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
                "SELECT confidence, baseline_days, after_days, after_spend, verified_at FROM promo_action_records WHERE id = ?",
                (item["source_action_id"],),
            ).fetchone()
        if source:
            item.update(dict(source))
        item["evidence_score"] = _strategy_evidence_score(item)
        item["evidence_level"] = "high" if item["evidence_score"] >= 75 else "medium" if item["evidence_score"] >= 50 else "low"
        strategies.append(item)

    grouped: dict[tuple[str, str], list[dict]] = {}
    for strategy in strategies:
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

def _promo_insight_data(mode: str, db, user: dict, store_id: int | None = None) -> dict:
    mode = _mode(mode)
    today = date_cls.today()
    visible = visible_store_ids(user)
    if store_id is not None:
        selected = {store_id} if visible is None or store_id in visible else set()
    else:
        selected = visible
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
    if selected is None:
        plan_scope = ""
    elif not selected:
        plan_scope = " WHERE 1=0"
    else:
        plan_scope = " WHERE p.store_id IN (%s)" % ",".join(str(i) for i in sorted(selected))
    plans = db.execute(
        "SELECT p.id, p.store_id, p.scene, p.scene_name, p.campaign_id, p.plan_name, p.status, p.day_budget, p.bid_value, "
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
        "SELECT id, source_action_id, name, action_type, conditions, evidence, success_count, use_count, outcome, scene, min_roi, max_roi, updated_at "
        "FROM promo_strategies WHERE status = 'active'" + strategy_scope + " ORDER BY updated_at DESC LIMIT 100",
        strategy_params,
    ).fetchall()
    strategies, strategy_groups = _enrich_promo_strategies(db, strategy_rows)
    from .learning import learn_strategy_weights

    decision_learning_rows = db.execute(
        "SELECT strategy_id, feedback_status, created_at, updated_at FROM promo_decision_records "
        "WHERE strategy_id IS NOT NULL" + strategy_scope + " ORDER BY updated_at DESC LIMIT 2000",
        strategy_params,
    ).fetchall()
    action_learning_rows = db.execute(
        "SELECT strategy_id, status, confidence, interference_notes, manual_conclusion, created_at, executed_at, verified_at "
        "FROM promo_action_records WHERE strategy_id IS NOT NULL" + strategy_scope + " ORDER BY id DESC LIMIT 2000",
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
        "scenes": scenes,
        "plans": plan_list,
        "total_spend": round(total_spend, 2),
        "total_sales": round(total_sales, 2),
        "total_roi": round(total_sales / total_spend, 2) if total_spend else 0.0,
        "active_count": len(active),
        "low_count": len(low),
        "mid_count": len(mid),
        "high_count": len(high),
        "strategies": strategies,
        "strategy_groups": strategy_groups,
        "learning": learning,
        "decision_constraints": decision_constraints,
    }


def _build_promo_drafts(data: dict) -> list[dict]:
    """根据真实计划指标生成需要人工确认的三档执行草案。"""
    drafts: list[dict] = []
    active_plans = [plan for plan in data.get("plans", []) if plan.get("status") == "在投" and float(plan.get("spend") or 0) > 0]
    low_plans = sorted((plan for plan in active_plans if float(plan.get("roi") or 0) < 1), key=lambda plan: float(plan.get("spend") or 0), reverse=True)[:4]
    high_plans = sorted((plan for plan in active_plans if float(plan.get("roi") or 0) >= 2), key=lambda plan: float(plan.get("spend") or 0), reverse=True)[:4]
    mid_plans = sorted((plan for plan in active_plans if 1 <= float(plan.get("roi") or 0) < 2), key=lambda plan: float(plan.get("spend") or 0), reverse=True)[:2]
    selected_plans = low_plans + high_plans + mid_plans
    for plan in selected_plans:
        spend = float(plan.get("spend") or 0)
        roi = float(plan.get("roi") or 0)
        if spend <= 0:
            continue
        if roi < 1:
            priority, priority_label = "urgent", "优先止损"
            field = "day_budget"
            action_type = "降低预算/止损"
            reason = f"当前 ROI {roi:.2f} 低于保本线，需要控制无效花费。"
            risk = "预算下降可能同步减少成交规模，需要关注自然成交和库存"
            option_configs = [
                ("conservative", "稳健", -10, 72, "先小幅收缩花费，确认低效是否持续", {"roi_change_min": 0.05, "spend_change_pct_max": -3}),
                ("balanced", "平衡", -20, 48, "明显降低无效花费并推动 ROI 回升", {"roi_change_min": 0.1, "spend_change_pct_max": -5}),
                ("aggressive", "激进", -35, 48, "快速止损并重新评估计划投放价值", {"roi_change_min": 0.2, "spend_change_pct_max": -10}),
            ]
            rollback_condition = "日均成交下降超过 20%，且 ROI 未提升 0.1 时恢复原预算"
        elif roi >= 2:
            priority, priority_label = "growth", "增长机会"
            field = "day_budget"
            action_type = "增加预算/放量"
            reason = f"当前 ROI {roi:.2f} 达到健康线，可以验证边际增量。"
            risk = "边际流量可能变差，放量后需重点关注 ROI 和日均成交"
            option_configs = [
                ("conservative", "稳健", 10, 72, "小幅放量，优先保持当前 ROI", {"target_roi_min": max(1, round(roi * 0.9, 2)), "sales_change_pct_min": 3}),
                ("balanced", "平衡", 15, 48, "扩大成交规模，同时控制 ROI 回落", {"target_roi_min": max(1, round(roi * 0.85, 2)), "sales_change_pct_min": 5}),
                ("aggressive", "激进", 25, 48, "快速争取增量，接受更高边际波动", {"target_roi_min": max(1, round(roi * 0.8, 2)), "sales_change_pct_min": 10}),
            ]
            rollback_condition = f"ROI 低于 {max(1, round(roi * 0.75, 2))}，或日均花费增长但成交未增长时回退"
        else:
            priority, priority_label = "efficiency", "效率优化"
            field = "bid_value"
            action_type = "降低出价/控成本"
            reason = f"当前 ROI {roi:.2f} 处于关注区间，需要测试流量成本改善空间。"
            risk = "出价降低可能导致展现和点击减少"
            option_configs = [
                ("conservative", "稳健", -5, 72, "轻微降低流量成本，尽量保持规模", {"roi_change_min": 0.05, "spend_change_pct_max": 0}),
                ("balanced", "平衡", -10, 48, "兼顾成本改善与流量稳定", {"roi_change_min": 0.1, "spend_change_pct_max": -3}),
                ("aggressive", "激进", -15, 48, "优先提升效率，接受流量规模下降", {"roi_change_min": 0.15, "spend_change_pct_max": -5}),
            ]
            rollback_condition = "展现或点击明显下降，且 ROI 未提升 0.1 时恢复原出价"

        candidates = [
            strategy for strategy in data.get("strategies", [])
            if (not strategy.get("action_type") or strategy["action_type"] == action_type)
            and (not strategy.get("scene") or strategy["scene"] == plan.get("scene_name"))
            and (strategy.get("min_roi") is None or roi >= float(strategy["min_roi"]))
            and (strategy.get("max_roi") is None or roi <= float(strategy["max_roi"]))
        ]
        candidates.sort(
            key=lambda strategy: (
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
        if has_constraint_signal or has_conflict or not matching or matching.get("outcome") != "success" or int(matching.get("evidence_score") or 0) < 50:
            recommended_tier = "conservative"
        elif learning_samples >= 3 and learning_weight < 0.9:
            recommended_tier = "conservative"
        elif int(matching.get("sample_count") or 0) >= 3 and float(matching.get("group_success_rate") or 0) >= 70 and int(matching.get("evidence_score") or 0) >= 75 and (learning_samples < 3 or learning_weight >= 1.05):
            recommended_tier = "aggressive"
        else:
            recommended_tier = "balanced"

        old_value = float(plan.get(field) or 0)
        if matching:
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
                "strategy_score": matching.get("evidence_score") if matching else None,
                "learning_weight": round(learning_weight, 4),
                "learning_sample_count": learning_samples,
                "learning_explanation": matching.get("learning_explanation") if matching else "暂无可学习的关联策略样本",
                "strategy_candidates": candidates[:5],
                "strategy_conflict": has_conflict,
                "conflict_reason": "高质量历史证据中同时存在成功与谨慎经验，默认采用稳健方案并等待人工选择" if has_conflict else "",
                "constraint_summary": constraint_summary,
            }
        )
    return drafts

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
    if d.get("strategies"):
        lines.append("历史验证策略（证据分表示数据可靠程度，不等于建议方向）：" + "；".join(
            f"{s['name']}：{s['conditions']}（适用场景{s.get('scene') or '不限'}，ROI {s.get('min_roi') if s.get('min_roi') is not None else '-∞'}~{s.get('max_roi') if s.get('max_roi') is not None else '+∞'}，结果{s.get('outcome', 'success')}，证据分{s.get('evidence_score', 0)}，学习权重{s.get('learning_weight', 1)}，学习样本{s.get('learning_sample_count', 0)}条，同类样本{s.get('sample_count', 1)}次，同类成功率{s.get('group_success_rate', 0)}%，证据{s['evidence'][:80]}）"
            for s in d["strategies"][:6]
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
