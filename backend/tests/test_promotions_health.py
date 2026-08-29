import json
import os
import sqlite3
from datetime import date, datetime, timedelta

from backend.app.api.promotions.health import record_sync_result


def _insert_health_store(db_path: str, name: str = "推广健康店") -> int:
    conn = sqlite3.connect(db_path)
    now_dt = datetime.now().astimezone()
    now = now_dt.isoformat(timespec="seconds")
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES (?, 'active', ?)", (name, now))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    conn.close()
    return store_id


def test_health_endpoint_exposes_source_freshness_completeness_and_retry(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    store_id = _insert_health_store(db_path)
    now_dt = datetime.now().astimezone()
    now = now_dt.isoformat(timespec="seconds")
    today = date.today().isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO promo_realtime (store_id, scene, scene_name, data_date, hour, spend, sales, created_at) VALUES (?, 'keyword', '关键词推广', ?, ?, 10, 30, ?)",
        (store_id, today, now_dt.strftime("%H:00"), now),
    )
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/promotions/health?store_id={store_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "degraded"
    realtime = next(item for item in payload["datasets"] if item["dataset"] == "realtime")
    assert realtime["source_code"] == "alimama_scene_realtime"
    assert realtime["freshness"] == "fresh"
    assert realtime["business_data_at"]
    assert realtime["freshness_basis"] == "business_data_at"
    assert realtime["storage_updated_at"] == now
    assert realtime["last_sync_at"] is None
    assert realtime["completeness"] in {"complete", "partial"}
    assert realtime["sync"]["status"] == "never"
    assert realtime["sync"]["ok"] == 0
    assert realtime["sync"]["total"] == 0
    assert realtime["retry_method"] == "POST"
    assert realtime["retry_url"].startswith("/api/promotions/sync?")
    assert f"store_id={store_id}" in realtime["retry_url"]
    assert payload["summary"]["missing"] >= 1


def test_record_sync_result_keeps_last_success_when_next_attempt_partially_fails(client, admin_token):
    from backend.app.core.db import connect_db

    db_path = os.environ["TAOBAO_DB_PATH"]
    store_a = _insert_health_store(db_path, "同步成功店")
    store_b = _insert_health_store(db_path, "同步失败店")
    db = connect_db()
    success = record_sync_result(
        db,
        "realtime",
        {
            "total": 2,
            "ok": 2,
            "results": [
                {"store_id": store_a, "store_name": "同步成功店", "ok": True, "rows": 4},
                {"store_id": store_b, "store_name": "同步失败店", "ok": True, "rows": 3},
            ],
        },
        source="alimama_scene_realtime",
    )
    partial = record_sync_result(
        db,
        "realtime",
        {
            "total": 2,
            "ok": 1,
            "results": [
                {"store_id": store_a, "store_name": "同步成功店", "ok": True, "rows": 5},
                {"store_id": store_b, "store_name": "同步失败店", "ok": False, "error": "登录态失效"},
            ],
        },
        source="alimama_scene_realtime",
    )
    db.commit()
    db.close()

    assert partial["status"] == "partial"
    assert partial["last_success_at"] == success["last_success_at"]
    assert partial["last_any_success_at"]
    assert partial["stores"][str(store_b)]["last_success_at"] == success["stores"][str(store_b)]["last_success_at"]
    assert partial["stores"][str(store_b)]["retryable"] is True
    assert partial["failures"] == [{"store_id": store_b, "store_name": "同步失败店", "error": "登录态失效"}]

    response = client.get(
        f"/api/promotions/health?store_id={store_b}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    realtime = next(item for item in response.json()["datasets"] if item["dataset"] == "realtime")
    assert realtime["sync"]["status"] == "failed"
    assert realtime["sync"]["ok"] == 0
    assert realtime["sync"]["total"] == 1
    assert realtime["sync"]["failed"] == 1
    assert realtime["sync"]["last_success_at"] == success["last_success_at"]
    assert realtime["retryable"] is True


def test_daily_data_metadata_marks_missing_dates_as_partial(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    store_id = _insert_health_store(db_path, "日报缺失店")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO promo_daily_data (store_id, scene, scene_name, data_date, spend, sales, created_at) VALUES (?, 'wholesite', '货品全站推广', ?, 20, 40, ?)",
        (store_id, yesterday, now),
    )
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/promotions/data?mode=7d&store_id={store_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    metadata = response.json()["data_metadata"]
    assert metadata["source_code"] == "alimama_scene_daily"
    assert metadata["business_data_at"]
    assert metadata["freshness_basis"] == "business_data_at"
    assert metadata["expected_points"] == 7
    assert metadata["actual_points"] == 1
    assert metadata["completeness"] == "partial"
    assert metadata["completeness_rate"] == 14.3
    assert metadata["retryable"] is True


def test_health_filters_sync_failures_to_visible_store(client, admin_token):
    from backend.app.core.db import connect_db
    from backend.tests.test_promotions_collaboration import _member_token

    db_path = os.environ["TAOBAO_DB_PATH"]
    store_a = _insert_health_store(db_path, "可见同步店")
    store_b = _insert_health_store(db_path, "不可见同步店")
    db = connect_db()
    record_sync_result(
        db,
        "realtime",
        {
            "total": 2,
            "ok": 0,
            "results": [
                {"store_id": store_a, "store_name": "可见同步店", "ok": False, "error": "可见错误"},
                {"store_id": store_b, "store_name": "不可见同步店", "ok": False, "error": "敏感错误"},
            ],
        },
        source="alimama_scene_realtime",
    )
    db.commit()
    db.close()
    member_token = _member_token(db_path, store_a, username=f"health_member_{store_a}")

    payload = client.get(
        "/api/promotions/health",
        headers={"Authorization": f"Bearer {member_token}"},
    ).json()
    realtime = next(item for item in payload["datasets"] if item["dataset"] == "realtime")
    assert realtime["sync"]["failures"] == [{"store_id": store_a, "store_name": "可见同步店", "error": "可见错误"}]
    assert "敏感错误" not in json.dumps(payload, ensure_ascii=False)


def test_realtime_freshness_uses_business_hour_not_recent_database_write(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    store_id = _insert_health_store(db_path, "业务时间过期店")
    storage_now = datetime.now().astimezone().isoformat(timespec="seconds")
    old_date = (date.today() - timedelta(days=2)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO promo_realtime (store_id, scene, scene_name, data_date, hour, spend, sales, created_at) VALUES (?, 'keyword', '关键词推广', ?, '23:00', 10, 30, ?)",
        (store_id, old_date, storage_now),
    )
    conn.commit()
    conn.close()

    payload = client.get(
        f"/api/promotions/health?store_id={store_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    realtime = next(item for item in payload["datasets"] if item["dataset"] == "realtime")
    assert realtime["storage_updated_at"] == storage_now
    assert realtime["freshness_basis"] == "business_data_at"
    assert realtime["freshness"] == "stale"


def test_high_risk_plan_write_is_blocked_when_realtime_metric_is_missing(client, admin_token, monkeypatch):
    from backend.app.api.promotions import data as promotions_data

    db_path = os.environ["TAOBAO_DB_PATH"]
    store_id = _insert_health_store(db_path, "执行阻断店")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, status, day_budget, updated_at) VALUES (?, 'keyword', '关键词推广', 'guard-plan', '守卫计划', '在投', 100, ?)",
        (store_id, now),
    )
    plan_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    conn.close()
    monkeypatch.setattr(promotions_data, "has_profile", lambda _store_id: True)
    calls = []
    monkeypatch.setattr(promotions_data, "_write_campaign_field", lambda *args: calls.append(args) or {"success": True})

    preview = client.post(
        f"/api/promotions/plans/{plan_id}/adjust",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"field": "day_budget", "value": 120, "execute": False},
    )
    assert preview.status_code == 200
    assert preview.json()["can_execute"] is False
    assert "实时指标" in preview.json()["block_reason"]

    execute = client.post(
        f"/api/promotions/plans/{plan_id}/adjust",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"field": "day_budget", "value": 120, "execute": True},
    )
    assert execute.status_code == 409
    assert "实时指标" in execute.json()["detail"]
    assert calls == []
