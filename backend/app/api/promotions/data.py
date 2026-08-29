"""推广管理：数据、计划、同步、导出、关键词。"""

from __future__ import annotations

import json

from datetime import date as date_cls
from datetime import datetime, timedelta

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
    PlanBatchStatusIn,
    PlanBatchAdjustIn,
    PlanAdjustIn,
    PlanCreateIn,
    PlanChatIn,
    PlanChatBody,
    _ensure_plan_daily,
    _collect_plan_data,
    _build_plan_prompt,
    _enrich_promo_strategies,
)
from .channel import CHANNEL_NAMES, channel_for_scene, channel_matches, with_channel
from .health import build_dataset_metadata, record_sync_result

router = APIRouter()


def _plan_execution_guard(db, user: dict, plan) -> dict:
    """高风险平台写入守卫：关键实时指标缺失或计划同步过期时禁止执行。"""
    stat = db.execute(
        "SELECT updated_at FROM promo_plan_stats WHERE store_id = ? AND campaign_id = ? AND mode = 'realtime'",
        (plan["store_id"], plan["campaign_id"]),
    ).fetchone()
    metadata = build_dataset_metadata(db, "plans", user, int(plan["store_id"]))
    if not stat:
        return {"can_execute": False, "block_reason": "缺少该计划的实时指标，请先同步推广计划后再执行。", "data_metadata": metadata}
    if metadata["freshness"] != "fresh":
        return {"can_execute": False, "block_reason": "推广计划数据已过期，请先同步最新数据后再执行。", "data_metadata": metadata}
    if metadata["completeness"] != "complete":
        return {"can_execute": False, "block_reason": "推广计划关键数据不完整，请完成同步后再执行。", "data_metadata": metadata}
    return {"can_execute": True, "block_reason": "", "data_metadata": metadata}


def _require_plan_execution_guard(db, user: dict, plan) -> dict:
    guard = _plan_execution_guard(db, user, plan)
    if not guard["can_execute"]:
        raise HTTPException(status_code=409, detail=guard["block_reason"])
    return guard


class PromoActionRecordIn(BaseModel):
    plan_id: int
    action_type: str
    description: str = ""
    after_value: float | None = None
    expected: str = ""
    observation_hours: int = 48
    decision_id: str | None = None
    strategy_id: int | None = None
    success_criteria: dict[str, float] = Field(default_factory=dict)
    rollback_condition: str = ""
    decision_record_id: int | None = None
    decision_tier: str = ""
    decision_field: str = ""
    change_pct: float | None = None


class PromoActionPlatformStatusIn(BaseModel):
    status: str
    note: str = Field(default="", max_length=500)


class PromoDecisionFeedbackIn(BaseModel):
    decision_id: str
    plan_id: int
    strategy_id: int | None = None
    recommended_tier: str
    selected_tier: str
    feedback_status: str
    ai_field: str
    ai_change_pct: float
    final_field: str
    final_change_pct: float
    ai_success_criteria: dict[str, float] = Field(default_factory=dict)
    final_success_criteria: dict[str, float] = Field(default_factory=dict)
    ai_observation_hours: int = 48
    final_observation_hours: int = 48
    rollback_condition: str = ""
    feedback_reason: str = ""
    feedback_note: str = ""


class PromoActionReviewIn(BaseModel):
    success_criteria: dict[str, float] | None = None
    interference_notes: str | None = None
    manual_conclusion: str | None = None


class PromoActionLifecycleIn(BaseModel):
    action: str
    reason: str = Field(default="", max_length=500)


class PromoStrategyUpdateIn(BaseModel):
    name: str | None = None
    conditions: str | None = None
    status: str | None = None
    scene: str | None = None
    min_roi: float | None = None
    max_roi: float | None = None


class PromoStrategyCreateIn(BaseModel):
    store_id: int
    name: str = Field(min_length=1, max_length=100)
    action_type: str = Field(min_length=1, max_length=100)
    conditions: str = Field(min_length=1, max_length=1000)
    evidence: str = Field(min_length=1, max_length=1000)
    scene: str = Field(default="", max_length=100)
    min_roi: float | None = Field(default=None, ge=0)
    max_roi: float | None = Field(default=None, ge=0)


def _action_record_row(db, record_id: int, user: dict):
    scope_frag, scope_params = _scope_filter(None, user)
    row = db.execute("SELECT * FROM promo_action_records WHERE id = ?" + scope_frag, [record_id] + scope_params).fetchone()
    if not row:
        return None
    plan = db.execute("SELECT plan_name, campaign_id, scene_name FROM promo_plans WHERE id = ?", (row["plan_id"],)).fetchone()
    item = {**dict(row), **(dict(plan) if plan else {})}
    for key in ("success_criteria", "metric_summary"):
        try:
            item[key] = json.loads(item.get(key) or "{}")
        except (TypeError, json.JSONDecodeError):
            item[key] = {}
    return item


def _plan_window_metrics(db, store_id: int, campaign_id: str, start: str, end: str) -> dict:
    rows = db.execute(
        "SELECT data_date, spend, sales, clicks, updated_at FROM promo_plan_daily "
        "WHERE store_id = ? AND campaign_id = ? AND data_date >= ? AND data_date <= ? ORDER BY data_date ASC",
        (store_id, campaign_id, start, end),
    ).fetchall()
    spend = sum(float(row["spend"] or 0) for row in rows)
    sales = sum(float(row["sales"] or 0) for row in rows)
    return {
        "start": start,
        "end": end,
        "days": len(rows),
        "spend": round(spend, 2),
        "sales": round(sales, 2),
        "clicks": sum(int(row["clicks"] or 0) for row in rows),
        "roi": round(sales / spend, 2) if spend else 0.0,
        "updated_at": max((row["updated_at"] or "" for row in rows), default=""),
    }


def _parse_action_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _change_pct(after: float, before: float) -> float | None:
    if before == 0:
        return None
    return round((after - before) / before * 100, 2)


def _verification_confidence(baseline_days: int, after_days: int, after_spend: float, has_interference: bool) -> str:
    if baseline_days >= 3 and after_days >= 3 and after_spend >= 100:
        confidence = "high"
    elif baseline_days >= 2 and after_days >= 2 and after_spend >= 20:
        confidence = "medium"
    else:
        confidence = "low"
    if has_interference and confidence == "high":
        return "medium"
    if has_interference and confidence == "medium":
        return "low"
    return confidence


def _verification_stats(items: list[dict]) -> dict:
    completed_statuses = {"success", "partial", "failed", "insufficient"}
    conclusive_statuses = {"success", "partial", "failed"}
    completed = [item for item in items if item.get("status") in completed_statuses]
    conclusive = [item for item in completed if item.get("status") in conclusive_statuses]
    reliable = [item for item in conclusive if item.get("confidence") in ("high", "medium")]

    def metric_average(key: str) -> float | None:
        values = []
        for item in conclusive:
            value = (item.get("metric_summary") or {}).get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
        return round(sum(values) / len(values), 2) if values else None

    success = sum(1 for item in conclusive if item.get("status") == "success")
    return {
        "actions": len(items),
        "verified": len(completed),
        "conclusive": len(conclusive),
        "success": success,
        "partial": sum(1 for item in conclusive if item.get("status") == "partial"),
        "failed": sum(1 for item in conclusive if item.get("status") == "failed"),
        "insufficient": sum(1 for item in completed if item.get("status") == "insufficient"),
        "reliable": len(reliable),
        "success_rate": round(success / len(conclusive) * 100, 1) if conclusive else 0.0,
        "reliable_rate": round(len(reliable) / len(conclusive) * 100, 1) if conclusive else 0.0,
        "avg_roi_change": metric_average("roi_change"),
        "avg_sales_change_pct": metric_average("sales_change_pct"),
        "avg_spend_change_pct": metric_average("spend_change_pct"),
    }


def _verification_groups(items: list[dict], key: str, fallback: str) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for item in items:
        name = str(item.get(key) or fallback)
        grouped.setdefault(name, []).append(item)
    result = [{"name": name, **_verification_stats(group)} for name, group in grouped.items()]
    return sorted(result, key=lambda item: (item["conclusive"], item["verified"], item["actions"]), reverse=True)


def _verification_focuses(items: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for item in items:
        labels: set[str] = set()
        result = item.get("result") or ""
        status = item.get("status")
        if status == "insufficient":
            labels.add("数据不足")
        if status in ("failed", "partial"):
            if "ROI" in result and ("未达标" in result or "下降" in result or "不明显" in result):
                labels.add("ROI 未达标")
            if "成交" in result and "未达标" in result:
                labels.add("成交未达标")
            if "花费" in result and "未达标" in result:
                labels.add("花费未达标")
            if not labels:
                labels.add("效果部分有效或不明显")
        if (item.get("interference_notes") or "").strip():
            labels.add("存在外部干扰")
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
    return [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)]


