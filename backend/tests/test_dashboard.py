import sqlite3


def test_dashboard_empty(client):
    token = _login(client)
    r = client.get("/api/dashboard", headers={"Authorization": f"Bearer {token}"})
    data = r.json()
    assert data["data_date"] is None
    assert data["today_sales"] == 0


def test_dashboard_aggregates_real_data(client):
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
        INSERT INTO store_item_daily
        (store_id, item_id, item_title, data_date, sales, orders, visitors, created_at)
        VALUES (1, 'i1', '商品一', '2026-08-16', 100, 10, 50, '2026-08-17T00:00:00'),
               (1, 'i2', '商品二', '2026-08-16', 50, 5, 20, '2026-08-17T00:00:00')
        """
    )
    conn.commit()
    conn.close()

    token = _login(client)
    data = client.get("/api/dashboard", headers={"Authorization": f"Bearer {token}"}).json()
    assert data["store_count"] >= 1  # 测试库含演示店铺
    assert data["data_date"] == "2026-08-16"
    assert data["product_count"] == 2
    assert data["today_sales"] == 150
    assert data["today_orders"] == 15
    assert data["today_visitors"] == 70


_token_cache: str | None = None


def _login(client) -> str:
    global _token_cache
    if _token_cache is None:
        reg = client.post(
            "/api/auth/register",
            json={"username": "dashuser", "password": "pass123456", "nickname": "总览测试"},
        )
        assert reg.status_code == 200, reg.text
        _token_cache = reg.json()["token"]
    return _token_cache
