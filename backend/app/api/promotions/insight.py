"""推广管理：AI 解读与计划 AI 分析。"""

from __future__ import annotations

import json
import re
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
    _build_promo_drafts,
    _lookup_item_image,
    _refresh_plan_items,
    PlanStatusIn,
    PlanChatIn,
    PlanChatBody,
    _ensure_plan_daily,
    _collect_plan_data,
    _build_plan_prompt,
)
from .channel import channel_for_scene, channel_name

router = APIRouter()


def _parse_ai_decisions(reply: str) -> dict[int, dict]:
    """Parse guarded plan decisions from a model response.

    The execution draft still applies deterministic safety boundaries, so a
    malformed or over-confident model response can never become an action by
    itself.
    """
    candidate = (reply or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.S | re.I)
    if fenced:
        candidate = fenced.group(1)
    else:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            candidate = candidate[start : end + 1]
    try:
        payload = json.loads(candidate)
    except (TypeError, ValueError):
        return {}
    rows = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return {}
    result: dict[int, dict] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        try:
            plan_id = int(raw.get("plan_id"))
        except (TypeError, ValueError):
            continue
        decision = str(raw.get("decision") or "证据不足")
        if decision not in {"建议干预", "建议观察", "证据不足"}:
            decision = "证据不足"
        confidence = str(raw.get("confidence") or "低")
        if confidence not in {"高", "中", "低"}:
            confidence = "低"
        try:
            change_pct = abs(float(raw.get("change_pct") or 0))
        except (TypeError, ValueError):
            change_pct = 0.0
        try:
            observation_hours = max(24, min(168, int(raw.get("observation_hours") or 48)))
        except (TypeError, ValueError):
            observation_hours = 48
        result[plan_id] = {
            "decision": decision,
            "primary_cause": str(raw.get("primary_cause") or "").strip(),
            "affected_stage": str(raw.get("affected_stage") or "").strip(),
            "recommended_variable": str(raw.get("recommended_variable") or "").strip(),
            "recommended_direction": str(raw.get("recommended_direction") or "").strip(),
            "change_pct": min(30.0, change_pct),
            "observation_hours": observation_hours,
            "confidence": confidence,
            "evidence": [str(item).strip() for item in raw.get("evidence", []) if str(item).strip()][:5] if isinstance(raw.get("evidence"), list) else [],
            "missing_data": [str(item).strip() for item in raw.get("missing_data", []) if str(item).strip()][:5] if isinstance(raw.get("missing_data"), list) else [],
            "success_criteria": [str(item).strip() for item in raw.get("success_criteria", []) if str(item).strip()][:4] if isinstance(raw.get("success_criteria"), list) else [],
            "rollback_condition": str(raw.get("rollback_condition") or "").strip(),
            "next_step": str(raw.get("next_step") or "").strip(),
        }
    return result


