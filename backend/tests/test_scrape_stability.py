import pytest

from backend.app.core.sycm import SycmError, _parse_day_overview, _parse_live_overview
from backend.app.main import _sync_result_error


def _metric(value):
    return {"value": value}


def test_live_overview_requires_core_metrics():
    payload = {"content": {"code": 0, "data": {"data": {"today": {"uv": _metric(1)}}}}}

    with pytest.raises(SycmError, match="接口结构已变化"):
        _parse_live_overview(payload)


def test_day_overview_requires_core_metrics():
    payload = {"content": {"code": 0, "data": {"self": {"payAmt": _metric(10)}}}}

    with pytest.raises(SycmError, match="接口结构已变化"):
        _parse_day_overview(payload)


def test_partial_sync_result_becomes_error():
    result = {
        "total": 2,
        "ok": 1,
        "results": [
            {"store_name": "店铺甲", "ok": True},
            {"store_name": "店铺乙", "ok": False, "error": "登录过期"},
        ],
    }

    assert _sync_result_error(result) == "成功 1/2（店铺乙: 登录过期）"
    assert _sync_result_error({"total": 2, "ok": 2, "results": []}) is None
