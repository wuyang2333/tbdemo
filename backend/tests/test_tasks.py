import os
import json
import sqlite3
from datetime import datetime, timedelta, timezone


def test_tasks_returns_status_summary_and_history(client, admin_token):
    from backend.app.core import loops

    loops.register("realtime_sync")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    conn.execute("DELETE FROM sync_runs")
    conn.execute(
        """
        INSERT INTO sync_runs
            (name, status, trigger, store_id, started_at, finished_at, duration, error)
        VALUES (?, 'success', 'auto', NULL, ?, ?, 5.0, ''),
               (?, 'error', 'manual', NULL, ?, ?, 8.0, '登录失效')
        """,
        ("realtime_sync", now, now, "product_catalog_sync", now, now),
    )
    conn.commit()
    conn.close()

    response = client.get("/api/tasks", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    data = response.json()
    assert any(item["name"] == "realtime_sync" for item in data["tasks"])
    assert data["summary"]["today_total"] == 2
    assert data["summary"]["today_success"] == 1
    assert data["summary"]["today_error"] == 1
    assert data["summary"]["success_rate"] == 50.0
    assert data["history"][0]["error"] == "登录失效"


def test_maintenance_pauses_tasks_and_blocks_manual_retry(client, admin_token):
    from backend.app.core import loops

    loops.register("realtime_sync")
    loops.register("product_catalog_sync")
    headers = {"Authorization": f"Bearer {admin_token}"}
    enabled = client.put(
        "/api/system/maintenance",
        headers=headers,
        json={
            "enabled": True,
            "reason": "升级抓取模块",
            "duration_minutes": 60,
            "pause_tasks": ["realtime_sync", "product_catalog_sync"],
            "resume_strategy": "next_cycle",
        },
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["enabled"] is True

    tasks = client.get("/api/tasks", headers=headers).json()
    realtime = next(item for item in tasks["tasks"] if item["name"] == "realtime_sync")
    assert realtime["paused"] is True
    assert tasks["maintenance"]["reason"] == "升级抓取模块"

    before = loops.get_status("realtime_sync")["error_count"]
    loops.mark_running("realtime_sync")
    loops.record_error("realtime_sync", RuntimeError("维护中的模拟失败"), 1.0)
    assert loops.get_status("realtime_sync")["error_count"] == before

    retry = client.post("/api/system/loops/realtime_sync/retry", headers=headers)
    assert retry.status_code == 423
    assert "维护模式" in retry.json()["detail"]

    resumed = client.put(
        "/api/system/maintenance",
        headers=headers,
        json={
            "enabled": False,
            "reason": "",
            "duration_minutes": 0,
            "pause_tasks": [],
            "resume_strategy": "next_cycle",
        },
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["enabled"] is False

    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    actions = {row[0] for row in conn.execute("SELECT action FROM op_logs WHERE target_name = '后台任务维护模式'")}
    conn.close()
    assert "maintenance_enable" in actions
    assert "maintenance_resume" in actions


def test_maintenance_auto_resume_sets_pending_tasks(client, admin_token):
    from backend.app.core import maintenance

    headers = {"Authorization": f"Bearer {admin_token}"}
    enabled = client.put(
        "/api/system/maintenance",
        headers=headers,
        json={
            "enabled": True,
            "reason": "短时维护",
            "duration_minutes": 30,
            "pause_tasks": ["inspect", "report_push"],
            "resume_strategy": "run_once",
        },
    )
    assert enabled.status_code == 200, enabled.text

    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (maintenance.META_KEY,)).fetchone()
    state = json.loads(row["value"])
    state["ends_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    conn.execute("UPDATE meta SET value = ? WHERE key = ?", (json.dumps(state, ensure_ascii=False), maintenance.META_KEY))
    conn.commit()
    conn.close()

    current = client.get("/api/system/maintenance", headers=headers)
    assert current.status_code == 200
    assert current.json()["enabled"] is False
    assert current.json()["pending_resume"] == ["inspect", "report_push"]
    assert maintenance.claim_pending_resume_tasks() == ["inspect", "report_push"]