def _build_ai_decision_prompt(data: dict) -> str:
    """Build the actual decision prompt rather than a generic report prompt."""
    candidates = []
    focus_plan_id = data.get("focus_plan_id")
    for plan in data.get("plans", []):
        findings = plan.get("diagnostic_findings") or []
        if not findings and int(plan.get("id") or 0) != int(focus_plan_id or 0):
            continue
        candidates.append({
            "plan_id": plan.get("id"),
            "plan_name": plan.get("plan_name"),
            "campaign_id": plan.get("campaign_id"),
            "scene_name": plan.get("scene_name"),
            "status": plan.get("status"),
            "day_budget": plan.get("day_budget"),
            "bid_value": plan.get("bid_value"),
            "current": {
                "spend": plan.get("spend"),
                "sales": plan.get("sales"),
                "roi": plan.get("roi"),
                "clicks": plan.get("clicks"),
                "updated_at": plan.get("stats_updated_at"),
            },
            "comparison": {
                "scope": plan.get("prev_scope"),
                "spend": plan.get("prev_spend"),
                "sales": plan.get("prev_sales"),
                "roi": plan.get("prev_roi"),
                "clicks": plan.get("prev_clicks"),
            },
            "diagnostics": [
                {
                    "rule_code": item.get("rule_code"),
                    "signal_type": item.get("signal_type"),
                    "severity": item.get("severity"),
                    "title": item.get("title"),
                    "summary": item.get("summary"),
                    "confidence": item.get("confidence"),
                    "evidence": item.get("evidence") or [],
                    "possible_causes": item.get("possible_causes") or [],
                    "unknown_dimensions": item.get("unknown_dimensions") or [],
                }
                for item in findings
            ],
            "recent_daily": plan.get("recent_daily") or [],
            "recent_actions": plan.get("recent_actions") or [],
        })
    context = json.dumps({"mode": "realtime", "plans": candidates}, ensure_ascii=False, separators=(",", ":"))
    return (
        "你是淘宝推广决策分析师。你的任务不是写经营报告，而是针对诊断中心已经发现的问题，判断是否需要调整。"
        "必须先区分事实、推测和缺失信息。诊断规则命中不等于根因成立；没有风险异常、数据过期、样本不足、对比口径不一致时，不得生成可执行调整。"
        "只允许为一个计划选择一个投放变量；不得同时改预算、出价、人群或素材。预算是消耗上限，不得仅因为ROI高就建议增加预算。"
        "如果异常更像商品承接、归因延迟、计划资格或投放状态问题，应选择建议观察或证据不足，并把排查动作写入next_step。"
        "change_pct只填写建议幅度的绝对值，范围0到30；没有充分证据时填写0。recommended_variable只能填写day_budget、bid_value或不调整。"
        "严格返回JSON，不要Markdown：{\"decisions\":[{\"plan_id\":1,\"decision\":\"建议干预/建议观察/证据不足\",\"primary_cause\":\"最可能原因，不能确定则留空\",\"affected_stage\":\"数据质量/流量/点击/转化/成本/预算/商品承接\",\"recommended_variable\":\"day_budget/bid_value/不调整\",\"recommended_direction\":\"提高/降低/不调整\",\"change_pct\":0,\"confidence\":\"高/中/低\",\"evidence\":[\"事实\"],\"missing_data\":[\"缺失信息\"],\"observation_hours\":48,\"success_criteria\":[\"可验证标准\"],\"rollback_condition\":\"回滚条件\",\"next_step\":\"下一步\"}]}。\n\n"
        f"当前可用事实：{context}"
    )


def _decision_sections(decisions: dict[int, dict]) -> dict:
    if not decisions:
        return {"overall": "模型没有返回可识别的计划判断，本次不会生成可执行调整。", "suggestions": ["请补齐诊断数据后重新生成。"]}
    interventions = [item for item in decisions.values() if item.get("decision") == "建议干预"]
    observations = [item for item in decisions.values() if item.get("decision") == "建议观察"]
    insufficient = [item for item in decisions.values() if item.get("decision") == "证据不足"]
    return {
        "overall": f"本次复核 {len(decisions)} 个计划：建议干预 {len(interventions)} 个、继续观察 {len(observations)} 个、证据不足 {len(insufficient)} 个。",
        "risks": [item["primary_cause"] for item in decisions.values() if item.get("primary_cause")],
        "suggestions": [item["next_step"] for item in decisions.values() if item.get("next_step")],
    }


def _decision_confidence(draft: dict) -> tuple[str, str]:
    """Return an explainable confidence label without changing old draft rules."""
    decision_confidence = draft.get("decision_confidence")
    if decision_confidence in {"high", "medium", "low"}:
        diagnostic_confidence = draft.get("diagnostic_confidence") or "unknown"
        return decision_confidence, f"AI 判断为 {decision_confidence}，诊断证据置信度为 {diagnostic_confidence}；执行仍受规则边界保护"
    evidence_score = int(draft.get("strategy_score") or 0)
    strategy_samples = max(
        (int(item.get("sample_count") or 0) for item in draft.get("strategy_candidates") or []),
        default=0,
    )
    learning_samples = int(draft.get("learning_sample_count") or 0)
    sample_count = max(strategy_samples, learning_samples)
    if draft.get("strategy_conflict") or draft.get("constraint_summary"):
        return "low", "历史证据存在冲突或业务约束，需人工确认后再执行"
    if evidence_score >= 75 and sample_count >= 3:
        return "high", f"证据分 {evidence_score}，并有 {sample_count} 条同类或反馈样本"
    if evidence_score >= 50 and sample_count >= 2:
        return "medium", f"证据分 {evidence_score}，当前有效样本 {sample_count} 条"
    return "low", "历史样本不足，当前方案主要依据本期计划指标生成"


