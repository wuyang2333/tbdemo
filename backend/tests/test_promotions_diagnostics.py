import os
import sqlite3
from datetime import datetime


def test_diagnostics_returns_evidence_and_respects_store_scope(client, admin_token):
    from backend.tests.test_promotions_collaboration import _member_token

    db_path = os.environ["TAOBAO_DB_PATH"]
    now_dt = datetime(2026, 8, 27, 17, 0).astimezone()
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
    assert {item["rule_code"] for item in payload["items"]} >= {"budget_over", "spend_without_sales"}
    assert {item["store_id"] for item in payload["items"]} == {store_a}
    budget_item = next(item for item in payload["items"] if item["rule_code"] == "budget_over")
    assert budget_item["evidence"][0]["label"] == "今日花费"
    assert budget_item["confidence"] == "high"
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
