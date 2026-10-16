import os
import sqlite3
from datetime import datetime


def _store_and_plans(db_path: str):
    from backend.app.core.db import init_db

    init_db()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('平台对账测试店', 'active', ?)", (now,))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    for campaign_id in ("keep-campaign", "missing-campaign"):
        conn.execute(
            "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, status, updated_at) VALUES (?, 'keyword', '关键词推广', ?, ?, '在投', ?)",
            (store_id, campaign_id, campaign_id, now),
        )
    conn.commit()
    conn.close()
    return store_id


def test_platform_reconciliation_marks_missing_and_preserves_history():
    from backend.app.api.promotions.data import _mark_missing_platform_plans
    from backend.app.core.db import connect_db

    db_path = os.environ["TAOBAO_DB_PATH"]
    store_id = _store_and_plans(db_path)
    db = connect_db()
    count = _mark_missing_platform_plans(db, store_id, {"keep-campaign"}, "2026-08-31T12:00:00+08:00")
    db.commit()
    missing = db.execute("SELECT * FROM promo_plans WHERE store_id = ? AND campaign_id = 'missing-campaign'", (store_id,)).fetchone()
    keep = db.execute("SELECT * FROM promo_plans WHERE store_id = ? AND campaign_id = 'keep-campaign'", (store_id,)).fetchone()
    assert count == 1
    assert missing["platform_presence"] == "missing"
    assert missing["status"] == "平台已失效"
    assert missing["platform_missing_at"] == "2026-08-31T12:00:00+08:00"
    assert keep["platform_presence"] == "active"
    db.close()


def test_missing_plan_is_hidden_by_default_and_execution_is_blocked(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    store_id = _store_and_plans(db_path)
    conn = sqlite3.connect(db_path)
    plan_id = int(conn.execute("SELECT id FROM promo_plans WHERE store_id = ? AND campaign_id = 'missing-campaign'", (store_id,)).fetchone()[0])
    conn.execute("UPDATE promo_plans SET platform_presence = 'missing', status = '平台已失效' WHERE id = ?", (plan_id,))
    conn.commit()
    conn.close()
    headers = {"Authorization": f"Bearer {admin_token}"}

    listed = client.get(f"/api/promotions/plans?store_id={store_id}", headers=headers)
    assert listed.status_code == 200
    assert "missing-campaign" not in {item["campaign_id"] for item in listed.json()["items"]}

    historical = client.get(f"/api/promotions/plans?store_id={store_id}&include_invalid=true", headers=headers)
    assert historical.status_code == 200
    item = next(item for item in historical.json()["items"] if item["campaign_id"] == "missing-campaign")
    assert item["platform_presence"] == "missing"
    assert item["status"] == "平台已失效"

    preview = client.post(
        f"/api/promotions/plans/{plan_id}/adjust",
        headers=headers,
        json={"field": "day_budget", "value": 120, "execute": False},
    )
    assert preview.status_code == 200
    assert preview.json()["can_execute"] is False
    assert "不在万相台当前计划列表" in preview.json()["block_reason"]