def _prediction_range(plan: dict, option: dict) -> dict:
    """Build a conservative rule-based range; this is not a model forecast."""
    spend = max(0.0, float(plan.get("spend") or 0))
    sales = max(0.0, float(plan.get("sales") or 0))
    roi = max(0.0, float(plan.get("roi") or (sales / spend if spend else 0)))
    change = float(option.get("change_pct") or 0) / 100
    tier = str(option.get("tier") or "conservative")
    uncertainty = {"conservative": 0.08, "balanced": 0.12, "aggressive": 0.18}.get(tier, 0.12)
    # Budget/bid changes rarely translate one-for-one into spend. Use a broad,
    # directionally useful response band and expose it as an estimate in the API.
    response_low, response_high = ((0.35, 0.8) if change >= 0 else (0.65, 1.0))
    spend_changes = sorted((change * response_low, change * response_high))
    spend_low = max(0.0, spend * (1 + spend_changes[0]))
    spend_high = max(spend_low, spend * (1 + spend_changes[1]))
    if change >= 0:
        roi_center = roi * (1 - min(0.25, abs(change) * 0.45))
    else:
        roi_center = roi * (1 + min(0.2, abs(change) * 0.3))
    roi_low = max(0.0, roi_center * (1 - uncertainty))
    roi_high = max(roi_low, roi_center * (1 + uncertainty))
    sales_low = spend_low * roi_low
    sales_high = spend_high * roi_high
    return {
        "basis": "按当前同口径周期指标与调整响应系数估算，不代表平台承诺",
        "spend_low": round(spend_low, 2),
        "spend_high": round(spend_high, 2),
        "sales_low": round(sales_low, 2),
        "sales_high": round(sales_high, 2),
        "roi_low": round(roi_low, 2),
        "roi_high": round(roi_high, 2),
    }


