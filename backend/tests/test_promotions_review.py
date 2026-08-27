import json
import os
import sqlite3
from datetime import datetime

from backend.app.api.promotions.review import _record_metrics


def test_review_dashboard_uses_verified_decision_metrics(client, admin_token):
    from backend.tests.test_promotions_collaboration import _member_token

    db_path = os.environ["TAOBAO_DB_PATH"]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    user_id = conn.execute("SELECT id FROM users WHERE username = 'bootadmin'").fetchone()[0]
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('复盘店', 'active', ?)", (now,))
    store_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, updated_at) "
        "VALUES (?, 'keyword', '关键词推广', 'review-dashboard', '复盘样本计划', ?)",
        (store_id, now),
    )
    plan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    metrics = {
        "before_daily_spend": 100,
        "after_daily_spend": 80,
        "before_daily_sales": 200,
        "after_daily_sales": 280,
        "roi_change": 0.5,
    }
    conn.execute(
        "INSERT INTO promo_action_records "
        "(user_id, username, store_id, plan_id, action_type, before_spend, before_sales, before_roi, status, result, executed_at, verified_at, created_at, metric_summary) "
        "VALUES (?, 'bootadmin', ?, ?, '调整关键词出价', 100, 200, 2, 'success', '验证成功', ?, ?, ?, ?)",
        (user_id, store_id, plan_id, now, now, now, json.dumps(metrics)),
    )
    action_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO promo_decision_records "
        "(decision_id, user_id, username, store_id, plan_id, recommended_tier, selected_tier, feedback_status, workflow_status, action_record_id, result_status, result_summary, created_at, updated_at) "
        "VALUES ('review-decision', ?, 'bootadmin', ?, ?, 'balanced', 'balanced', 'adopted', 'verified', ?, 'success', '验证成功', ?, ?)",
        (user_id, store_id, plan_id, action_id, now, now),
    )
    conn.commit()
    conn.close()
    member_token = _member_token(db_path, store_id, username=f"review_member_{store_id}")

    response = client.get(
        "/api/promotions/review-dashboard?window=7d",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"] == {
        "decision_count": 1,
        "adoption_rate": 100.0,
        "execution_rate": 100.0,
        "verification_rate": 100.0,
        "success_rate": 100.0,
        "roi_lift": 0.5,
        "sales_lift": 80.0,
        "saved_spend": 20.0,
    }
    assert payload["funnels"][-1]["count"] == 1
    assert payload["scenes"][0]["name"] == "关键词推广"
    assert payload["actions"][0]["name"] == "调整关键词出价"
    assert payload["tiers"][1]["verified_count"] == 1


def test_review_dashboard_rejects_unknown_window(client, admin_token):
    response = client.get(
        "/api/promotions/review-dashboard?window=90d",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 400


def test_failed_action_does_not_count_as_saved_spend():
    metrics = json.dumps({"before_daily_spend": 100, "after_daily_spend": 50})
    assert _record_metrics({"status": "failed", "metric_summary": metrics})["saved_spend"] == 0
    assert _record_metrics({"status": "success", "metric_summary": metrics})["saved_spend"] == 50
