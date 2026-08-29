"""推广管理：经营复盘看板。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.auth import get_current_user
from backend.app.core.db import get_db

from ._common import _now, _scope_filter
from .channel import channel_for_scene, channel_name

router = APIRouter()


def _percent(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator) * 100, 1) if denominator else 0.0


def _record_metrics(record: dict | None) -> dict[str, float]:
    if not record:
        return {"roi_lift": 0.0, "sales_lift": 0.0, "saved_spend": 0.0}
    try:
        metrics = json.loads(record.get("metric_summary") or "{}")
    except (TypeError, json.JSONDecodeError):
        metrics = {}
    before_daily_spend = float(metrics.get("before_daily_spend") or 0)
    after_daily_spend = float(metrics.get("after_daily_spend") or 0)
    before_daily_sales = float(metrics.get("before_daily_sales") or 0)
    after_daily_sales = float(metrics.get("after_daily_sales") or 0)
    roi_lift = float(metrics.get("roi_change") or (float(record.get("after_roi") or 0) - float(record.get("before_roi") or 0)))
    return {
        "roi_lift": round(roi_lift, 2),
        "sales_lift": round(after_daily_sales - before_daily_sales, 2),
        "saved_spend": round(max(0.0, before_daily_spend - after_daily_spend), 2) if record.get("status") == "success" else 0.0,
    }


def _record_quality(record: dict | None) -> dict[str, bool]:
    if not record:
        return {"reliable": False, "interfered": False, "sparse": True, "manually_reviewed": False, "reproducible": False}
    confidence = str(record.get("confidence") or "").lower()
    interfered = bool(str(record.get("interference_notes") or "").strip())
    baseline_days = record.get("baseline_days")
    after_days = record.get("after_days")
    sparse = (
        record.get("status") == "insufficient"
        or (baseline_days is not None and int(baseline_days or 0) < 2)
        or (after_days is not None and int(after_days or 0) < 2)
    )
    conclusion = str(record.get("manual_conclusion") or "").strip()
    explicit_reusable = "可复制性：可复制" in conclusion or "可复制" in conclusion and "不可复制" not in conclusion
    explicit_not_reusable = "不可复制" in conclusion
    reliable = confidence in ("high", "medium") and not sparse
    reproducible = (
        record.get("status") in ("success", "partial")
        and reliable
        and not interfered
        and not explicit_not_reusable
        and (explicit_reusable or bool(conclusion))
    )
    return {
        "reliable": reliable,
        "interfered": interfered,
        "sparse": sparse,
        "manually_reviewed": bool(conclusion),
        "reproducible": reproducible,
    }


def _group_result(name: str, key: str, members: list[dict]) -> dict:
    verified = [member for member in members if member.get("result_status") in ("success", "partial", "failed", "insufficient")]
    conclusive = [member for member in verified if member.get("result_status") in ("success", "partial", "failed")]
    successful = sum(1 for member in conclusive if member.get("result_status") == "success")
    metrics = [_record_metrics(member.get("action_record")) for member in verified]
    qualities = [_record_quality(member.get("action_record")) for member in verified]
    reliable_count = sum(item["reliable"] for item in qualities)
    reproducible_count = sum(item["reproducible"] for item in qualities)
    return {
        "key": key,
        "name": name,
        "decision_count": len(members),
        "verified_count": len(verified),
        "success_rate": _percent(successful, len(conclusive)),
        "roi_lift": round(sum(item["roi_lift"] for item in metrics) / len(metrics), 2) if metrics else 0.0,
        "sales_lift": round(sum(item["sales_lift"] for item in metrics), 2),
        "saved_spend": round(sum(item["saved_spend"] for item in metrics), 2),
        "reliable_count": reliable_count,
        "reliable_rate": _percent(reliable_count, len(verified)),
        "reproducible_count": reproducible_count,
        "reproducible_rate": _percent(reproducible_count, len(verified)),
    }


@router.get("/review-dashboard")
def promotion_review_dashboard(
    window: str = "7d",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if window not in ("7d", "30d"):
        raise HTTPException(status_code=400, detail="复盘周期仅支持 7d 或 30d")
    days = 7 if window == "7d" else 30
    cutoff = (datetime.now().astimezone() - timedelta(days=days - 1)).isoformat(timespec="seconds")
    scope_frag, scope_params = _scope_filter(store_id, user)
    decision_rows = db.execute(
        "SELECT * FROM promo_decision_records WHERE created_at >= ? AND (action_record_id IS NULL OR action_record_id IN ("
        "SELECT id FROM promo_action_records WHERE COALESCE(lifecycle_status, 'active') = 'active'))"
        + scope_frag + " ORDER BY created_at DESC LIMIT 2000",
        [cutoff] + scope_params,
    ).fetchall()
    action_rows = db.execute(
        "SELECT * FROM promo_action_records WHERE COALESCE(lifecycle_status, 'active') = 'active' AND created_at >= ?" + scope_frag + " ORDER BY created_at DESC LIMIT 2000",
        [cutoff] + scope_params,
    ).fetchall()
    actions = {int(row["id"]): dict(row) for row in action_rows}
    decisions: list[dict] = []
    for row in decision_rows:
        item = dict(row)
        plan = db.execute("SELECT plan_name, scene, scene_name FROM promo_plans WHERE id = ?", (item["plan_id"],)).fetchone()
        item["plan_name"] = plan["plan_name"] if plan else f"计划 {item['plan_id']}"
        item["scene_name"] = plan["scene_name"] if plan and plan["scene_name"] else "未标注场景"
        item["channel"] = channel_for_scene(plan["scene"] if plan else "", item["scene_name"])
        item["channel_name"] = channel_name(item["channel"])
        item["action_record"] = actions.get(int(item["action_record_id"])) if item.get("action_record_id") else None
        decisions.append(item)

    decision_count = len(decisions)
    adopted = sum(1 for item in decisions if item.get("feedback_status") == "adopted")
    insufficient = sum(1 for item in decisions if item.get("feedback_status") == "insufficient")
    selected = sum(1 for item in decisions if item.get("feedback_status") in ("adopted", "modified"))
    planned = sum(1 for item in decisions if item.get("workflow_status") in ("planned", "executed", "verified"))
    executed = sum(1 for item in decisions if item.get("workflow_status") in ("executed", "verified"))
    verified = [item for item in decisions if item.get("workflow_status") == "verified"]
    conclusive = [item for item in verified if item.get("result_status") in ("success", "partial", "failed")]
    successful = sum(1 for item in conclusive if item.get("result_status") == "success")
    verified_metrics = [_record_metrics(item.get("action_record")) for item in verified]
    verified_quality = [_record_quality(item.get("action_record")) for item in verified]

    funnels = [
        {"key": "decision", "name": "生成决策", "count": decision_count, "rate": 100.0 if decision_count else 0.0},
        {"key": "selected", "name": "人工确认", "count": selected, "rate": _percent(selected, decision_count)},
        {"key": "planned", "name": "建立动作", "count": planned, "rate": _percent(planned, decision_count)},
        {"key": "executed", "name": "确认执行", "count": executed, "rate": _percent(executed, decision_count)},
        {"key": "verified", "name": "完成验证", "count": len(verified), "rate": _percent(len(verified), decision_count)},
    ]

    scenes = [
        _group_result(scene, scene, [item for item in decisions if item["scene_name"] == scene])
        for scene in sorted({item["scene_name"] for item in decisions})
    ]
    scenes.sort(key=lambda item: (-item["decision_count"], -item["success_rate"], item["name"]))

    channels = [
        _group_result(
            channel_name(channel),
            channel,
            [item for item in decisions if item["channel"] == channel],
        )
        for channel in sorted({item["channel"] for item in decisions})
    ]
    channels.sort(key=lambda item: (-item["decision_count"], -item["success_rate"], item["name"]))

    action_members: dict[str, list[dict]] = {}
    for item in decisions:
        action_record = item.get("action_record")
        action_name = action_record.get("action_type") if action_record else "未建立动作"
        action_members.setdefault(action_name or "未标注动作", []).append(item)
    action_groups = [_group_result(name, name, members) for name, members in action_members.items()]
    action_groups.sort(key=lambda item: (-item["decision_count"], -item["success_rate"], item["name"]))

    tier_labels = {"conservative": "稳健", "balanced": "平衡", "aggressive": "激进"}
    tiers = [
        _group_result(label, tier, [item for item in decisions if item.get("selected_tier") == tier])
        for tier, label in tier_labels.items()
    ]

    weekly_insights: list[dict[str, str]] = []
    if not decisions:
        weekly_insights.append({"title": "暂无决策样本", "summary": f"近 {days} 天没有决策档案。", "action": "先在 AI 决策中心生成方案并记录人工反馈。", "level": "info"})
    else:
        intervention = sum(1 for item in decisions if item.get("feedback_status") in ("modified", "rejected"))
        weekly_insights.append({"title": "人工干预", "summary": f"近 {days} 天人工修改或拒绝 {intervention} 次，占全部决策 {_percent(intervention, decision_count)}%。", "action": "优先查看决策归因中的高干预场景和业务限制。", "level": "warning" if _percent(intervention, decision_count) >= 50 else "info"})
        if executed:
            weekly_insights.append({"title": "验证完成度", "summary": f"已执行 {executed} 个动作，完成验证 {len(verified)} 个。", "action": "及时处理已到期的观察任务，避免经验样本长期缺失。", "level": "warning" if len(verified) < executed else "success"})
        if conclusive:
            weekly_insights.append({"title": "已验证效果", "summary": f"有效结论 {len(conclusive)} 个，验证成功率 {_percent(successful, len(conclusive))}%。", "action": "结合场景和档位表现调整下一轮策略权重。", "level": "success" if successful else "warning"})
        else:
            weekly_insights.append({"title": "结论样本不足", "summary": "当前没有可用于判断成败的完整验证样本。", "action": "继续同步计划日报并完成观察验证。", "level": "info"})
        interfered_count = sum(item["interfered"] for item in verified_quality)
        reproducible_count = sum(item["reproducible"] for item in verified_quality)
        if verified:
            weekly_insights.append({
                "title": "经验可复制性",
                "summary": f"{len(verified)} 个已验证动作中，{reproducible_count} 个满足中高可信、无干扰且已填写人工结论。",
                "action": "优先复用可复制样本；对受干扰或低可信样本继续观察，不直接放大策略权重。",
                "level": "success" if reproducible_count else "warning",
            })
            if interfered_count:
                weekly_insights.append({"title": "外部干扰", "summary": f"有 {interfered_count} 个验证结果记录了活动、价格、库存或流量干扰。", "action": "复盘时单独查看这些样本，避免把外部变化误判为调整效果。", "level": "warning"})

    return {
        "window": window,
        "summary": {
            "decision_count": decision_count,
            "insufficient_count": insufficient,
            "adoption_rate": _percent(adopted, decision_count),
            "execution_rate": _percent(executed, selected),
            "verification_rate": _percent(len(verified), executed),
            "success_rate": _percent(successful, len(conclusive)),
            "roi_lift": round(sum(item["roi_lift"] for item in verified_metrics) / len(verified_metrics), 2) if verified_metrics else 0.0,
            "sales_lift": round(sum(item["sales_lift"] for item in verified_metrics), 2),
            "saved_spend": round(sum(item["saved_spend"] for item in verified_metrics), 2),
        },
        "funnels": funnels,
        "channels": channels,
        "scenes": scenes,
        "actions": action_groups,
        "tiers": tiers,
        "weekly_insights": weekly_insights,
        "quality_summary": {
            "verified": len(verified),
            "reliable": sum(item["reliable"] for item in verified_quality),
            "reliable_rate": _percent(sum(item["reliable"] for item in verified_quality), len(verified)),
            "interfered": sum(item["interfered"] for item in verified_quality),
            "sparse": sum(item["sparse"] for item in verified_quality),
            "manually_reviewed": sum(item["manually_reviewed"] for item in verified_quality),
            "reproducible": sum(item["reproducible"] for item in verified_quality),
            "reproducible_rate": _percent(sum(item["reproducible"] for item in verified_quality), len(verified)),
        },
        "generated_at": _now(),
    }
