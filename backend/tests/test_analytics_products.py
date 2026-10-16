import os
import sqlite3
from datetime import date, timedelta


def test_realtime_products_include_all_promotion_change_rates(client, admin_token):
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    store_id = conn.execute(
        "INSERT INTO stores (name, status, created_at) VALUES (?, 'active', ?)",
        ("商品涨跌幅测试店", "2026-09-16T00:00:00"),
    ).lastrowid
    item_id = "change-rate-product"
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    conn.execute(
        """
        INSERT INTO store_item_realtime
        (store_id, item_id, item_title, visitors, pv, buyers, orders, sales,
         conversion_rate, add_cart, updated_at)
        VALUES (?, ?, ?, 100, 300, 20, 20, 200, 20, 30, ?)
        """,
        (store_id, item_id, "涨跌幅测试商品", "2026-09-16T12:00:00"),
    )
    conn.execute(
        """
        INSERT INTO store_item_daily
        (store_id, item_id, item_title, data_date, sales, orders, buyers, created_at)
        VALUES (?, ?, ?, ?, 150, 15, 15, ?)
        """,
        (store_id, item_id, "涨跌幅测试商品", yesterday, "2026-09-16T08:00:00"),
    )
    conn.executemany(
        """
        INSERT INTO promo_item_stats
        (store_id, item_id, item_title, mode, spend, sales, roi, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (store_id, item_id, "涨跌幅测试商品", "realtime", 50, 80, 1.6, "2026-09-16T12:00:00"),
            (store_id, item_id, "涨跌幅测试商品", "yesterday", 40, 60, 1.5, "2026-09-16T08:00:00"),
        ],
    )
    conn.execute(
        """
        INSERT INTO promo_plan_items
        (store_id, campaign_id, item_id, item_title, updated_at)
        VALUES (?, 'change-rate-plan', ?, ?, ?)
        """,
        (store_id, item_id, "涨跌幅测试商品", "2026-09-16T12:00:00"),
    )
    conn.executemany(
        """
        INSERT INTO promo_plan_stats
        (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at, retained_sales)
        VALUES (?, 'change-rate-plan', ?, ?, ?, ?, 10, ?, ?)
        """,
        [
            (store_id, "realtime", 50, 80, 1.6, "2026-09-16T12:00:00", 100),
            (store_id, "yesterday", 40, 60, 1.5, "2026-09-16T08:00:00", 60),
        ],
    )
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/analytics/products?mode=realtime&store_id={store_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    item = next(row for row in payload["items"] if row["item_id"] == item_id)
    assert payload["promo_compare_label"] == "较昨日全天"
    assert item["promo_spend_cycle"] == 25.0
    assert item["promo_roi_cycle"] == 6.7
    assert item["promo_net_roi_cycle"] == 33.3
    assert item["real_roi"] == 4.0
    assert item["real_roi_cycle"] == 6.7
    assert item["promo_share"] == 40.0
    assert item["promo_share_cycle"] == 0.0


def test_realtime_products_leave_change_empty_without_yesterday_baseline(client, admin_token):
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    store_id = conn.execute(
        "INSERT INTO stores (name, status, created_at) VALUES (?, 'active', ?)",
        ("无基准测试店", "2026-09-16T00:00:00"),
    ).lastrowid
    item_id = "no-baseline-product"
    conn.execute(
        """
        INSERT INTO store_item_realtime
        (store_id, item_id, item_title, sales, updated_at)
        VALUES (?, ?, ?, 100, ?)
        """,
        (store_id, item_id, "无基准测试商品", "2026-09-16T12:00:00"),
    )
    conn.execute(
        """
        INSERT INTO promo_item_stats
        (store_id, item_id, item_title, mode, spend, sales, roi, updated_at)
        VALUES (?, ?, ?, 'realtime', 20, 30, 1.5, ?)
        """,
        (store_id, item_id, "无基准测试商品", "2026-09-16T12:00:00"),
    )
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/analytics/products?mode=realtime&store_id={store_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    item = next(row for row in response.json()["items"] if row["item_id"] == item_id)
    assert item["promo_spend_cycle"] is None
    assert item["promo_roi_cycle"] is None
    assert item["promo_net_roi_cycle"] is None
    assert item["real_roi_cycle"] is None
    assert item["promo_share_cycle"] is None


def test_realtime_products_only_include_each_stores_latest_snapshot(client, admin_token):
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    store_id = conn.execute(
        "INSERT INTO stores (name, status, created_at) VALUES (?, 'active', ?)",
        ("实时快照测试店", "2026-09-17T00:00:00"),
    ).lastrowid
    conn.executemany(
        """
        INSERT INTO store_item_realtime
        (store_id, item_id, item_title, sales, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (store_id, "stale-product", "旧批次商品", 999, "2026-09-16T12:00:00+00:00"),
            (store_id, "current-product", "最新批次商品", 100, "2026-09-17T03:00:00+00:00"),
        ],
    )
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/analytics/products?mode=realtime&store_id={store_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["fetched_at"] == "2026-09-17T03:00:00+00:00"
    assert [item["item_id"] for item in payload["items"]] == ["current-product"]


def test_historical_single_day_uses_persisted_item_promotion_data(client, admin_token):
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    store_id = conn.execute(
        "INSERT INTO stores (name, status, created_at) VALUES (?, 'active', ?)",
        ("历史商品推广测试店", "2026-10-10T00:00:00"),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO store_item_daily
        (store_id, item_id, item_title, data_date, sales, orders, buyers, visitors, created_at)
        VALUES (?, 'historic-product', '历史推广商品', '2026-10-01', 300, 3, 3, 30, ?)
        """,
        (store_id, "2026-10-02T00:00:00"),
    )
    conn.execute(
        """
        INSERT INTO promo_item_daily
        (store_id, item_id, item_title, data_date, spend, sales, roi, clicks, orders, impressions, source, updated_at)
        VALUES (?, 'historic-product', '历史推广商品', '2026-10-01', 100, 180, 1.8, 10, 2, 1000, 'report_daily', ?)
        """,
        (store_id, "2026-10-10T00:00:00"),
    )
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/analytics/products?mode=days&start=2026-10-01&end=2026-10-01&store_id={store_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    item = next(row for row in response.json()["items"] if row["item_id"] == "historic-product")
    assert item["promo_spend"] == 100
    assert item["promo_sales"] == 180
    assert item["promo_roi"] == 1.8
    assert item["real_roi"] == 3.0
    assert item["promo_share"] == 60.0
