"""推广管理：经营复盘看板。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.auth import get_current_user
from backend.app.core.db import get_db

from ._common import _now, _scope_filter

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


def _group_result(name: str, key: str, members: list[dict]) -> dict:
    verified = [member for member in members if member.get("result_status") in ("success", "partial", "failed", "insufficient")]
    conclusive = [member for member in verified if member.get("result_status") in ("success", "partial", "failed")]
    successful = sum(1 for member in conclusive if member.get("result_status") == "success")
    metrics = [_record_metrics(member.get("action_record")) for member in verified]
    return {
        "key": key,
        "name": name,
        "decision_count": len(members),
        "verified_count": len(verified),
        "success_rate": _percent(successful, len(conclusive)),
        "roi_lift": round(sum(item["roi_lift"] for item in metrics) / len(metrics), 2) if metrics else 0.0,
        "sales_lift": round(sum(item["sales_lift"] for item in metrics), 2),
        "saved_spend": round(sum(item["saved_spend"] for item in metrics), 2),
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
        "SELECT * FROM promo_decision_records WHERE created_at >= ?" + scope_frag + " ORDER BY created_at DESC LIMIT 2000",
        [cutoff] + scope_params,
    ).fetchall()
    action_rows = db.execute(
        "SELECT * FROM promo_action_records WHERE created_at >= ?" + scope_frag + " ORDER BY created_at DESC LIMIT 2000",
        [cutoff] + scope_params,
    ).fetchall()
    actions = {int(row["id"]): dict(row) for row in action_rows}
    decisions: list[dict] = []
    for row in decision_rows:
        item = dict(row)
        plan = db.execute("SELECT plan_name, scene_name FROM promo_plans WHERE id = ?", (item["plan_id"],)).fetchone()
        item["plan_name"] = plan["plan_name"] if plan else f"计划 {item['plan_id']}"
        item["scene_name"] = plan["scene_name"] if plan and plan["scene_name"] else "未标注场景"
        item["action_record"] = actions.get(int(item["action_record_id"])) if item.get("action_record_id") else None
        decisions.append(item)

    decision_count = len(decisions)
    adopted = sum(1 for item in decisions if item.get("feedback_status") == "adopted")
    selected = sum(1 for item in decisions if item.get("feedback_status") in ("adopted", "modified"))
    planned = sum(1 for item in decisions if item.get("workflow_status") in ("planned", "executed", "verified"))
    executed = sum(1 for item in decisions if item.get("workflow_status") in ("executed", "verified"))
    verified = [item for item in decisions if item.get("workflow_status") == "verified"]
    conclusive = [item for item in verified if item.get("result_status") in ("success", "partial", "failed")]
    successful = sum(1 for item in conclusive if item.get("result_status") == "success")
    verified_metrics = [_record_metrics(item.get("action_record")) for item in verified]

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

    return {
        "window": window,
        "summary": {
            "decision_count": decision_count,
            "adoption_rate": _percent(adopted, decision_count),
            "execution_rate": _percent(executed, selected),
            "verification_rate": _percent(len(verified), executed),
            "success_rate": _percent(successful, len(conclusive)),
            "roi_lift": round(sum(item["roi_lift"] for item in verified_metrics) / len(verified_metrics), 2) if verified_metrics else 0.0,
            "sales_lift": round(sum(item["sales_lift"] for item in verified_metrics), 2),
            "saved_spend": round(sum(item["saved_spend"] for item in verified_metrics), 2),
        },
        "funnels": funnels,
        "scenes": scenes,
        "actions": action_groups,
        "tiers": tiers,
        "weekly_insights": weekly_insights,
        "generated_at": _now(),
    }
