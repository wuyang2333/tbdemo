import pytest

from backend.app.api import stores as stores_api
from backend.app.core.db import connect_db
from backend.app.core.sycm import SycmError


def _set_sycm_status(store_id: int, status: str, error: str = "") -> None:
    db = connect_db()
    try:
        stores_api._record_sycm_status(db, store_id, status=status, error=error)
        db.commit()
    finally:
        db.close()


def _sycm_status(store_id: int) -> tuple[str | None, str | None]:
    db = connect_db()
    try:
        rows = db.execute(
            "SELECT key, value FROM meta WHERE key IN (?, ?)",
            (f"store_{store_id}_sycm_status", f"store_{store_id}_sycm_error"),
        ).fetchall()
        values = {row["key"]: row["value"] for row in rows}
        return values.get(f"store_{store_id}_sycm_status"), values.get(f"store_{store_id}_sycm_error")
    finally:
        db.close()


def test_manual_sycm_test_forces_fresh_login_check(client, admin_token, monkeypatch):
    forced = []

    def fake_check(store, *, force=False):
        forced.append((store["id"], force))
        return {"ok": True}

    monkeypatch.setattr(stores_api, "check_sycm_login", fake_check)

    response = client.post(
        "/api/stores/1/sycm/test",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert forced == [(1, True)]


def test_failed_store_sync_persists_expired_login_status(client, admin_token, monkeypatch):
    _set_sycm_status(1, "ok")

    def expired(_store):
        raise SycmError("生意参谋登录已失效，请重新打开浏览器登录")

    monkeypatch.setattr(stores_api, "fetch_store_daily", expired)
    response = client.post(
        "/api/stores/1/sync",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 502
    status, error = _sycm_status(1)
    assert status == "error"
    assert error == "生意参谋登录已失效，请重新打开浏览器登录"


def test_non_login_sync_error_does_not_invalidate_login(client, admin_token, monkeypatch):
    _set_sycm_status(1, "ok")

    def unavailable(_store):
        raise SycmError("生意参谋接口结构已变化")

    monkeypatch.setattr(stores_api, "fetch_store_daily", unavailable)
    response = client.post(
        "/api/stores/1/sync",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 502
    assert _sycm_status(1) == ("ok", "")


def test_sync_history_also_backfills_yesterday_realtime_hourly(client, admin_token, monkeypatch):
    daily = {"results": [{"store_id": 1, "store_name": "店铺1", "ok": True, "rows": 3}], "total": 1, "ok": 1, "days": 3}
    hourly = {"results": [{"store_id": 1, "store_name": "店铺1", "ok": True, "rows": 48}], "total": 1, "ok": 1}
    promo = {"results": [{"store_id": 1, "store_name": "店铺1", "ok": True, "rows": 12}], "total": 1, "ok": 1}
    calls = []

    monkeypatch.setattr(stores_api, "backfill_store_daily", lambda db, days: calls.append(("daily", days)) or daily)
    monkeypatch.setattr(stores_api, "sync_hourly_all", lambda db: calls.append(("hourly",)) or hourly)
    monkeypatch.setattr("backend.app.api.promotions.sync_promo_realtime_all", lambda db, target_date=None: calls.append(("promo", target_date)) or promo)

    response = client.post(
        "/api/stores/sync-history?days=3",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls[0] == ("daily", 3)
    assert calls[1][0] == "promo"
    assert calls[2] == ("hourly",)
    assert payload["ok"] == 1
    assert payload["realtime"]["ok"] == 1
    assert payload["realtime"]["results"][0]["rows"] == 48
    assert payload["promo_realtime"]["results"][0]["rows"] == 12


def test_realtime_item_sync_replaces_the_store_snapshot(client, monkeypatch):
    db = connect_db()
    try:
        store_id = db.execute(
            "INSERT INTO stores (name, status, created_at) VALUES (?, 'active', ?)",
            ("实时同步替换测试店", "2026-09-17T00:00:00"),
        ).lastrowid
        db.execute(
            """
            INSERT INTO store_item_realtime
            (store_id, item_id, item_title, sales, updated_at)
            VALUES (?, 'stale-product', '旧商品', 999, '2026-09-16T12:00:00+00:00')
            """,
            (store_id,),
        )
        db.commit()

        monkeypatch.setattr(stores_api, "has_profile", lambda sid: sid == store_id)
        monkeypatch.setattr(
            "backend.app.core.sycm.fetch_item_realtime",
            lambda store: [
                {
                    "item_id": "current-product",
                    "item_title": "最新商品",
                    "visitors": 10,
                    "pv": 20,
                    "buyers": 2,
                    "orders": 2,
                    "sales": 100,
                    "conversion_rate": 20,
                }
            ] if store["id"] == store_id else [],
        )

        result = stores_api.sync_items_realtime_all(db)

        row = db.execute(
            "SELECT item_id, item_title FROM store_item_realtime WHERE store_id = ?",
            (store_id,),
        ).fetchall()
        store_result = next(item for item in result["results"] if item["store_id"] == store_id)
        assert store_result["ok"] is True
        assert store_result["rows"] == 1
        assert [tuple(item) for item in row] == [("current-product", "最新商品")]
    finally:
        db.close()


def test_failed_realtime_item_sync_preserves_previous_snapshot(client, monkeypatch):
    db = connect_db()
    try:
        store_id = db.execute(
            "INSERT INTO stores (name, status, created_at) VALUES (?, 'active', ?)",
            ("实时同步失败测试店", "2026-09-17T00:00:00"),
        ).lastrowid
        db.execute(
            """
            INSERT INTO store_item_realtime
            (store_id, item_id, item_title, sales, updated_at)
            VALUES (?, 'last-known-product', '上次可用商品', 88, '2026-09-16T12:00:00+00:00')
            """,
            (store_id,),
        )
        db.commit()

        monkeypatch.setattr(stores_api, "has_profile", lambda sid: sid == store_id)

        def failed_fetch(store):
            if store["id"] == store_id:
                raise SycmError("实时商品接口暂不可用")
            return []

        monkeypatch.setattr("backend.app.core.sycm.fetch_item_realtime", failed_fetch)

        result = stores_api.sync_items_realtime_all(db)

        row = db.execute(
            "SELECT item_id, item_title FROM store_item_realtime WHERE store_id = ?",
            (store_id,),
        ).fetchall()
        store_result = next(item for item in result["results"] if item["store_id"] == store_id)
        assert store_result["ok"] is False
        assert [tuple(item) for item in row] == [("last-known-product", "上次可用商品")]
    finally:
        db.close()


def test_realtime_item_sync_rolls_back_when_snapshot_write_fails(client, monkeypatch):
    db = connect_db()
    try:
        store_id = db.execute(
            "INSERT INTO stores (name, status, created_at) VALUES (?, 'active', ?)",
            ("实时同步写入失败测试店", "2026-09-17T00:00:00"),
        ).lastrowid
        db.execute(
            """
            INSERT INTO store_item_realtime
            (store_id, item_id, item_title, sales, updated_at)
            VALUES (?, 'last-known-product', '上次可用商品', 88, '2026-09-16T12:00:00+00:00')
            """,
            (store_id,),
        )
        db.commit()

        monkeypatch.setattr(stores_api, "has_profile", lambda sid: sid == store_id)
        monkeypatch.setattr(
            "backend.app.core.sycm.fetch_item_realtime",
            lambda store: [{"item_id": "broken-product"}] if store["id"] == store_id else [],
        )

        with pytest.raises(KeyError):
            stores_api.sync_items_realtime_all(db)

        row = db.execute(
            "SELECT item_id, item_title FROM store_item_realtime WHERE store_id = ?",
            (store_id,),
        ).fetchall()
        assert [tuple(item) for item in row] == [("last-known-product", "上次可用商品")]
    finally:
        db.close()
