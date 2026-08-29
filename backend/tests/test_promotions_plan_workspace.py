import json
import os
import sqlite3
from datetime import date, datetime, timedelta


def test_plan_workspace_aggregates_metrics_timeline_and_scope(client, admin_token):
    from backend.tests.test_promotions_collaboration import _member_token

    db_path = os.environ["TAOBAO_DB_PATH"]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('计划档案店', 'active', ?)", (now,))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, day_budget, bid_type, bid_value, status, spend, sales, roi, clicks, updated_at) "
        "VALUES (?, 'keyword', '关键词推广', 'workspace-plan', '计划档案测试', 500, 'custom', 1.2, '在投', 120, 300, 2.5, 80, ?)",
        (store_id, now),
    )
    plan_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at) VALUES (?, 'workspace-plan', 'realtime', 120, 300, 2.5, 80, ?)",
        (store_id, now),
    )
    conn.execute(
        "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at) VALUES (?, 'workspace-plan', 'yesterday', 100, 200, 2, 70, ?)",
        (store_id, now),
    )
    data_date = (date.today() - timedelta(days=1)).isoformat()
    conn.execute(
        "INSERT INTO promo_plan_daily (store_id, campaign_id, data_date, spend, sales, roi, clicks, updated_at) VALUES (?, 'workspace-plan', ?, 100, 200, 2, 70, ?)",
        (store_id, data_date, now),
    )
    conn.execute(
        "INSERT INTO promo_plan_items (store_id, campaign_id, item_id, item_title, image, updated_at) VALUES (?, 'workspace-plan', 'item-1', '关联商品', '', ?)",
        (store_id, now),
    )
    user_id = int(conn.execute("SELECT id FROM users WHERE username = 'bootadmin'").fetchone()[0])
    conn.execute(
        "INSERT INTO promo_action_records (user_id, username, store_id, plan_id, action_type, description, before_value, after_value, status, executed_at, created_at, success_criteria, metric_summary, rollback_condition) "
        "VALUES (?, 'bootadmin', ?, ?, '提高出价', '获取更多有效流量', 1, 1.2, 'observing', ?, ?, '{}', ?, 'ROI低于1.8')",
        (user_id, store_id, plan_id, now, now, json.dumps({"roi_change": 0.2})),
    )
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/promotions/plans/{plan_id}/workspace",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["plan"]["channel"] == "search"
    assert payload["metrics"]["current"]["roi"] == 2.5
    assert payload["metrics"]["change_vs_yesterday"]["sales"] == 50
    assert payload["data_quality"]["status"] == "fresh"
    assert payload["data_quality"]["trend_days_with_data"] == 1
    assert payload["attribution"][0]["status"] == "ready"
    assert payload["observing"][0]["rollback_condition"] == "ROI低于1.8"
    assert payload["decision_summary"]["title"] == "继续观察，不要重复调整"
    assert payload["execution_check"]["action_id"]
    assert payload["execution_check"]["platform_status"] == "not_submitted"
    assert any(item["kind"] == "execution" for item in payload["timeline"])

    other_token = _member_token(db_path, store_id + 9999, username=f"workspace_member_{store_id}")
    forbidden = client.get(
        f"/api/promotions/plans/{plan_id}/workspace",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert forbidden.status_code == 404


def test_platform_execution_check_requires_executed_action_and_records_manual_confirmation(client, admin_token):
    import os
    import sqlite3
    from datetime import datetime

    db_path = os.environ["TAOBAO_DB_PATH"]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('回查店', 'active', ?)", (now,))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, status, spend, sales, roi, updated_at) VALUES (?, 'wholesite', '货品全站推广', 'platform-check-plan', '平台回查计划', '在投', 50, 100, 2, ?)",
        (store_id, now),
    )
    plan_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        "INSERT INTO promo_action_records (user_id, username, store_id, plan_id, action_type, status, created_at) VALUES (1, 'admin', ?, ?, '提高出价', 'planned', ?)",
        (store_id, plan_id, now),
    )
    action_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    conn.close()

    blocked = client.post(
        f"/api/promotions/action-records/{action_id}/platform-status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "manual_confirmed"},
    )
    assert blocked.status_code == 409

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE promo_action_records SET status = 'observing', executed_at = ? WHERE id = ?", (now, action_id))
    conn.commit()
    conn.close()
    confirmed = client.post(
        f"/api/promotions/action-records/{action_id}/platform-status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "manual_confirmed", "note": "万相台页面已核对"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "manual_confirmed"

    workspace = client.get(
        f"/api/promotions/plans/{plan_id}/workspace",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    assert workspace["execution_check"]["platform_status"] == "manual_confirmed"
    assert workspace["execution_check"]["platform_check_note"] == "万相台页面已核对"