def _enrich_decision_drafts(drafts: list[dict], plans: list[dict] | None = None) -> list[dict]:
    """Add decision context for new clients while keeping old draft fields intact."""
    enriched: list[dict] = []
    plan_by_id = {int(plan["id"]): plan for plan in (plans or []) if plan.get("id") is not None}
    for raw_draft in drafts:
        draft = dict(raw_draft)
        plan = plan_by_id.get(int(draft.get("plan_id") or 0), draft)
        channel = channel_for_scene(draft.get("scene"), draft.get("scene_name"))
        confidence, confidence_reason = _decision_confidence(draft)
        sample_count = max(
            int(draft.get("learning_sample_count") or 0),
            max((int(item.get("sample_count") or 0) for item in draft.get("strategy_candidates") or []), default=0),
        )
        max_change_pct = {"high": 30, "medium": 15, "low": 10}[confidence]
        options = []
        for raw_option in draft.get("options") or []:
            option = dict(raw_option)
            option["prediction"] = _prediction_range(plan, option)
            option["max_change_pct"] = max_change_pct
            option["within_boundary"] = abs(float(option.get("change_pct") or 0)) <= max_change_pct
            options.append(option)
        draft["options"] = options
        selected = next(
            (item for item in options if item.get("tier") == draft.get("recommended_tier")),
            {},
        )
        evidence_items = [
            f"当前计划：{draft.get('reason') or '暂无指标说明'}",
            f"历史经验：{selected.get('evidence_summary') or '暂无完全匹配的历史策略'}",
            f"样本保护：{confidence_reason}",
        ]
        if draft.get("learning_explanation"):
            evidence_items.append(f"学习记录：{draft['learning_explanation']}")
        evidence_score = int(draft.get("strategy_score") or 0)
        learning_weight = float(draft.get("learning_weight") or 1)
        sample_adequate = sample_count >= 2 and evidence_score >= 50
        target_conflicts: list[str] = []
        if "增加" in str(draft.get("action_type") or ""):
            target_conflicts.append("放量会同时追求成交增长与 ROI 稳定，两项目标存在边际效率冲突")
        if "降低" in str(draft.get("action_type") or ""):
            target_conflicts.append("控成本可能减少成交规模，需要以回退条件保护销量")
        if draft.get("strategy_conflict"):
            target_conflicts.append("同类历史验证同时存在成功和失败结果")
        if draft.get("constraint_summary"):
            target_conflicts.append("历史人工拒绝记录与本次调整方向存在业务目标冲突")
        not_recommended_reason = str(draft.get("not_recommended_reason") or "")
        engine_actionable = draft.get("engine_actionable")
        if float(selected.get("old_value") or 0) <= 0:
            not_recommended_reason = "当前调整字段没有可用原值，不建议直接执行；请先同步平台计划配置"
        elif engine_actionable is False:
            not_recommended_reason = not_recommended_reason or "当前数据或诊断证据不足，不建议直接调整"
        elif draft.get("strategy_conflict"):
            not_recommended_reason = "成功与失败历史证据冲突，不建议调整；请先补充同类验证样本"
        elif draft.get("constraint_summary"):
            not_recommended_reason = "存在重复人工拒绝约束，不建议调整；请先确认利润、库存或活动条件"
        elif engine_actionable is None and not sample_adequate:
            not_recommended_reason = f"历史证据不足（需要至少 2 条样本且证据分不低于 50；当前 {sample_count} 条、{evidence_score} 分），不建议调整"
        elif learning_weight < 0.75:
            not_recommended_reason = f"历史验证权重仅 {learning_weight:.2f}，结果偏负向，不建议调整"
        actionable = bool(engine_actionable) if engine_actionable is not None else not not_recommended_reason
        actionable = actionable and not bool(not_recommended_reason)
        missing_data = list(draft.get("missing_data") or [])
        if not sample_adequate and engine_actionable is None:
            missing_data.append("至少 2 条同类历史验证，且证据分达到 50")
        if float(selected.get("old_value") or 0) <= 0:
            missing_data.append("平台当前预算或出价原值")
        if "排查投放" in str(draft.get("action_type") or "") or "恢复消耗" in str(draft.get("action_type") or ""):
            missing_data.extend(["计划实际展现、点击与成交明细", "计划状态、定向、商品资格和出价是否正常"])
        if draft.get("constraint_summary"):
            missing_data.append("利润、库存或活动限制的人工确认")
        prediction = selected.get("prediction") or {}
        if not actionable and ("排查投放" in str(draft.get("action_type") or "") or "恢复消耗" in str(draft.get("action_type") or "")):
            why_not_operate = f"当前先做投放排查，不把预算或出价变化当成解决方案：{not_recommended_reason}"
            review_timing = "补齐计划状态、展现、点击和成交数据后立即复查；若确认可投但仍无量，再观察 24–48 小时"
            recovery_action = "先核查计划状态、出价、定向与商品资格，补齐数据后重新生成 AI 决策"
        else:
            why_not_operate = not_recommended_reason or "当前证据达到最低门槛，但仍需人工确认利润、库存和活动情况。"
            review_timing = f"执行后观察 {int(selected.get('observation_hours') or 48)} 小时，到期同步日报并复查 ROI、成交和花费。"
            recovery_action = "补齐上述数据后重新生成 AI 决策" if not actionable else "确认经营限制后进入执行预览"
        operating_explanation = {
            "why_recommended": f"{draft.get('reason') or '当前计划指标触发了调整规则'}；AI 建议干预，系统已把动作限制为一个变量并校验最大幅度。" if actionable else "当前只形成观察或证据不足结论，不形成执行建议。",
            "why_not_operate": why_not_operate,
            "safe_range": f"单次调整不超过 {max_change_pct}%；当前方案 {float(selected.get('change_pct') or 0):+.1f}%。",
            "worst_case": f"按规则估算，最差情况下同口径周期成交约 {float(prediction.get('sales_low') or 0):.2f} 元、ROI 约 {float(prediction.get('roi_low') or 0):.2f}；触发回退条件时恢复原值。",
            "review_timing": review_timing,
            "missing_data": missing_data,
            "recovery_action": draft.get("next_step") or recovery_action,
        }
        draft.update(
            {
                "channel": channel,
                "channel_name": channel_name(channel),
                "confidence": confidence,
                "confidence_reason": confidence_reason,
                "sample_count": sample_count,
                "minimum_sample_count": 2,
                "minimum_evidence_score": 50,
                "sample_adequate": sample_adequate,
                "historical_validation_weight": round(learning_weight, 4),
                "max_change_pct": max_change_pct,
                "target_conflicts": target_conflicts,
                "actionable": actionable,
                "operating_explanation": operating_explanation,
                "evidence_items": evidence_items,
                "risk_boundary": f"风险：{selected.get('risk') or draft.get('risk') or '待人工确认'}；回退：{selected.get('rollback_condition') or draft.get('rollback_condition') or '待补充'}",
                "not_recommended_reason": not_recommended_reason,
            }
        )
        enriched.append(draft)
    return enriched

