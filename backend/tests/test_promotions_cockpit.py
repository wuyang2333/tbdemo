import json
import os
import sqlite3
from datetime import datetime, timedelta


def _insert_plan(conn, store_id: int, campaign_id: str, name: str, now: str) -> int:
    conn.execute(
        "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, status, spend, sales, roi, updated_at) "
        "VALUES (?, 'keyword', '关键词推广', ?, ?, '在投', 100, 240, 2.4, ?)",
        (store_id, campaign_id, name, now),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def test_cockpit_aggregates_real_work_and_respects_store_scope(client, admin_token):
    from backend.tests.test_promotions_collaboration import _member_token

    db_path = os.environ["TAOBAO_DB_PATH"]
    now_dt = datetime.now().astimezone()
    now = now_dt.isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('作战台店A', 'active', ?)", (now,))
    store_a = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('作战台店B', 'active', ?)", (now,))
    store_b = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    plan_a = _insert_plan(conn, store_a, "cockpit-a", "作战计划A", now)
    plan_b = _insert_plan(conn, store_b, "cockpit-b", "作战计划B", now)
    user_id = int(conn.execute("SELECT id FROM users WHERE username = 'bootadmin'").fetchone()[0])
    conn.execute(
        "INSERT INTO promo_decision_records "
        "(decision_id, user_id, username, store_id, plan_id, selected_tier, feedback_status, workflow_status, created_at, updated_at) "
        "VALUES ('cockpit-decision-a', ?, 'bootadmin', ?, ?, 'balanced', 'adopted', 'selected', ?, ?)",
        (user_id, store_a, plan_a, now, now),
    )
    conn.execute(
        "INSERT INTO promo_decision_records "
        "(decision_id, user_id, username, store_id, plan_id, selected_tier, feedback_status, workflow_status, created_at, updated_at) "
        "VALUES ('cockpit-decision-b', ?, 'bootadmin', ?, ?, 'balanced', 'adopted', 'selected', ?, ?)",
        (user_id, store_b, plan_b, now, now),
    )
    due_at = (now_dt - timedelta(hours=1)).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO promo_action_records "
        "(user_id, username, store_id, plan_id, action_type, before_spend, before_sales, before_roi, expected, observation_hours, status, executed_at, observation_due_at, created_at, success_criteria) "
        "VALUES (?, 'bootadmin', ?, ?, '下调出价', 100, 240, 2.4, '提高 ROI', 24, 'observing', ?, ?, ?, ?)",
        (user_id, store_a, plan_a, now, due_at, now, json.dumps({"roi_change_min": 0.1})),
    )
    action_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        "INSERT INTO promo_collaboration_tasks "
        "(store_id, plan_id, action_record_id, title, owner_name, approval_status, execution_status, rollback_reason, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, '回退失败动作', '小王', 'approved', 'needs_rollback', 'ROI 未达标', ?, ?, ?)",
        (store_a, plan_a, action_id, user_id, now, now),
    )
    conn.commit()
    conn.close()

    member_token = _member_token(db_path, store_a, username=f"cockpit_member_{store_a}")
    response = client.get(
        "/api/promotions/cockpit",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert {item["plan_id"] for item in payload["queue"]} == {plan_a}
    assert {item["kind"] for item in payload["queue"]} >= {"decision_action", "verification_overdue", "needs_rollback"}
    assert payload["summary"]["urgent"] == 1
    assert payload["data_health"]["visible_plan_count"] == 1
    assert payload["cases"][0]["risk_level"] == "urgent"

    detail = client.get(
        f"/api/promotions/cockpit/plans/{plan_a}",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["plan"]["plan_name"] == "作战计划A"
    assert any(item["kind"] == "verification" or item["kind"] == "execution" for item in detail.json()["timeline"])

    forbidden = client.get(
        f"/api/promotions/cockpit/plans/{plan_b}",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert forbidden.status_code == 404
