"""推广计划档案：聚合指标、趋势、归因、诊断与调整验证时间线。"""

from __future__ import annotations

import json
from datetime import date as date_cls
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.auth import get_current_user
from backend.app.core.db import get_db

from ._common import _now, _scope_filter
from .channel import with_channel


router = APIRouter()


def _json_object(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _change(current: float, baseline: float) -> float | None:
    if not baseline:
        return None
    return round((current - baseline) / baseline * 100, 2)


def _metric(row: dict | None, key: str) -> float:
    return round(float((row or {}).get(key) or 0), 2)


@router.get("/plans/{plan_id}/workspace")
def promotion_plan_workspace(
    plan_id: int,
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """返回单个推广计划的完整运营档案，不触发平台抓取或写操作。"""
    scope_frag, scope_params = _scope_filter(store_id, user)
    row = db.execute(
        "SELECT * FROM promo_plans WHERE id = ?" + scope_frag,
        [plan_id, *scope_params],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="推广计划不存在或无权访问")

    plan = with_channel(dict(row))
    store = db.execute("SELECT name FROM stores WHERE id = ?", (plan["store_id"],)).fetchone()
    plan["store_name"] = store["name"] if store else ""

    stat_rows = [
        dict(item)
        for item in db.execute(
            "SELECT * FROM promo_plan_stats WHERE store_id = ? AND campaign_id = ?",
            (plan["store_id"], plan["campaign_id"]),
        ).fetchall()
    ]
    stats = {item["mode"]: item for item in stat_rows}
    current = stats.get("realtime") or dict(plan)
    yesterday = stats.get("yesterday") or {}
    seven_days = stats.get("7d") or {}

    today = date_cls.today()
    start = today - timedelta(days=29)
    daily_rows = [
        dict(item)
        for item in db.execute(
            "SELECT data_date, spend, sales, roi, clicks, updated_at FROM promo_plan_daily "
            "WHERE store_id = ? AND campaign_id = ? AND data_date >= ? AND data_date <= ? ORDER BY data_date",
            (plan["store_id"], plan["campaign_id"], start.isoformat(), today.isoformat()),
        ).fetchall()
    ]
    daily_by_date = {item["data_date"]: item for item in daily_rows}
    trend = []
    for offset in range(30):
        day = (start + timedelta(days=offset)).isoformat()
        item = daily_by_date.get(day) or {}
        trend.append({
            "date": day,
            "spend": _metric(item, "spend"),
            "sales": _metric(item, "sales"),
            "roi": _metric(item, "roi"),
            "clicks": int(item.get("clicks") or 0),
            "has_data": bool(item),
        })

    item_row = db.execute(
        "SELECT item_id, item_title, image, updated_at FROM promo_plan_items WHERE store_id = ? AND campaign_id = ?",
        (plan["store_id"], plan["campaign_id"]),
    ).fetchone()
    attribution = [
        {
            "dimension": "item",
            "label": "商品",
            "status": "ready" if item_row else "empty",
            "items": [dict(item_row)] if item_row else [],
            "message": "已关联推广商品" if item_row else "暂未同步到关联商品",
        },
        {"dimension": "keyword", "label": "关键词", "status": "pending", "items": [], "message": "等待平台关键词明细接入"},
        {"dimension": "audience", "label": "人群", "status": "pending", "items": [], "message": "等待平台人群明细接入"},
        {"dimension": "creative", "label": "素材", "status": "pending", "items": [], "message": "等待平台素材明细接入"},
    ]

    decisions = [
        dict(item)
        for item in db.execute(
            "SELECT * FROM promo_decision_records WHERE plan_id = ? AND store_id = ? ORDER BY updated_at DESC LIMIT 100",
            (plan_id, plan["store_id"]),
        ).fetchall()
    ]
    actions = [
        dict(item)
        for item in db.execute(
            "SELECT * FROM promo_action_records WHERE plan_id = ? AND store_id = ? AND COALESCE(lifecycle_status, 'active') = 'active' ORDER BY id DESC LIMIT 100",
            (plan_id, plan["store_id"]),
        ).fetchall()
    ]
    timeline: list[dict] = []
    for decision in decisions:
        timeline.append({
            "id": f"decision:{decision['id']}",
            "kind": "decision",
            "title": (
                "AI 决策已拒绝"
                if decision.get("feedback_status") == "rejected"
                else "AI 决策暂缓"
                if decision.get("feedback_status") == "insufficient"
                else "AI 决策已确认"
            ),
            "summary": decision.get("feedback_reason") or decision.get("feedback_note") or "已记录人工选择",
            "status": decision.get("workflow_status") or "selected",
            "occurred_at": decision.get("updated_at") or decision.get("created_at") or "",
        })
    for action in actions:
        metrics = _json_object(action.get("metric_summary"))
        platform_labels = {
            "not_submitted": "尚未提交平台",
            "submitted": "已提交平台，等待回查",
            "effective": "平台已生效",
            "manual_confirmed": "已人工确认生效",
            "failed": "平台回查失败",
        }
        timeline.append({
            "id": f"action:{action['id']}",
            "kind": "verification" if action.get("verified_at") else "execution",
            "title": action.get("action_type") or "推广调整",
            "summary": action.get("result") or action.get("description") or action.get("expected") or "已记录调整动作",
            "status": action.get("status") or "observing",
            "occurred_at": action.get("verified_at") or action.get("executed_at") or action.get("created_at") or "",
            "before_value": action.get("before_value"),
            "after_value": action.get("after_value"),
            "confidence": action.get("confidence") or "",
            "metrics": metrics,
            "rollback_condition": action.get("rollback_condition") or "",
            "platform_status": action.get("platform_status") or "not_submitted",
            "platform_status_label": platform_labels.get(action.get("platform_status") or "not_submitted", "平台状态待确认"),
            "platform_checked_at": action.get("platform_checked_at") or "",
            "platform_check_note": action.get("platform_check_note") or "",
        })
    timeline.sort(key=lambda item: item.get("occurred_at") or "", reverse=True)

    now = datetime.now().astimezone()
    try:
        updated = datetime.fromisoformat(str(plan.get("updated_at") or "").replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=now.tzinfo)
        age_hours = max(0.0, (now - updated.astimezone(now.tzinfo)).total_seconds() / 3600)
    except (TypeError, ValueError):
        age_hours = None
    data_status = "missing" if age_hours is None else "stale" if age_hours > 24 else "fresh"
    observing = [item for item in actions if (item.get("status") or "") in {"planned", "observing"}]
    latest_decision = next((item for item in decisions if item.get("feedback_status") != "rejected"), decisions[0] if decisions else None)
    latest_action = actions[0] if actions else None
    platform_missing = plan.get("platform_presence") == "missing" or plan.get("status") == "平台已失效"
    if platform_missing:
        decision_summary = {
            "title": "平台已无此计划",
            "reason": "最近一次完整同步中，万相台当前计划列表已不再返回该计划。",
            "recommended_action": "仅查看历史数据与操作记录；如需继续投放，请在万相台确认是否已删除或重建。",
            "avoid_action": "不要再对这条历史计划生成决策或执行预算、出价和启停操作。",
            "review_at": "无需继续观察",
            "rollback_condition": "该计划当前不可执行",
            "source": "平台计划对账",
        }
    elif data_status != "fresh":
        decision_summary = {
            "title": "先补数据，暂不调整",
            "reason": "计划业务数据已经过期或缺少可靠更新时间，继续执行会放大误判风险。",
            "recommended_action": "返回计划执行中心同步最新数据，再重新生成判断。",
            "avoid_action": "不要依据旧数据连续修改预算、出价或计划状态。",
            "review_at": "数据同步成功后立即复查",
            "rollback_condition": "当前不执行，无需回退",
            "source": "数据可信度规则",
        }
    elif observing:
        focus = observing[0]
        due_at = focus.get("observation_due_at") or ""
        decision_summary = {
            "title": "继续观察，不要重复调整",
            "reason": f"当前有 {len(observing)} 个动作仍在观察窗口，继续改动会破坏单一变量验证。",
            "recommended_action": "保持当前设置，按观察节点检查花费、成交和 ROI。",
            "avoid_action": "不要在观察结束前再次调整同一计划。",
            "review_at": due_at or f"执行后 {int(focus.get('observation_hours') or 48)} 小时复查",
            "rollback_condition": focus.get("rollback_condition") or "若核心 ROI 明显恶化，再进入回退评估",
            "source": "最近调整动作",
        }
    elif latest_decision and latest_decision.get("feedback_status") == "insufficient":
        decision_summary = {
            "title": "证据不足，暂不调整",
            "reason": latest_decision.get("feedback_note") or "上次 AI 决策缺少足够样本或关键数据，已记录为暂缓。",
            "recommended_action": "补齐实时花费、点击、成交和同类验证样本后，重新生成 AI 决策。",
            "avoid_action": "不要把暂缓记录当成拒绝，也不要在证据未补齐前直接修改预算或出价。",
            "review_at": "数据补齐后立即复查",
            "rollback_condition": "当前未执行，无需回退",
            "source": "最近 AI 决策",
        }
    elif latest_decision:
        decision_summary = {
            "title": "按已确认决策进入执行",
            "reason": latest_decision.get("feedback_reason") or latest_decision.get("feedback_note") or "已有 AI 决策经过人工确认。",
            "recommended_action": "进入计划执行中心核对调整幅度并保留观察任务。",
            "avoid_action": "不要跳过预览、回退条件和执行后回查。",
            "review_at": f"执行后 {int(latest_decision.get('final_observation_hours') or 48)} 小时验证",
            "rollback_condition": latest_decision.get("rollback_condition") or "执行前补充明确回退条件",
            "source": "最近 AI 决策",
        }
    elif _metric(current, "spend") < 20:
        decision_summary = {
            "title": "样本不足，先积累数据",
            "reason": "当前消耗样本较少，不足以支持扩大调整幅度。",
            "recommended_action": "继续观察流量与成交，达到有效样本后再判断。",
            "avoid_action": "不要因为短时零成交立即大幅降价或停投。",
            "review_at": "累计消耗达到 20 元后复查",
            "rollback_condition": "当前不执行，无需回退",
            "source": "样本门槛规则",
        }
    elif _metric(current, "roi") < 1:
        decision_summary = {
            "title": "先诊断，再评估止损",
            "reason": "当前 ROI 低于 1，成本效率已经进入高风险区间。",
            "recommended_action": "先排查流量、素材和承接问题，再决定降低出价或暂停。",
            "avoid_action": "不要在原因未明确前直接放量。",
            "review_at": "完成异常诊断后立即复查",
            "rollback_condition": latest_action.get("rollback_condition") if latest_action else "若调整后 ROI 继续恶化，恢复调整前值",
            "source": "实时计划指标",
        }
    else:
        decision_summary = {
            "title": "当前无需立即调整",
            "reason": "数据状态正常，当前 ROI 未进入止损区间，也没有未完成动作。",
            "recommended_action": "保持投放并关注新的异常或放量信号。",
            "avoid_action": "不要为了操作而操作，避免无依据的频繁调整。",
            "review_at": "下一次数据同步后复查",
            "rollback_condition": "当前无调整，无需回退",
            "source": "当前计划指标",
        }

    return {
        "plan": plan,
        "metrics": {
            "current": {"spend": _metric(current, "spend"), "sales": _metric(current, "sales"), "roi": _metric(current, "roi"), "clicks": int(current.get("clicks") or 0)},
            "yesterday": {"spend": _metric(yesterday, "spend"), "sales": _metric(yesterday, "sales"), "roi": _metric(yesterday, "roi"), "clicks": int(yesterday.get("clicks") or 0)},
            "seven_days": {"spend": _metric(seven_days, "spend"), "sales": _metric(seven_days, "sales"), "roi": _metric(seven_days, "roi"), "clicks": int(seven_days.get("clicks") or 0)},
            "change_vs_yesterday": {
                "spend": _change(_metric(current, "spend"), _metric(yesterday, "spend")),
                "sales": _change(_metric(current, "sales"), _metric(yesterday, "sales")),
                "roi": _change(_metric(current, "roi"), _metric(yesterday, "roi")),
            },
        },
        "trend": trend,
        "attribution": attribution,
        "timeline": timeline,
        "observing": [
            {
                "id": int(item["id"]),
                "action_type": item.get("action_type") or "推广调整",
                "status": item.get("status") or "observing",
                "executed_at": item.get("executed_at") or "",
                "observation_hours": int(item.get("observation_hours") or 48),
                "rollback_condition": item.get("rollback_condition") or "",
                "platform_status": item.get("platform_status") or "not_submitted",
                "platform_submitted_at": item.get("platform_submitted_at") or "",
                "platform_checked_at": item.get("platform_checked_at") or "",
                "platform_check_note": item.get("platform_check_note") or "",
            }
            for item in observing
        ],
        "decision_summary": decision_summary,
        "execution_check": {
            "action_id": int(latest_action["id"]) if latest_action else None,
            "action_type": latest_action.get("action_type") if latest_action else "",
            "action_status": latest_action.get("status") if latest_action else "",
            "platform_status": latest_action.get("platform_status") if latest_action else "not_submitted",
            "platform_submitted_at": latest_action.get("platform_submitted_at") if latest_action else "",
            "platform_checked_at": latest_action.get("platform_checked_at") if latest_action else "",
            "platform_check_note": latest_action.get("platform_check_note") if latest_action else "",
            "can_check": bool(latest_action and latest_action.get("status") != "planned"),
        },
        "data_quality": {
            "status": data_status,
            "source": "万相台推广报表",
            "updated_at": plan.get("updated_at") or "",
            "age_hours": round(age_hours, 1) if age_hours is not None else None,
            "trend_days_with_data": sum(1 for item in trend if item["has_data"]),
            "trend_days_total": len(trend),
        },
        "generated_at": _now(),
    }
