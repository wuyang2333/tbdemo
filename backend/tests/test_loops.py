from backend.app.core import loops


def test_loop_status_lifecycle():
    name = "test_loop"
    loops.register(name)
    loops.mark_running(name)
    status = loops.get_status(name)
    assert status["running"] is True
    assert status["last_started"] is not None

    loops.record_success(name, 1.5)
    status = loops.get_status(name)
    assert status["running"] is False
    assert status["success_count"] == 1
    assert status["last_duration"] == 1.5

    loops.record_error(name, RuntimeError("boom"), 2.0)
    status = loops.get_status(name)
    assert status["error_count"] == 1
    assert "boom" in status["last_error"]
