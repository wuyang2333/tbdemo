"""推广闭环作战台：聚合真实待办、风险和计划完整链路。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.auth import get_current_user
from backend.app.core.db import get_db

from ._common import _now, _scope_filter
from .channel import channel_matches, with_channel


router = APIRouter()


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


def _json_object(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _store_names(db, store_ids: set[int]) -> dict[int, str]:
    if not store_ids:
        return {}
    placeholders = ",".join("?" for _ in store_ids)
    rows = db.execute(f"SELECT id, name FROM stores WHERE id IN ({placeholders})", sorted(store_ids)).fetchall()
    return {int(row["id"]): row["name"] for row in rows}


def _queue_item(
    *,
    kind: str,
    source_id: int,
    priority: str,
    title: str,
    reason: str,
    plan: dict,
    store_name: str,
    source_path: str,
    due_at: str | None = None,
    updated_at: str = "",
) -> dict:
    return {
        "id": f"{kind}:{source_id}",
        "kind": kind,
        "source_id": source_id,
        "priority": priority,
        "title": title,
        "reason": reason,
        "plan_id": int(plan["id"]),
        "plan_name": plan.get("plan_name") or f"计划 {plan['id']}",
        "scene_name": plan.get("scene_name") or "未标注场景",
        "channel": with_channel(plan)["channel"],
        "channel_name": with_channel(plan)["channel_name"],
        "store_id": int(plan["store_id"]),
        "store_name": store_name,
        "source_path": source_path,
        "due_at": due_at,
        "updated_at": updated_at,
    }


def _load_cockpit_rows(db, user: dict, store_id: int | None) -> tuple[list[dict], list[dict], list[dict]]:
    scope_frag, scope_params = _scope_filter(store_id, user)
    plans = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM promo_plans WHERE COALESCE(platform_presence, 'active') != 'missing'" + scope_frag + " ORDER BY updated_at DESC LIMIT 2000",
            scope_params,
        ).fetchall()
    ]
    decisions = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM promo_decision_records WHERE 1=1" + scope_frag + " ORDER BY updated_at DESC LIMIT 2000",
            scope_params,
        ).fetchall()
    ]
    actions = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM promo_action_records WHERE COALESCE(lifecycle_status, 'active') = 'active'" + scope_frag + " ORDER BY id DESC LIMIT 2000",
            scope_params,
        ).fetchall()
    ]
    return plans, decisions, actions


@router.get("/cockpit")
def promotion_cockpit(
    store_id: int | None = None,
    channel: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """返回当前可见店铺的真实推广待办、风险和计划链路摘要。"""
    now = datetime.now().astimezone()
    plans, decisions, actions = _load_cockpit_rows(db, user, store_id)
    plans = [plan for plan in plans if channel_matches(channel, plan.get("scene"), plan.get("scene_name"))]
    plan_by_id = {int(plan["id"]): plan for plan in plans}
    visible_plan_ids = set(plan_by_id)
    decisions = [decision for decision in decisions if int(decision["plan_id"]) in visible_plan_ids]
    actions = [action for action in actions if int(action["plan_id"]) in visible_plan_ids]
    store_names = _store_names(db, {int(plan["store_id"]) for plan in plans})
    queue: list[dict] = []

    from .diagnostics import detect_promotion_anomalies

    diagnostic_payload = detect_promotion_anomalies(db, user, store_id, channel, now=now)
    for diagnostic in diagnostic_payload["items"]:
        if diagnostic["severity"] not in ("critical", "high"):
            continue
        queue.append({
            "id": f"diagnostic:{diagnostic['id']}",
            "kind": "diagnostic",
            "source_id": diagnostic["plan_id"],
            "priority": "urgent" if diagnostic["severity"] == "critical" else "high",
            "title": diagnostic["title"],
            "reason": diagnostic["summary"],
            "plan_id": diagnostic["plan_id"],
            "plan_name": diagnostic["plan_name"],
            "scene_name": diagnostic["scene_name"],
            "channel": diagnostic["channel"],
            "channel_name": diagnostic["channel_name"],
            "store_id": diagnostic["store_id"],
            "store_name": diagnostic["store_name"],
            "source_path": f"/promotions/diagnostics?diagnostic_id={diagnostic['id']}",
            "due_at": None,
            "updated_at": diagnostic["detected_at"],
        })

    for decision in decisions:
        plan = plan_by_id.get(int(decision["plan_id"]))
        if not plan or decision.get("feedback_status") in ("rejected", "insufficient"):
            continue
        if decision.get("workflow_status") == "selected" and not decision.get("action_record_id"):
            queue.append(_queue_item(
                kind="decision_action",
                source_id=int(decision["id"]),
                priority="high",
                title="把已确认方案建立为执行动作",
                reason="方案已经人工确认，但尚未建立动作记录，无法进入执行和验证。",
                plan=plan,
                store_name=store_names.get(int(plan["store_id"]), ""),
                source_path=f"/promotions/decisions?plan_id={plan['id']}&decision_record_id={decision['id']}",
                updated_at=decision.get("updated_at") or "",
            ))

    for action in actions:
        plan = plan_by_id.get(int(action["plan_id"]))
        if not plan:
            continue
        action_id = int(action["id"])
        if action.get("status") == "planned":
            queue.append(_queue_item(
                kind="pending_execution",
                source_id=action_id,
                priority="high",
                title=f"执行：{action.get('action_type') or '推广调整'}",
                reason="动作已经建立，但尚未确认已在平台执行。",
                plan=plan,
                store_name=store_names.get(int(plan["store_id"]), ""),
                source_path=f"/promotions/validation?action_id={action_id}&plan_id={plan['id']}&from=cockpit",
                due_at=action.get("observation_due_at"),
                updated_at=action.get("created_at") or action.get("executed_at") or "",
            ))
        if action.get("status") != "observing":
            continue
        due_at = _parse_datetime(action.get("observation_due_at"), now)
        if due_at is None:
            continue
        if due_at <= now:
            queue.append(_queue_item(
                kind="verification_overdue",
                source_id=action_id,
                priority="high",
                title=f"验证：{action.get('action_type') or '推广调整'}",
                reason="观察窗口已经结束，需要同步数据并完成效果验证。",
                plan=plan,
                store_name=store_names.get(int(plan["store_id"]), ""),
                source_path=f"/promotions/validation?action_id={action_id}&plan_id={plan['id']}",
                due_at=action.get("observation_due_at"),
                updated_at=action.get("executed_at") or "",
            ))
        elif due_at <= now + timedelta(hours=12):
            queue.append(_queue_item(
                kind="verification_due_soon",
                source_id=action_id,
                priority="medium",
                title=f"即将验证：{action.get('action_type') or '推广调整'}",
                reason="观察窗口将在 12 小时内结束，可提前确认数据同步和成功标准。",
                plan=plan,
                store_name=store_names.get(int(plan["store_id"]), ""),
                source_path=f"/promotions/validation?action_id={action_id}&plan_id={plan['id']}",
                due_at=action.get("observation_due_at"),
                updated_at=action.get("executed_at") or "",
            ))

    priority_order = {"urgent": 0, "high": 1, "medium": 2}
    queue.sort(key=lambda item: (priority_order.get(item["priority"], 9), item.get("due_at") or "9999", item["id"]))
    queue_by_plan: dict[int, list[dict]] = {}
    for item in queue:
        queue_by_plan.setdefault(int(item["plan_id"]), []).append(item)

    decisions_by_plan: dict[int, list[dict]] = {}
    actions_by_plan: dict[int, list[dict]] = {}
    for row, target in ((decisions, decisions_by_plan), (actions, actions_by_plan)):
        for item in row:
            target.setdefault(int(item["plan_id"]), []).append(item)

    active_plan_ids = set(decisions_by_plan) | set(actions_by_plan)
    cases: list[dict] = []
    for plan_id in active_plan_ids:
        plan = plan_by_id.get(plan_id)
        if not plan:
            continue
        plan_decisions = decisions_by_plan.get(plan_id, [])
        plan_actions = actions_by_plan.get(plan_id, [])
        open_items = queue_by_plan.get(plan_id, [])
        priorities = {item["priority"] for item in open_items}
        if "urgent" in priorities:
            risk_level = "urgent"
        elif "high" in priorities:
            risk_level = "high"
        elif "medium" in priorities:
            risk_level = "medium"
        else:
            risk_level = "normal"
        if any(action.get("status") == "failed" for action in plan_actions):
            chain_stage = "rollback"
        elif any(action.get("status") == "observing" for action in plan_actions):
            chain_stage = "validation"
        elif any(action.get("status") == "planned" for action in plan_actions):
            chain_stage = "execution"
        elif any(decision.get("workflow_status") == "selected" for decision in plan_decisions):
            chain_stage = "decision"
        else:
            chain_stage = "completed"
        timestamps = [
            value
            for item in [*plan_decisions, *plan_actions]
            for value in (item.get("updated_at"), item.get("verified_at"), item.get("created_at"), item.get("executed_at"))
            if value
        ]
        updated_at = plan.get("updated_at") or ""
        updated_dt = _parse_datetime(updated_at, now)
        data_status = "missing" if updated_dt is None else "stale" if updated_dt < now - timedelta(hours=24) else "fresh"
        cases.append(with_channel({
            "plan_id": plan_id,
            "plan_name": plan.get("plan_name") or f"计划 {plan_id}",
            "store_id": int(plan["store_id"]),
            "store_name": store_names.get(int(plan["store_id"]), ""),
            "scene_name": plan.get("scene_name") or "未标注场景",
            "status": plan.get("status") or "",
            "spend": round(float(plan.get("spend") or 0), 2),
            "sales": round(float(plan.get("sales") or 0), 2),
            "roi": round(float(plan.get("roi") or 0), 2),
            "risk_level": risk_level,
            "chain_stage": chain_stage,
            "open_work_count": len(open_items),
            "decision_count": len(plan_decisions),
            "action_count": len(plan_actions),
            "verified_count": sum(1 for action in plan_actions if action.get("status") in ("success", "partial", "failed", "insufficient")),
            "data_status": data_status,
            "data_updated_at": updated_at,
            "latest_activity_at": max(timestamps, default=updated_at),
            "scene": plan.get("scene") or "",
        }))
    cases.sort(key=lambda item: (priority_order.get(item["risk_level"], 9), -item["open_work_count"], item["latest_activity_at"]), reverse=False)

    plan_datetimes = [_parse_datetime(plan.get("updated_at"), now) for plan in plans]
    stale_plan_count = sum(1 for value in plan_datetimes if value is None or value < now - timedelta(hours=24))
    low_confidence_count = sum(
        1
        for action in actions
        if action.get("confidence") == "low" and action.get("status") in ("success", "partial", "failed", "insufficient")
    )
    summary = {
        "total": len(queue),
        "urgent": sum(1 for item in queue if item["priority"] == "urgent"),
        "high": sum(1 for item in queue if item["priority"] == "high"),
        "medium": sum(1 for item in queue if item["priority"] == "medium"),
        "pending_execution": sum(1 for item in queue if item["kind"] == "pending_execution"),
        "pending_verification": sum(1 for item in queue if item["kind"] in ("verification_overdue", "verification_due_soon", "pending_verification")),
        "needs_rollback": sum(1 for action in actions if action.get("status") == "failed"),
        "diagnostic_count": sum(1 for item in queue if item["kind"] == "diagnostic"),
    }
    return {
        "summary": summary,
        "queue": queue[:500],
        "cases": cases[:200],
        "data_health": {
            "visible_plan_count": len(plans),
            "active_case_count": len(cases),
            "stale_plan_count": stale_plan_count,
            "missing_due_count": sum(1 for action in actions if action.get("status") == "observing" and not action.get("observation_due_at")),
            "low_confidence_count": low_confidence_count,
            "last_plan_update": max((plan.get("updated_at") or "" for plan in plans), default=""),
        },
        "generated_at": _now(),
    }


@router.get("/cockpit/plans/{plan_id}")
def promotion_cockpit_plan_detail(
    plan_id: int,
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """返回单个计划从决策、执行到验证的完整真实链路。"""
    scope_frag, scope_params = _scope_filter(store_id, user)
    plan_row = db.execute(
        "SELECT * FROM promo_plans WHERE id = ?" + scope_frag,
        [plan_id, *scope_params],
    ).fetchone()
    if not plan_row:
        raise HTTPException(status_code=404, detail="推广计划不存在或无权访问")
    plan = with_channel(dict(plan_row))
    store = db.execute("SELECT name FROM stores WHERE id = ?", (plan["store_id"],)).fetchone()
    plan["store_name"] = store["name"] if store else ""

    decisions = [dict(row) for row in db.execute(
        "SELECT * FROM promo_decision_records WHERE plan_id = ? AND store_id = ? ORDER BY updated_at DESC LIMIT 100",
        (plan_id, plan["store_id"]),
    ).fetchall()]
    for decision in decisions:
        decision["ai_success_criteria"] = _json_object(decision.get("ai_success_criteria"))
        decision["final_success_criteria"] = _json_object(decision.get("final_success_criteria"))

    actions = [dict(row) for row in db.execute(
        "SELECT * FROM promo_action_records WHERE plan_id = ? AND store_id = ? AND COALESCE(lifecycle_status, 'active') = 'active' ORDER BY id DESC LIMIT 100",
        (plan_id, plan["store_id"]),
    ).fetchall()]
    for action in actions:
        action["success_criteria"] = _json_object(action.get("success_criteria"))
        action["metric_summary"] = _json_object(action.get("metric_summary"))

    timeline: list[dict] = []
    for decision in decisions:
        timeline.append({
            "id": f"decision:{decision['id']}",
            "kind": "decision",
            "title": (
                "拒绝 AI 决策"
                if decision.get("feedback_status") == "rejected"
                else "AI 决策暂缓"
                if decision.get("feedback_status") == "insufficient"
                else "人工确认 AI 决策"
            ),
            "summary": decision.get("feedback_reason") or decision.get("feedback_note") or f"选择 {decision.get('selected_tier') or '未标注'} 档方案",
            "status": decision.get("workflow_status") or "selected",
            "occurred_at": decision.get("updated_at") or decision.get("created_at") or "",
            "source_id": int(decision["id"]),
        })
    for action in actions:
        timeline.append({
            "id": f"action-created:{action['id']}",
            "kind": "action",
            "title": f"建立动作：{action.get('action_type') or '推广调整'}",
            "summary": action.get("description") or action.get("expected") or "已记录执行动作",
            "status": "planned",
            "occurred_at": action.get("created_at") or action.get("executed_at") or "",
            "source_id": int(action["id"]),
        })
        if action.get("status") != "planned":
            timeline.append({
                "id": f"action-executed:{action['id']}",
                "kind": "execution",
                "title": "确认动作已执行",
                "summary": action.get("data_quality") or "进入观察窗口",
                "status": "observing",
                "occurred_at": action.get("executed_at") or "",
                "source_id": int(action["id"]),
            })
        if action.get("verified_at"):
            timeline.append({
                "id": f"action-verified:{action['id']}",
                "kind": "verification",
                "title": f"验证结论：{action.get('status') or '已验证'}",
                "summary": action.get("result") or "已完成效果验证",
                "status": action.get("status") or "verified",
                "occurred_at": action.get("verified_at") or "",
                "source_id": int(action["id"]),
            })
    timeline.sort(key=lambda item: item.get("occurred_at") or "", reverse=True)
    return {
        "plan": plan,
        "decisions": decisions,
        "actions": actions,
        "timeline": timeline,
        "generated_at": _now(),
    }
