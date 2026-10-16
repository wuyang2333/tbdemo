import sqlite3
from datetime import datetime, timedelta

from backend.app.api.promotions import data as promotions_data
from backend.app.core.db import DB_PATH


def _insert_promo_plan(*, campaign_id: str, day_budget: float = 100, bid_value: float = 10) -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES (?, 'active', ?)", (f"测试店-{campaign_id}", now))
    store_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, day_budget, bid_value, status, updated_at) VALUES (?, 'wholesite', '货品全站推广', ?, ?, ?, ?, '在投', ?)",
        (store_id, campaign_id, f"测试计划-{campaign_id}", day_budget, bid_value, now),
    )
    plan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at) VALUES (?, ?, 'realtime', 10, 30, 3, 5, ?)",
        (store_id, campaign_id, now),
    )
    from backend.app.api.promotions.health import record_sync_result

    record_sync_result(
        conn,
        "plans_realtime",
        {"total": 1, "ok": 1, "results": [{"store_id": store_id, "store_name": f"测试店-{campaign_id}", "ok": True, "plans": 1}]},
        source="alimama_campaign_report",
    )
    conn.commit()
    conn.close()
    return plan_id


def test_workspace_scaffolds_are_registered(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}

    expected = {
        "/api/content": 6,
        "/api/monitoring": 4,
        "/api/market": 3,
        "/api/growth-lab": 5,
        "/api/ops-knowledge": 4,
        "/api/promotions-workspace": 7,
    }
    for path, section_count in expected.items():
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        assert len(response.json()["sections"]) == section_count


def test_workspace_section_rejects_unknown_page(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    for path in ("/api/content", "/api/monitoring", "/api/market", "/api/promotions-workspace"):
        response = client.get(f"{path}/not-a-page", headers=headers)
        assert response.status_code == 404


def test_promotion_batch_status_requires_plan_ids(client, admin_token):
    response = client.post(
        "/api/promotions/plans/batch-status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"plan_ids": [], "status": "pause"},
    )
    assert response.status_code == 400
    assert "至少选择一个" in response.json()["detail"]


def test_promotion_adjust_preview_validates_change_range(client, admin_token):
    response = client.post(
        "/api/promotions/plans/batch-adjust-preview",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"plan_ids": [1], "field": "day_budget", "change_pct": 301},
    )
    assert response.status_code == 400
    assert "-90% 到 300%" in response.json()["detail"]


def test_promotion_adjust_preview_uses_explicit_target_value(client, admin_token):
    plan_id = _insert_promo_plan(campaign_id="target-value-test", day_budget=3000)
    response = client.post(
        "/api/promotions/plans/batch-adjust-preview",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"plan_ids": [plan_id], "field": "day_budget", "change_pct": 3.3, "target_value": 3100},
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["new_value"] == 3100


def test_promotion_batch_adjust_rejects_invalid_range(client, admin_token):
    response = client.post(
        "/api/promotions/plans/batch-adjust",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"plan_ids": [1], "field": "day_budget", "change_pct": 301},
    )
    assert response.status_code == 400
    assert "-90% 到 300%" in response.json()["detail"]


