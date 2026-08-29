"""推广策略学习评分。

本模块只读取已经记录的决策和验证结果，不产生或补全业务数据。调用方可把
``strategy_weights`` 传给 AI 决策提示词，用作策略排序的可解释先验。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from math import exp
from typing import Any


DEFAULT_MIN_SAMPLES = 3
DEFAULT_DECAY_DAYS = 180

_OUTCOME_WEIGHTS = {"success": 1.25, "partial": 0.85, "failed": 0.45}
_CONFIDENCE_WEIGHTS = {"high": 1.0, "medium": 0.7, "low": 0.25}
_FEEDBACK_WEIGHTS = {"adopted": 1.1, "modified": 0.75, "rejected": 0.15}


def _as_dict(record: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Accept sqlite rows and mappings without making persistence assumptions."""
    return dict(record)


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def _recency_weight(value: object, now: datetime, decay_days: int) -> float:
    recorded_at = _as_datetime(value)
    if not recorded_at:
        return 0.5
    age_days = max(0.0, (now - recorded_at).total_seconds() / 86400)
    return exp(-age_days / max(1, decay_days))


def _strategy_key(record: Mapping[str, Any]) -> int | None:
    strategy_id = record.get("strategy_id")
    if isinstance(strategy_id, bool):
        return None
    try:
        return int(strategy_id) if strategy_id is not None else None
    except (TypeError, ValueError):
        return None


def _round(value: float) -> float:
    return round(value, 4)


