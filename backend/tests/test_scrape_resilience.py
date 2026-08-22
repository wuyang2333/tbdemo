from pathlib import Path

import pytest

from backend.app.core.scrape_resilience import (
    clear_login_circuit,
    ensure_login_available,
    reset_login_circuits,
    retry_with_backoff,
    trip_login_circuit,
)


class ExampleError(Exception):
    pass


@pytest.fixture(autouse=True)
def _reset_circuits():
    reset_login_circuits()
    yield
    reset_login_circuits()


def test_retry_with_backoff_retries_transient_errors(monkeypatch):
    attempts = []
    sleeps = []

    def operation():
        attempts.append(1)
        if len(attempts) < 3:
            raise ExampleError("请求超时，请稍后再试")
        return "ok"

    monkeypatch.setattr("backend.app.core.scrape_resilience.random.uniform", lambda _a, _b: 0)
    result = retry_with_backoff(operation, delays=(10, 30, 120), sleep=sleeps.append)

    assert result == "ok"
    assert len(attempts) == 3
    assert sleeps == [10, 30]


def test_retry_with_backoff_does_not_retry_login_errors():
    attempts = []

    def operation():
        attempts.append(1)
        raise ExampleError("登录已过期，请重新登录")

    with pytest.raises(ExampleError):
        retry_with_backoff(operation, delays=(0, 0), sleep=lambda _delay: None)
    assert len(attempts) == 1


def test_login_circuit_reopens_after_profile_changes(tmp_path: Path):
    profile = tmp_path / "store_1.json"
    profile.write_text("old", encoding="utf-8")
    trip_login_circuit("qianniu", 1, profile, "千牛登录已过期")

    with pytest.raises(ExampleError, match="已暂停自动抓取"):
        ensure_login_available("qianniu", 1, profile, ExampleError)

    profile.write_text("new-profile", encoding="utf-8")
    ensure_login_available("qianniu", 1, profile, ExampleError)
    clear_login_circuit("qianniu", 1)
