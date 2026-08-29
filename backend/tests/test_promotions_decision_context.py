from backend.app.api.promotions._common import _build_promo_drafts, _enrich_promo_strategies
from backend.app.api.promotions.insight import _enrich_decision_drafts, _parse_ai_decisions


def test_manual_pending_strategy_is_reference_only():
    items, groups = _enrich_promo_strategies(
        None,
        [
            {
                "id": 1,
                "source_action_id": None,
                "name": "人工经验",
                "action_type": "降低出价/控成本",
                "conditions": "ROI 低于 1.5 时参考",
                "evidence": "来自人工复盘",
                "outcome": "pending",
                "source_type": "manual",
                "verification_status": "pending",
                "scene": "关键词推广",
            }
        ],
    )

    assert items[0]["evidence_score"] == 0
    assert items[0]["evidence_level"] == "low"
    assert groups == []


def test_decision_context_explains_channel_evidence_and_execution_guard():
    result = _enrich_decision_drafts(
        [
            {
                "plan_id": 1,
                "scene_name": "关键词推广",
                "reason": "当前 ROI 2.50 达到健康线，可以验证边际增量。",
                "recommended_tier": "conservative",
                "strategy_score": 40,
                "learning_sample_count": 1,
                "learning_explanation": "仅有 1 条已验证结果",
                "strategy_candidates": [{"sample_count": 1}],
                "options": [
                    {
                        "tier": "conservative",
                        "old_value": 100,
                        "risk": "边际流量可能变差",
                        "rollback_condition": "ROI 跌破底线时回退",
                        "evidence_summary": "同类经验 1 次",
                    }
                ],
            }
        ]
    )[0]

    assert result["channel"] == "search"
    assert result["channel_name"] == "搜索推广"
    assert result["confidence"] == "low"
    assert result["sample_count"] == 1
    assert len(result["evidence_items"]) >= 3
    assert result["actionable"] is False
    assert result["sample_adequate"] is False
    assert "不建议调整" in result["not_recommended_reason"]
    assert "ROI 跌破底线时回退" in result["risk_boundary"]


def test_decision_context_adds_prediction_boundaries_and_allows_sufficient_evidence():
    result = _enrich_decision_drafts(
        [
            {
                "plan_id": 2,
                "scene_name": "全站推广",
                "action_type": "增加预算/放量",
                "reason": "ROI 达到健康线",
                "recommended_tier": "balanced",
                "strategy_score": 80,
                "learning_weight": 1.1,
                "learning_sample_count": 4,
                "strategy_candidates": [{"sample_count": 4}],
                "options": [
                    {
                        "tier": "balanced",
                        "old_value": 1000,
                        "change_pct": 15,
                        "risk": "边际流量变差",
                        "rollback_condition": "ROI 跌破 2.0 回退",
                        "evidence_summary": "4 条高质量样本",
                    },
                    {
                        "tier": "aggressive",
                        "old_value": 1000,
                        "change_pct": 35,
                        "risk": "边际流量变差",
                        "rollback_condition": "ROI 跌破 2.0 回退",
                        "evidence_summary": "4 条高质量样本",
                    },
                ],
            }
        ],
        [{"id": 2, "spend": 1000, "sales": 3000, "roi": 3}],
    )[0]

    assert result["actionable"] is True
    assert result["sample_adequate"] is True
    assert result["max_change_pct"] == 30
    assert result["options"][0]["within_boundary"] is True
    assert result["options"][1]["within_boundary"] is False
    assert result["options"][0]["prediction"] == {
        "basis": "按当前同口径周期指标与调整响应系数估算，不代表平台承诺",
        "spend_low": 1052.5,
        "spend_high": 1120.0,
        "sales_low": 2591.04,
        "sales_high": 3509.18,
        "roi_low": 2.46,
        "roi_high": 3.13,
    }
    assert result["target_conflicts"]
    assert result["operating_explanation"]["why_recommended"]
    assert "30%" in result["operating_explanation"]["safe_range"]
    assert result["operating_explanation"]["review_timing"]


def test_guarded_decision_uses_ai_judgment_but_caps_to_one_safe_variable():
    data = {
        "focus_plan_id": 7,
        "plans": [{
            "id": 7,
            "store_id": 1,
            "campaign_id": "P7",
            "plan_name": "低效计划",
            "scene_name": "全站推广",
            "status": "在投",
            "day_budget": 1000,
            "bid_value": 0,
            "spend": 300,
            "sales": 120,
            "roi": 0.4,
            "clicks": 80,
            "prev_scope": "same_hour",
            "decision_status": "needs_decision",
            "diagnostic_findings": [{
                "rule_code": "roi_low",
                "signal_type": "risk",
                "severity": "high",
                "confidence": "high",
                "title": "当前 ROI 低于健康阈值",
                "summary": "ROI 0.4 低于阈值",
                "evidence": [{"label": "当前 ROI", "current": 0.4, "baseline": 1.0, "unit": ""}],
            }],
        }],
        "strategies": [],
        "decision_constraints": {},
    }
    ai = {7: {
        "decision": "建议干预",
        "primary_cause": "当前流量成本与转化产出不匹配",
        "affected_stage": "成本",
        "recommended_variable": "day_budget",
        "recommended_direction": "降低",
        "change_pct": 30,
        "observation_hours": 48,
        "confidence": "高",
        "evidence": ["当前 ROI 仅 0.4"],
        "missing_data": ["商品毛利"],
        "success_criteria": ["ROI 回升"],
        "rollback_condition": "成交下降且 ROI 未改善时回滚",
        "next_step": "降低一个变量后观察 48 小时",
    }}

    result = _enrich_decision_drafts(_build_promo_drafts(data, ai), data["plans"])[0]

    assert result["actionable"] is True
    assert result["field"] == "day_budget"
    assert result["recommended_tier"] == "balanced"
    assert result["change_pct"] == -20
    assert result["new_value"] == 800
    assert {option["field"] for option in result["options"]} == {"day_budget"}
    assert max(abs(option["change_pct"]) for option in result["options"]) <= 20


def test_guarded_decision_does_not_adjust_a_plan_without_risk_diagnosis():
    data = {
        "focus_plan_id": 8,
        "plans": [{
            "id": 8,
            "store_id": 1,
            "campaign_id": "P8",
            "plan_name": "正常计划",
            "scene_name": "全站推广",
            "status": "在投",
            "day_budget": 1000,
            "bid_value": 0,
            "spend": 500,
            "sales": 1500,
            "roi": 3,
            "clicks": 100,
            "prev_scope": "same_hour",
            "decision_status": "observe",
            "diagnostic_findings": [],
        }],
        "strategies": [],
        "decision_constraints": {},
    }
    ai = {8: {
        "decision": "建议干预",
        "recommended_variable": "day_budget",
        "recommended_direction": "提高",
        "change_pct": 20,
        "confidence": "高",
    }}

    result = _enrich_decision_drafts(_build_promo_drafts(data, ai), data["plans"])[0]

    assert result["actionable"] is False
    assert result["change_pct"] == 0
    assert "没有发现风险异常" in result["not_recommended_reason"]


def test_parse_ai_decisions_rejects_unstructured_model_output():
    assert _parse_ai_decisions("建议直接加预算") == {}
    parsed = _parse_ai_decisions('{"decisions":[{"plan_id":9,"decision":"建议观察","confidence":"中","change_pct":99}]}')
    assert parsed[9]["decision"] == "建议观察"
    assert parsed[9]["change_pct"] == 30
