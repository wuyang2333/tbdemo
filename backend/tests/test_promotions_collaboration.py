import os
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.promotions.collaboration import ensure_promo_collaboration_tables, router


def _member_token(db_path: str, store_id: int, username: str | None = None) -> str:
    import json
    import secrets

    from backend.app.api.auth import hash_password

    conn = sqlite3.connect(db_path)
    try:
        salt = secrets.token_bytes(16)
        user_id = conn.execute(
            "INSERT INTO users (username, password_hash, salt, nickname, created_at, role, status, allowed_store_ids) VALUES (?, ?, ?, ?, ?, 'member', 'active', ?)",
            (username or f"collab_member_{store_id}", hash_password("member123", salt), salt.hex(), "协同成员", datetime.now(timezone.utc).isoformat(), json.dumps([store_id])),
        ).lastrowid
        token = secrets.token_hex(24)
        conn.execute("INSERT INTO tokens (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)", (token, user_id, datetime.now(timezone.utc).isoformat(), (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()))
        conn.commit()
    finally:
        conn.close()
    return token


def test_collaboration_lifecycle_and_store_scope(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    conn = sqlite3.connect(db_path)
    ensure_promo_collaboration_tables(conn)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('协同店A', 'active', '2026-08-01')")
    store_a = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('协同店B', 'active', '2026-08-01')")
    store_b = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for store_id, campaign in ((store_a, "a"), (store_b, "b")):
        conn.execute("INSERT INTO promo_plans (store_id, campaign_id, plan_name, updated_at) VALUES (?, ?, ?, '2026-08-01')", (store_id, campaign, f"计划{campaign}"))
    plan_a, plan_b = [row[0] for row in conn.execute("SELECT id FROM promo_plans ORDER BY id DESC LIMIT 2").fetchall()][::-1]
    conn.commit()
    conn.close()

    member_token = _member_token(db_path, store_a)
    headers = {"Authorization": f"Bearer {member_token}"}
    app = FastAPI()
    app.include_router(router, prefix="/api/promotions")
    api = TestClient(app)

    forbidden = api.post("/api/promotions/collaboration/tasks", headers=headers, json={"plan_id": plan_b, "title": "越权"})
    assert forbidden.status_code == 404
    created = api.post("/api/promotions/collaboration/tasks", headers=headers, json={"plan_id": plan_a, "title": "调整预算", "owner_name": "小王", "approval_status": "pending"})
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    updated = api.patch(f"/api/promotions/collaboration/tasks/{task_id}", headers=headers, json={"execution_status": "observing", "planned_at": "2026-08-28T09:00:00"})
    assert updated.status_code == 200
    assert updated.json()["execution_status"] == "observing"
    reminder = api.post(f"/api/promotions/collaboration/tasks/{task_id}/reminders", headers=headers, json={"message": "明早复盘"})
    assert reminder.status_code == 201
    rollback = api.post(f"/api/promotions/collaboration/tasks/{task_id}/rollback-suggestion", headers=headers, json={"reason": "ROI 未达标"})
    assert rollback.status_code == 200
    assert rollback.json()["applied_to_platform"] is False
    summary = api.get("/api/promotions/collaboration/summary", headers=headers)
    assert summary.json()["needs_rollback"] == 1
    assert api.get("/api/promotions/collaboration/tasks", headers=headers).json()["items"][0]["reminder_count"] == 1


def test_action_record_runs_single_operator_workflow_without_collaboration_task(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('动作协同店', 'active', '2026-08-27')")
    store_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, spend, sales, roi, updated_at) "
        "VALUES (?, 'wholesite', '全站推广', 'collab-action', '动作联动计划', 300, 600, 2, '2026-08-27')",
        (store_id,),
    )
    plan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    headers = {"Authorization": f"Bearer {admin_token}"}
    created = client.post(
        "/api/promotions/action-records",
        headers=headers,
        json={
            "plan_id": plan_id,
            "action_type": "下调预算",
            "description": "降低无效花费",
            "observation_hours": 24,
            "success_criteria": {"roi_change_min": 0.1},
        },
    )
    assert created.status_code == 200, created.text
    action_id = created.json()["id"]
    collaboration_task_id = created.json()["collaboration_task_id"]
    assert collaboration_task_id is None

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    task = conn.execute("SELECT * FROM promo_collaboration_tasks WHERE action_record_id = ?", (action_id,)).fetchone()
    action = conn.execute("SELECT status, executed_at FROM promo_action_records WHERE id = ?", (action_id,)).fetchone()
    assert task is None
    assert action["status"] == "planned"
    assert action["executed_at"] is None
    conn.close()

    marked = client.post(f"/api/promotions/action-records/{action_id}/mark-executed", headers=headers)
    assert marked.status_code == 200, marked.text

    now = datetime.now().astimezone()
    executed_at = now - timedelta(days=3)
    due_at = now - timedelta(minutes=1)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE promo_action_records SET executed_at = ?, observation_due_at = ?, baseline_days = 3, "
        "before_spend = 300, before_sales = 600, before_roi = 2 WHERE id = ?",
        (executed_at.isoformat(timespec="seconds"), due_at.isoformat(timespec="seconds"), action_id),
    )
    for offset in range(3):
        data_date = (executed_at.date() + timedelta(days=offset)).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO promo_plan_daily (store_id, campaign_id, data_date, spend, sales, roi, clicks, updated_at) "
            "VALUES (?, 'collab-action', ?, 100, 150, 1.5, 10, ?)",
            (store_id, data_date, now.isoformat(timespec="seconds")),
        )
    conn.commit()
    conn.close()

    verified = client.post(f"/api/promotions/action-records/{action_id}/verify", headers=headers)
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "failed"

    conn = sqlite3.connect(db_path)
    task = conn.execute("SELECT * FROM promo_collaboration_tasks WHERE action_record_id = ?", (action_id,)).fetchone()
    conn.close()
    assert task is None