def learn_strategy_weights(
    decision_records: Iterable[Mapping[str, Any] | Any],
    action_records: Iterable[Mapping[str, Any] | Any],
    *,
    now: datetime | str | None = None,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    decay_days: int = DEFAULT_DECAY_DAYS,
) -> dict[str, Any]:
    """Calculate explainable strategy weights from persisted promotion records.

    A weight of ``1.0`` is neutral. Sparse evidence is shrunk toward neutral so
    an isolated action or a single manual response cannot dominate AI advice.
    Only records carrying a real ``strategy_id`` take part in learning.
    """
    if min_samples < 1:
        raise ValueError("min_samples must be at least 1")
    if decay_days < 1:
        raise ValueError("decay_days must be at least 1")

    reference_time = _as_datetime(now) if now is not None else datetime.now(timezone.utc)
    if reference_time is None:
        raise ValueError("now must be an ISO datetime string or datetime")

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    ignored = {"decisions_without_strategy": 0, "actions_without_strategy": 0, "unverified_actions": 0}

    for raw_record in decision_records:
        record = _as_dict(raw_record)
        strategy_id = _strategy_key(record)
        if strategy_id is None:
            ignored["decisions_without_strategy"] += 1
            continue
        feedback = str(record.get("feedback_status") or "").lower()
        if feedback not in _FEEDBACK_WEIGHTS:
            continue
        recency = _recency_weight(record.get("updated_at") or record.get("created_at"), reference_time, decay_days)
        grouped[strategy_id].append(
            {
                "kind": "human_feedback",
                "value": _FEEDBACK_WEIGHTS[feedback],
                "weight": recency,
                "feedback": feedback,
                "recency": recency,
            }
        )

    for raw_record in action_records:
        record = _as_dict(raw_record)
        strategy_id = _strategy_key(record)
        if strategy_id is None:
            ignored["actions_without_strategy"] += 1
            continue
        outcome = str(record.get("status") or "").lower()
        if outcome not in _OUTCOME_WEIGHTS:
            ignored["unverified_actions"] += 1
            continue
        confidence = str(record.get("confidence") or "low").lower()
        confidence_weight = _CONFIDENCE_WEIGHTS.get(confidence, _CONFIDENCE_WEIGHTS["low"])
        interfered = bool((record.get("interference_notes") or "").strip())
        if interfered:
            confidence_weight *= 0.5
        baseline_days = record.get("baseline_days")
        after_days = record.get("after_days")
        sparse_window = (
            (baseline_days is not None and int(baseline_days or 0) < 2)
            or (after_days is not None and int(after_days or 0) < 2)
        )
        if sparse_window:
            confidence_weight *= 0.6
        manual_conclusion = str(record.get("manual_conclusion") or "").strip().lower()
        outcome_weight = _OUTCOME_WEIGHTS[outcome]
        if manual_conclusion in {"failed", "失败", "无效"}:
            outcome_weight = min(outcome_weight, _OUTCOME_WEIGHTS["failed"])
        elif manual_conclusion in {"success", "成功", "有效"}:
            outcome_weight = max(outcome_weight, _OUTCOME_WEIGHTS["success"])
        recency = _recency_weight(record.get("verified_at") or record.get("executed_at") or record.get("created_at"), reference_time, decay_days)
        quality_adjusted_outcome = 1.0 + (outcome_weight - 1.0) * confidence_weight
        grouped[strategy_id].append(
            {
                "kind": "verified_result",
                "value": quality_adjusted_outcome,
                "weight": confidence_weight * recency,
                "outcome": outcome,
                "confidence": confidence,
                "recency": recency,
                "interfered": interfered,
                "sparse_window": sparse_window,
            }
        )

    strategy_weights: list[dict[str, Any]] = []
    for strategy_id, evidence in grouped.items():
        result_events = [item for item in evidence if item["kind"] == "verified_result"]
        feedback_events = [item for item in evidence if item["kind"] == "human_feedback"]
        total_weight = sum(item["weight"] for item in evidence)
        raw_weight = sum(item["value"] * item["weight"] for item in evidence) / total_weight if total_weight else 1.0
        sample_count = len(evidence)
        sample_protection = min(1.0, sample_count / min_samples)
        learned_weight = 1.0 + (raw_weight - 1.0) * sample_protection
        successes = sum(item.get("outcome") == "success" for item in result_events)
        rejected = sum(item.get("feedback") == "rejected" for item in feedback_events)
        modified = sum(item.get("feedback") == "modified" for item in feedback_events)
        interfered_count = sum(bool(item.get("interfered")) for item in result_events)
        low_confidence_count = sum(item.get("confidence") == "low" for item in result_events)
        sparse_window_count = sum(bool(item.get("sparse_window")) for item in result_events)
        explanation = (
            f"{sample_count} 条证据（{len(result_events)} 条已验证结果、{len(feedback_events)} 条人工反馈）；"
            f"结果成功 {successes} 条，人工拒绝 {rejected} 条、修改 {modified} 条；"
            f"干扰样本 {interfered_count} 条、低可信 {low_confidence_count} 条、观察窗稀疏 {sparse_window_count} 条；"
            f"这些证据已降权，加权原始评分 {_round(raw_weight)}，样本保护系数 {_round(sample_protection)}。"
        )
        strategy_weights.append(
            {
                "strategy_id": strategy_id,
                "weight": _round(learned_weight),
                "raw_weight": _round(raw_weight),
                "sample_count": sample_count,
                "min_samples": min_samples,
                "sample_protection": _round(sample_protection),
                "verified_result_count": len(result_events),
                "human_feedback_count": len(feedback_events),
                "success_count": successes,
                "rejected_count": rejected,
                "modified_count": modified,
                "interfered_count": interfered_count,
                "low_confidence_count": low_confidence_count,
                "sparse_window_count": sparse_window_count,
                "explanation": explanation,
            }
        )
    strategy_weights.sort(key=lambda item: (-item["weight"], -item["sample_count"], item["strategy_id"]))
    return {
        "strategy_weights": strategy_weights,
        "summary": {
            "strategy_count": len(strategy_weights),
            "evidence_count": sum(item["sample_count"] for item in strategy_weights),
            "min_samples": min_samples,
            "decay_days": decay_days,
            "reference_time": reference_time.isoformat(),
            "ignored": ignored,
        },
    }
