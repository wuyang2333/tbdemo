from datetime import datetime, timezone

import pytest

from backend.app.api.promotions.learning import learn_strategy_weights


NOW = datetime(2026, 8, 27, tzinfo=timezone.utc)


def test_learning_weights_verified_results_human_signals_and_recency():
    result = learn_strategy_weights(
        [
            {"strategy_id": 1, "feedback_status": "adopted", "updated_at": "2026-08-26T00:00:00Z"},
            {"strategy_id": 1, "feedback_status": "rejected", "updated_at": "2025-08-27T00:00:00Z"},
            {"strategy_id": 2, "feedback_status": "modified", "updated_at": "2026-08-26T00:00:00Z"},
        ],
        [
            {"strategy_id": 1, "status": "success", "confidence": "high", "verified_at": "2026-08-26T00:00:00Z"},
            {"strategy_id": 2, "status": "failed", "confidence": "high", "verified_at": "2026-08-26T00:00:00Z"},
            {"strategy_id": 2, "status": "success", "confidence": "high", "interference_notes": "大促干扰", "verified_at": "2026-08-26T00:00:00Z"},
        ],
        now=NOW,
    )

    first, second = result["strategy_weights"]
    assert first["strategy_id"] == 1
    assert first["weight"] > 1
    assert second["strategy_id"] == 2
    assert second["weight"] < 1
    assert first["rejected_count"] == 1
    assert "样本保护系数" in first["explanation"]


def test_learning_protects_minimum_sample_and_ignores_unverified_records():
    result = learn_strategy_weights(
        [],
        [
            {"strategy_id": 9, "status": "success", "confidence": "high", "verified_at": "2026-08-27T00:00:00Z"},
            {"strategy_id": 10, "status": "observing", "confidence": "high"},
            {"status": "success", "confidence": "high"},
        ],
        now=NOW,
        min_samples=4,
    )

    item = result["strategy_weights"][0]
    assert item["strategy_id"] == 9
    assert item["raw_weight"] == 1.25
    assert item["sample_protection"] == 0.25
    assert item["weight"] == 1.0625
    assert result["summary"]["ignored"] == {
        "decisions_without_strategy": 0,
        "actions_without_strategy": 1,
        "unverified_actions": 1,
    }


def test_learning_validates_parameters():
    with pytest.raises(ValueError, match="min_samples"):
        learn_strategy_weights([], [], min_samples=0)
    with pytest.raises(ValueError, match="decay_days"):
        learn_strategy_weights([], [], decay_days=0)
