"""推广异常诊断中心：基于真实计划指标输出规则、证据和处理建议。"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.api.auth import get_current_user
from backend.app.core.db import get_db

from ._common import _now, _scope_filter
from .channel import CHANNEL_NAMES, channel_for_scene, channel_matches


router = APIRouter()


class AIDiagnosticIn(BaseModel):
    diagnostic_id: str
    plan_id: int
    store_id: int | None = None
    channel: str = ""
    rule_code: str = ""
    evidence: list[dict] = Field(default_factory=list)
    force: bool = False


def _ai_diagnostic_fingerprint(item: dict, diagnostics_config: dict | None = None, context: dict | None = None) -> str:
    """Return a stable fingerprint for the data behind one diagnostic signal."""
    payload = {
        "diagnostic_id": item.get("id"),
        "rule_code": item.get("rule_code"),
        "plan_status": item.get("plan_status"),
        "evidence": item.get("evidence") or [],
        "rule_explanation": item.get("rule_explanation") or "",
        "confidence": item.get("confidence"),
        "possible_causes": item.get("possible_causes") or [],
        "unknown_dimensions": item.get("unknown_dimensions") or [],
        "item_traffic": item.get("item_traffic") or {},
        "diagnostics_config": diagnostics_config or {},
        "context": context or {},
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _find_diagnostic(payload: dict, body: AIDiagnosticIn) -> dict | None:
    item = next((candidate for candidate in payload["items"] if candidate["id"] == body.diagnostic_id), None)
    if item is None:
        item = next((candidate for candidate in payload["items"] if candidate["plan_id"] == body.plan_id and (not body.rule_code or candidate["rule_code"] == body.rule_code)), None)
    return item


def _item_traffic_context(db, store_id: int, item_id: str, stats_by_item: dict[tuple[int, str], list[dict]] | None = None) -> dict:
    """Load the product-level promotion metrics available for a diagnostic.

    ``promo_item_stats`` is currently keyed by store/item/mode, so this is
    deliberately reported as product evidence rather than attributed to a
    specific campaign when the source is the plan-allocation fallback.
    """
    item_id = str(item_id or "").strip()
    if not item_id:
        return {
            "status": "missing",
            "reason": "当前计划没有关联到具体商品",
            "item_id": "",
            "metrics": [],
        }
    if stats_by_item is None:
        rows = db.execute(
            "SELECT item_id, item_title, mode, spend, sales, roi, clicks, orders, impressions, source, updated_at "
            "FROM promo_item_stats WHERE store_id = ? AND item_id = ? "
            "ORDER BY CASE mode WHEN 'realtime' THEN 0 WHEN 'yesterday' THEN 1 WHEN '7' THEN 2 WHEN '14' THEN 3 WHEN '30' THEN 4 ELSE 9 END",
            (store_id, item_id),
        ).fetchall()
        metrics = [dict(row) for row in rows]
    else:
        metrics = stats_by_item.get((store_id, item_id), [])
    if not metrics:
        return {
            "status": "missing",
            "reason": "商品级推广数据尚未同步",
            "item_id": item_id,
            "metrics": [],
        }
    # report 来源代表商品报表口径，即便订单为 0 也是真实的无转化结果；
    # plan_scene/plan 是计划归因，可能只提供花费、成交、点击，不能把缺失字段当成真实 0。
    has_full_traffic = any(str(row.get("source") or "") == "report" for row in metrics)
    return {
        "status": "complete" if has_full_traffic else "partial",
        "reason": "已同步商品报表指标" if has_full_traffic else "当前主要来自计划归因，展现量或订单等字段可能缺失",
        "item_id": item_id,
        "metrics": metrics,
    }


def _plan_stat_context(row: dict) -> dict:
    """Expose normalized plan metrics plus the complete raw report payload to AI."""
    stat = dict(row)
    raw = stat.pop("extra_json", "") or ""
    try:
        details = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        details = {}
    if not isinstance(details, dict):
        details = {}
    def _percent(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return value
        return round(number * 100, 2) if number <= 1 else number
    stat["report_details"] = details
    # Keep the names used by the UI alongside raw platform names so the model
    # can reason about funnel metrics without guessing what adPv/cvr mean.
    stat["funnel"] = {
        "impressions": details.get("adPv"),
        "clicks": details.get("click", stat.get("clicks")),
        "ctr_percent": _percent(details.get("ctr")),
        "conversion_rate_percent": _percent(details.get("cvr")),
        "orders": details.get("alipayInshopNum"),
        "direct_sales": details.get("alipayDirAmt", stat.get("alipay_dir")),
        "indirect_sales": details.get("alipayIndirAmt", stat.get("alipay_indir")),
        "retained_sales": details.get("retainedAlipayInshopAmt", stat.get("retained_sales")),
        "add_cart_orders": details.get("cartInshopNum"),
        "refund_amount": (details.get("refundDirAmt") or 0) + (details.get("refundIndirAmt") or 0) if details else stat.get("refund_amt"),
    }
    return stat


def _build_ai_context(db, item: dict) -> dict:
    """Collect plan and associated product evidence without pretending missing dimensions exist."""
    store_id = int(item["store_id"])
    plan_id = int(item["plan_id"])
    campaign_id = str(item.get("campaign_id") or "")
    plan_row = db.execute(
        "SELECT * FROM promo_plans WHERE id = ? AND store_id = ?",
        (plan_id, store_id),
    ).fetchone()
    stats_rows = db.execute(
        "SELECT * FROM promo_plan_stats WHERE store_id = ? AND campaign_id = ? ORDER BY CASE mode WHEN 'realtime' THEN 0 WHEN 'yesterday' THEN 1 ELSE 2 END",
        (store_id, campaign_id),
    ).fetchall()
    daily_rows = db.execute(
        "SELECT data_date, spend, sales, roi, clicks, updated_at FROM promo_plan_daily WHERE store_id = ? AND campaign_id = ? ORDER BY data_date DESC LIMIT 7",
        (store_id, campaign_id),
    ).fetchall()
    action_rows = db.execute(
        "SELECT action_type, description, before_value, after_value, change_pct, status, result, manual_conclusion, executed_at, verified_at, platform_status FROM promo_action_records WHERE store_id = ? AND plan_id = ? ORDER BY COALESCE(executed_at, created_at) DESC LIMIT 5",
        (store_id, plan_id),
    ).fetchall()
    strategy_rows = db.execute(
        "SELECT name, action_type, evidence, outcome, success_count, use_count, min_roi, max_roi, updated_at FROM promo_strategies WHERE store_id = ? ORDER BY updated_at DESC LIMIT 5",
        (store_id,),
    ).fetchall()
    item_traffic = _item_traffic_context(db, store_id, item.get("item_id") or "")
    return {
        "plan": dict(plan_row) if plan_row else {
            "id": plan_id,
            "store_id": store_id,
            "campaign_id": campaign_id,
            "plan_name": item.get("plan_name") or "",
        },
        "item": {
            "item_id": item.get("item_id") or "",
            "item_title": item.get("item_title") or "",
        },
        "item_traffic": item_traffic,
        "channel": {
            "code": item.get("channel") or "",
            "name": item.get("channel_name") or "",
        },
        "current_diagnostic": {
            "id": item.get("id"),
            "rule_code": item.get("rule_code"),
            "category": item.get("category"),
            "signal_type": item.get("signal_type"),
            "severity": item.get("severity"),
            "priority": item.get("priority"),
            "title": item.get("title"),
            "summary": item.get("summary"),
            "confidence": item.get("confidence"),
            "confidence_reason": item.get("confidence_reason"),
            "rule_explanation": item.get("rule_explanation"),
            "evidence": item.get("evidence") or [],
            "possible_causes": item.get("possible_causes") or [],
            "unknown_dimensions": item.get("unknown_dimensions") or [],
            "spend_at_risk": item.get("spend_at_risk") or 0,
            "sales_gap": item.get("sales_gap") or 0,
        },
        "stats": [_plan_stat_context(dict(row)) for row in stats_rows],
        "recent_daily": [dict(row) for row in daily_rows],
        "recent_actions": [dict(row) for row in action_rows],
        "learned_strategies": [dict(row) for row in strategy_rows],
    }


def _parse_ai_diagnostic(reply: str) -> dict:
    """Parse the model response while keeping a readable fallback for non-JSON models."""
    import json
    import re

    defaults = {
        "conclusion": reply.strip(),
        "issue_type": "待人工确认",
        "decision": "证据不足",
        "primary_cause": "",
        "affected_stage": "",
        "recommended_variable": "",
        "recommended_direction": "",
        "recommended_range": "不建议直接调整",
        "observation_hours": 48,
        "success_criteria": [],
        "rollback_condition": "证据不足时不执行调整",
        "causes": [],
        "evidence": [],
        "missing_data": [],
        "confidence": "low",
        "recommend_intervention": "先观察",
        "next_step": "补充数据后再进入 AI 决策",
    }
    candidate = reply.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.S | re.I)
    if fenced:
        candidate = fenced.group(1)
    else:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            candidate = candidate[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        return defaults
    if not isinstance(parsed, dict):
        return defaults
    result = dict(defaults)
    for key in ("conclusion", "issue_type", "decision", "primary_cause", "affected_stage", "recommended_variable", "recommended_direction", "recommended_range", "confidence", "recommend_intervention", "rollback_condition", "next_step"):
        if parsed.get(key):
            result[key] = str(parsed[key])
    observation_hours = parsed.get("observation_hours")
    try:
        if observation_hours is not None:
            result["observation_hours"] = max(1, min(168, int(observation_hours)))
    except (TypeError, ValueError):
        pass
    for key in ("causes", "evidence", "missing_data", "success_criteria"):
        value = parsed.get(key)
        if isinstance(value, list):
            result[key] = [str(item) for item in value if str(item).strip()][:6]
    return result


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2}
PRIORITY_ORDER = {"p0": 0, "p1": 1, "p2": 2, "p3": 3}
PRIORITY_METRIC_LABELS = {
    "drop_pct": ("ROI 跌幅", "%"),
    "spend": ("当前花费", "元"),
    "budget_utilization_pct": ("预算消耗率", "%"),
    "elapsed_pct": ("时间进度", "%"),
    "yesterday_spend": ("昨日花费", "元"),
    "pace_gap_pct": ("投放节奏落差", "%"),
    "stale_hours": ("数据滞后", "小时"),
}

RISK_RULES = {
    "budget_over",
    "budget_near",
    "spend_without_sales",
    "roi_drop",
    "roi_low",
    "delivery_stopped",
    "spend_too_fast",
}


def _signal_type(rule_code: str) -> str:
    if rule_code == "high_roi_low_spend":
        return "opportunity"
    if rule_code in RISK_RULES:
        return "risk"
    return "observation"


def _rule_explanation(rule_code: str, thresholds: dict | None = None) -> str:
    thresholds = thresholds or {}
    def _threshold(key: str, fallback: float) -> str:
        try:
            value = float(thresholds.get(key, fallback))
        except (TypeError, ValueError):
            value = fallback
        return f"{value:g}"

    explanations = {
        "data_stale": "计划或统计数据超过 24 小时未更新；为避免误判，本次只提示先同步数据，不继续运行其他业务规则。",
        "budget_over": "今日花费 ÷ 日预算达到或超过配置的预算上限比例。",
        "budget_near": "今日花费 ÷ 日预算达到配置的接近预算比例，但尚未超过预算上限。",
        "spend_without_sales": f"今日花费达到 {_threshold('spend_without_sales_min_spend', 50)} 元及以上，但平台归因成交仍为 0。",
        "roi_drop": f"今日花费达到 {_threshold('roi_drop_min_spend', 20)} 元及以上，且今日 ROI 低于昨日 ROI × 配置的下滑比例。",
        "roi_low": f"今日花费达到 {_threshold('roi_low_min_spend', 50)} 元及以上，且当前 ROI 低于配置的健康阈值。",
        "delivery_stopped": f"当前时间已到 10:00 以后、计划显示在投、昨日花费达到 {_threshold('delivery_stopped_min_yesterday_spend', 50)} 元及以上，但今日花费仍为 0。",
        "no_spend": "当前时间已到 10:00 以后且在投计划今日花费为 0，但缺少昨日有效消耗作为稳定基线。",
        "delivery_slow": f"当前时间已到 16:00 以后、昨日花费达到 {_threshold('delivery_slow_min_yesterday_spend', 50)} 元及以上，且今日花费不足昨日的 30%。",
        "low_spend": "当前时间已到 12:00 以后，消耗样本偏少且 ROI 尚未达到健康放量门槛。",
        "high_roi_low_spend": "当前时间已到 12:00 以后、今日花费达到 20 元及以上、ROI 达到健康门槛，同时预算消耗或预计全天花费明显低于正常节奏。",
        "spend_too_fast": "当前时间早于 20:00，预算消耗率达到 50% 以上或超过当前时间进度的 115%，且尚未真正超出预算上限。",
    }
    return explanations.get(rule_code, "当前指标命中了系统配置的诊断规则，仍需结合计划目标和业务背景人工复核。")


def _parse_datetime(value: str | None, now: datetime) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    return parsed.astimezone(now.tzinfo)


def _confidence(spend: float, clicks: int) -> tuple[str, str]:
    if spend >= 200 or clicks >= 100:
        return "high", "当前消耗或点击样本较充分，规则判断可信度较高。"
    if spend >= 50 or clicks >= 20:
        return "medium", "当前样本可以支持方向判断，但仍建议结合商品和活动信息复核。"
    return "low", "当前消耗和点击样本较少，只作为观察信号，不建议直接执行调整。"


def _evidence(label: str, current: float | int | str, baseline: float | int | str | None = None, unit: str = "") -> dict:
    return {"label": label, "current": current, "baseline": baseline, "unit": unit}


def _priority_metrics(item: dict) -> dict[str, float]:
    """Normalize the numeric evidence used by the dynamic priority engine."""
    metrics: dict[str, float] = {}
    for key, value in (item.get("priority_metrics") or {}).items():
        try:
            metrics[str(key)] = float(value)
        except (TypeError, ValueError):
            pass
    label_map = {
        "下降幅度": "drop_pct",
        "今日花费": "spend",
        "预算消耗率": "budget_utilization_pct",
        "当日时间进度": "elapsed_pct",
        "昨日花费": "yesterday_spend",
        "消耗节奏差": "pace_gap_pct",
        "预计全天花费": "projected_spend",
        "风险花费": "spend_at_risk",
    }
    for evidence in item.get("evidence") or []:
        label = str(evidence.get("label") or "")
        metric = label_map.get(label)
        if not metric:
            continue
        try:
            metrics[metric] = float(evidence.get("current") or 0)
        except (TypeError, ValueError):
            continue
    pacing = item.get("pacing") or {}
    for key, metric in (("budget_utilization_rate", "budget_utilization_pct"), ("elapsed_day_rate", "elapsed_pct"), ("projected_full_day_spend", "projected_spend")):
        if metric not in metrics:
            try:
                metrics[metric] = float(pacing.get(key))
            except (TypeError, ValueError):
                pass
    if "pace_gap_pct" not in metrics and metrics.get("budget_utilization_pct") is not None and metrics.get("elapsed_pct") is not None:
        metrics["pace_gap_pct"] = max(0.0, metrics["budget_utilization_pct"] - metrics["elapsed_pct"])
    if "pace_gap_pct" not in metrics and metrics.get("yesterday_spend", 0) > 0 and metrics.get("spend") is not None:
        metrics["pace_gap_pct"] = max(0.0, (1 - metrics["spend"] / metrics["yesterday_spend"]) * 100)
    if "spend_at_risk" not in metrics:
        metrics["spend_at_risk"] = float(item.get("spend_at_risk") or 0)
    return metrics


def _dynamic_priority(item: dict, setting: dict, bands: dict) -> tuple[str, str]:
    """Return the highest matching configured priority and a human-readable reason."""
    metrics = _priority_metrics(item)
    rule_bands = bands.get(item.get("rule_code"), {}) if isinstance(bands, dict) else {}
    matched: list[tuple[str, list[str]]] = []
    for priority in ("p0", "p1", "p2", "p3"):
        clauses = rule_bands.get(priority) or {}
        if not isinstance(clauses, dict):
            continue
        reasons: list[str] = []
        valid = True
        for metric, raw_threshold in clauses.items():
            try:
                threshold = float(raw_threshold)
            except (TypeError, ValueError):
                continue
            value = metrics.get(metric)
            if value is None or value < threshold:
                valid = False
                break
            label, unit = PRIORITY_METRIC_LABELS.get(metric, (metric, ""))
            reasons.append(f"{label} {value:g}{unit}≥{threshold:g}{unit}")
        if valid and reasons:
            matched.append((priority, reasons))
    if matched:
        priority, reasons = min(matched, key=lambda pair: PRIORITY_ORDER[pair[0]])
        return priority, "动态判定：" + "；".join(reasons)
    fallback = str(setting.get("priority") or "p2").lower()
    if fallback not in PRIORITY_ORDER:
        fallback = "p2"
    return fallback, "动态条件未命中，沿用规则兜底优先级"


def _context_path(path: str, *, plan_id: int, store_id: int, channel: str, diagnostic_id: str, rule_code: str) -> str:
    separator = "&" if "?" in path else "?"
    return (
        f"{path}{separator}store_id={store_id}&channel={channel}&plan_id={plan_id}"
        f"&diagnostic_id={diagnostic_id}&diagnostic={rule_code}&rule={rule_code}"
    )


def _recommendations(plan_id: int, rule_code: str, *, store_id: int, channel: str, diagnostic_id: str) -> list[dict]:
    actions = {
        "high_roi_low_spend": ("评估温和放量", "先检查出价、定向范围和流量获取能力；确认利润空间后，可从小幅提高出价或扩量开始。"),
        "delivery_stopped": ("排查无消耗原因", "检查计划状态、商品推广资格、出价竞争力和定向范围，恢复后再观察。"),
        "delivery_slow": ("排查消耗不足", "先区分流量不足、出价竞争力不足、人群过窄和素材承接问题，再选择单一变量调整。"),
        "spend_too_fast": ("控制投放节奏", "结合当前 ROI 判断是否收窄流量或降低出价；预算仅作为消耗上限。"),
        "roi_low": ("止损或收缩流量", "结合毛利底线复核；若低效持续，可降低出价、收窄人群或暂停问题单元。"),
        "spend_without_sales": ("排查转化断点", "检查流量意图、商品价格库存、详情承接和归因延迟，未确认原因前不继续放量。"),
    }
    action, reason = actions.get(rule_code, ("人工复核后调整", "结合异常证据和计划目标选择调整动作，系统不会自动执行。"))
    return [
        {
            "key": "recommended_action",
            "label": action,
            "action": action,
            "reason": reason,
            "requires_confirmation": True,
            "auto_execute": False,
            "path": _context_path("/promotions/plans", plan_id=plan_id, store_id=store_id, channel=channel, diagnostic_id=diagnostic_id, rule_code=rule_code),
        },
        {
            "key": "inspect_plan",
            "label": "查看计划明细",
            "reason": "先确认计划状态、预算、出价和最近操作，排除配置或同步问题。",
            "path": _context_path("/promotions/plans", plan_id=plan_id, store_id=store_id, channel=channel, diagnostic_id=diagnostic_id, rule_code=rule_code),
        },
        {
            "key": "ai_decision",
            "label": "生成 AI 决策",
            "reason": "结合当前异常证据生成稳健、平衡、激进三档处理方案，再由人工确认。",
            "path": _context_path("/promotions/decisions", plan_id=plan_id, store_id=store_id, channel=channel, diagnostic_id=diagnostic_id, rule_code=rule_code),
        },
        {
            "key": "cockpit",
            "label": "进入闭环作战台",
            "reason": "查看该计划已有的决策、动作和验证记录，避免重复或冲突调整。",
            "path": _context_path("/promotions/cockpit", plan_id=plan_id, store_id=store_id, channel=channel, diagnostic_id=diagnostic_id, rule_code=rule_code),
        },
    ]


def _diagnostic(
    *,
    plan: dict,
    store_name: str,
    rule_code: str,
    category: str,
    severity: str,
    title: str,
    summary: str,
    confidence: str,
    confidence_reason: str,
    evidence: list[dict],
    possible_causes: list[str],
    detected_at: str,
    spend_at_risk: float = 0.0,
    sales_gap: float = 0.0,
    pacing: dict | None = None,
) -> dict:
    plan_id = int(plan["id"])
    channel = channel_for_scene(plan.get("scene"), plan.get("scene_name"))
    diagnostic_id = f"{rule_code}:{plan_id}"
    recommendations = _recommendations(
        plan_id,
        rule_code,
        store_id=int(plan["store_id"]),
        channel=channel,
        diagnostic_id=diagnostic_id,
    )
    return {
        "id": diagnostic_id,
        "rule_code": rule_code,
        "rule_explanation": _rule_explanation(rule_code),
        "signal_type": _signal_type(rule_code),
        "category": category,
        "severity": severity,
        "title": title,
        "summary": summary,
        "confidence": confidence,
        "confidence_reason": confidence_reason,
        "plan_id": plan_id,
        "plan_name": plan.get("plan_name") or f"计划 {plan_id}",
        "campaign_id": str(plan.get("campaign_id") or ""),
        "item_id": str(plan.get("item_id") or ""),
        "item_title": plan.get("item_title") or "",
        "item_image": plan.get("item_image") or "",
        "store_id": int(plan["store_id"]),
        "store_name": store_name,
        "scene_name": plan.get("scene_name") or "未标注场景",
        "channel": channel,
        "channel_name": CHANNEL_NAMES[channel],
        "plan_status": plan.get("status") or "",
        "spend_at_risk": round(max(0.0, spend_at_risk), 2),
        "sales_gap": round(max(0.0, sales_gap), 2),
        "evidence": evidence,
        "possible_causes": possible_causes,
        "recommendations": recommendations,
        "recommendation": recommendations[0],
        "pacing": pacing or {},
        "item_traffic": plan.get("item_traffic") or {"status": "missing", "reason": "商品未同步", "item_id": "", "metrics": []},
        "unknown_dimensions": ["商品库存与价格", "活动节奏", "素材与人群明细", "竞争环境变化"],
        "detected_at": detected_at,
    }


def detect_promotion_anomalies(
    db,
    user: dict,
    store_id: int | None = None,
    channel: str = "",
    *,
    now: datetime | None = None,
) -> dict:
    """按当前权限范围检测推广异常；不写入数据库或万相台。"""
    from backend.app.api.alerts import get_alert_config

    current_time = now or datetime.now().astimezone()
    if current_time.tzinfo is None:
        current_time = current_time.astimezone()
    detected_at = current_time.isoformat(timespec="seconds")
    scope_frag, scope_params = _scope_filter(store_id, user)
    plans = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM promo_plans WHERE 1=1" + scope_frag + " ORDER BY updated_at DESC LIMIT 3000",
            scope_params,
        ).fetchall()
    ]
    plans = [plan for plan in plans if channel_matches(channel, plan.get("scene"), plan.get("scene_name"))]
    stats = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM promo_plan_stats WHERE 1=1" + scope_frag + " ORDER BY updated_at DESC",
            scope_params,
        ).fetchall()
    ]
    stat_by_key = {(int(row["store_id"]), str(row["campaign_id"]), row["mode"]): row for row in stats}
    plan_items = [
        dict(row)
        for row in db.execute(
            "SELECT store_id, campaign_id, item_id, item_title, image FROM promo_plan_items WHERE 1=1" + scope_frag,
            scope_params,
        ).fetchall()
    ]
    item_by_key = {(int(row["store_id"]), str(row["campaign_id"])): row for row in plan_items}
    item_stats = [
        dict(row)
        for row in db.execute(
            "SELECT store_id, item_id, item_title, mode, spend, sales, roi, clicks, orders, impressions, source, updated_at "
            "FROM promo_item_stats WHERE 1=1" + scope_frag + " "
            "ORDER BY CASE mode WHEN 'realtime' THEN 0 WHEN 'yesterday' THEN 1 WHEN '7' THEN 2 WHEN '14' THEN 3 WHEN '30' THEN 4 ELSE 9 END",
            scope_params,
        ).fetchall()
    ]
    stats_by_item: dict[tuple[int, str], list[dict]] = {}
    for row in item_stats:
        stats_by_item.setdefault((int(row["store_id"]), str(row.get("item_id") or "").strip()), []).append(row)
    store_ids = sorted({int(plan["store_id"]) for plan in plans})
    store_names: dict[int, str] = {}
    if store_ids:
        placeholders = ",".join("?" for _ in store_ids)
        store_names = {
            int(row["id"]): row["name"]
            for row in db.execute(f"SELECT id, name FROM stores WHERE id IN ({placeholders})", store_ids).fetchall()
        }

    alert_config = get_alert_config(db) or {}
    config = alert_config.get("plan") or {}
    diagnostics_config = alert_config.get("diagnostics") or {}
    diagnostic_channels = diagnostics_config.get("channels") or {}
    enabled_channels = {
        str(channel)
        for channel, enabled in diagnostic_channels.items()
        if enabled is not False
    }
    # 诊断渠道由设置控制；未配置的渠道保持兼容并默认启用。
    plans = [
        plan for plan in plans
        if plan.get("platform_presence") != "missing"
        and plan.get("status") != "平台已失效"
        and channel_for_scene(plan.get("scene"), plan.get("scene_name")) in enabled_channels
    ]
    diagnostic_rules = diagnostics_config.get("rules") or {}
    diagnostic_thresholds = diagnostics_config.get("thresholds") or {}

    def rule_enabled(rule_code: str) -> bool:
        setting = diagnostic_rules.get(rule_code)
        return not isinstance(setting, dict) or setting.get("enabled", True) is not False

    def threshold(key: str, fallback: float) -> float:
        try:
            return float(diagnostic_thresholds.get(key, fallback))
        except (TypeError, ValueError):
            return fallback

    budget_over = float(config.get("budget_over") or 1.0)
    budget_warn = float(config.get("budget_warn") or 0.8)
    roi_drop_ratio = float(config.get("roi_drop_ratio") or 0.6)
    roi_low = float(config.get("roi_low") or 1.0)
    spend_without_sales_min_spend = threshold("spend_without_sales_min_spend", 50.0)
    roi_drop_min_spend = threshold("roi_drop_min_spend", 20.0)
    roi_drop_high_drop_pct = threshold("roi_drop_high_drop_pct", 50.0)
    roi_drop_high_spend = threshold("roi_drop_high_spend", 100.0)
    roi_low_min_spend = threshold("roi_low_min_spend", 50.0)
    roi_low_high_spend = threshold("roi_low_high_spend", 200.0)
    delivery_stopped_min_yesterday_spend = threshold("delivery_stopped_min_yesterday_spend", 50.0)
    delivery_slow_min_yesterday_spend = threshold("delivery_slow_min_yesterday_spend", 50.0)
    diagnostics: list[dict] = []
    realtime_coverage = 0

    for plan in plans:
        if plan.get("status") != "在投":
            continue
        diagnostic_start = len(diagnostics)
        key = (int(plan["store_id"]), str(plan["campaign_id"]))
        item = item_by_key.get(key) or {}
        plan["item_id"] = item.get("item_id") or ""
        plan["item_title"] = item.get("item_title") or ""
        plan["item_image"] = item.get("image") or ""
        plan["item_traffic"] = _item_traffic_context(db, int(plan["store_id"]), plan["item_id"], stats_by_item)
        realtime = stat_by_key.get((*key, "realtime"))
        yesterday = stat_by_key.get((*key, "yesterday"))
        if realtime:
            realtime_coverage += 1
        rt_spend = float((realtime or {}).get("spend") or 0)
        rt_sales = float((realtime or {}).get("sales") or 0)
        rt_roi = float((realtime or {}).get("roi") or 0)
        rt_clicks = int((realtime or {}).get("clicks") or 0)
        # 实时同步会把昨日截至同一小时的基准写入 realtime.prev_*；优先使用它，
        # 避免诊断把今天累计与昨日全天混比。旧数据或基准缺失时才回退到昨日模式。
        same_hour = (realtime or {}).get("prev_scope") == "same_hour"
        if same_hour:
            ye_spend = float((realtime or {}).get("prev_spend") or 0)
            ye_sales = float((realtime or {}).get("prev_sales") or 0)
            ye_roi = float((realtime or {}).get("prev_roi") or 0)
        elif realtime:
            # 有实时数据但没有同小时基准时，不回退昨日全天，避免环比规则误报。
            ye_spend = ye_sales = ye_roi = 0.0
        else:
            ye_spend = float((yesterday or {}).get("spend") or 0)
            ye_sales = float((yesterday or {}).get("sales") or 0)
            ye_roi = float((yesterday or {}).get("roi") or 0)
        budget = float(plan.get("day_budget") or 0)
        elapsed_ratio = min(1.0, max(1 / 24, (current_time.hour + current_time.minute / 60) / 24))
        budget_ratio = rt_spend / budget if budget > 0 else None
        projected_spend = rt_spend / elapsed_ratio if rt_spend > 0 else 0.0
        pacing = {
            "elapsed_day_rate": round(elapsed_ratio * 100, 1),
            "budget_ceiling": round(budget, 2),
            "budget_utilization_rate": round(budget_ratio * 100, 1) if budget_ratio is not None else None,
            "projected_full_day_spend": round(projected_spend, 2),
            "yesterday_spend": round(ye_spend, 2),
            "budget_role": "spend_ceiling",
        }
        store_name = store_names.get(int(plan["store_id"]), "")
        confidence, confidence_reason = _confidence(rt_spend, rt_clicks)
        latest_update = max(
            (realtime or {}).get("updated_at") or "",
            (yesterday or {}).get("updated_at") or "",
            plan.get("updated_at") or "",
        )
        latest_dt = _parse_datetime(latest_update, current_time)

        if rule_enabled("data_stale") and (latest_dt is None or latest_dt < current_time - timedelta(hours=24)):
            diagnostics.append(_diagnostic(
                plan=plan,
                store_name=store_name,
                rule_code="data_stale",
                category="data",
                severity="medium",
                title="推广计划数据超过 24 小时未更新",
                summary="当前指标可能无法代表真实投放状态，处理其他异常前应先完成数据同步。",
                confidence="high",
                confidence_reason="数据更新时间可以直接验证，无需推断业务原因。",
                evidence=[_evidence("最近更新时间", latest_update or "缺失"), _evidence("过期阈值", 24, unit="小时")],
                possible_causes=["万相台登录态或授权失效（待核查）", "推广同步任务失败或尚未运行（待核查）", "平台报表暂未返回该计划（待核查）"],
                detected_at=detected_at,
            ))
            diagnostics[-1]["pacing"] = pacing
            diagnostics[-1]["priority_metrics"] = {
                "stale_hours": round(max(24.0, (current_time - latest_dt).total_seconds() / 3600) if latest_dt else 99999.0, 1),
            }
            continue

        if budget > 0 and rt_spend > 0:
            if rule_enabled("budget_over") and budget_ratio >= budget_over:
                diagnostics.append(_diagnostic(
                    plan=plan,
                    store_name=store_name,
                    rule_code="budget_over",
                    category="budget",
                    severity="critical",
                    title="今日花费已经超过日预算",
                    summary=f"当前花费达到日预算的 {budget_ratio * 100:.0f}%，需要先核对平台预算与当前消耗节奏。",
                    confidence="high",
                    confidence_reason="预算与实时花费均为平台直接指标，异常已经发生。",
                    evidence=[_evidence("今日花费", round(rt_spend, 2), unit="元"), _evidence("日预算", round(budget, 2), unit="元"), _evidence("预算消耗率", round(budget_ratio * 100, 1), 100, "%")],
                    possible_causes=["当前平台预算与本地同步值不一致（待核查）", "流量高峰导致消耗加快（待核查）", "近期出价或定向范围发生变化（待核查）"],
                    spend_at_risk=rt_spend - budget,
                    detected_at=detected_at,
                ))
            elif rule_enabled("budget_near") and budget_ratio >= budget_warn:
                diagnostics.append(_diagnostic(
                    plan=plan,
                    store_name=store_name,
                    rule_code="budget_near",
                    category="budget",
                    severity="medium",
                    title="今日预算即将耗尽",
                    summary=f"当前花费达到日预算的 {budget_ratio * 100:.0f}%，需结合剩余时段和 ROI 判断是否调整。",
                    confidence="high",
                    confidence_reason="预算消耗率由平台花费与计划日预算直接计算。",
                    evidence=[_evidence("今日花费", round(rt_spend, 2), unit="元"), _evidence("日预算", round(budget, 2), unit="元"), _evidence("预算消耗率", round(budget_ratio * 100, 1), 100, "%")],
                    possible_causes=["当前流量节奏高于日常（待核查）", "预算设置不足以覆盖全天（待核查）", "出价或流量范围扩大（待核查）"],
                    detected_at=detected_at,
                ))

        if rule_enabled("spend_without_sales") and rt_spend >= spend_without_sales_min_spend and rt_sales <= 0:
            diagnostics.append(_diagnostic(
                plan=plan,
                store_name=store_name,
                rule_code="spend_without_sales",
                category="conversion",
                severity="high",
                title="已有明显消耗但暂未产生成交",
                summary=f"今日已花费 {rt_spend:.0f} 元、点击 {rt_clicks} 次，但平台归因成交仍为 0。",
                confidence=confidence,
                confidence_reason=confidence_reason,
                evidence=[_evidence("今日花费", round(rt_spend, 2), unit="元"), _evidence("今日点击", rt_clicks, unit="次"), _evidence("归因成交", round(rt_sales, 2), unit="元"), _evidence("昨日成交", round(ye_sales, 2), unit="元")],
                possible_causes=["点击流量与商品购买意图不匹配（待核查）", "商品价格、库存、评价或详情页承接不足（待核查）", "平台归因回传存在延迟（待核查）"],
                spend_at_risk=rt_spend,
                sales_gap=ye_sales,
                detected_at=detected_at,
            ))
        elif rule_enabled("roi_drop") and rt_spend >= roi_drop_min_spend and ye_roi > 0 and 0 < rt_roi < ye_roi * roi_drop_ratio:
            drop_pct = (1 - rt_roi / ye_roi) * 100
            diagnostics.append(_diagnostic(
                plan=plan,
                store_name=store_name,
                rule_code="roi_drop",
                category="efficiency",
                severity="high" if drop_pct >= roi_drop_high_drop_pct and rt_spend >= roi_drop_high_spend else "medium",
                title="ROI 较昨日明显下滑",
                summary=f"今日 ROI {rt_roi:.2f}，较昨日 {ye_roi:.2f} 下降 {drop_pct:.0f}%。",
                confidence=confidence,
                confidence_reason=confidence_reason,
                evidence=[_evidence("今日 ROI", round(rt_roi, 2), unit=""), _evidence("昨日 ROI", round(ye_roi, 2), unit=""), _evidence("下降幅度", round(drop_pct, 1), unit="%"), _evidence("今日花费", round(rt_spend, 2), unit="元")],
                possible_causes=["流量结构或推广对象发生变化（待核查）", "商品转化率下降（待核查）", "价格、活动或竞争环境变化（待核查）"],
                spend_at_risk=rt_spend * min(1.0, drop_pct / 100),
                sales_gap=max(0.0, ye_sales - rt_sales),
                detected_at=detected_at,
            ))

        if rule_enabled("roi_low") and rt_spend >= roi_low_min_spend and 0 < rt_roi < roi_low:
            diagnostics.append(_diagnostic(
                plan=plan,
                store_name=store_name,
                rule_code="roi_low",
                category="efficiency",
                severity="high" if rt_spend >= roi_low_high_spend else "medium",
                title="当前 ROI 低于健康阈值",
                summary=f"今日 ROI {rt_roi:.2f} 低于配置阈值 {roi_low:.2f}，需要结合毛利和计划目标判断是否止损。",
                confidence=confidence,
                confidence_reason=confidence_reason,
                evidence=[_evidence("今日 ROI", round(rt_roi, 2)), _evidence("健康阈值", round(roi_low, 2)), _evidence("今日花费", round(rt_spend, 2), unit="元"), _evidence("今日成交", round(rt_sales, 2), unit="元")],
                possible_causes=["出价或流量获取成本偏高（待核查）", "商品转化与客单不足（待核查）", "该计划的目标可能不是直接成交（待核查）"],
                spend_at_risk=rt_spend * max(0.0, 1 - rt_roi / roi_low),
                detected_at=detected_at,
            ))

        if rule_enabled("delivery_stopped") and current_time.hour >= 10 and ye_spend >= delivery_stopped_min_yesterday_spend and rt_spend <= 0:
            diagnostics.append(_diagnostic(
                plan=plan,
                store_name=store_name,
                rule_code="delivery_stopped",
                category="delivery",
                severity="high",
                title="在投计划今日尚未产生消耗",
                summary=f"昨日花费 {ye_spend:.0f} 元，但今日截至 {current_time.strftime('%H:%M')} 仍无消耗。",
                confidence="high" if current_time.hour >= 14 else "medium",
                confidence_reason="计划状态、昨日消耗和今日实时消耗均可直接验证；越接近下午判断越稳定。",
                evidence=[_evidence("今日花费", round(rt_spend, 2), unit="元"), _evidence("昨日花费", round(ye_spend, 2), unit="元"), _evidence("当前时间", current_time.strftime("%H:%M"))],
                possible_causes=["计划在平台被暂停或审核受限（待核查）", "预算、出价或流量范围无法获得展现（待核查）", "商品状态、库存或推广资格异常（待核查）"],
                sales_gap=ye_sales,
                detected_at=detected_at,
            ))
        elif rule_enabled("no_spend") and current_time.hour >= 10 and rt_spend <= 0:
            diagnostics.append(_diagnostic(
                plan=plan,
                store_name=store_name,
                rule_code="no_spend",
                category="delivery",
                severity="medium",
                title="在投计划当前无消耗",
                summary=f"计划显示在投，但截至 {current_time.strftime('%H:%M')} 实时花费仍为 0；因缺少充分历史样本，仅作为排查信号。",
                confidence="low",
                confidence_reason="无消耗可以直接验证，但缺少昨日有效消耗，无法确认是否偏离正常节奏。",
                evidence=[_evidence("今日花费", 0, unit="元"), _evidence("昨日花费", round(ye_spend, 2), unit="元"), _evidence("当前时间", current_time.strftime("%H:%M"))],
                possible_causes=["计划尚未获得流量（待核查）", "出价或定向范围限制流量（待核查）", "商品推广资格或计划状态异常（待核查）"],
                detected_at=detected_at,
            ))
        elif rule_enabled("delivery_slow") and current_time.hour >= 16 and ye_spend >= delivery_slow_min_yesterday_spend and 0 < rt_spend < ye_spend * 0.3:
            diagnostics.append(_diagnostic(
                plan=plan,
                store_name=store_name,
                rule_code="delivery_slow",
                category="delivery",
                severity="medium",
                title="今日投放节奏明显低于昨日",
                summary=f"截至 {current_time.strftime('%H:%M')} 今日花费仅为昨日的 {rt_spend / ye_spend * 100:.0f}%。",
                confidence=confidence,
                confidence_reason=confidence_reason,
                evidence=[_evidence("今日花费", round(rt_spend, 2), unit="元"), _evidence("昨日花费", round(ye_spend, 2), unit="元"), _evidence("昨日占比", round(rt_spend / ye_spend * 100, 1), 100, "%")],
                possible_causes=["流量竞争或人群规模变化（待核查）", "预算、出价或推广对象被调整（待核查）", "商品或计划状态发生限制（待核查）"],
                sales_gap=max(0.0, ye_sales - rt_sales),
                detected_at=detected_at,
            ))

        if rule_enabled("low_spend") and current_time.hour >= 12 and 0 < rt_spend < max(20.0, projected_spend * 0.25) and rt_roi < max(2.0, roi_low * 1.5):
            diagnostics.append(_diagnostic(
                plan=plan,
                store_name=store_name,
                rule_code="low_spend",
                category="delivery",
                severity="medium",
                title="计划消耗偏低，暂不具备放量结论",
                summary="当前消耗样本较少且 ROI 尚未达到健康放量门槛，建议先定位获量和转化问题。",
                confidence="low",
                confidence_reason="当前消耗样本不足，只能用于发现问题，不能支持直接放量。",
                evidence=[_evidence("今日花费", round(rt_spend, 2), unit="元"), _evidence("当前 ROI", round(rt_roi, 2)), _evidence("预计全天花费", round(projected_spend, 2), unit="元")],
                possible_causes=["出价竞争力不足（待核查）", "人群或推广范围过窄（待核查）", "素材和商品承接不足（待核查）"],
                detected_at=detected_at,
            ))

        healthy_roi = max(2.0, roi_low * 1.5)
        low_budget_pace = budget_ratio is not None and budget_ratio < elapsed_ratio * 0.35
        low_history_pace = ye_spend >= 50 and projected_spend < ye_spend * 0.6
        if rule_enabled("high_roi_low_spend") and current_time.hour >= 12 and rt_spend >= 20 and rt_roi >= healthy_roi and (low_budget_pace or low_history_pace):
            diagnostics.append(_diagnostic(
                plan=plan,
                store_name=store_name,
                rule_code="high_roi_low_spend",
                category="growth",
                severity="medium",
                title="高 ROI 计划存在放量机会",
                summary=f"当前 ROI {rt_roi:.2f}，但按当前节奏预计全天花费仅 {projected_spend:.0f} 元；建议先定位流量获取瓶颈，再小步放量。",
                confidence=confidence,
                confidence_reason=confidence_reason,
                evidence=[
                    _evidence("当前 ROI", round(rt_roi, 2), healthy_roi),
                    _evidence("今日花费", round(rt_spend, 2), unit="元"),
                    _evidence("预计全天花费", round(projected_spend, 2), round(ye_spend, 2) if ye_spend else None, "元"),
                    _evidence("预算消耗率", round(budget_ratio * 100, 1), round(elapsed_ratio * 100, 1), "%") if budget_ratio is not None else _evidence("日预算", "未设置或未同步"),
                ],
                possible_causes=["出价竞争力不足（待核查）", "人群或推广范围过窄（待核查）", "素材点击和商品承接限制流量（待核查）"],
                sales_gap=max(0.0, ye_sales - rt_sales),
                detected_at=detected_at,
            ))

        if rule_enabled("spend_too_fast") and budget_ratio is not None and current_time.hour < 20 and budget_ratio >= max(0.5, elapsed_ratio * 1.15) and budget_ratio < budget_over:
            diagnostics.append(_diagnostic(
                plan=plan,
                store_name=store_name,
                rule_code="spend_too_fast",
                category="delivery",
                severity="medium" if rt_roi >= roi_low else "high",
                title="当前消耗节奏偏快",
                summary=f"全天已过 {elapsed_ratio * 100:.0f}%，预算上限已消耗 {budget_ratio * 100:.0f}%；应结合 ROI 决定保持放量还是控制节奏。",
                confidence="high",
                confidence_reason="当前时间、实时花费和预算上限均为可直接验证数据。",
                evidence=[_evidence("当日时间进度", round(elapsed_ratio * 100, 1), unit="%"), _evidence("预算消耗率", round(budget_ratio * 100, 1), unit="%"), _evidence("当前 ROI", round(rt_roi, 2), roi_low)],
                possible_causes=["流量高峰带来消耗加速（待核查）", "近期提高出价或扩大定向（待核查）", "平台预算与本地同步值不一致（待核查）"],
                spend_at_risk=max(0.0, projected_spend - budget),
                detected_at=detected_at,
            ))

        for diagnostic in diagnostics[diagnostic_start:]:
            diagnostic["pacing"] = pacing

    diagnostics_config = alert_config.get("diagnostics") or {}
    diagnostic_rules = diagnostics_config.get("rules") or {}
    priority_thresholds = diagnostics_config.get("priority_thresholds") or {}
    for diagnostic in diagnostics:
        diagnostic["rule_explanation"] = _rule_explanation(diagnostic["rule_code"], diagnostic_thresholds)
        setting = diagnostic_rules.get(diagnostic["rule_code"])
        configured_priority = setting.get("priority") if isinstance(setting, dict) else None
        if isinstance(setting, dict) and str(setting.get("priority_mode") or "dynamic").lower() == "fixed":
            priority = configured_priority if configured_priority in PRIORITY_ORDER else None
            reason = "固定优先级：由诊断规则设置指定"
        else:
            priority, reason = _dynamic_priority(diagnostic, setting if isinstance(setting, dict) else {}, priority_thresholds)
        if not priority:
            priority = "p3" if diagnostic["signal_type"] == "observation" else "p2" if diagnostic["signal_type"] == "opportunity" else "p0" if diagnostic["severity"] == "critical" else "p1" if diagnostic["severity"] == "high" else "p2"
            reason = "按异常类型与严重度使用系统默认优先级"
        diagnostic["priority"] = priority
        diagnostic["priority_reason"] = reason

    diagnostics.sort(key=lambda item: (PRIORITY_ORDER.get(item.get("priority"), 9), -item["spend_at_risk"], SEVERITY_ORDER.get(item["severity"], 9), item["id"]))
    risk_by_plan: dict[int, float] = {}
    for item in diagnostics:
        risk_by_plan[item["plan_id"]] = max(risk_by_plan.get(item["plan_id"], 0.0), float(item["spend_at_risk"] or 0))
    categories: dict[str, int] = {}
    channels: dict[str, int] = {}
    for item in diagnostics:
        categories[item["category"]] = categories.get(item["category"], 0) + 1
        channels[item["channel"]] = channels.get(item["channel"], 0) + 1
    active_plan_count = sum(1 for plan in plans if plan.get("status") == "在投")
    item_traffic_coverage_count = sum(
        1 for plan in plans
        if plan.get("status") == "在投" and (plan.get("item_traffic") or {}).get("status") != "missing"
    )
    item_traffic_complete_count = sum(
        1 for plan in plans
        if plan.get("status") == "在投" and (plan.get("item_traffic") or {}).get("status") == "complete"
    )
    return {
        "summary": {
            "total": len(diagnostics),
            "risk_count": sum(1 for item in diagnostics if item["signal_type"] == "risk"),
            "opportunity_count": sum(1 for item in diagnostics if item["signal_type"] == "opportunity"),
            "observation_count": sum(1 for item in diagnostics if item["signal_type"] == "observation"),
            "critical": sum(1 for item in diagnostics if item["severity"] == "critical"),
            "high": sum(1 for item in diagnostics if item["severity"] == "high"),
            "medium": sum(1 for item in diagnostics if item["severity"] == "medium"),
            "affected_plan_count": len({item["plan_id"] for item in diagnostics}),
            "estimated_spend_at_risk": round(sum(risk_by_plan.values()), 2),
        },
        "items": diagnostics[:1000],
        "categories": [{"category": key, "count": value} for key, value in sorted(categories.items(), key=lambda pair: (-pair[1], pair[0]))],
        "channels": [{"channel": key, "channel_name": CHANNEL_NAMES[key], "count": value} for key, value in sorted(channels.items(), key=lambda pair: (-pair[1], pair[0]))],
        "data_health": {
            "visible_plan_count": len(plans),
            "active_plan_count": active_plan_count,
            "realtime_coverage_count": realtime_coverage,
            "realtime_coverage_rate": round(realtime_coverage / active_plan_count * 100, 1) if active_plan_count else 0.0,
            "item_traffic_coverage_count": item_traffic_coverage_count,
            "item_traffic_complete_count": item_traffic_complete_count,
            "item_traffic_coverage_rate": round(item_traffic_coverage_count / active_plan_count * 100, 1) if active_plan_count else 0.0,
        },
        "thresholds": {
            "budget_over": budget_over,
            "budget_warn": budget_warn,
            "roi_drop_ratio": roi_drop_ratio,
            "roi_low": roi_low,
            "minimum_spend_for_conversion": 50.0,
            "budget_role": "spend_ceiling",
        },
        "diagnostics": diagnostics_config,
        "generated_at": detected_at,
    }


@router.post("/diagnostics/ai")
def ai_diagnose_promotion(
    body: AIDiagnosticIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """对单条规则命中的异常做 AI 二次诊断，不直接生成或执行调整动作。"""
    payload = detect_promotion_anomalies(db, user, body.store_id, body.channel)
    item = _find_diagnostic(payload, body)
    if item is None:
        raise HTTPException(status_code=404, detail="诊断信号不存在，可能已因规则配置或数据更新而失效")

    context = _build_ai_context(db, item)
    fingerprint = _ai_diagnostic_fingerprint(item, payload.get("diagnostics"), context)
    if not body.force:
        cached = db.execute(
            "SELECT result_json, updated_at FROM promo_ai_diagnoses WHERE user_id = ? AND diagnostic_id = ? AND data_fingerprint = ?",
            (int(user["id"]), item["id"], fingerprint),
        ).fetchone()
        if cached:
            try:
                result = json.loads(cached["result_json"])
            except (TypeError, ValueError):
                result = None
            if isinstance(result, dict) and isinstance(result.get("ai_diagnosis"), dict):
                return {
                    **result,
                    "cached": True,
                    "generated_at": cached["updated_at"],
                }

    # 模型请求可能持续几十秒；先释放本次诊断读取事务，避免 SQLite 长时间
    # 持有读锁，阻塞后台同步或本接口稍后的诊断结果写入。
    db.commit()

    from backend.app.api.model_configs import get_default_config
    from backend.app.core.ai_client import AIError, chat_completion

    cfg = get_default_config(db)
    if not cfg or not cfg.get("api_key"):
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")

    context_json = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    prompt = (
        "你是淘宝推广运营的资深诊断师，负责把规则异常转化为可验证的运营判断。"
        "只能使用输入 JSON 中的事实，不能补造数据；明确区分事实、推测和缺失信息。"
        "规则命中只是发现异常，不等于根因成立。先判断是否值得干预：如果样本不足、数据过期、没有因果证据，必须选择‘证据不足’或‘建议观察’，不要为了给方案而给方案。"
        "如果建议干预，只允许选择一个最主要的投放变量，给出方向和保守的幅度范围，不得同时修改多个变量；没有足够基线时，recommended_range 填‘不建议直接调整’。"
        "必须结合最近动作和已验证经验，避免重复建议刚做过且无效的调整。"
        "请严格返回 JSON，不要 Markdown，字段必须包含："
        "conclusion（1-2句结论）、decision（建议干预/建议观察/证据不足三选一）、issue_type（问题类型）、"
        "primary_cause（最可能的一个原因；不能确定时为空）、affected_stage（流量/点击/转化/成本/预算/商品承接/数据质量之一）、"
        "causes（按可能性排序，最多3条）、evidence（支持判断的事实，最多4条）、missing_data（仍需人工确认，最多4条）、"
        "confidence（高/中/低）、recommend_intervention（建议干预/建议观察/暂不判断三选一）、"
        "recommended_variable（建议调整的唯一变量）、recommended_direction（提高/降低/收窄/扩大/暂停/不调整）、"
        "recommended_range（幅度范围或不建议直接调整）、observation_hours（1-168的整数）、"
        "success_criteria（可验证的成功标准数组，最多3条）、rollback_condition（回滚条件）、next_step（下一步动作）。\n\n"
        "stats 中的 report_details 是万相台计划报表原始明细，adPv=展现量、click=点击、ctr/cvr 为比例、alipayInshopNum=成交件数；funnel 是已换算的可读漏斗指标。"
        "请优先用 realtime 明细判断当前状态，再用 yesterday/7d 与历史趋势做对比；字段缺失时明确标注，不要把缺失当成 0。\n\n"
        "下面是当前可用数据，请先理解字段含义再作答：\n"
        f"{context_json}"
    )
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": prompt}], timeout=120.0, max_tokens=1200)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    diagnosis = _parse_ai_diagnostic(reply)
    next_path = next((rec["path"] for rec in item.get("recommendations", []) if rec.get("key") == "ai_decision"), "/promotions/decisions")
    now = _now()
    result = {
        "diagnostic": item,
        "input_context": context,
        "ai_diagnosis": diagnosis,
        "raw_reply": reply,
        "source_context": {
            "diagnostic_id": item["id"],
            "rule_code": item["rule_code"],
            "plan_id": item["plan_id"],
            "store_id": item["store_id"],
            "channel": item.get("channel") or body.channel,
        },
        "next_path": next_path,
    }
    db.execute(
        """
        INSERT INTO promo_ai_diagnoses
            (user_id, diagnostic_id, plan_id, store_id, channel, rule_code, data_fingerprint, result_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, diagnostic_id, data_fingerprint) DO UPDATE SET
            result_json = excluded.result_json,
            updated_at = excluded.updated_at,
            channel = excluded.channel,
            rule_code = excluded.rule_code
        """,
        (
            int(user["id"]), item["id"], int(item["plan_id"]), int(item["store_id"]),
            item.get("channel") or body.channel or "", item.get("rule_code") or body.rule_code or "",
            fingerprint, json.dumps(result, ensure_ascii=False), now, now,
        ),
    )
    return {**result, "cached": False, "generated_at": now}


@router.get("/diagnostics/ai")
def get_ai_diagnosis(
    diagnostic_id: str,
    plan_id: int,
    store_id: int | None = None,
    channel: str = "",
    rule_code: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """读取当前诊断数据对应的 AI 结果；没有缓存时不触发模型调用。"""
    payload = detect_promotion_anomalies(db, user, store_id, channel)
    body = AIDiagnosticIn(diagnostic_id=diagnostic_id, plan_id=plan_id, store_id=store_id, channel=channel, rule_code=rule_code)
    item = _find_diagnostic(payload, body)
    if item is None:
        return {"cached": False}
    context = _build_ai_context(db, item)
    fingerprint = _ai_diagnostic_fingerprint(item, payload.get("diagnostics"), context)
    cached = db.execute(
        "SELECT result_json, updated_at FROM promo_ai_diagnoses WHERE user_id = ? AND diagnostic_id = ? AND data_fingerprint = ?",
        (int(user["id"]), item["id"], fingerprint),
    ).fetchone()
    if not cached:
        return {"cached": False}
    try:
        result = json.loads(cached["result_json"])
    except (TypeError, ValueError):
        return {"cached": False}
    if not isinstance(result, dict) or not isinstance(result.get("ai_diagnosis"), dict):
        return {"cached": False}
    return {**result, "cached": True, "generated_at": cached["updated_at"]}


@router.get("/diagnostics")
def promotion_diagnostics(
    store_id: int | None = None,
    channel: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    return detect_promotion_anomalies(db, user, store_id, channel)
