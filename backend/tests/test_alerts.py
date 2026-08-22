import json
import os
import sqlite3
from datetime import datetime, timedelta

from backend.app.api.alerts import _check_operating_rules, _check_product_rules, _check_promotion_rules, _norm_hourly_rule


def test_norm_hourly_rule_defaults():
    rule = _norm_hourly_rule({"field": "sales", "operator": "lt", "threshold": 100})
    assert rule is not None
    assert rule["enabled"] is True
    assert rule["field"] == "sales"
    assert rule["threshold"] == 100


def test_norm_hourly_rule_rejects_invalid_field():
    assert _norm_hourly_rule({"field": "not-a-field", "operator": "lt", "threshold": 1.0}) is None
    assert _norm_hourly_rule({"field": "sales", "operator": "bad-op", "threshold": 1.0}) is None


def test_norm_hourly_rule_rejects_cycle_operator_for_value_only_fields():
    assert _norm_hourly_rule(
        {"field": "goal_progress", "operator": "cycle_drop_pct", "threshold": 10},
        "report",
    ) is None
    assert _norm_hourly_rule(
        {"field": "promo_roi", "operator": "cycle_up_pct", "threshold": 10},
        "products",
    ) is None
    assert _norm_hourly_rule(
        {"field": "real_roi", "operator": "lt", "threshold": 2},
        "products",
    ) is not None
    assert _norm_hourly_rule(
        {"field": "budget_usage", "operator": "cycle_drop_pct", "threshold": 10},
        "promotions",
    ) is None
    assert _norm_hourly_rule(
        {"field": "budget_usage", "operator": "gt", "threshold": 90},
        "promotions",
    ) is not None


