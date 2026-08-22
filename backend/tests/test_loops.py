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


def test_manual_retry_and_sync_history(client, admin_token, monkeypatch):
    from backend.app.api import stores

    monkeypatch.setattr(stores, "run_inspect_once", lambda: 1)
    headers = {"Authorization": f"Bearer {admin_token}"}
    retried = client.post("/api/system/loops/inspect/retry", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["ok"] is True

    history = client.get("/api/system/loops/history?name=inspect", headers=headers)
    assert history.status_code == 200
    assert history.json()["items"][0]["trigger"] == "manual"
    assert history.json()["items"][0]["status"] == "success"


def test_promo_daily_passes_database_by_keyword(monkeypatch):
    from backend.app import main

    calls = []

    class FakeConnection:
        def commit(self):
            pass

        def close(self):
            pass

    connection = FakeConnection()
    monkeypatch.setattr(main, "connect_db", lambda: connection)
    monkeypatch.setattr(main, "sync_promo_daily_all", lambda db, days: None)
    monkeypatch.setattr(main, "sync_items_daily_all", lambda db, days: None)
    monkeypatch.setattr(main, "backfill_store_daily", lambda db, days: None)
    monkeypatch.setattr(
        main,
        "sync_plans",
        lambda *, mode, store_id, user, db: calls.append(("plans", mode, store_id, user, db)),
    )
    monkeypatch.setattr(
        main,
        "sync_items",
        lambda *, mode, user, db: calls.append(("items", mode, None, user, db)),
    )

    main._run_promo_daily_once()

    assert len(calls) == 6
    assert all(call[3] is None for call in calls)
    assert all(call[4] is connection for call in calls)


def test_realtime_sync_passes_database_to_plan_sync(monkeypatch):
    from backend.app import main

    calls = []

    class FakeConnection:
        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    connection = FakeConnection()
    monkeypatch.setattr(main, "connect_db", lambda: connection)
    monkeypatch.setattr(main, "_sync_store_daily_step", lambda db: None)
    for name in (
        "sync_hourly_all",
        "sync_promo_realtime_all",
        "sync_items_realtime_all",
        "sync_promo_items_realtime_all",
        "sync_operational_status_all",
        "sync_flow_source_all",
        "sync_refund_all",
    ):
        monkeypatch.setattr(main, name, lambda db: None)
    monkeypatch.setattr(
        main,
        "sync_plans",
        lambda *, mode, store_id, user, db: calls.append((mode, store_id, user, db)),
    )

    main._run_realtime_sync()

    assert calls == [("realtime", None, None, connection)]


def test_manual_retry_supports_promo_daily(client, admin_token, monkeypatch):
    from backend.app import main

    monkeypatch.setattr(main, "_run_promo_daily_once", lambda: None)
    response = client.post(
        "/api/system/loops/promo_daily/retry",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
