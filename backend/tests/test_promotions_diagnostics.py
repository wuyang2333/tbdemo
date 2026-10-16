import os
import json
import sqlite3
from datetime import datetime


def test_diagnostics_returns_evidence_and_respects_store_scope(client, admin_token):
    from backend.tests.test_promotions_collaboration import _member_token

    db_path = os.environ["TAOBAO_DB_PATH"]
    now_dt = datetime.now().astimezone()
    now = now_dt.isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('诊断店A', 'active', ?)", (now,))
    store_a = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('诊断店B', 'active', ?)", (now,))
    store_b = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    for store_id, campaign_id, plan_name in ((store_a, "diagnostic-a", "诊断计划A"), (store_b, "diagnostic-b", "诊断计划B")):
        conn.execute(
            "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, status, day_budget, updated_at) "
            "VALUES (?, 'keyword', '关键词推广', ?, ?, '在投', 100, ?)",
            (store_id, campaign_id, plan_name, now),
        )
        conn.execute(
            "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at) "
            "VALUES (?, ?, 'realtime', 120, 0, 0, 50, ?)",
            (store_id, campaign_id, now),
        )
        conn.execute(
            "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at) "
            "VALUES (?, ?, 'yesterday', 80, 160, 2, 40, ?)",
            (store_id, campaign_id, now),
        )
        conn.execute(
            "INSERT INTO promo_plan_items (store_id, campaign_id, item_id, item_title, image, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (store_id, campaign_id, f"item-{store_id}", f"诊断商品{store_id}", "https://example.com/item.png", now),
        )
    conn.execute(
        "INSERT INTO promo_item_stats (store_id, item_id, item_title, mode, spend, sales, roi, clicks, orders, impressions, source, updated_at) "
        "VALUES (?, ?, ?, 'realtime', 35, 140, 4, 28, 7, 560, 'report', ?)",
        (store_a, f"item-{store_a}", f"诊断商品{store_a}", now),
    )
    conn.commit()
    conn.close()

    member_token = _member_token(db_path, store_a, username=f"diagnostic_member_{store_a}")
    response = client.get(
        "/api/promotions/diagnostics",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["affected_plan_count"] == 1
    assert payload["summary"]["critical"] == 1
    assert payload["summary"]["risk_count"] >= 2
    assert payload["summary"]["risk_count"] + payload["summary"]["opportunity_count"] + payload["summary"]["observation_count"] == payload["summary"]["total"]
    assert {item["rule_code"] for item in payload["items"]} >= {"budget_over", "spend_without_sales"}
    assert {item["store_id"] for item in payload["items"]} == {store_a}
    budget_item = next(item for item in payload["items"] if item["rule_code"] == "budget_over")
    assert budget_item["evidence"][0]["label"] == "今日花费"
    assert budget_item["signal_type"] == "risk"
    assert "日预算" in budget_item["rule_explanation"]
    ai_path = next(item["path"] for item in budget_item["recommendations"] if item["key"] == "ai_decision")
    assert f"store_id={store_a}" in ai_path
    assert "channel=" in ai_path
    assert f"plan_id={budget_item['plan_id']}" in ai_path
    assert f"diagnostic_id={budget_item['id']}" in ai_path
    assert "rule=budget_over" in ai_path
    assert budget_item["confidence"] == "high"
    assert budget_item["campaign_id"] == "diagnostic-a"
    assert budget_item["item_id"] == f"item-{store_a}"
    assert budget_item["item_title"] == f"诊断商品{store_a}"
    assert budget_item["item_image"] == "https://example.com/item.png"
    assert budget_item["item_traffic"]["status"] == "complete"
    assert budget_item["item_traffic"]["item_id"] == f"item-{store_a}"
    assert budget_item["item_traffic"]["metrics"][0]["impressions"] == 560
    assert budget_item["item_traffic"]["metrics"][0]["orders"] == 7
    assert budget_item["recommendations"][0]["path"].startswith("/promotions/plans")
    assert budget_item["spend_at_risk"] == 20.0
    assert payload["data_health"]["realtime_coverage_rate"] == 100.0


def test_diagnostic_engine_marks_stale_data_without_business_guess(client, admin_token):
    from backend.app.api.promotions.diagnostics import detect_promotion_anomalies
    from backend.app.core.db import connect_db

    db = connect_db()
    user = db.execute("SELECT * FROM users WHERE username = 'bootadmin'").fetchone()
    payload = detect_promotion_anomalies(db, dict(user), now=datetime(2027, 8, 27, 17, 0).astimezone())
    stale_items = [item for item in payload["items"] if item["rule_code"] == "data_stale"]
    assert stale_items
    assert all(item["confidence"] == "high" for item in stale_items)
    assert all("待核查" in cause for item in stale_items for cause in item["possible_causes"])
    db.close()


def test_diagnostics_config_can_change_rule_state_priority_and_threshold(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    original = client.get("/api/alerts/config", headers=headers)
    assert original.status_code == 200, original.text
    original_cfg = original.json()
    try:
        updated = client.put(
            "/api/alerts/config",
            headers=headers,
            json={
                "diagnostics": {
                    "rules": {
                        "budget_over": {"enabled": False, "priority": "p3"},
                    },
                    "thresholds": {"spend_without_sales_min_spend": 88},
                }
            },
        )
        assert updated.status_code == 200, updated.text
        payload = updated.json()
        assert payload["diagnostics"]["rules"]["budget_over"] == {"enabled": False, "priority": "p3"}
        assert payload["diagnostics"]["thresholds"]["spend_without_sales_min_spend"] == 88

        fetched = client.get("/api/alerts/config", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["diagnostics"]["rules"]["budget_over"]["enabled"] is False
    finally:
        client.put(
            "/api/alerts/config",
            headers=headers,
            json={"diagnostics": original_cfg["diagnostics"]},
        )


def test_diagnostics_config_can_disable_a_channel(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    original = client.get("/api/alerts/config", headers=headers)
    assert original.status_code == 200, original.text
    original_cfg = original.json()
    try:
        db_path = os.environ["TAOBAO_DB_PATH"]
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('渠道设置测试店', 'active', ?)", (now,))
        store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute(
            "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, status, day_budget, updated_at) "
            "VALUES (?, 'keyword', '关键词推广', 'channel-settings-search', '渠道设置搜索计划', '在投', 100, ?)",
            (store_id, now),
        )
        conn.execute(
            "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at) "
            "VALUES (?, 'channel-settings-search', 'realtime', 120, 0, 0, 50, ?)",
            (store_id, now),
        )
        conn.commit()
        conn.close()

        updated = client.put(
            "/api/alerts/config",
            headers=headers,
            json={"diagnostics": {"channels": {"search": False}}},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["diagnostics"]["channels"]["search"] is False

        from backend.app.api.promotions.diagnostics import detect_promotion_anomalies
        from backend.app.core.db import connect_db

        db = connect_db()
        user = db.execute("SELECT * FROM users WHERE username = 'bootadmin'").fetchone()
        payload = detect_promotion_anomalies(db, dict(user), store_id=store_id)
        assert payload["items"] == []
        db.close()
    finally:
        client.put(
            "/api/alerts/config",
            headers=headers,
            json={"diagnostics": original_cfg["diagnostics"]},
        )


def test_dynamic_priority_uses_multiple_evidence_values():
    from backend.app.api.promotions.diagnostics import _dynamic_priority

    bands = {
        "roi_drop": {
            "p0": {"drop_pct": 60, "spend": 300},
            "p1": {"drop_pct": 40, "spend": 100},
            "p2": {"drop_pct": 20, "spend": 50},
        }
    }
    severe = {
        "rule_code": "roi_drop",
        "evidence": [
            {"label": "下降幅度", "current": 68},
            {"label": "今日花费", "current": 420},
        ],
    }
    mild = {
        "rule_code": "roi_drop",
        "evidence": [
            {"label": "下降幅度", "current": 25},
            {"label": "今日花费", "current": 60},
        ],
    }
    assert _dynamic_priority(severe, {"priority": "p1"}, bands) == ("p0", "动态判定：ROI 跌幅 68%≥60%；当前花费 420元≥300元")
    assert _dynamic_priority(mild, {"priority": "p1"}, bands) == ("p2", "动态判定：ROI 跌幅 25%≥20%；当前花费 60元≥50元")


def test_ai_diagnostic_releases_read_transaction_before_model_call(client, admin_token, monkeypatch):
    """模型请求期间不能持有 SQLite 读锁，否则保存 AI 结果会失败。"""
    from backend.app.api import model_configs
    from backend.app.core import ai_client

    db_path = os.environ["TAOBAO_DB_PATH"]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('AI锁测试店', 'active', ?)", (now,))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, status, day_budget, updated_at) "
        "VALUES (?, 'keyword', '关键词推广', 'ai-lock-campaign', 'AI锁测试计划', '在投', 100, ?)",
        (store_id, now),
    )
    plan_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at) "
        "VALUES (?, 'ai-lock-campaign', 'realtime', 120, 0, 0, 50, ?)",
        (store_id, now),
    )
    conn.commit()
    conn.close()

    headers = {"Authorization": f"Bearer {admin_token}"}
    diagnostics = client.get(f"/api/promotions/diagnostics?store_id={store_id}", headers=headers)
    assert diagnostics.status_code == 200, diagnostics.text
    item = diagnostics.json()["items"][0]
    monkeypatch.setattr(model_configs, "get_default_config", lambda db: {"api_key": "test", "base_url": "https://example.com/v1", "model": "test"})
    monkeypatch.setattr(ai_client, "chat_completion", lambda *args, **kwargs: json.dumps({"conclusion": "可观察", "decision": "建议观察"}, ensure_ascii=False))

    response = client.post(
        "/api/promotions/diagnostics/ai",
        headers=headers,
        json={
            "diagnostic_id": item["id"],
            "plan_id": plan_id,
            "store_id": store_id,
            "channel": item["channel"],
            "rule_code": item["rule_code"],
            "force": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["ai_diagnosis"]["decision"] == "建议观察"


def test_ai_context_preserves_plan_report_detail_fields():
    from backend.app.api.promotions.diagnostics import _plan_stat_context

    context = _plan_stat_context({
        "mode": "realtime",
        "spend": 480.13,
        "sales": 1066.75,
        "roi": 2.16,
        "clicks": 208,
        "alipay_dir": 900,
        "alipay_indir": 166.75,
        "retained_sales": 1036.85,
        "refund_amt": 0,
        "extra_json": json.dumps({"adPv": 13227, "ctr": 0.0157, "cvr": 0.1394, "alipayInshopNum": 29}),
    })
    assert context["report_details"]["adPv"] == 13227
    assert context["funnel"] == {
        "impressions": 13227,
        "clicks": 208,
        "ctr_percent": 1.57,
        "conversion_rate_percent": 13.94,
        "orders": 29,
        "direct_sales": 900,
        "indirect_sales": 166.75,
        "retained_sales": 1036.85,
        "add_cart_orders": None,
        "refund_amount": 0,
    }