def test_hourly_push_test_without_token_returns_400(client):
    """回归测试：alerts.py 曾因未导入 HTTPException 在此时抛 NameError 500。"""
    token = _login(client)
    r = client.post(
        "/api/alerts/hourly-push/test",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert "token" in r.json()["detail"]


def test_hourly_push_channel_config_roundtrip(client):
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    saved = client.put(
        "/api/alerts/hourly-push-config",
        headers=headers,
        json={"enabled": True, "token": "tok-1", "webhook": "https://example.com/hook", "channel": "both"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["channel"] == "both"
    assert saved.json()["webhook"] == "https://example.com/hook"

    got = client.get("/api/alerts/hourly-push-config", headers=headers).json()
    assert got["channel"] == "both"
    assert got["webhook"] == "https://example.com/hook"


def test_hourly_push_invalid_channel_rejected(client):
    token = _login(client)
    r = client.put(
        "/api/alerts/hourly-push-config",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": "sms"},
    )
    assert r.status_code == 400


def test_hourly_push_test_webhook_missing(client):
    token = _login(client)
    client.put(
        "/api/alerts/hourly-push-config",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": "webhook", "webhook": ""},
    )
    r = client.post(
        "/api/alerts/hourly-push/test",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert "webhook" in r.json()["detail"]


def test_hourly_push_page_scopes_are_independent(client):
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    report_rule = {"id": "report-sales", "field": "sales", "operator": "lt", "threshold": 1000, "compare": "yesterday", "enabled": True}
    product_rule = {"id": "product-visitors", "field": "visitors", "operator": "cycle_drop_pct", "threshold": 30, "compare": "yesterday", "enabled": True}

    report = client.put(
        "/api/alerts/hourly-push-config?scope=report",
        headers=headers,
        json={"enabled": True, "rules": [report_rule]},
    )
    products = client.put(
        "/api/alerts/hourly-push-config?scope=products",
        headers=headers,
        json={"enabled": True, "rules": [product_rule]},
    )
    assert report.status_code == 200, report.text
    assert products.status_code == 200, products.text

    got_report = client.get("/api/alerts/hourly-push-config?scope=report", headers=headers).json()
    got_products = client.get("/api/alerts/hourly-push-config?scope=products", headers=headers).json()
    root = client.get("/api/alerts/hourly-push-config", headers=headers).json()
    assert got_report["enabled"] is True
    assert got_report["rules"][0]["id"] == "report-sales"
    assert got_products["rules"][0]["id"] == "product-visitors"
    assert root["pages"]["report"]["rules"][0]["id"] == "report-sales"
    assert root["pages"]["products"]["rules"][0]["id"] == "product-visitors"


def test_hourly_push_scope_rejects_fields_from_other_pages(client):
    token = _login(client)
    response = client.put(
        "/api/alerts/hourly-push-config?scope=report",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "enabled": True,
            "rules": [{"id": "bad", "field": "retained_roi", "operator": "lt", "threshold": 1, "enabled": True}],
        },
    )
    assert response.status_code == 200
    assert response.json()["rules"] == []


def test_legacy_hourly_push_config_migrates_to_hours_scope(client):
    token = _login(client)
    legacy = {
        "enabled": True,
        "token": "legacy-token",
        "webhook": "",
        "channel": "pushplus",
        "rules": [{"id": "legacy", "field": "sales", "operator": "lt", "threshold": 10, "enabled": True}],
    }
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('hourly_push_config', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (json.dumps(legacy),),
    )
    conn.commit()
    conn.close()

    headers = {"Authorization": f"Bearer {token}"}
    hours = client.get("/api/alerts/hourly-push-config?scope=hours", headers=headers).json()
    report = client.get("/api/alerts/hourly-push-config?scope=report", headers=headers).json()
    assert hours["enabled"] is True
    assert hours["rules"][0]["id"] == "legacy"
    assert report["enabled"] is False


def test_product_and_promotion_rules_use_their_own_data(client):
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    conn.row_factory = sqlite3.Row
    conn.execute("DELETE FROM store_item_realtime WHERE item_id = 'scope-product'")
    conn.execute(
        """
        INSERT INTO store_item_realtime
            (store_id, item_id, item_title, sales, visitors, orders, conversion_rate, add_cart,
             sales_cycle, visitors_cycle, orders_cycle, conversion_cycle, add_cart_cycle, updated_at)
        VALUES (1, 'scope-product', '页面独立商品', 100, 20, 1, 5, 8,
                -60, -50, -40, -2, 80, '2026-08-23T00:00:00')
        """
    )
    conn.execute("DELETE FROM promo_item_stats WHERE item_id = 'scope-product'")
    conn.execute(
        """
        INSERT INTO promo_item_stats
            (store_id, item_id, item_title, mode, spend, sales, roi, updated_at)
        VALUES (1, 'scope-product', '页面独立商品', 'realtime', 80, 40, 0.5, '2026-08-23T00:00:00')
        """
    )
    conn.execute("DELETE FROM promo_plan_stats WHERE campaign_id = 'scope-plan'")
    conn.execute("DELETE FROM promo_plans WHERE campaign_id = 'scope-plan'")
    conn.execute(
        "INSERT INTO promo_plans (store_id, campaign_id, plan_name, day_budget, updated_at) VALUES (1, 'scope-plan', '页面独立计划', 1000, '2026-08-23T00:00:00')"
    )
    conn.execute(
        """
        INSERT INTO promo_plan_stats
            (store_id, campaign_id, mode, spend, sales, roi, clicks, retained_roi,
             prev_spend, prev_sales, prev_roi, prev_clicks, refund_amt, extra_json, updated_at)
        VALUES (1, 'scope-plan', 'realtime', 500, 200, 0.4, 10, 0.5,
                400, 400, 1, 20, 80, '{"adPv": 1000, "ctr": 0.03}', '2026-08-23T00:00:00')
        """
    )
    conn.commit()

    product_messages = _check_product_rules(
        conn,
        [
            {"field": "visitors", "operator": "cycle_drop_pct", "threshold": 30, "enabled": True},
            {"field": "add_cart", "operator": "cycle_up_pct", "threshold": 50, "enabled": True},
            {"field": "promo_roi", "operator": "lt", "threshold": 1, "enabled": True},
            {"field": "real_roi", "operator": "lt", "threshold": 2, "enabled": True},
        ],
    )
    promotion_messages = _check_promotion_rules(
        conn,
        [
            {"field": "retained_roi", "operator": "lt", "threshold": 1, "enabled": True},
            {"field": "budget_usage", "operator": "gt", "threshold": 40, "enabled": True},
            {"field": "ctr", "operator": "gt", "threshold": 2, "enabled": True},
            {"field": "refund_amt", "operator": "gt", "threshold": 50, "enabled": True},
        ],
    )
    conn.close()

    assert any("页面独立商品" in message for message in product_messages)
    assert any("加购数上涨" in message for message in product_messages)
    assert any("推广ROI" in message for message in product_messages)
    assert any("真实ROI" in message for message in product_messages)
    assert any("页面独立计划" in message for message in promotion_messages)
    assert any("预算消耗率" in message for message in promotion_messages)
    assert any("点击率" in message for message in promotion_messages)
    assert any("退款金额" in message for message in promotion_messages)


def test_operating_rules_support_pv_buyers_and_promo_sales(client):
    now = datetime.now()
    current = now - timedelta(hours=1)
    yesterday = current - timedelta(days=1)
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    conn.row_factory = sqlite3.Row
    conn.execute("DELETE FROM store_hourly_data WHERE hour = ? AND data_date IN (?, ?)", (
        current.strftime("%H:00"), current.strftime("%Y-%m-%d"), yesterday.strftime("%Y-%m-%d"),
    ))
    conn.execute("DELETE FROM promo_realtime WHERE hour = ? AND data_date IN (?, ?)", (
        current.strftime("%H:00"), current.strftime("%Y-%m-%d"), yesterday.strftime("%Y-%m-%d"),
    ))
    conn.executemany(
        """
        INSERT INTO store_hourly_data
            (store_id, data_date, hour, visitors, pv, sales, orders, buyers, created_at)
        VALUES (991, ?, ?, ?, ?, ?, ?, ?, '2026-08-23T00:00:00')
        """,
        [
            (current.strftime("%Y-%m-%d"), current.strftime("%H:00"), 100, 100, 1000, 10, 10),
            (yesterday.strftime("%Y-%m-%d"), yesterday.strftime("%H:00"), 200, 200, 2000, 20, 20),
        ],
    )
    conn.executemany(
        """
        INSERT INTO promo_realtime
            (store_id, scene, data_date, hour, spend, sales, created_at)
        VALUES (991, '', ?, ?, ?, ?, '2026-08-23T00:00:00')
        """,
        [
            (current.strftime("%Y-%m-%d"), current.strftime("%H:00"), 100, 50),
            (yesterday.strftime("%Y-%m-%d"), yesterday.strftime("%H:00"), 100, 200),
        ],
    )
    conn.commit()

    messages = _check_operating_rules(
        conn,
        [
            {"field": "pv", "operator": "cycle_drop_pct", "threshold": 40, "compare": "yesterday", "enabled": True},
            {"field": "buyers", "operator": "cycle_drop_pct", "threshold": 40, "compare": "yesterday", "enabled": True},
            {"field": "promo_sales", "operator": "cycle_drop_pct", "threshold": 70, "compare": "yesterday", "enabled": True},
        ],
        "report",
    )
    conn.close()

    assert any("浏览量" in message for message in messages)
    assert any("买家数" in message for message in messages)
    assert any("推广成交额" in message for message in messages)


_token_cache: str | None = None


def _login(client) -> str:
    global _token_cache
    if _token_cache is None:
        reg = client.post(
            "/api/auth/register",
            json={"username": "alertuser", "password": "pass123456", "nickname": "告警测试"},
        )
        assert reg.status_code == 200, reg.text
        _token_cache = reg.json()["token"]
    return _token_cache
