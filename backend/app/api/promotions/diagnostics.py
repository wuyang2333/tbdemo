"""推广异常诊断中心：基于真实计划指标输出规则、证据和处理建议。"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

from backend.app.api.auth import get_current_user
from backend.app.core.db import get_db

from ._common import _now, _scope_filter


router = APIRouter()


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2}


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


def _recommendations(plan_id: int, rule_code: str) -> list[dict]:
    return [
        {
            "key": "inspect_plan",
            "label": "查看计划明细",
            "reason": "先确认计划状态、预算、出价和最近操作，排除配置或同步问题。",
            "path": f"/promotions/plans?plan_id={plan_id}&diagnostic={rule_code}",
        },
        {
            "key": "ai_decision",
            "label": "生成 AI 决策",
            "reason": "结合当前异常证据生成稳健、平衡、激进三档处理方案，再由人工确认。",
            "path": f"/promotions/decisions?plan_id={plan_id}&diagnostic={rule_code}",
        },
        {
            "key": "cockpit",
            "label": "进入闭环作战台",
            "reason": "查看该计划已有的决策、动作和验证记录，避免重复或冲突调整。",
            "path": f"/promotions/cockpit?plan_id={plan_id}&diagnostic={rule_code}",
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
    spend_at_risk: float = 0.0,
    sales_gap: float = 0.0,
    detected_at: str,
) -> dict:
    plan_id = int(plan["id"])
    return {
        "id": f"{rule_code}:{plan_id}",
        "rule_code": rule_code,
        "category": category,
        "severity": severity,
        "title": title,
        "summary": summary,
        "confidence": confidence,
        "confidence_reason": confidence_reason,
        "plan_id": plan_id,
        "plan_name": plan.get("plan_name") or f"计划 {plan_id}",
        "store_id": int(plan["store_id"]),
        "store_name": store_name,
        "scene_name": plan.get("scene_name") or "未标注场景",
        "plan_status": plan.get("status") or "",
        "spend_at_risk": round(max(0.0, spend_at_risk), 2),
        "sales_gap": round(max(0.0, sales_gap), 2),
        "evidence": evidence,
        "possible_causes": possible_causes,
        "recommendations": _recommendations(plan_id, rule_code),
        "unknown_dimensions": ["商品库存与价格", "活动节奏", "素材与人群明细", "竞争环境变化"],
        "detected_at": detected_at,
    }


def detect_promotion_anomalies(
    db,
    user: dict,
    store_id: int | None = None,
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
    stats = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM promo_plan_stats WHERE 1=1" + scope_frag + " ORDER BY updated_at DESC",
            scope_params,
        ).fetchall()
    ]
    stat_by_key = {(int(row["store_id"]), str(row["campaign_id"]), row["mode"]): row for row in stats}
    store_ids = sorted({int(plan["store_id"]) for plan in plans})
    store_names: dict[int, str] = {}
    if store_ids:
        placeholders = ",".join("?" for _ in store_ids)
        store_names = {
            int(row["id"]): row["name"]
            for row in db.execute(f"SELECT id, name FROM stores WHERE id IN ({placeholders})", store_ids).fetchall()
        }

    config = (get_alert_config(db) or {}).get("plan") or {}
    budget_over = float(config.get("budget_over") or 1.0)
    budget_warn = float(config.get("budget_warn") or 0.8)
    roi_drop_ratio = float(config.get("roi_drop_ratio") or 0.6)
    roi_low = float(config.get("roi_low") or 1.0)
    diagnostics: list[dict] = []
    realtime_coverage = 0

    for plan in plans:
        if plan.get("status") != "在投":
            continue
        key = (int(plan["store_id"]), str(plan["campaign_id"]))
        realtime = stat_by_key.get((*key, "realtime"))
        yesterday = stat_by_key.get((*key, "yesterday"))
        if realtime:
            realtime_coverage += 1
        rt_spend = float((realtime or {}).get("spend") or 0)
        rt_sales = float((realtime or {}).get("sales") or 0)
        rt_roi = float((realtime or {}).get("roi") or 0)
        rt_clicks = int((realtime or {}).get("clicks") or 0)
        ye_spend = float((yesterday or {}).get("spend") or 0)
        ye_sales = float((yesterday or {}).get("sales") or 0)
        ye_roi = float((yesterday or {}).get("roi") or 0)
        budget = float(plan.get("day_budget") or 0)
        store_name = store_names.get(int(plan["store_id"]), "")
        confidence, confidence_reason = _confidence(rt_spend, rt_clicks)
        latest_update = max(
            (realtime or {}).get("updated_at") or "",
            (yesterday or {}).get("updated_at") or "",
            plan.get("updated_at") or "",
        )
        latest_dt = _parse_datetime(latest_update, current_time)

        if latest_dt is None or latest_dt < current_time - timedelta(hours=24):
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
            continue

        if budget > 0 and rt_spend > 0:
            budget_ratio = rt_spend / budget
            if budget_ratio >= budget_over:
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
            elif budget_ratio >= budget_warn:
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

        if rt_spend >= 50 and rt_sales <= 0:
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
        elif rt_spend >= 20 and ye_roi > 0 and 0 < rt_roi < ye_roi * roi_drop_ratio:
            drop_pct = (1 - rt_roi / ye_roi) * 100
            diagnostics.append(_diagnostic(
                plan=plan,
                store_name=store_name,
                rule_code="roi_drop",
                category="efficiency",
                severity="high" if drop_pct >= 50 and rt_spend >= 100 else "medium",
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

        if rt_spend >= 50 and 0 < rt_roi < roi_low:
            diagnostics.append(_diagnostic(
                plan=plan,
                store_name=store_name,
                rule_code="roi_low",
                category="efficiency",
                severity="high" if rt_spend >= 200 else "medium",
                title="当前 ROI 低于健康阈值",
                summary=f"今日 ROI {rt_roi:.2f} 低于配置阈值 {roi_low:.2f}，需要结合毛利和计划目标判断是否止损。",
                confidence=confidence,
                confidence_reason=confidence_reason,
                evidence=[_evidence("今日 ROI", round(rt_roi, 2)), _evidence("健康阈值", round(roi_low, 2)), _evidence("今日花费", round(rt_spend, 2), unit="元"), _evidence("今日成交", round(rt_sales, 2), unit="元")],
                possible_causes=["出价或流量获取成本偏高（待核查）", "商品转化与客单不足（待核查）", "该计划的目标可能不是直接成交（待核查）"],
                spend_at_risk=rt_spend * max(0.0, 1 - rt_roi / roi_low),
                detected_at=detected_at,
            ))

        if current_time.hour >= 10 and ye_spend >= 50 and rt_spend <= 0:
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
        elif current_time.hour >= 16 and ye_spend >= 50 and 0 < rt_spend < ye_spend * 0.3:
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

    diagnostics.sort(key=lambda item: (SEVERITY_ORDER.get(item["severity"], 9), -item["spend_at_risk"], item["id"]))
    risk_by_plan: dict[int, float] = {}
    for item in diagnostics:
        risk_by_plan[item["plan_id"]] = max(risk_by_plan.get(item["plan_id"], 0.0), float(item["spend_at_risk"] or 0))
    categories: dict[str, int] = {}
    for item in diagnostics:
        categories[item["category"]] = categories.get(item["category"], 0) + 1
    active_plan_count = sum(1 for plan in plans if plan.get("status") == "在投")
    return {
        "summary": {
            "total": len(diagnostics),
            "critical": sum(1 for item in diagnostics if item["severity"] == "critical"),
            "high": sum(1 for item in diagnostics if item["severity"] == "high"),
            "medium": sum(1 for item in diagnostics if item["severity"] == "medium"),
            "affected_plan_count": len({item["plan_id"] for item in diagnostics}),
            "estimated_spend_at_risk": round(sum(risk_by_plan.values()), 2),
        },
        "items": diagnostics[:1000],
        "categories": [{"category": key, "count": value} for key, value in sorted(categories.items(), key=lambda pair: (-pair[1], pair[0]))],
        "data_health": {
            "visible_plan_count": len(plans),
            "active_plan_count": active_plan_count,
            "realtime_coverage_count": realtime_coverage,
            "realtime_coverage_rate": round(realtime_coverage / active_plan_count * 100, 1) if active_plan_count else 0.0,
        },
        "thresholds": {
            "budget_over": budget_over,
            "budget_warn": budget_warn,
            "roi_drop_ratio": roi_drop_ratio,
            "roi_low": roi_low,
            "minimum_spend_for_conversion": 50.0,
        },
        "generated_at": detected_at,
    }


@router.get("/diagnostics")
def promotion_diagnostics(
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    return detect_promotion_anomalies(db, user, store_id)