@router.get("/action-records")
def list_action_records(
    status: str = "",
    lifecycle: str = "active",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    scope_frag, scope_params = _scope_filter(store_id, user)
    query = "SELECT * FROM promo_action_records WHERE 1=1" + scope_frag
    params = list(scope_params)
    if lifecycle not in ("active", "voided", "archived", "all"):
        raise HTTPException(status_code=422, detail="无效的记录范围")
    if lifecycle != "all":
        query += " AND COALESCE(lifecycle_status, 'active') = ?"
        params.append(lifecycle)
    if status:
        query += " AND status = ?"
        params.append(status)
    rows = db.execute(query + " ORDER BY id DESC LIMIT 200", params).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        for key in ("success_criteria", "metric_summary"):
            try:
                item[key] = json.loads(item.get(key) or "{}")
            except (TypeError, json.JSONDecodeError):
                item[key] = {}
        plan = db.execute("SELECT plan_name, campaign_id, scene_name FROM promo_plans WHERE id = ?", (row["plan_id"],)).fetchone()
        if plan:
            item.update(dict(plan))
        items.append(item)
    return {"items": items}


@router.get("/action-records/summary")
def action_record_summary(
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    scope_frag, scope_params = _scope_filter(store_id, user)
    rows = db.execute(
        "SELECT * FROM promo_action_records WHERE COALESCE(lifecycle_status, 'active') = 'active'" + scope_frag + " ORDER BY id DESC LIMIT 1000",
        scope_params,
    ).fetchall()
    items: list[dict] = []
    for row in rows:
        item = dict(row)
        try:
            item["metric_summary"] = json.loads(item.get("metric_summary") or "{}")
        except (TypeError, json.JSONDecodeError):
            item["metric_summary"] = {}
        plan = db.execute("SELECT plan_name, scene_name FROM promo_plans WHERE id = ?", (row["plan_id"],)).fetchone()
        item["plan_name"] = plan["plan_name"] if plan else f"计划 {row['plan_id']}"
        item["scene_name"] = plan["scene_name"] if plan else "未标注场景"
        items.append(item)

    status_labels = {
        "planned": "待执行",
        "observing": "观察中",
        "success": "验证成功",
        "partial": "部分有效",
        "failed": "验证失败",
        "insufficient": "数据不足",
    }
    confidence_labels = {"high": "高可信", "medium": "中可信", "low": "低可信"}
    outcomes = [
        {"key": key, "name": label, "count": sum(1 for item in items if item.get("status") == key)}
        for key, label in status_labels.items()
    ]
    confidence = [
        {"key": key, "name": label, "count": sum(1 for item in items if item.get("confidence") == key)}
        for key, label in confidence_labels.items()
    ]
    review_items = [
        {
            "id": item["id"],
            "plan_name": item["plan_name"],
            "scene_name": item["scene_name"],
            "action_type": item["action_type"],
            "status": item["status"],
            "confidence": item.get("confidence") or "",
            "result": item.get("result") or "",
            "interference_notes": item.get("interference_notes") or "",
            "manual_conclusion": item.get("manual_conclusion") or "",
            "verified_at": item.get("verified_at"),
        }
        for item in items
        if item.get("status") in ("failed", "partial", "insufficient")
    ][:8]
    return {
        "totals": _verification_stats(items),
        "outcomes": outcomes,
        "confidence": confidence,
        "action_types": _verification_groups(items, "action_type", "未标注动作")[:8],
        "scenes": _verification_groups(items, "scene_name", "未标注场景")[:8],
        "plans": _verification_groups(items, "plan_name", "未标注计划")[:10],
        "focuses": _verification_focuses(items),
        "review_items": review_items,
        "generated_at": _now(),
    }


@router.post("/decision-records")
def save_decision_feedback(
    body: PromoDecisionFeedbackIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    decision_id = body.decision_id.strip()
    if not decision_id:
        raise HTTPException(status_code=400, detail="决策批次 ID 不能为空")
    if body.feedback_status not in ("adopted", "modified", "rejected", "insufficient"):
        raise HTTPException(status_code=400, detail="决策反馈状态无效")
    if body.recommended_tier not in ("conservative", "balanced", "aggressive") or body.selected_tier not in ("conservative", "balanced", "aggressive"):
        raise HTTPException(status_code=400, detail="决策方案档位无效")
    if body.feedback_status == "adopted" and body.selected_tier != body.recommended_tier:
        raise HTTPException(status_code=400, detail="改选其他档位时应记录为修改方案")
    if body.feedback_status == "rejected" and not body.feedback_reason.strip():
        raise HTTPException(status_code=400, detail="拒绝方案时请选择原因")
    scope_frag, scope_params = _scope_filter(None, user)
    plan = db.execute("SELECT id, store_id, plan_name FROM promo_plans WHERE id = ?" + scope_frag, [body.plan_id] + scope_params).fetchone()
    if not plan:
        raise HTTPException(status_code=404, detail="推广计划不存在")
    if body.strategy_id:
        strategy = db.execute(
            "SELECT id FROM promo_strategies WHERE id = ? AND store_id = ? AND status = 'active'",
            (body.strategy_id, plan["store_id"]),
        ).fetchone()
        if not strategy:
            raise HTTPException(status_code=400, detail="关联策略不存在或已停用")
    now = _now()
    workflow_status = "rejected" if body.feedback_status == "rejected" else "deferred" if body.feedback_status == "insufficient" else "selected"
    db.execute(
        "INSERT INTO promo_decision_records "
        "(decision_id, user_id, username, store_id, plan_id, strategy_id, recommended_tier, selected_tier, feedback_status, workflow_status, ai_field, ai_change_pct, final_field, final_change_pct, ai_success_criteria, final_success_criteria, ai_observation_hours, final_observation_hours, rollback_condition, feedback_reason, feedback_note, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(decision_id, plan_id) DO UPDATE SET "
        "strategy_id=excluded.strategy_id, recommended_tier=excluded.recommended_tier, selected_tier=excluded.selected_tier, feedback_status=excluded.feedback_status, workflow_status=excluded.workflow_status, "
        "ai_field=excluded.ai_field, ai_change_pct=excluded.ai_change_pct, final_field=excluded.final_field, final_change_pct=excluded.final_change_pct, ai_success_criteria=excluded.ai_success_criteria, final_success_criteria=excluded.final_success_criteria, "
        "ai_observation_hours=excluded.ai_observation_hours, final_observation_hours=excluded.final_observation_hours, rollback_condition=excluded.rollback_condition, feedback_reason=excluded.feedback_reason, feedback_note=excluded.feedback_note, updated_at=excluded.updated_at",
        (
            decision_id, user["id"], user["username"], plan["store_id"], plan["id"], body.strategy_id,
            body.recommended_tier, body.selected_tier, body.feedback_status, workflow_status, body.ai_field, body.ai_change_pct,
            body.final_field, body.final_change_pct, json.dumps(body.ai_success_criteria, ensure_ascii=False), json.dumps(body.final_success_criteria, ensure_ascii=False),
            max(1, min(int(body.ai_observation_hours), 720)), max(1, min(int(body.final_observation_hours), 720)), body.rollback_condition.strip(),
            body.feedback_reason.strip(), body.feedback_note.strip(), now, now,
        ),
    )
    row = db.execute(
        "SELECT * FROM promo_decision_records WHERE decision_id = ? AND plan_id = ? AND store_id = ?",
        (decision_id, plan["id"], plan["store_id"]),
    ).fetchone()
    _log(db, user, "记录 AI 决策反馈", plan["plan_name"], f"decision_record_id={row['id']}；反馈={body.feedback_status}")
    return {"ok": True, "id": row["id"], "item": dict(row)}


@router.get("/decision-records")
def list_decision_records(
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    scope_frag, scope_params = _scope_filter(store_id, user)
    rows = db.execute("SELECT * FROM promo_decision_records WHERE 1=1" + scope_frag + " ORDER BY updated_at DESC LIMIT 500", scope_params).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        for key in ("ai_success_criteria", "final_success_criteria"):
            try:
                item[key] = json.loads(item.get(key) or "{}")
            except (TypeError, json.JSONDecodeError):
                item[key] = {}
        plan = db.execute("SELECT plan_name, scene_name FROM promo_plans WHERE id = ?", (row["plan_id"],)).fetchone()
        item["plan_name"] = plan["plan_name"] if plan else f"计划 {row['plan_id']}"
        item["scene_name"] = plan["scene_name"] if plan and plan["scene_name"] else "未标注场景"
        items.append(item)

    tier_labels = {"conservative": "稳健", "balanced": "平衡", "aggressive": "激进"}
    tiers = []
    for tier, label in tier_labels.items():
        tier_items = [item for item in items if item.get("selected_tier") == tier]
        verified = [item for item in tier_items if item.get("workflow_status") == "verified"]
        conclusive = [item for item in verified if item.get("result_status") in ("success", "partial", "failed")]
        success = sum(1 for item in conclusive if item.get("result_status") == "success")
        tiers.append({
            "tier": tier,
            "name": label,
            "selected": len(tier_items),
            "executed": sum(1 for item in tier_items if item.get("workflow_status") in ("executed", "verified")),
            "verified": len(verified),
            "success": success,
            "partial": sum(1 for item in conclusive if item.get("result_status") == "partial"),
            "failed": sum(1 for item in conclusive if item.get("result_status") == "failed"),
            "insufficient": sum(1 for item in verified if item.get("result_status") == "insufficient"),
            "success_rate": round(success / len(conclusive) * 100, 1) if conclusive else 0.0,
        })

    rejected_items = [item for item in items if item.get("feedback_status") == "rejected"]
    insufficient_items = [item for item in items if item.get("feedback_status") == "insufficient"]
    modified_items = [item for item in items if item.get("feedback_status") == "modified"]
    reason_counts: dict[str, int] = {}
    for item in rejected_items:
        reason = (item.get("feedback_reason") or "未填写原因").strip()
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    reasons = [
        {
            "reason": reason,
            "count": count,
            "share": round(count / len(rejected_items) * 100, 1) if rejected_items else 0.0,
        }
        for reason, count in sorted(reason_counts.items(), key=lambda entry: (-entry[1], entry[0]))
    ]

    tier_rank = {"conservative": 0, "balanced": 1, "aggressive": 2}
    direction_counts = {"more_conservative": 0, "same_tier_adjustment": 0, "more_aggressive": 0}
    transition_counts: dict[tuple[str, str], int] = {}
    for item in modified_items:
        recommended_tier = item.get("recommended_tier") or "balanced"
        selected_tier = item.get("selected_tier") or recommended_tier
        transition = (recommended_tier, selected_tier)
        transition_counts[transition] = transition_counts.get(transition, 0) + 1
        rank_delta = tier_rank.get(selected_tier, 1) - tier_rank.get(recommended_tier, 1)
        if rank_delta < 0:
            direction_counts["more_conservative"] += 1
        elif rank_delta > 0:
            direction_counts["more_aggressive"] += 1
        else:
            direction_counts["same_tier_adjustment"] += 1
    directions = [
        {"key": key, "name": name, "count": direction_counts[key]}
        for key, name in (
            ("more_conservative", "改得更稳健"),
            ("same_tier_adjustment", "同档微调"),
            ("more_aggressive", "改得更激进"),
        )
    ]
    transitions = [
        {
            "recommended_tier": recommended,
            "selected_tier": selected,
            "count": count,
        }
        for (recommended, selected), count in sorted(transition_counts.items(), key=lambda entry: -entry[1])
    ]

    scenes = []
    for scene_name in sorted({item.get("scene_name") or "未标注场景" for item in items}):
        scene_items = [item for item in items if (item.get("scene_name") or "未标注场景") == scene_name]
        scene_verified = [item for item in scene_items if item.get("workflow_status") == "verified"]
        scene_conclusive = [item for item in scene_verified if item.get("result_status") in ("success", "partial", "failed")]
        scene_success = sum(1 for item in scene_conclusive if item.get("result_status") == "success")
        scene_modified = sum(1 for item in scene_items if item.get("feedback_status") == "modified")
        scene_rejected = sum(1 for item in scene_items if item.get("feedback_status") == "rejected")
        scene_insufficient = sum(1 for item in scene_items if item.get("feedback_status") == "insufficient")
        scene_decidable = len(scene_items) - scene_insufficient
        scenes.append({
            "scene_name": scene_name,
            "total": len(scene_items),
            "adopted": sum(1 for item in scene_items if item.get("feedback_status") == "adopted"),
            "modified": scene_modified,
            "rejected": scene_rejected,
            "insufficient": scene_insufficient,
            "manual_intervention_rate": round((scene_modified + scene_rejected) / scene_decidable * 100, 1) if scene_decidable else 0.0,
            "verified": len(scene_verified),
            "success_rate": round(scene_success / len(scene_conclusive) * 100, 1) if scene_conclusive else 0.0,
        })
    scenes.sort(key=lambda item: (-item["total"], -item["manual_intervention_rate"], item["scene_name"]))

    manual_intervention = len(modified_items) + len(rejected_items)
    decidable_count = len(items) - len(insufficient_items)
    return {
        "items": items,
        "summary": {
            "total": len(items),
            "adopted": sum(1 for item in items if item.get("feedback_status") == "adopted"),
            "modified": sum(1 for item in items if item.get("feedback_status") == "modified"),
            "rejected": sum(1 for item in items if item.get("feedback_status") == "rejected"),
            "insufficient": len(insufficient_items),
            "executed": sum(1 for item in items if item.get("workflow_status") in ("executed", "verified")),
            "verified": sum(1 for item in items if item.get("workflow_status") == "verified"),
        },
        "tiers": tiers,
        "attribution": {
            "summary": {
            "manual_intervention": manual_intervention,
                "manual_intervention_rate": round(manual_intervention / decidable_count * 100, 1) if decidable_count else 0.0,
            "insufficient": len(insufficient_items),
                "tier_changed": direction_counts["more_conservative"] + direction_counts["more_aggressive"],
                "same_tier_adjustment": direction_counts["same_tier_adjustment"],
                "reason_coverage": round(sum(1 for item in rejected_items if (item.get("feedback_reason") or "").strip()) / len(rejected_items) * 100, 1) if rejected_items else 0.0,
            },
            "reasons": reasons,
            "directions": directions,
            "transitions": transitions,
            "scenes": scenes,
        },
    }


@router.put("/action-records/{record_id}/review")
def update_action_record_review(
    record_id: int,
    body: PromoActionReviewIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    row = _action_record_row(db, record_id, user)
    if not row:
        raise HTTPException(status_code=404, detail="调整记录不存在")
    updates: list[str] = []
    params: list = []
    if body.success_criteria is not None:
        allowed = {"target_roi_min", "roi_change_min", "sales_change_pct_min", "spend_change_pct_max"}
        criteria = {key: float(value) for key, value in body.success_criteria.items() if key in allowed}
        updates.append("success_criteria = ?")
        params.append(json.dumps(criteria, ensure_ascii=False))
    if body.interference_notes is not None:
        updates.append("interference_notes = ?")
        params.append(body.interference_notes.strip())
    if body.manual_conclusion is not None:
        updates.append("manual_conclusion = ?")
        params.append(body.manual_conclusion.strip())
    if updates:
        params.append(record_id)
        db.execute("UPDATE promo_action_records SET " + ", ".join(updates) + " WHERE id = ?", params)
        _log(db, user, "更新验证设置", row.get("plan_name") or f"计划 {row['plan_id']}", f"action_record_id={record_id}")
    return {"ok": True, "item": _action_record_row(db, record_id, user)}


@router.put("/action-records/{record_id}/lifecycle")
def update_action_record_lifecycle(
    record_id: int,
    body: PromoActionLifecycleIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """作废、归档或恢复动作记录；保留原始业务状态和审计链路。"""
    row = _action_record_row(db, record_id, user)
    if not row:
        raise HTTPException(status_code=404, detail="调整记录不存在")
    action = body.action.strip()
    reason = body.reason.strip()
    current = row.get("lifecycle_status") or "active"
    completed_statuses = {"success", "partial", "failed", "insufficient"}
    if action == "void":
        if current != "active":
            raise HTTPException(status_code=409, detail="只有有效记录可以作废")
        if row["status"] not in ("planned", "observing"):
            raise HTTPException(status_code=409, detail="已形成验证结论的记录请使用归档")
        if not reason:
            raise HTTPException(status_code=422, detail="请填写取消或终止原因")
        target = "voided"
        log_action = "作废推广动作"
    elif action == "archive":
        if current != "active":
            raise HTTPException(status_code=409, detail="只有有效记录可以归档")
        if row["status"] not in completed_statuses:
            raise HTTPException(status_code=409, detail="只有已完成验证的记录可以归档")
        target = "archived"
        log_action = "归档推广动作"
    elif action == "restore":
        if current == "active":
            raise HTTPException(status_code=409, detail="该记录已经是有效状态")
        target = "active"
        log_action = "恢复推广动作"
    else:
        raise HTTPException(status_code=422, detail="无效的生命周期操作")
    now = _now()
    db.execute(
        "UPDATE promo_action_records SET lifecycle_status = ?, lifecycle_reason = ?, lifecycle_updated_at = ? WHERE id = ?",
        (target, reason if action != "restore" else "", now, record_id),
    )
    _log(db, user, log_action, row.get("plan_name") or f"计划 {row['plan_id']}", f"action_record_id={record_id}；{reason}")
    return {"ok": True, "item": _action_record_row(db, record_id, user)}


@router.get("/strategies")
def list_promo_strategies(
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    scope_frag, scope_params = _scope_filter(store_id, user)
    rows = db.execute("SELECT * FROM promo_strategies WHERE 1=1" + scope_frag + " ORDER BY updated_at DESC LIMIT 200", scope_params).fetchall()
    items, groups = _enrich_promo_strategies(db, rows)
    return {"items": items, "groups": groups}


@router.post("/strategies")
def create_manual_promo_strategy(
    body: PromoStrategyCreateIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """新增人工经验；待真实执行验证前不计入历史证据。"""
    visible = visible_store_ids(user)
    if visible is not None and body.store_id not in visible:
        raise HTTPException(status_code=404, detail="店铺不存在或无权访问")
    store = db.execute("SELECT id, name FROM stores WHERE id = ?", (body.store_id,)).fetchone()
    if not store:
        raise HTTPException(status_code=404, detail="店铺不存在或无权访问")
    name = body.name.strip()
    action_type = body.action_type.strip()
    conditions = body.conditions.strip()
    evidence = body.evidence.strip()
    if not all((name, action_type, conditions, evidence)):
        raise HTTPException(status_code=400, detail="请完整填写经验名称、推荐动作、适用条件和经验依据")
    if body.min_roi is not None and body.max_roi is not None and body.min_roi > body.max_roi:
        raise HTTPException(status_code=400, detail="ROI 下限不能高于上限")
    now = _now()
    cur = db.execute(
        "INSERT INTO promo_strategies "
        "(user_id, store_id, source_action_id, name, action_type, conditions, evidence, use_count, success_count, status, outcome, scene, min_roi, max_roi, source_type, verification_status, created_at, updated_at) "
        "VALUES (?, ?, NULL, ?, ?, ?, ?, 0, 0, 'active', 'pending', ?, ?, ?, 'manual', 'pending', ?, ?)",
        (
            user["id"], body.store_id, name, action_type, conditions, evidence,
            body.scene.strip(), body.min_roi, body.max_roi, now, now,
        ),
    )
    strategy_id = int(cur.lastrowid)
    row = db.execute("SELECT * FROM promo_strategies WHERE id = ?", (strategy_id,)).fetchone()
    items, _ = _enrich_promo_strategies(db, [row] if row else [])
    _log(db, user, "添加人工推广经验", name, f"strategy_id={strategy_id}；状态=待验证")
    return {"ok": True, "id": strategy_id, "item": items[0] if items else dict(row)}


@router.put("/strategies/{strategy_id}")
def update_promo_strategy(
    strategy_id: int,
    body: PromoStrategyUpdateIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """编辑或停用策略卡，不修改原始验证证据。"""
    scope_frag, scope_params = _scope_filter(None, user)
    row = db.execute("SELECT * FROM promo_strategies WHERE id = ?" + scope_frag, [strategy_id] + scope_params).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="策略卡不存在")
    updates: list[str] = []
    params: list = []
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="策略名称不能为空")
        updates.append("name = ?")
        params.append(name)
    if body.conditions is not None:
        updates.append("conditions = ?")
        params.append(body.conditions.strip())
    if body.scene is not None:
        updates.append("scene = ?")
        params.append(body.scene.strip())
    if body.min_roi is not None or body.max_roi is not None:
        min_roi = body.min_roi
        max_roi = body.max_roi
        if min_roi is not None and max_roi is not None and min_roi > max_roi:
            raise HTTPException(status_code=400, detail="ROI 下限不能高于上限")
        if min_roi is not None:
            updates.append("min_roi = ?")
            params.append(min_roi)
        if max_roi is not None:
            updates.append("max_roi = ?")
            params.append(max_roi)
    if body.status is not None:
        if body.status not in ("active", "inactive"):
            raise HTTPException(status_code=400, detail="策略状态无效")
        updates.append("status = ?")
        params.append(body.status)
    if not updates:
        return {"ok": True, "item": dict(row)}
    now = _now()
    updates.append("updated_at = ?")
    params.extend([now, strategy_id])
    db.execute("UPDATE promo_strategies SET " + ", ".join(updates) + " WHERE id = ?", params)
    _log(db, user, "更新推广策略", row["name"], f"strategy_id={strategy_id}")
    updated = db.execute("SELECT * FROM promo_strategies WHERE id = ?", (strategy_id,)).fetchone()
    return {"ok": True, "item": dict(updated) if updated else None}


@router.post("/action-records")
def create_action_record(
    body: PromoActionRecordIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not body.action_type.strip():
        raise HTTPException(status_code=400, detail="请填写调整动作")
    observation_hours = max(1, min(int(body.observation_hours), 720))
    scope_frag, scope_params = _scope_filter(None, user)
    plan = db.execute("SELECT * FROM promo_plans WHERE id = ?" + scope_frag, [body.plan_id] + scope_params).fetchone()
    if not plan:
        raise HTTPException(status_code=404, detail="推广计划不存在")
    decision_record = None
    if body.decision_record_id:
        decision_record = db.execute(
            "SELECT * FROM promo_decision_records WHERE id = ? AND plan_id = ? AND store_id = ?",
            (body.decision_record_id, plan["id"], plan["store_id"]),
        ).fetchone()
        if not decision_record or decision_record["workflow_status"] in ("rejected", "deferred"):
            raise HTTPException(status_code=400, detail="关联的 AI 决策记录无效")
    now = _now()
    cur = db.execute(
        "INSERT INTO promo_action_records "
        "(user_id, username, store_id, plan_id, action_type, description, after_value, before_spend, before_sales, before_roi, expected, observation_hours, status, executed_at, created_at, decision_id, strategy_id, success_criteria, rollback_condition, decision_record_id, decision_tier, change_pct) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user["id"], user["username"], plan["store_id"], plan["id"], body.action_type.strip(), body.description.strip(),
            body.after_value, float(plan["spend"] or 0), float(plan["sales"] or 0), float(plan["roi"] or 0),
            body.expected.strip(), observation_hours, now, body.decision_id.strip() if body.decision_id else None, body.strategy_id,
            json.dumps(body.success_criteria, ensure_ascii=False),
            body.rollback_condition.strip(),
            body.decision_record_id,
            body.decision_tier.strip(),
            body.change_pct,
        ),
    )
    if body.strategy_id:
        strategy = db.execute(
            "SELECT id FROM promo_strategies WHERE id = ? AND store_id = ? AND status = 'active'",
            (body.strategy_id, plan["store_id"]),
        ).fetchone()
        if strategy:
            db.execute("UPDATE promo_strategies SET use_count = use_count + 1, updated_at = ? WHERE id = ?", (now, body.strategy_id))
    record_id = cur.lastrowid
    if decision_record:
        try:
            stored_criteria = json.loads(decision_record["final_success_criteria"] or "{}")
        except (TypeError, json.JSONDecodeError):
            stored_criteria = {}
        changed = (
            (body.decision_field and body.decision_field != decision_record["final_field"])
            or (body.change_pct is not None and abs(float(body.change_pct) - float(decision_record["final_change_pct"] or 0)) > 0.001)
            or observation_hours != int(decision_record["final_observation_hours"] or 48)
            or body.success_criteria != stored_criteria
        )
        feedback_status = "modified" if changed else decision_record["feedback_status"]
        db.execute(
            "UPDATE promo_decision_records SET feedback_status = ?, workflow_status = 'planned', action_record_id = ?, selected_tier = ?, final_field = ?, final_change_pct = ?, final_success_criteria = ?, final_observation_hours = ?, rollback_condition = ?, updated_at = ? WHERE id = ?",
            (feedback_status, record_id, body.decision_tier.strip(), body.decision_field.strip(), body.change_pct, json.dumps(body.success_criteria, ensure_ascii=False), observation_hours, body.rollback_condition.strip(), now, decision_record["id"]),
        )
    _log(db, user, "记录调整动作", plan["plan_name"], f"action_record_id={record_id}；{body.action_type.strip()}")
    # 单人运营主链路不再自动创建协同任务；保留字段避免破坏旧客户端。
    return {"ok": True, "id": record_id, "collaboration_task_id": None}


@router.post("/action-records/{record_id}/mark-executed")
def mark_action_record_executed(
    record_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    row = _action_record_row(db, record_id, user)
    if not row:
        raise HTTPException(status_code=404, detail="调整记录不存在")
    if row["status"] != "planned":
        raise HTTPException(status_code=400, detail="该记录不在待执行状态")
    plan = db.execute("SELECT spend, sales, roi, campaign_id, store_id FROM promo_plans WHERE id = ?", (row["plan_id"],)).fetchone()
    executed_at = _now()
    executed_date = _parse_action_time(executed_at).date()
    baseline_end = executed_date - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=2)
    baseline = _plan_window_metrics(db, plan["store_id"], plan["campaign_id"], baseline_start.isoformat(), baseline_end.isoformat())
    if baseline["days"] == 0:
        baseline = {"spend": float(plan["spend"] or 0), "sales": float(plan["sales"] or 0), "roi": float(plan["roi"] or 0), "days": 0, "updated_at": ""}
    due_at = _parse_action_time(executed_at) + timedelta(hours=int(row["observation_hours"] or 48))
    quality = f"动作前日报 {baseline.get('days', 0)} 天"
    db.execute(
        "UPDATE promo_action_records SET status = 'observing', before_spend = ?, before_sales = ?, before_roi = ?, baseline_start = ?, baseline_end = ?, observation_due_at = ?, data_quality = ?, baseline_days = ?, executed_at = ?, platform_status = CASE WHEN platform_status = 'not_submitted' THEN 'submitted' ELSE platform_status END, platform_submitted_at = COALESCE(platform_submitted_at, ?) WHERE id = ?",
        (baseline["spend"], baseline["sales"], baseline["roi"], baseline_start.isoformat(), baseline_end.isoformat(), due_at.isoformat(timespec="seconds"), quality, baseline.get("days", 0), executed_at, executed_at, record_id),
    )
    if row.get("decision_record_id"):
        db.execute("UPDATE promo_decision_records SET workflow_status = 'executed', updated_at = ? WHERE id = ?", (executed_at, row["decision_record_id"]))
    _log(db, user, "确认执行调整动作", row["plan_name"], f"action_record_id={record_id}")
    return {"ok": True, "status": "observing"}


@router.post("/action-records/{record_id}/platform-status")
def update_action_platform_status(
    record_id: int,
    body: PromoActionPlatformStatusIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """记录平台执行回查结果；只更新本地档案，不再次写入万相台。"""
    labels = {
        "submitted": "已提交平台",
        "effective": "平台已生效",
        "failed": "回查失败",
        "manual_confirmed": "人工确认生效",
    }
    if body.status not in labels:
        raise HTTPException(status_code=422, detail="无效的平台回查状态")
    row = _action_record_row(db, record_id, user)
    if not row:
        raise HTTPException(status_code=404, detail="调整记录不存在")
    if row["status"] == "planned":
        raise HTTPException(status_code=409, detail="请先确认动作已经执行，再记录平台回查结果")
    now = _now()
    submitted_at = row.get("platform_submitted_at") or (now if body.status == "submitted" else row.get("executed_at") or now)
    db.execute(
        "UPDATE promo_action_records SET platform_status = ?, platform_submitted_at = ?, platform_checked_at = ?, platform_check_note = ? WHERE id = ?",
        (body.status, submitted_at, now, body.note.strip(), record_id),
    )
    _log(db, user, "平台执行回查", row["plan_name"], f"action_record_id={record_id}；{labels[body.status]}；{body.note.strip()}")
    return {
        "ok": True,
        "status": body.status,
        "label": labels[body.status],
        "platform_submitted_at": submitted_at,
        "platform_checked_at": now,
        "note": body.note.strip(),
    }


@router.post("/action-records/{record_id}/verify")
def verify_action_record(
    record_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    row = _action_record_row(db, record_id, user)
    if not row:
        raise HTTPException(status_code=404, detail="调整记录不存在")
    if row["status"] == "planned":
        raise HTTPException(status_code=400, detail="请先标记动作已执行，再开始验证")
    if row["status"] != "observing":
        raise HTTPException(status_code=400, detail="该记录已经完成验证")
    now_dt = _parse_action_time(_now())
    due_at = _parse_action_time(row["observation_due_at"]) if row.get("observation_due_at") else now_dt
    if now_dt < due_at:
        raise HTTPException(status_code=409, detail=f"观察窗口尚未结束，预计 {due_at.strftime('%m-%d %H:%M')} 后可验证")
    executed_date = _parse_action_time(row["executed_at"]).date()
    after_end = min(now_dt.date(), due_at.date())
    after = _plan_window_metrics(db, row["store_id"], row["campaign_id"], executed_date.isoformat(), after_end.isoformat())
    after_spend = after["spend"]
    after_sales = after["sales"]
    after_roi = after["roi"]
    before_roi = float(row["before_roi"] or 0)
    baseline_days = int(row.get("baseline_days") or 0)
    after_days = int(after["days"] or 0)
    before_daily_spend = round(float(row["before_spend"] or 0) / baseline_days, 2) if baseline_days else float(row["before_spend"] or 0)
    before_daily_sales = round(float(row["before_sales"] or 0) / baseline_days, 2) if baseline_days else float(row["before_sales"] or 0)
    after_daily_spend = round(after_spend / after_days, 2) if after_days else 0.0
    after_daily_sales = round(after_sales / after_days, 2) if after_days else 0.0
    roi_change = round(after_roi - before_roi, 2)
    spend_change_pct = _change_pct(after_daily_spend, before_daily_spend)
    sales_change_pct = _change_pct(after_daily_sales, before_daily_sales)
    metrics = {
        "before_daily_spend": before_daily_spend,
        "before_daily_sales": before_daily_sales,
        "after_daily_spend": after_daily_spend,
        "after_daily_sales": after_daily_sales,
        "roi_change": roi_change,
        "spend_change_pct": spend_change_pct,
        "sales_change_pct": sales_change_pct,
    }
    confidence = _verification_confidence(baseline_days, after_days, after_spend, bool(row.get("interference_notes")))
    criteria = row.get("success_criteria") or {}
    checks: list[tuple[str, bool]] = []
    if "target_roi_min" in criteria:
        checks.append((f"ROI≥{criteria['target_roi_min']}", after_roi >= float(criteria["target_roi_min"])))
    if "roi_change_min" in criteria:
        checks.append((f"ROI提升≥{criteria['roi_change_min']}", roi_change >= float(criteria["roi_change_min"])))
    if "sales_change_pct_min" in criteria:
        checks.append((f"日均成交变化≥{criteria['sales_change_pct_min']}%", sales_change_pct is not None and sales_change_pct >= float(criteria["sales_change_pct_min"])))
    if "spend_change_pct_max" in criteria:
        checks.append((f"日均花费变化≤{criteria['spend_change_pct_max']}%", spend_change_pct is not None and spend_change_pct <= float(criteria["spend_change_pct_max"])))
    if after_days == 0 or (after_spend == 0 and after_sales == 0) or confidence == "low":
        status, result = "insufficient", "数据量或观察天数不足，当前结论可信度低，建议继续观察并同步计划日报"
    elif checks:
        passed = sum(1 for _, ok in checks if ok)
        details = "；".join(f"{label}{'达标' if ok else '未达标'}" for label, ok in checks)
        if passed == len(checks):
            status, result = "success", f"全部成功标准达标：{details}"
        elif passed > 0:
            status, result = "partial", f"部分成功标准达标：{details}"
        else:
            status, result = "failed", f"成功标准均未达标：{details}"
    elif roi_change >= 0.1:
        status, result = "success", f"ROI 较动作前提升 {roi_change:.2f}，当前计划表现改善"
    elif roi_change <= -0.1:
        status, result = "failed", f"ROI 较动作前下降 {abs(roi_change):.2f}，建议回退或重新调整"
    else:
        status, result = "partial", "ROI 变化不明显，建议结合日均成交和花费继续观察"
    verified_at = _now()
    db.execute(
        "UPDATE promo_action_records SET status = ?, result = ?, after_spend = ?, after_sales = ?, after_roi = ?, data_quality = ?, confidence = ?, after_days = ?, metric_summary = ?, verified_at = ? WHERE id = ?",
        (status, result, after_spend, after_sales, after_roi, f"基线 {baseline_days} 天 · 观察 {after_days} 天", confidence, after_days, json.dumps(metrics, ensure_ascii=False), verified_at, record_id),
    )
    if row.get("decision_record_id"):
        db.execute(
            "UPDATE promo_decision_records SET workflow_status = 'verified', result_status = ?, result_summary = ?, updated_at = ? WHERE id = ?",
            (status, result, verified_at, row["decision_record_id"]),
        )
    upgraded_manual_strategy = False
    if row.get("strategy_id") and status in ("success", "partial", "failed"):
        manual_strategy = db.execute(
            "SELECT * FROM promo_strategies WHERE id = ? AND store_id = ? AND source_type = 'manual' AND verification_status = 'pending'",
            (row["strategy_id"], row["store_id"]),
        ).fetchone()
        if manual_strategy:
            verified_evidence = f"{manual_strategy['evidence']}；系统验证：ROI {before_roi:.2f} → {after_roi:.2f}，观察日报 {after['days']} 天，{result}"
            db.execute(
                "UPDATE promo_strategies SET source_action_id = ?, evidence = ?, success_count = ?, outcome = ?, verification_status = 'verified', updated_at = ? WHERE id = ?",
                (record_id, verified_evidence, 1 if status == "success" else 0, status, verified_at, manual_strategy["id"]),
            )
            upgraded_manual_strategy = True
    if status == "success" and not upgraded_manual_strategy:
        strategy_name = f"{row['action_type']}（已验证）"
        evidence = f"ROI {before_roi:.2f} → {after_roi:.2f}；观察日报 {after['days']} 天；{result}"
        min_roi = max(0, round(before_roi - 0.5, 2))
        max_roi = round(before_roi + 0.5, 2)
        db.execute(
            "INSERT INTO promo_strategies (user_id, store_id, source_action_id, name, action_type, conditions, evidence, use_count, success_count, status, created_at, updated_at, outcome, scene, min_roi, max_roi) "
            "SELECT ?, ?, ?, ?, ?, ?, ?, 0, 1, 'active', ?, ?, 'success', ?, ?, ? "
            "WHERE NOT EXISTS (SELECT 1 FROM promo_strategies WHERE source_action_id = ?)",
            (user["id"], row["store_id"], record_id, strategy_name, row["action_type"], row["expected"] or "适用于相似计划和相同经营目标", evidence, verified_at, verified_at, row.get("scene_name") or "", min_roi, max_roi, record_id),
        )
    elif status in ("failed", "partial") and not upgraded_manual_strategy:
        strategy_name = f"{row['action_type']}（{('失败' if status == 'failed' else '部分有效')}经验）"
        evidence = f"ROI {before_roi:.2f} → {after_roi:.2f}；观察日报 {after['days']} 天；{result}"
        min_roi = max(0, round(before_roi - 0.5, 2))
        max_roi = round(before_roi + 0.5, 2)
        db.execute(
            "INSERT INTO promo_strategies (user_id, store_id, source_action_id, name, action_type, conditions, evidence, use_count, success_count, status, outcome, created_at, updated_at, scene, min_roi, max_roi) "
            "SELECT ?, ?, ?, ?, ?, ?, ?, 0, 0, 'active', ?, ?, ?, ?, ?, ? "
            "WHERE NOT EXISTS (SELECT 1 FROM promo_strategies WHERE source_action_id = ?)",
            (user["id"], row["store_id"], record_id, strategy_name, row["action_type"], row["expected"] or "相似条件下谨慎使用", evidence, status, verified_at, verified_at, row.get("scene_name") or "", min_roi, max_roi, record_id),
        )
    _log(db, user, "验证调整动作", row["plan_name"], f"action_record_id={record_id}；结果={status}")
    return {
        "ok": True,
        "status": status,
        "result": result,
        "before": {"spend": row["before_spend"], "sales": row["before_sales"], "roi": before_roi},
        "after": {"spend": after_spend, "sales": after_sales, "roi": after_roi, "days": after["days"]},
    }

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
        except Exception as exc:  # noqa: BLE001 - 单店失败不能中断其他店铺同步
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": f"同步异常：{str(exc) or exc.__class__.__name__}"})
    return {"results": results}

@router.get("/data")
def promo_data(
    mode: str = "realtime",
    scene: str = "",
    channel: str = "",
    start: str = "",
    end: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    mode = _mode(mode)
    today = date_cls.today()
    scope_frag, scope_params = _scope_filter(store_id, user)
    visible = visible_store_ids(user)
    if store_id is not None:
        if visible is not None and store_id not in visible:
            raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
        bound_store_count = sum(1 for s in _bound_stores(db) if s["id"] == store_id)
    elif visible is None:
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
                sd, ed = today - timedelta(days=7), today - timedelta(days=1)
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

    def _channel_groups(scenes: list[dict]) -> list[dict]:
        grouped: dict[str, dict] = {}
        for scene_item in scenes:
            channel_key = scene_item["channel"]
            item = grouped.setdefault(
                channel_key,
                {
                    "channel": channel_key,
                    "channel_name": CHANNEL_NAMES[channel_key],
                    "impressions": 0,
                    "clicks": 0,
                    "spend": 0.0,
                    "sales": 0.0,
                    "orders": 0,
                    "add_cart": 0,
                },
            )
            for field in ("impressions", "clicks", "spend", "sales", "orders", "add_cart"):
                item[field] += scene_item.get(field) or 0
        return sorted((_finalize(item) for item in grouped.values()), key=lambda item: item["spend"], reverse=True)

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
            if scene and r["scene"] != scene:
                continue
            if not channel_matches(channel, r["scene"], r["scene_name"]):
                continue
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
        scenes = sorted((with_channel(_finalize(v)) for v in scene_map.values()), key=lambda x: x["spend"], reverse=True)
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
            if scene and r["scene"] != scene:
                continue
            if not channel_matches(channel, r["scene"], r["scene_name"]):
                continue
            y_sum["spend"] += r["spend"] or 0
            y_sum["sales"] += r["sales"] or 0
        store_sales = _store_sales(cur_hour=cur_hour)
        summary = _final_summary(summary, store_sales)
        realtime_points = len({(r["store_id"], r["hour"]) for r in rows if (not scene or r["scene"] == scene) and channel_matches(channel, r["scene"], r["scene_name"])})
        metadata_store_count = max(bound_store_count, len({r["store_id"] for r in rows}))
        elapsed_hours = datetime.now().hour + 1
        data_metadata = build_dataset_metadata(db, "realtime", user, store_id, expected_points=metadata_store_count * elapsed_hours, actual_points=realtime_points)
        return {
            "mode": mode,
            "summary": summary,
            "compare": {"spend": _pct(summary["spend"], y_sum["spend"]), "sales": _pct(summary["sales"], y_sum["sales"])},
            "scenes": scenes,
            "channels": _channel_groups(scenes),
            "alerts": _alerts(scenes),
            "trend": trend,
            "trend_unit": "hour",
            "business_data_at": data_metadata["business_data_at"],
            "last_sync_at": data_metadata["last_sync_at"],
            "last_sync": data_metadata["last_sync_at"] or _last_sync(db),
            "data_metadata": data_metadata,
            "bound_stores": bound_store_count,
        }

    # yesterday / 7d / range：按天报表（分场景）
    if mode == "yesterday":
        start_d = end_d = today - timedelta(days=1)
    elif mode == "range":
        start_d, end_d = range_start, range_end
    else:
        start_d, end_d = today - timedelta(days=7), today - timedelta(days=1)
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
        if not channel_matches(channel, r["scene"], r["scene_name"]):
            continue
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

    scenes = sorted((with_channel(_finalize(v)) for v in scene_map.values()), key=lambda x: x["spend"], reverse=True)
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
            if scene and r["scene"] != scene:
                continue
            if not channel_matches(channel, r["scene"], r["scene_name"]):
                continue
            prev_totals["spend"] += r["spend"] or 0
            prev_totals["sales"] += r["sales"] or 0

    store_sales = _store_sales()
    summary = _final_summary(totals, store_sales)
    metadata_store_count = max(bound_store_count, len({r["store_id"] for r in rows}))
    data_metadata = build_dataset_metadata(
        db,
        "daily",
        user,
        store_id,
        expected_points=metadata_store_count * span,
        actual_points=len({(r["store_id"], r["data_date"]) for r in rows if channel_matches(channel, r["scene"], r["scene_name"])}),
    )
    return {
        "mode": mode,
        "summary": summary,
        "compare": {"spend": _pct(summary["spend"], prev_totals["spend"]), "sales": _pct(summary["sales"], prev_totals["sales"])},
        "scenes": scenes,
        "channels": _channel_groups(scenes),
        "alerts": _alerts(scenes),
        "trend": trend,
        "trend_unit": "day",
        "business_data_at": data_metadata["business_data_at"],
        "last_sync_at": data_metadata["last_sync_at"],
        "last_sync": data_metadata["last_sync_at"] or _last_sync(db),
        "data_metadata": data_metadata,
        "bound_stores": bound_store_count,
    }

@router.post("/sync")
def sync_promo(
    mode: str = "realtime",
    start: str = "",
    end: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    requested_mode = mode
    mode = _mode(mode)
    today = date_cls.today()
    range_start = range_end = None
    if requested_mode == "range":
        if not start.strip() or not end.strip():
            raise HTTPException(status_code=400, detail="自定义区间需要同时提供开始和结束日期")
        try:
            range_start = date_cls.fromisoformat(start.strip())
            range_end = date_cls.fromisoformat(end.strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="日期格式不正确（应为 YYYY-MM-DD）") from exc
        if range_start > range_end:
            range_start, range_end = range_end, range_start
        mode = "range"
    results = []
    visible = visible_store_ids(user)
    stores = _all_stores(db)
    if visible is not None:
        stores = [store for store in stores if store["id"] in visible]
    if store_id is not None:
        stores = [store for store in stores if store["id"] == store_id]
        if not stores:
            raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
    for store in stores:
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
            elif mode == "range":
                items = fetch_scene_daily(store, range_start.isoformat(), range_end.isoformat())
                count = _store_daily_rows(db, store["id"], items, now)
            else:
                start = today - timedelta(days=7)
                end = today - timedelta(days=1)
                items = fetch_scene_daily(store, start.isoformat(), end.isoformat())
                count = _store_daily_rows(db, store["id"], items, now)
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": True, "rows": count})
        except AlimamaError as exc:
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - 单店失败不能中断其他店铺同步
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": f"同步异常：{str(exc) or exc.__class__.__name__}"})
    sync_state = record_sync_result(
        db,
        "realtime" if mode == "realtime" else "daily",
        {"results": results, "total": len(results), "ok": sum(1 for result in results if result["ok"])},
        source="alimama_scene_realtime" if mode == "realtime" else "alimama_scene_daily",
    )
    if sync_state["status"] in {"success", "partial"}:
        db.execute(
            "INSERT INTO meta (key, value) VALUES ('promo_last_sync', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (sync_state["last_attempt_at"],),
        )
    _log(db, user, "同步万相台数据", "", f"模式={mode} 成功 {sum(1 for r in results if r['ok'])} / {len(results)} 家")
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"]), "sync": sync_state}

@router.get("/plans")
def list_plans(
    scene: str = "",
    channel: str = "",
    mode: str = "realtime",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    mode = _mode(mode)
    query = (
        "SELECT p.*, "
        "(SELECT pi.item_id FROM promo_plan_items pi WHERE pi.store_id = p.store_id AND pi.campaign_id = p.campaign_id ORDER BY pi.updated_at DESC LIMIT 1) AS linked_item_id, "
        "(SELECT pi.item_title FROM promo_plan_items pi WHERE pi.store_id = p.store_id AND pi.campaign_id = p.campaign_id ORDER BY pi.updated_at DESC LIMIT 1) AS linked_item_title, "
        "(SELECT pi.image FROM promo_plan_items pi WHERE pi.store_id = p.store_id AND pi.campaign_id = p.campaign_id ORDER BY pi.updated_at DESC LIMIT 1) AS linked_item_image, "
        "COALESCE(s.spend, 0) AS stat_spend, COALESCE(s.sales, 0) AS stat_sales, "
        "COALESCE(s.roi, 0) AS stat_roi, COALESCE(s.clicks, 0) AS stat_clicks, "
        "COALESCE(s.prev_spend, 0) AS prev_spend, COALESCE(s.prev_sales, 0) AS prev_sales, "
        "COALESCE(s.prev_roi, 0) AS prev_roi, COALESCE(s.prev_clicks, 0) AS prev_clicks, "
        "COALESCE(s.prev_scope, 'unknown') AS prev_scope, "
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
    if store_id is not None:
        if visible is not None and store_id not in visible:
            raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
        where_parts.append("p.store_id = ?")
        params.append(store_id)
    if scene:
        where_parts.append("p.scene = ?")
        params.append(scene)
    if where_parts:
        query += " WHERE " + " AND ".join(where_parts)
    query += " ORDER BY CASE p.status WHEN '在投' THEN 0 ELSE 1 END, stat_spend DESC, p.id ASC"
    rows = db.execute(query, params).fetchall()
    items = []
    def _cycle(cur, prev, scope="unknown"):
        if prev and (mode != "realtime" or scope == "same_hour"):
            return round((cur - prev) / prev * 100, 2)
        return None

    for r in rows:
        d = dict(r)
        if not channel_matches(channel, d.get("scene"), d.get("scene_name")):
            continue
        d["spend"] = d.pop("stat_spend", 0) or 0
        d["sales"] = d.pop("stat_sales", 0) or 0
        d["roi"] = d.pop("stat_roi", 0) or 0
        d["clicks"] = d.pop("stat_clicks", 0) or 0
        d["alipay_dir"] = d.pop("stat_alipay_dir", 0) or 0
        d["alipay_indir"] = d.pop("stat_alipay_indir", 0) or 0
        d["retained_sales"] = d.pop("stat_retained_sales", 0) or 0
        d["retained_roi"] = d.pop("stat_retained_roi", 0) or 0
        d["refund_amt"] = d.pop("stat_refund_amt", 0) or 0
        d["item_id"] = d.pop("linked_item_id", "") or ""
        d["item_title"] = d.pop("linked_item_title", "") or ""
        d["item_image"] = d.pop("linked_item_image", "") or ""
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
        d["prev_scope"] = d.pop("prev_scope", "unknown") or "unknown"
        d["spend_cycle"] = _cycle(d["spend"], d["prev_spend"], d["prev_scope"])
        d["sales_cycle"] = _cycle(d["sales"], d["prev_sales"], d["prev_scope"])
        d["roi_cycle"] = _cycle(d["roi"], d["prev_roi"], d["prev_scope"])
        d["mode"] = mode
        items.append(with_channel(d))
    compare_labels = {"realtime": "昨日同时段", "yesterday": "前日全天", "7d": "前7天"}
    compare_notes = {
        "realtime": "仅在计划级昨日同时段数据可用时计算；否则显示—",
        "yesterday": "当前与前日均为完整自然日",
        "7d": "当前与对比均为连续7天汇总",
    }
    return {
        "items": items,
        "mode": mode,
        "compare_label": compare_labels.get(mode, "上期"),
        "compare_note": compare_notes.get(mode, "按上期数据比较"),
        "data_metadata": build_dataset_metadata(db, "plans", user, store_id, expected_points=len(items), actual_points=sum(1 for item in items if item.get("updated_at"))),
    }

@router.post("/sync-plans")
def sync_plans(
    mode: str = "realtime",
    store_id: int | None = None,
    user: dict | None = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    mode = _mode(mode)
    today = date_cls.today()
    results = []
    visible = visible_store_ids(user) if user is not None else None
    stores = _all_stores(db)
    if visible is not None:
        stores = [store for store in stores if store["id"] in visible]
    if store_id is not None:
        stores = [store for store in stores if store["id"] == store_id]
        if not stores:
            raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
    for store in stores:
        if not has_profile(store["id"]):
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": PROFILE_MISSING_MSG})
            continue
        try:
            snapshots = fetch_plan_snapshots(store)
            if mode == "realtime":
                stats_list = fetch_plan_realtime(store)
                _pd = today - timedelta(days=1)
                # 当前值是今天累计，历史基准取昨日截至同一小时，避免把今天部分时段与昨日全天比较。
                current_hour = datetime.now().astimezone().hour
                prev_list = fetch_plan_realtime(store, _pd.isoformat(), through_hour=current_hour)
            elif mode == "yesterday":
                d = today - timedelta(days=1)
                stats_list = fetch_plan_reports(store, d.isoformat(), d.isoformat())
                _pd = today - timedelta(days=2)
                prev_list = fetch_plan_reports(store, _pd.isoformat(), _pd.isoformat())
            else:
                start = today - timedelta(days=7)
                end = today - timedelta(days=1)
                stats_list = fetch_plan_reports(store, start.isoformat(), end.isoformat())
                _ps = today - timedelta(days=14)
                _pe = today - timedelta(days=8)
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
                    "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, day_budget, budget_type, bid_type, bid_value, status, gmt_create, spend, sales, roi, clicks, note, tag, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, '', '', ?) "
                    "ON CONFLICT(store_id, campaign_id) DO UPDATE SET "
                    "scene = excluded.scene, scene_name = excluded.scene_name, plan_name = excluded.plan_name, "
                    "day_budget = excluded.day_budget, budget_type = excluded.budget_type, bid_type = excluded.bid_type, bid_value = excluded.bid_value, "
                    "status = excluded.status, gmt_create = excluded.gmt_create, updated_at = excluded.updated_at",
                    (
                        store["id"],
                        p["scene"],
                        p["scene_name"],
                        p["campaign_id"],
                        p["plan_name"],
                        p["day_budget"],
                        p.get("budget_type") or ("unlimited" if not p["day_budget"] else "normal"),
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
                        "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, prev_spend, prev_sales, prev_roi, prev_clicks, prev_scope, alipay_dir, alipay_indir, retained_sales, retained_roi, refund_amt, extra_json, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(store_id, campaign_id, mode) DO UPDATE SET "
                        "spend = excluded.spend, sales = excluded.sales, roi = excluded.roi, "
                        "clicks = excluded.clicks, prev_spend = excluded.prev_spend, prev_sales = excluded.prev_sales, "
                        "prev_roi = excluded.prev_roi, prev_clicks = excluded.prev_clicks, "
                        "prev_scope = excluded.prev_scope, "
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
                            (_pv.get("retained_roi") if mode == "realtime" else _pv.get("roi")) or 0,
                            _pv.get("clicks") or 0,
                            "same_hour" if mode == "realtime" and _pv else ("full_day" if mode != "realtime" else "unknown"),
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
        except Exception as exc:  # noqa: BLE001 - 单店失败不能中断其他店铺同步
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": f"同步异常：{str(exc) or exc.__class__.__name__}"})
    _log(db, user, "同步推广计划", "", f"模式={mode} 成功 {sum(1 for r in results if r['ok'])} / {len(results)} 家")
    sync_state = record_sync_result(
        db,
        f"plans_{mode}",
        {"results": results, "total": len(results), "ok": sum(1 for result in results if result["ok"])},
        source="alimama_campaign_report",
    )
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"]), "sync": sync_state}

@router.post("/sync-items")
def sync_items(
    mode: str = "realtime",
    store_id: int | None = None,
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
    visible = visible_store_ids(user)
    stores = _all_stores(db)
    if visible is not None:
        stores = [store for store in stores if store["id"] in visible]
    if store_id is not None:
        stores = [store for store in stores if store["id"] == store_id]
        if not stores:
            raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
    for store in stores:
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
        except Exception as exc:  # noqa: BLE001 - 单店失败不能中断其他店铺同步
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": f"同步异常：{str(exc) or exc.__class__.__name__}"})
    _log(db, user, "同步商品推广数据", "", f"模式={db_mode} 成功 {sum(1 for r in results if r['ok'])} / {len(results)} 家")
    sync_state = record_sync_result(
        db,
        f"items_{db_mode}",
        {"results": results, "total": len(results), "ok": sum(1 for result in results if result["ok"])},
        source="alimama_item_or_plan_attribution",
    )
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"]), "mode": db_mode, "sync": sync_state}

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
    store_id: int | None = None,
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
    if store_id is not None:
        if visible is not None and store_id not in visible:
            raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
        store_scope = f"p.store_id = {int(store_id)}"
    elif visible is None:
        store_scope = "1=1"
    elif not visible:
        store_scope = "1=0"
    else:
        store_scope = "p.store_id IN (%s)" % ",".join(str(i) for i in sorted(visible))
    rows = db.execute(
        "SELECT p.id AS plan_id, p.store_id, p.plan_name, p.scene_name, p.status, p.day_budget, "
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
                alerts.append({"level": "error", "type": "预算超限", "plan_id": r["plan_id"], "store_id": r["store_id"], "message": f"「{name}」今日花费 {rt_spend:.0f} 元已超日预算 {budget:.0f} 元，建议调整"})
            elif ratio >= budget_warn:
                alerts.append({"level": "warn", "type": "接近预算", "plan_id": r["plan_id"], "store_id": r["store_id"], "message": f"「{name}」今日花费已达日预算 {ratio * 100:.0f}%（{rt_spend:.0f}/{budget:.0f} 元）"})
        if rt_spend > 0 and ye_roi > 0 and 0 < rt_roi < ye_roi * roi_drop_ratio:
            alerts.append({"level": "warn", "type": "ROI下滑", "plan_id": r["plan_id"], "store_id": r["store_id"], "message": f"「{name}」今日ROI {rt_roi:.2f} 较昨日 {ye_roi:.2f} 明显下滑"})
        if rt_spend > 0 and 0 < rt_roi < roi_low:
            alerts.append({"level": "warn", "type": "ROI偏低", "plan_id": r["plan_id"], "store_id": r["store_id"], "message": f"「{name}」今日ROI {rt_roi:.2f} 低于 {roi_low:.2f}，建议关注"})
    alerts.sort(key=lambda a: 0 if a["level"] == "error" else 1)
    return {"items": alerts[:50], "count": len(alerts)}

@router.get("/export")
def export_promo(
    mode: str = "7d",
    store_id: int | None = None,
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
    scope_frag, scope_params = _scope_filter(store_id, user)
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
        start = today - timedelta(days=7)
        end = today - timedelta(days=1)
        rows = db.execute(
            "SELECT data_date, scene, scene_name, SUM(spend) AS spend, SUM(sales) AS sales, SUM(orders) AS orders "
            "FROM promo_daily_data WHERE data_date>=? AND data_date<=?" + scope_frag + " GROUP BY data_date, scene ORDER BY data_date, spend DESC",
            [start.isoformat(), end.isoformat()] + scope_params,
        ).fetchall()
        scene_names = {}
        by_date = {}
        for r in rows:
            scene_names[r["scene"]] = r["scene_name"] or r["scene"]
            by_date.setdefault(r["data_date"], {})[r["scene"]] = {"spend": r["spend"] or 0, "sales": r["sales"] or 0}
        dates = [(today - timedelta(days=i)).isoformat() for i in range(7, 0, -1)]
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
    store_id: int | None = None,
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
    if store_id is not None:
        if visible is not None and store_id not in visible:
            raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
        plan_scope = f" WHERE p.store_id = {int(store_id)}"
    elif visible is None:
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
    store_id: int | None = None,
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
    if store_id is not None:
        stores = [store for store in stores if store["id"] == store_id]
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
    scope_frag, scope_params = _scope_filter(store_id, user)
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
    store_id: int | None = None,
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
        start = (today - timedelta(days=7)).isoformat()
        end = (today - timedelta(days=1)).isoformat()
    stores = [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY id").fetchall() if has_profile(r["id"])]
    visible = visible_store_ids(user)
    if visible is not None:
        stores = [store for store in stores if store["id"] in visible]
    if store_id is not None:
        stores = [store for store in stores if store["id"] == store_id]
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
    guard = _plan_execution_guard(db, user, row)
    if body.execute and not guard["can_execute"]:
        raise HTTPException(status_code=409, detail=guard["block_reason"])
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
            _log(db, user, "计划操作(预检)", label, f"plan_id={plan_id}；{target}，命中 {count} 个单元（未执行）")
            return {"ok": True, "execute": False, "count": count, "units": pre.get("units", []), **guard}
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
    executed_at = _now()
    due_at = (_parse_action_time(executed_at) + timedelta(hours=48)).isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO promo_action_records "
        "(user_id, username, store_id, plan_id, action_type, description, before_value, after_value, before_spend, before_sales, before_roi, expected, observation_hours, status, executed_at, observation_due_at, data_quality) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'observing', ?, ?, ?)",
        (
            user["id"], user["username"], row["store_id"], row["id"], "暂停计划" if body.status == "pause" else "开启计划",
            f"万相台计划状态调整为{new_status}", None, None, float(row["spend"] or 0), float(row["sales"] or 0),
            float(row["roi"] or 0), "验证调整后 ROI、花费和成交变化", 48, executed_at, due_at, "计划操作前快照",
        ),
    )
    _log(db, user, "计划操作", label, f"plan_id={plan_id}；{target}（万相台已执行，命中 {count} 个单元）")
    return {"ok": True, "execute": True, "count": count, "response": str(resp)[:300], "can_execute": True, "block_reason": ""}

@router.post("/plans/batch-status")
def set_plans_status_batch(
    body: PlanBatchStatusIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """批量暂停/开启推广计划；每个计划独立返回结果，允许部分成功。"""
    plan_ids = list(dict.fromkeys(body.plan_ids))
    if not plan_ids:
        raise HTTPException(status_code=400, detail="至少选择一个推广计划")
    if len(plan_ids) > 50:
        raise HTTPException(status_code=400, detail="单次最多操作 50 个推广计划")
    if body.status not in ("pause", "start"):
        raise HTTPException(status_code=400, detail="仅支持 pause（暂停）/ start（开启）")

    results = []
    for plan_id in plan_ids:
        try:
            result = set_plan_status(plan_id, PlanStatusIn(status=body.status, execute=body.execute), user, db)
            results.append({"plan_id": plan_id, "ok": True, "count": result.get("count", 0)})
        except HTTPException as exc:
            results.append({"plan_id": plan_id, "ok": False, "error": str(exc.detail)})
        except Exception:
            results.append({"plan_id": plan_id, "ok": False, "error": "执行失败，请稍后重试"})
    return {
        "ok": sum(1 for item in results if item["ok"]),
        "total": len(results),
        "status": body.status,
        "execute": body.execute,
        "items": results,
    }

@router.post("/plans/batch-adjust-preview")
def preview_plans_adjust_batch(
    body: PlanBatchAdjustIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """生成批量预算/出价调整预览，不写入本地或万相台。"""
    plan_ids = list(dict.fromkeys(body.plan_ids))
    if not plan_ids:
        raise HTTPException(status_code=400, detail="至少选择一个推广计划")
    if len(plan_ids) > 50:
        raise HTTPException(status_code=400, detail="单次最多调整 50 个推广计划")
    if body.field not in ("day_budget", "bid_value"):
        raise HTTPException(status_code=400, detail="只支持调整日预算或出价")
    if not -90 <= body.change_pct <= 300:
        raise HTTPException(status_code=400, detail="调整幅度需在 -90% 到 300% 之间")

    scope_frag, scope_params = _scope_filter(None, user)
    results = []
    for plan_id in plan_ids:
        row = db.execute(
            "SELECT id, store_id, campaign_id, plan_name, status, day_budget, bid_value FROM promo_plans WHERE id = ?" + scope_frag,
            [plan_id] + scope_params,
        ).fetchone()
        if not row:
            results.append({"plan_id": plan_id, "ok": False, "error": "推广计划不存在或无权访问"})
            continue
        old_value = float(row[body.field] or 0)
        new_value = (
            round(body.target_value, 2)
            if body.target_value is not None and len(plan_ids) == 1
            else round(max(0, old_value * (1 + body.change_pct / 100)), 2)
        )
        risks = []
        if old_value <= 0:
            risks.append("当前值为 0，百分比调整不会产生有效值")
        if abs(body.change_pct) >= 30:
            risks.append("调整幅度较大，建议先小范围观察")
        if row["status"] != "在投":
            risks.append("计划当前未投放，调整后不会立即产生花费")
        guard = _plan_execution_guard(db, user, row)
        results.append({
            "plan_id": plan_id,
            "plan_name": row["plan_name"] or "未命名计划",
            "status": row["status"],
            "ok": True,
            "old_value": round(old_value, 2),
            "new_value": new_value,
            "risks": risks,
            "can_execute": guard["can_execute"],
            "block_reason": guard["block_reason"],
        })
    _log(db, user, "批量调整预览", "推广计划", f"plan_ids={','.join(str(plan_id) for plan_id in plan_ids)}；字段={body.field}，幅度={body.change_pct}% ，计划数={len(plan_ids)}")
    return {
        "field": body.field,
        "change_pct": body.change_pct,
        "items": results,
        "count": len(results),
        "valid_count": sum(1 for item in results if item["ok"]),
    }


_SCENE_BIZ_CODES = {
    "wholesite": "onebpSite",
    "keyword": "onebpSearch",
    "crowd": "onebpDisplay",
    "content": "onebpShortVideo",
}


def _write_campaign_field(store: dict, row, field: str, value: float) -> dict:
    """写入万相台计划字段；调用客户端已验证的 campaign 批量接口。"""
    from backend.app.core.alimama import _run_json

    biz_code = _SCENE_BIZ_CODES.get(row["scene"])
    if not biz_code:
        raise HTTPException(status_code=400, detail="该计划场景暂不支持写入")
    campaign = {"campaignId": row["campaign_id"]}
    if field == "day_budget":
        campaign["dayBudget"] = round(value, 2)
        # batchUpdate 接口不会根据金额自动推断模式，缺少 dmcType 会返回
        # INVALID_PARAMETER「计划预算类型只能为日预算或不限预算」。
        # 优先使用同步保存的平台类型；老数据没有该列时按当前金额兜底。
        try:
            budget_type = str(row["budget_type"] or "").strip().lower()
        except (KeyError, IndexError):
            budget_type = ""
        if budget_type not in {"normal", "unlimited"}:
            budget_type = "unlimited" if round(value, 2) <= 0 else "normal"
        campaign["dmcType"] = budget_type
        path = f"/campaign/budget/batchUpdate.json?bizCode={biz_code}"
        body = {"bizCode": biz_code, "budgetList": [campaign]}
    elif field == "bid_value":
        campaign["constraintValue"] = round(value, 2)
        path = f"/campaign/bid/batchUpdate.json?bizCode={biz_code}"
        body = {"bizCode": biz_code, "bidList": [campaign]}
    else:
        raise HTTPException(status_code=400, detail="只支持调整日预算或出价")
    return _run_json(store, ["api", path, "--body", json.dumps(body, ensure_ascii=False)])


@router.post("/plans/{plan_id}/adjust")
def adjust_plan(
    plan_id: int,
    body: PlanAdjustIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """预检或真实写入单个计划的日预算/出价。"""
    if body.field not in ("day_budget", "bid_value"):
        raise HTTPException(status_code=400, detail="只支持调整日预算或出价")
    scope_frag, scope_params = _scope_filter(None, user)
    row = db.execute("SELECT * FROM promo_plans WHERE id = ?" + scope_frag, [plan_id] + scope_params).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="推广计划不存在")
    old_value = float(row[body.field] or 0)
    guard = _plan_execution_guard(db, user, row)
    if not body.execute:
        return {"ok": True, "execute": False, "plan_id": plan_id, "field": body.field, "old_value": old_value, "new_value": round(body.value, 2), **guard}
    if not guard["can_execute"]:
        raise HTTPException(status_code=409, detail=guard["block_reason"])
    store = db.execute("SELECT * FROM stores WHERE id = ?", (row["store_id"],)).fetchone()
    if not store or not has_profile(store["id"]):
        raise HTTPException(status_code=400, detail="该店铺未绑定万相台登录，无法操作")
    try:
        response = _write_campaign_field(dict(store), row, body.field, body.value)
    except AlimamaError as exc:
        raise HTTPException(status_code=502, detail=f"万相台操作失败：{exc}") from exc
    new_value = round(body.value, 2)
    executed_at = _now()
    due_at = (_parse_action_time(executed_at) + timedelta(hours=48)).isoformat(timespec="seconds")
    field_label = "日预算" if body.field == "day_budget" else "出价"
    increasing = new_value > old_value
    action_type = (
        ("增加预算/放量" if increasing else "降低预算/止损")
        if body.field == "day_budget"
        else ("提高出价" if increasing else "降低出价/控成本")
    )
    expected = "成交增长且 ROI 保持稳定" if increasing else "ROI 改善并减少无效花费"
    rollback_condition = (
        f"调整后 ROI 较当前下降超过 15% 时，将{field_label}恢复至 {old_value:g}"
        if increasing
        else f"成交明显下降且 ROI 未改善时，将{field_label}恢复至 {old_value:g}"
    )
    success_criteria = (
        {"target_roi_min": max(1, round(float(row["roi"] or 0) * 0.85, 2)), "sales_change_pct_min": 5}
        if increasing
        else {"roi_change_min": 0.1, "spend_change_pct_max": -5}
    )
    change_pct = round((new_value - old_value) / old_value * 100, 2) if old_value else None
    db.execute(
        f"UPDATE promo_plans SET {body.field} = ?, updated_at = ? WHERE id = ?" + scope_frag,
        [new_value, executed_at, plan_id] + scope_params,
    )
    action_cur = db.execute(
        "INSERT INTO promo_action_records "
        "(user_id, username, store_id, plan_id, action_type, description, before_value, after_value, before_spend, before_sales, before_roi, expected, observation_hours, status, executed_at, observation_due_at, data_quality, created_at, success_criteria, rollback_condition, change_pct, platform_status, platform_submitted_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 48, 'observing', ?, ?, ?, ?, ?, ?, ?, 'submitted', ?)",
        (
            user["id"], user["username"], row["store_id"], row["id"], action_type,
            f"万相台{field_label}从 {old_value:g} 调整为 {new_value:g}", old_value, new_value,
            float(row["spend"] or 0), float(row["sales"] or 0), float(row["roi"] or 0), expected,
            executed_at, due_at, "计划操作前快照", executed_at,
            json.dumps(success_criteria, ensure_ascii=False), rollback_condition, change_pct, executed_at,
        ),
    )
    _log(db, user, "计划参数调整", row["plan_name"], f"plan_id={plan_id}；{body.field} {old_value} → {new_value}")
    return {
        "ok": True,
        "execute": True,
        "plan_id": plan_id,
        "field": body.field,
        "old_value": old_value,
        "new_value": new_value,
        "action_id": action_cur.lastrowid,
        "observation_hours": 48,
        "response": str(response)[:300],
        "can_execute": True,
        "block_reason": "",
    }


@router.post("/plans/batch-adjust")
def adjust_plans_batch(
    body: PlanBatchAdjustIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """按百分比批量写入预算/出价；默认只预检，execute=true 才触发平台写入。"""
    if body.field not in ("day_budget", "bid_value"):
        raise HTTPException(status_code=400, detail="只支持调整日预算或出价")
    if not -90 <= body.change_pct <= 300:
        raise HTTPException(status_code=400, detail="调整幅度需在 -90% 到 300% 之间")
    if not body.plan_ids or len(body.plan_ids) > 50:
        raise HTTPException(status_code=400, detail="至少选择一个计划，单次最多 50 个")
    results = []
    for plan_id in dict.fromkeys(body.plan_ids):
        try:
            scope_frag, scope_params = _scope_filter(None, user)
            row = db.execute("SELECT * FROM promo_plans WHERE id = ?" + scope_frag, [plan_id] + scope_params).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="推广计划不存在或无权访问")
            old_value = float(row[body.field] or 0)
            new_value = (
                round(body.target_value, 2)
                if body.target_value is not None and len(dict.fromkeys(body.plan_ids)) == 1
                else round(max(0, old_value * (1 + body.change_pct / 100)), 2)
            )
            guard = _plan_execution_guard(db, user, row)
            if body.execute:
                if not guard["can_execute"]:
                    raise HTTPException(status_code=409, detail=guard["block_reason"])
                store = db.execute("SELECT * FROM stores WHERE id = ?", (row["store_id"],)).fetchone()
                if not store or not has_profile(store["id"]):
                    raise HTTPException(status_code=400, detail="店铺未绑定万相台登录")
                _write_campaign_field(dict(store), row, body.field, new_value)
                db.execute(f"UPDATE promo_plans SET {body.field} = ?, updated_at = ? WHERE id = ?" + scope_frag, [new_value, _now(), plan_id] + scope_params)
                _log(db, user, "批量计划参数调整", row["plan_name"], f"plan_id={plan_id}；{body.field} {old_value} → {new_value}")
            results.append({"plan_id": plan_id, "plan_name": row["plan_name"], "ok": True, "old_value": old_value, "new_value": new_value, "can_execute": guard["can_execute"], "block_reason": guard["block_reason"]})
        except HTTPException as exc:
            results.append({"plan_id": plan_id, "ok": False, "error": str(exc.detail)})
        except AlimamaError as exc:
            results.append({"plan_id": plan_id, "ok": False, "error": f"万相台操作失败：{exc}"})
        except Exception:
            results.append({"plan_id": plan_id, "ok": False, "error": "执行失败，请稍后重试"})
    return {"ok": sum(1 for item in results if item["ok"]), "total": len(results), "execute": body.execute, "field": body.field, "items": results}


@router.post("/plans/create")
def create_plan(
    body: PlanCreateIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """创建万相台计划。solution_list 为平台创建页生成的原始方案结构。"""
    from backend.app.core.alimama import _run_json

    if body.biz_code not in set(_SCENE_BIZ_CODES.values()):
        raise HTTPException(status_code=400, detail="不支持的推广场景")
    if not body.solution_list or len(body.solution_list) > 10:
        raise HTTPException(status_code=400, detail="至少需要一个方案，单次最多 10 个")
    stores = _bound_stores(db)
    visible = visible_store_ids(user)
    if visible is not None:
        stores = [store for store in stores if store["id"] in visible]
    if len(stores) != 1:
        raise HTTPException(status_code=400, detail="请先限定一个已绑定万相台登录的店铺")
    try:
        response = _run_json(
            stores[0],
            ["api", "/solution/addList.json", "--body", json.dumps({"bizCode": body.biz_code, "solutionList": body.solution_list}, ensure_ascii=False)],
        )
    except AlimamaError as exc:
        raise HTTPException(status_code=502, detail=f"万相台创建失败：{exc}") from exc
    _log(db, user, "新建推广计划", body.biz_code, f"方案数={len(body.solution_list)}")
    return {"ok": True, "biz_code": body.biz_code, "response": response}

@router.get("/plans/write-capabilities")
def promo_plan_write_capabilities(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """返回当前推广计划各类写操作的接入状态，不触发平台请求。"""
    return {
        "status": {"read": True, "write": True, "message": "支持计划暂停/开启"},
        "day_budget": {"read": True, "write": True, "message": "支持计划日预算写入"},
        "bid_value": {"read": True, "write": True, "message": "支持计划出价写入"},
        "create": {"read": False, "write": True, "message": "支持透传万相台 solutionList 新建计划"},
    }

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

@router.get("/plans/{plan_id}/funnel")
def plan_funnel(
    plan_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """返回计划详情 2.0 的投放链路数据；未接入的平台维度明确标记为 pending。"""
    scope_frag, scope_params = _scope_filter(None, user)
    row = db.execute(
        "SELECT * FROM promo_plans WHERE id = ?" + scope_frag,
        [plan_id] + scope_params,
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="推广计划不存在")
    item = db.execute(
        "SELECT item_id, item_title, image FROM promo_plan_items WHERE store_id = ? AND campaign_id = ?",
        (row["store_id"], row["campaign_id"]),
    ).fetchone()
    stats = db.execute(
        "SELECT mode, spend, sales, roi, clicks FROM promo_plan_stats WHERE store_id = ? AND campaign_id = ? ORDER BY CASE mode WHEN 'realtime' THEN 0 WHEN 'yesterday' THEN 1 ELSE 2 END",
        (row["store_id"], row["campaign_id"]),
    ).fetchall()
    return {
        "plan": {"id": row["id"], "plan_name": row["plan_name"], "campaign_id": row["campaign_id"], "scene_name": row["scene_name"], "status": row["status"]},
        "item": dict(item) if item else None,
        "metrics": [
            {"mode": stat["mode"], "spend": round(stat["spend"] or 0, 2), "sales": round(stat["sales"] or 0, 2), "roi": round(stat["roi"] or 0, 2), "clicks": int(stat["clicks"] or 0)}
            for stat in stats
        ],
        "links": [
            {"type": "item", "label": "商品", "status": "ready" if item else "empty"},
            {"type": "keyword", "label": "关键词", "status": "pending"},
            {"type": "crowd", "label": "人群", "status": "pending"},
            {"type": "creative", "label": "素材", "status": "pending"},
        ],
        "timeline": [
            {
                "kind": "operation",
                "action": log["action"],
                "detail": log["detail"],
                "username": log["username"],
                "created_at": log["created_at"],
            }
            for log in db.execute(
                "SELECT action, detail, username, created_at FROM op_logs WHERE module = 'promotions' AND (detail LIKE ? OR target_name LIKE ?) ORDER BY id DESC LIMIT 20",
                (f"%plan_id={plan_id}%", f"%{row['campaign_id']}%"),
            ).fetchall()
        ],
    }
