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
    assert {item["kind"] for item in payload["queue"]} >= {"decision_action", "verification_overdue"}
    assert all("owner_name" not in item for item in payload["queue"])
    assert payload["summary"]["high"] >= 1
    assert payload["data_health"]["visible_plan_count"] == 1
    assert payload["cases"][0]["risk_level"] == "high"

    channel_response = client.get(
        "/api/promotions/cockpit?channel=search",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert channel_response.status_code == 200, channel_response.text
    assert channel_response.json()["data_health"]["visible_plan_count"] == 1
    assert {item["channel"] for item in channel_response.json()["queue"]} == {"search"}

    detail = client.get(
        f"/api/promotions/cockpit/plans/{plan_a}",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["plan"]["plan_name"] == "作战计划A"
    assert "collaboration_tasks" not in detail.json()
    assert any(item["kind"] == "verification" or item["kind"] == "execution" for item in detail.json()["timeline"])

    forbidden = client.get(
        f"/api/promotions/cockpit/plans/{plan_b}",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert forbidden.status_code == 404


def test_insufficient_decision_is_deferred_and_not_an_execution_item(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('暂缓决策店', 'active', ?)", (now,))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    plan_id = _insert_plan(conn, store_id, "insufficient-plan", "待补证据计划", now)
    conn.commit()
    conn.close()

    headers = {"Authorization": f"Bearer {admin_token}"}
    response = client.post(
        "/api/promotions/decision-records",
        headers=headers,
        json={
            "decision_id": "insufficient-decision",
            "plan_id": plan_id,
            "recommended_tier": "conservative",
            "selected_tier": "conservative",
            "feedback_status": "insufficient",
            "ai_field": "day_budget",
            "ai_change_pct": 0,
            "final_field": "day_budget",
            "final_change_pct": 0,
            "feedback_note": "缺少同类验证样本，先不调整",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["item"]["workflow_status"] == "deferred"

    archive = client.get(f"/api/promotions/decision-records?store_id={store_id}", headers=headers)
    assert archive.status_code == 200, archive.text
    assert archive.json()["summary"]["insufficient"] == 1
    assert archive.json()["summary"]["rejected"] == 0

    cockpit = client.get(f"/api/promotions/cockpit?store_id={store_id}", headers=headers)
    assert cockpit.status_code == 200, cockpit.text
    assert not any(item["kind"] == "decision_action" for item in cockpit.json()["queue"])


def test_manual_strategy_can_be_added_but_does_not_count_as_verified_evidence(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('人工经验店', 'active', ?)", (now,))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    conn.close()

    headers = {"Authorization": f"Bearer {admin_token}"}
    created = client.post(
        "/api/promotions/strategies",
        headers=headers,
        json={
            "store_id": store_id,
            "name": "搜索推广低 ROI 先降出价",
            "action_type": "降低出价/控成本",
            "conditions": "关键词推广 ROI 低于 1.5 且已有有效消耗",
            "evidence": "来自运营人员历史复盘，尚未在系统内验证",
            "scene": "关键词推广",
            "min_roi": 0,
            "max_roi": 1.5,
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["item"]["source_type"] == "manual"
    assert created.json()["item"]["verification_status"] == "pending"
    assert created.json()["item"]["evidence_score"] == 0

    listed = client.get(f"/api/promotions/strategies?store_id={store_id}", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["verification_status"] == "pending"
    assert listed.json()["groups"] == []

    strategy_id = created.json()["id"]
    now_dt = datetime.now().astimezone()
    executed_dt = now_dt - timedelta(days=2)
    due_dt = now_dt - timedelta(days=1)
    conn = sqlite3.connect(db_path)
    user_id = int(conn.execute("SELECT id FROM users WHERE username = 'bootadmin'").fetchone()[0])
    plan_id = _insert_plan(conn, store_id, "manual-strategy-plan", "人工经验验证计划", now)
    conn.execute(
        "INSERT INTO promo_action_records "
        "(user_id, username, store_id, plan_id, strategy_id, action_type, before_spend, before_sales, before_roi, baseline_days, observation_hours, status, executed_at, observation_due_at, created_at, success_criteria) "
        "VALUES (?, 'bootadmin', ?, ?, ?, '降低出价/控成本', 40, 40, 1, 2, 24, 'observing', ?, ?, ?, '{}')",
        (user_id, store_id, plan_id, strategy_id, executed_dt.isoformat(timespec="seconds"), due_dt.isoformat(timespec="seconds"), executed_dt.isoformat(timespec="seconds")),
    )
    action_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    for data_date in (executed_dt.date(), due_dt.date()):
        conn.execute(
            "INSERT INTO promo_plan_daily (store_id, campaign_id, data_date, spend, sales, roi, clicks, updated_at) VALUES (?, 'manual-strategy-plan', ?, 30, 60, 2, 10, ?)",
            (store_id, data_date.isoformat(), now),
        )
    conn.commit()
    conn.close()

    verified = client.post(f"/api/promotions/action-records/{action_id}/verify", headers=headers)
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "success"
    upgraded = client.get(f"/api/promotions/strategies?store_id={store_id}", headers=headers).json()["items"][0]
    assert upgraded["id"] == strategy_id
    assert upgraded["verification_status"] == "verified"
    assert upgraded["source_type"] == "manual"
    assert upgraded["source_action_id"] == action_id
    assert upgraded["evidence_score"] > 0


def test_action_record_can_be_voided_and_restored_without_deletion(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('动作生命周期店', 'active', ?)", (now,))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    plan_id = _insert_plan(conn, store_id, "lifecycle-plan", "生命周期计划", now)
    user_id = int(conn.execute("SELECT id FROM users WHERE username = 'bootadmin'").fetchone()[0])
    conn.execute(
        "INSERT INTO promo_action_records "
        "(user_id, username, store_id, plan_id, action_type, description, before_spend, before_sales, before_roi, expected, observation_hours, status, created_at) "
        "VALUES (?, 'bootadmin', ?, ?, '降低出价', '待取消动作', 100, 240, 2.4, '降低无效花费', 48, 'planned', ?)",
        (user_id, store_id, plan_id, now),
    )
    action_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    conn.close()

    headers = {"Authorization": f"Bearer {admin_token}"}
    voided = client.put(
        f"/api/promotions/action-records/{action_id}/lifecycle",
        headers=headers,
        json={"action": "void", "reason": "重复创建"},
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["item"]["lifecycle_status"] == "voided"
    assert voided.json()["item"]["status"] == "planned"

    active_records = client.get(
        f"/api/promotions/action-records?store_id={store_id}&lifecycle=active",
        headers=headers,
    )
    assert action_id not in {item["id"] for item in active_records.json()["items"]}
    voided_records = client.get(
        f"/api/promotions/action-records?store_id={store_id}&lifecycle=voided",
        headers=headers,
    )
    assert action_id in {item["id"] for item in voided_records.json()["items"]}
    cockpit = client.get(f"/api/promotions/cockpit?store_id={store_id}", headers=headers)
    assert f"pending_execution:{action_id}" not in {item["id"] for item in cockpit.json()["queue"]}

    restored = client.put(
        f"/api/promotions/action-records/{action_id}/lifecycle",
        headers=headers,
        json={"action": "restore"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["item"]["lifecycle_status"] == "active"
    cockpit_after_restore = client.get(f"/api/promotions/cockpit?store_id={store_id}", headers=headers)
    assert f"pending_execution:{action_id}" in {item["id"] for item in cockpit_after_restore.json()["queue"]}