def test_promotion_plan_adjust_writes_platform_and_local_value(client, admin_token, monkeypatch):
    plan_id = _insert_promo_plan(campaign_id="adjust-test")
    calls = []
    monkeypatch.setattr(promotions_data, "has_profile", lambda _store_id: True)
    monkeypatch.setattr(promotions_data, "_write_campaign_field", lambda store, row, field, value: calls.append((row["campaign_id"], field, value)) or {"success": True})

    response = client.post(
        f"/api/promotions/plans/{plan_id}/adjust",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"field": "day_budget", "value": 180, "execute": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["new_value"] == 180
    assert calls == [("adjust-test", "day_budget", 180)]

    conn = sqlite3.connect(DB_PATH)
    value = conn.execute("SELECT day_budget FROM promo_plans WHERE id = ?", (plan_id,)).fetchone()[0]
    action = conn.execute(
        "SELECT action_type, before_value, after_value, status, observation_hours, platform_status FROM promo_action_records WHERE id = ?",
        (response.json()["action_id"],),
    ).fetchone()
    conn.close()
    assert value == 180
    assert action == ("增加预算/放量", 100, 180, "observing", 48, "submitted")


def test_campaign_budget_write_includes_platform_budget_type(monkeypatch):
    captured = {}

    def fake_run_json(store, args):
        captured["store"] = store
        captured["args"] = args
        return {"info": {"ok": True}}

    monkeypatch.setattr("backend.app.core.alimama._run_json", fake_run_json)
    row = {"scene": "wholesite", "campaign_id": "budget-type-test", "budget_type": "normal"}
    result = promotions_data._write_campaign_field({"id": 1}, row, "day_budget", 250)

    assert result["info"]["ok"] is True
    body = __import__("json").loads(captured["args"][captured["args"].index("--body") + 1])
    assert body["budgetList"] == [{"campaignId": "budget-type-test", "dayBudget": 250, "dmcType": "normal"}]


def test_promotion_batch_adjust_reports_partial_platform_failure(client, admin_token, monkeypatch):
    first = _insert_promo_plan(campaign_id="batch-ok")
    second = _insert_promo_plan(campaign_id="batch-fail")
    monkeypatch.setattr(promotions_data, "has_profile", lambda _store_id: True)

    def fake_write(store, row, field, value):
        if row["campaign_id"] == "batch-fail":
            from backend.app.core.alimama import AlimamaError
            raise AlimamaError("模拟失败")
        return {"success": True}

    monkeypatch.setattr(promotions_data, "_write_campaign_field", fake_write)
    response = client.post(
        "/api/promotions/plans/batch-adjust",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"plan_ids": [first, second], "field": "bid_value", "change_pct": 20, "execute": True},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] == 1
    assert payload["total"] == 2
    assert [item["ok"] for item in payload["items"]] == [True, False]


def test_promotion_plan_create_requires_supported_scene(client, admin_token):
    response = client.post(
        "/api/promotions/plans/create",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"biz_code": "unsupported", "solution_list": [{"name": "demo"}]},
    )
    assert response.status_code == 400
    assert "不支持的推广场景" in response.json()["detail"]


def test_promotion_plan_write_capabilities_are_explicit(client, admin_token):
    response = client.get(
        "/api/promotions/plans/write-capabilities",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"]["write"] is True
    assert response.json()["day_budget"]["write"] is True
    assert response.json()["bid_value"]["write"] is True
    assert response.json()["create"]["write"] is True


def test_promotion_plan_funnel_rejects_unknown_plan(client, admin_token):
    response = client.get(
        "/api/promotions/plans/999999999/funnel",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


def test_promotion_sync_preserves_custom_range_and_full_seven_days(client, admin_token, monkeypatch):
    plan_id = _insert_promo_plan(campaign_id="sync-range")
    conn = sqlite3.connect(DB_PATH)
    store_id = conn.execute("SELECT store_id FROM promo_plans WHERE id = ?", (plan_id,)).fetchone()[0]
    conn.close()
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(promotions_data, "has_profile", lambda _store_id: True)
    monkeypatch.setattr(
        promotions_data,
        "fetch_scene_daily",
        lambda _store, start, end: calls.append((start, end)) or [],
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    custom = client.post(
        f"/api/promotions/sync?mode=range&start=2026-08-10&end=2026-08-16&store_id={store_id}",
        headers=headers,
    )
    assert custom.status_code == 200, custom.text
    assert calls[-1] == ("2026-08-10", "2026-08-16")

    recent = client.post(
        f"/api/promotions/sync?mode=7d&store_id={store_id}",
        headers=headers,
    )
    assert recent.status_code == 200, recent.text
    today = promotions_data.date_cls.today()
    assert calls[-1] == (
        (today - timedelta(days=7)).isoformat(),
        (today - timedelta(days=1)).isoformat(),
    )
