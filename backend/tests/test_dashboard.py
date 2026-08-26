import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import quote


def _member_token(db_path: str, username: str, allowed_modules: list[str], allowed_store_ids: list[int]) -> str:
    import json
    import secrets

    from backend.app.api.auth import hash_password

    conn = sqlite3.connect(db_path)
    salt = secrets.token_bytes(16)
    cursor = conn.execute(
        """
        INSERT INTO users
        (username, password_hash, salt, nickname, created_at, role, status, allowed_modules, allowed_store_ids)
        VALUES (?, ?, ?, ?, ?, 'member', 'active', ?, ?)
        """,
        (
            username,
            hash_password("member123", salt),
            salt.hex(),
            "待办测试成员",
            datetime.now(timezone.utc).isoformat(),
            json.dumps(allowed_modules),
            json.dumps(allowed_store_ids),
        ),
    )
    token = secrets.token_hex(24)
    conn.execute(
        "INSERT INTO tokens (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (
            token,
            cursor.lastrowid,
            datetime.now(timezone.utc).isoformat(),
            (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    return token


def test_dashboard_empty(client, admin_token):
    token = admin_token
    r = client.get("/api/dashboard", headers={"Authorization": f"Bearer {token}"})
    data = r.json()
    assert data["data_date"] is None
    assert data["today_sales"] == 0


def test_dashboard_aggregates_real_data(client, admin_token):
    import os

    db_path = os.environ["TAOBAO_DB_PATH"]
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO stores (name, status, created_at) VALUES ('测试店', 'active', '2026-08-17T00:00:00')
        """
    )
    conn.execute(
        """
        INSERT INTO store_daily_data
        (store_id, data_date, visitors, pv, sales, orders, conversion_rate, created_at)
        VALUES (1, '2026-08-16', 70, 100, 150, 15, 15.0, '2026-08-17T00:00:00')
        """
    )
    conn.execute(
        """
        INSERT INTO store_operational_status
        (store_id, pending_shipments, product_count, updated_at)
        VALUES (1, 7, 180, '2026-08-17T00:00:00')
        """
    )
    conn.commit()
    conn.close()

    token = admin_token
    data = client.get("/api/dashboard", headers={"Authorization": f"Bearer {token}"}).json()
    assert data["store_count"] >= 1  # 测试库含演示店铺
    assert data["data_date"] == "2026-08-16"
    assert data["product_count"] == 180
    assert data["pending_shipments"] == 7
    assert data["operational_updated_at"] == "2026-08-17T00:00:00"
    assert data["operational_stale"] is True
    assert data["today_sales"] == 150
    assert data["today_orders"] == 15
    assert data["today_visitors"] == 70

    scoped = client.get(
        "/api/dashboard?store_id=1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert scoped.status_code == 200
    assert scoped.json()["store_count"] == 1


def test_dashboard_todos_aggregate_and_exclude_products(client, admin_token, monkeypatch):
    import os

    from backend.app.api import dashboard

    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    store_id = conn.execute(
        "INSERT INTO stores (name, status, created_at) VALUES ('待办聚合店', 'active', '2026-08-25T08:00:00')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO gifts (store_id, order_no, recipient, gift_name, quantity, price, status, created_at, remark_status)
        VALUES (?, '', '买家', '礼品', 1, 9.9, 'pending', '2026-08-25T09:00:00', 'order_not_found')
        """,
        (store_id,),
    )
    conn.execute(
        "INSERT INTO store_operational_status (store_id, pending_shipments, product_count, updated_at) VALUES (?, 4, 99, '2026-08-25T09:10:00')",
        (store_id,),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        dashboard.loops,
        "get_all_status",
        lambda: [
            {"name": "realtime_sync", "error_count": 2, "last_error": "同步失败", "last_run": "2026-08-25 09:12:00"},
            {"name": "product_catalog_sync", "error_count": 8, "last_error": "商品失败", "last_run": "2026-08-25 09:12:00"},
        ],
    )

    response = client.get(
        f"/api/dashboard/todos?store_id={store_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    keys = {item["key"] for item in data["items"]}
    assert f"gifts:remark:order_not_found:{store_id}" in keys
    assert f"fulfillment:pending:{store_id}" not in keys
    assert "tasks:error:realtime_sync" in keys
    assert "tasks:error:product_catalog_sync" not in keys
    assert all(item["module"] != "products" for item in data["items"])

    todo_key = f"gifts:remark:order_not_found:{store_id}"
    snooze = client.post(
        f"/api/dashboard/todos/{quote(todo_key, safe='')}/snooze",
        json={"minutes": 60},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert snooze.status_code == 200, snooze.text
    refreshed = client.get(
        f"/api/dashboard/todos?store_id={store_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    snoozed_item = next(item for item in refreshed["items"] if item["key"] == todo_key)
    assert snoozed_item["snoozed"] is True
    assert refreshed["summary"]["snoozed"] >= 1


def test_dashboard_todos_respect_module_and_store_scope(client):
    import os

    db_path = os.environ["TAOBAO_DB_PATH"]
    conn = sqlite3.connect(db_path)
    first_store = conn.execute(
        "INSERT INTO stores (name, status, created_at) VALUES ('成员可见店', 'active', '2026-08-25T08:00:00')"
    ).lastrowid
    second_store = conn.execute(
        "INSERT INTO stores (name, status, created_at) VALUES ('成员不可见店', 'active', '2026-08-25T08:00:00')"
    ).lastrowid
    for store_id in (first_store, second_store):
        conn.execute(
            """
            INSERT INTO gifts (store_id, order_no, recipient, gift_name, quantity, price, status, created_at, remark_status)
            VALUES (?, '', '买家', '礼品', 1, 9.9, 'pending', '2026-08-25T09:00:00', 'order_closed')
            """,
            (store_id,),
        )
    conn.commit()
    conn.close()
    token = _member_token(db_path, "todoonlymember", ["gifts"], [first_store])

    response = client.get("/api/dashboard/todos", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items
    assert {item["module"] for item in items} == {"gifts"}
    assert all(item["store_id"] == first_store for item in items)

    forbidden = client.get(
        f"/api/dashboard/todos?store_id={second_store}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert forbidden.status_code == 403