@router.post("/insight")
def promo_ai_insight(
    mode: str = "realtime",
    store_id: int | None = None,
    channel: str = "",
    plan_id: int | None = None,
    diagnostic_id: str = "",
    diagnostic: str = "",
    rule: str = "",
    evidence: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """AI 推广解读：基于计划/场景数据给出投放优化建议。"""
    from backend.app.api.model_configs import get_default_config
    from backend.app.core.ai_client import AIError, chat_completion
    from .diagnostics import detect_promotion_anomalies

    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    # 决策必须使用当前实时口径；近 7 天只作为趋势证据，不能拿汇总值
    # 直接和诊断中心的实时/昨日同小时信号混用。
    data = _promo_insight_data("realtime", db, user, store_id, plan_id)
    # 决策候选必须承接诊断中心的结果；ROI 只作为诊断证据，不能在这里再次定义待处理状态。
    diagnostic_data = detect_promotion_anomalies(db, user, store_id, channel)
    findings_by_plan: dict[int, list[dict]] = {}
    for finding in diagnostic_data.get("items", []):
        findings_by_plan.setdefault(int(finding.get("plan_id") or 0), []).append(finding)
    insufficient_rules = {"data_stale", "no_spend", "low_spend"}
    for plan in data.get("plans", []):
        if plan.get("status") != "在投":
            continue
        findings = findings_by_plan.get(int(plan.get("id") or 0), [])
        plan["diagnostic_findings"] = findings
        if any(finding.get("signal_type") == "risk" for finding in findings):
            plan["decision_status"] = "needs_decision"
            plan["decision_status_label"] = "待处理"
            plan["decision_reason"] = "诊断中心已标记风险异常，进入 AI 决策复核"
        elif any(finding.get("rule_code") in insufficient_rules for finding in findings):
            plan["decision_status"] = "insufficient"
            plan["decision_status_label"] = "证据不足"
            plan["decision_reason"] = "诊断中心标记为数据不足，暂不形成调整建议"
        else:
            plan["decision_status"] = "observe"
            plan["decision_status_label"] = "正常观察"
            plan["decision_reason"] = "诊断中心未发现风险异常，保持观察"
        if findings or (plan_id is not None and int(plan.get("id") or 0) == int(plan_id)):
            plan["recent_daily"] = [
                dict(row)
                for row in db.execute(
                    "SELECT data_date, spend, sales, roi, clicks FROM promo_plan_daily "
                    "WHERE store_id = ? AND campaign_id = ? ORDER BY data_date DESC LIMIT 7",
                    (int(plan["store_id"]), str(plan.get("campaign_id") or "")),
                ).fetchall()
            ]
            plan["recent_actions"] = [
                dict(row)
                for row in db.execute(
                    "SELECT action_type, description, before_value, after_value, change_pct, status, result, manual_conclusion, executed_at, verified_at "
                    "FROM promo_action_records WHERE store_id = ? AND plan_id = ? AND COALESCE(lifecycle_status, 'active') = 'active' "
                    "ORDER BY COALESCE(executed_at, created_at) DESC LIMIT 5",
                    (int(plan["store_id"]), int(plan["id"])),
                ).fetchall()
            ]
    active_plans = [plan for plan in data.get("plans", []) if plan.get("status") == "在投"]
    data["decision_count"] = sum(1 for plan in active_plans if plan.get("decision_status") == "needs_decision")
    data["observe_count"] = sum(1 for plan in active_plans if plan.get("decision_status") == "observe")
    data["insufficient_count"] = sum(1 for plan in active_plans if plan.get("decision_status") == "insufficient")
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": _build_ai_decision_prompt(data)}], timeout=120.0, max_tokens=2200)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    ai_decisions = _parse_ai_decisions(reply)
    drafts = _enrich_decision_drafts(_build_promo_drafts(data, ai_decisions), data.get("plans", []))
    if plan_id is not None:
        drafts = [draft for draft in drafts if int(draft.get("plan_id") or 0) == plan_id]
    try:
        evidence_payload = json.loads(evidence) if evidence else []
    except (TypeError, json.JSONDecodeError):
        evidence_payload = []
    if not isinstance(evidence_payload, list):
        evidence_payload = []
    source_context = {
        "store_id": store_id,
        "channel": channel,
        "plan_id": plan_id,
        "diagnostic_id": diagnostic_id,
        "diagnostic": diagnostic or rule,
        "rule": rule or diagnostic,
        "evidence": evidence_payload[:12],
    }
    return {
        "decision_id": f"promo-{datetime.now().strftime('%Y%m%d%H%M%S')}-{abs(hash(reply)) % 100000:05d}",
        "sections": _decision_sections(ai_decisions),
        "reply": reply,
        "drafts": drafts,
        "source_context": source_context,
        "recovery": {
            "can_retry": True,
            "action": "同步计划数据后重新生成" if plan_id is not None and not drafts else "复核方案后进入执行预览",
        },
        "strategies": data.get("strategies", []),
        "strategy_groups": data.get("strategy_groups", []),
        "learning_summary": data.get("learning", {}).get("summary", {}),
        "decision_constraints": list(data.get("decision_constraints", {}).values()),
        "mode": data["mode"],
        "decision_engine": {
            "version": "evidence_guarded_v2",
            "data_scope": "实时数据 + 昨日同小时 + 近7天趋势 + 最近动作 + 诊断证据",
            "model_judgment_count": len(ai_decisions),
            "guardrail": "AI负责原因与干预判断，规则负责数据门槛、允许变量和最大幅度",
        },
        "summary": {
            "total_spend": data["total_spend"],
            "total_sales": data["total_sales"],
            "total_roi": data["total_roi"],
            "active_count": data["active_count"],
            "high_count": data["high_count"],
            "mid_count": data["mid_count"],
            "low_count": data["low_count"],
            "decision_count": data.get("decision_count", data["low_count"]),
            "observe_count": data.get("observe_count", 0),
            "insufficient_count": data.get("insufficient_count", 0),
        },
    }

@router.post("/plans/{plan_id}/insight")
def plan_ai_insight(
    plan_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """单个推广计划的 AI 分析。"""
    from backend.app.api.analytics import _parse_insight_sections
    from backend.app.api.model_configs import get_default_config
    from backend.app.core.ai_client import AIError, chat_completion

    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    scope_frag, scope_params = _scope_filter(None, user)
    row = db.execute(
        "SELECT * FROM promo_plans WHERE id = ?" + scope_frag,
        [plan_id] + scope_params,
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="推广计划不存在")
    store = db.execute("SELECT * FROM stores WHERE id = ?", (row["store_id"],)).fetchone()
    if not store:
        raise HTTPException(status_code=400, detail="店铺不存在")
    data = _collect_plan_data(db, dict(store), dict(row), user)
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": _build_plan_prompt(data)}], timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "sections": _parse_insight_sections(reply),
        "reply": reply,
        "plan": {"id": row["id"], "plan_name": row["plan_name"], "campaign_id": row["campaign_id"], "scene_name": row["scene_name"]},
        "date": date_cls.today().isoformat(),
    }

@router.post("/plans/{plan_id}/insight/chat")
def plan_ai_insight_chat(
    plan_id: int,
    body: PlanChatBody,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """围绕单个计划的 AI 追问。"""
    from backend.app.api.model_configs import get_default_config
    from backend.app.core.ai_client import AIError, chat_completion

    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    scope_frag, scope_params = _scope_filter(None, user)
    row = db.execute(
        "SELECT * FROM promo_plans WHERE id = ?" + scope_frag,
        [plan_id] + scope_params,
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="推广计划不存在")
    store = db.execute("SELECT * FROM stores WHERE id = ?", (row["store_id"],)).fetchone()
    if not store:
        raise HTTPException(status_code=400, detail="店铺不存在")
    data = _collect_plan_data(db, dict(store), dict(row), user)
    context = (
        "你是淘宝万相台推广运营专家。以下是这个推广计划的数据上下文：\n"
        + "计划：%s（ID %s）\n" % (row["plan_name"], row["campaign_id"])
        + "\n".join(data["lines"])
        + "\n用户会围绕这个计划追问，请结合数据回答，简洁务实，不要编造；数据里没有的信息要如实说明。"
    )
    msgs = [{"role": "system", "content": context}]
    for m in body.messages:
        msgs.append({"role": m.role, "content": m.content})
    try:
        reply = chat_completion(cfg, msgs, timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"reply": reply}
