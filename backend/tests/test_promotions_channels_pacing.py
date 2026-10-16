import os
import sqlite3
from datetime import date, datetime, timedelta

from backend.app.api.promotions.channel import channel_for_scene, channel_name, normalize_channel


def test_channel_mapping_uses_real_scene_and_biz_code():
    assert channel_for_scene("wholesite", "货品全站推广") == "whole_site"
    assert channel_for_scene("onebpSearch", "") == "search"
    assert channel_for_scene("crowd", "人群推广") == "audience"
    assert channel_for_scene("content", "内容营销") == "content"
    assert channel_for_scene("unknown", "未知玩法") == "other"
    assert normalize_channel("whole_site") == "whole_site"
    assert channel_name("search") == "搜索推广"


def test_plans_support_channel_filter_and_return_channel(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('渠道测试店', 'active', ?)", (now,))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    for scene, scene_name, campaign in (
        ("wholesite", "货品全站推广", "channel-whole"),
        ("keyword", "关键词推广", "channel-search"),
    ):
        conn.execute(
            "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, status, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '在投', ?)",
            (store_id, scene, scene_name, campaign, campaign, now),
        )
    conn.execute(
        "INSERT INTO promo_plan_items (store_id, campaign_id, item_id, item_title, image, updated_at) VALUES (?, 'channel-search', 'item-1001', '搜索测试宝贝', 'https://example.com/item-1001.png', ?)",
        (store_id, now),
    )
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/promotions/plans?store_id={store_id}&channel=search",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    assert [item["campaign_id"] for item in response.json()["items"]] == ["channel-search"]
    assert response.json()["items"][0]["channel"] == "search"
    assert response.json()["items"][0]["channel_name"] == "搜索推广"
    assert response.json()["items"][0]["item_id"] == "item-1001"
    assert response.json()["items"][0]["item_title"] == "搜索测试宝贝"
    assert response.json()["items"][0]["item_image"] == "https://example.com/item-1001.png"


def test_plans_return_real_roi_from_item_sales_for_realtime_mode(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    now = datetime.now().astimezone()
    now_text = now.isoformat(timespec="seconds")
    today = now.date().isoformat()
    current_hour = now.strftime("%H:00")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('真实ROI测试店', 'active', ?)", (now_text,))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, status, updated_at) "
        "VALUES (?, 'keyword', '关键词推广', 'real-roi-plan', '真实ROI计划', '在投', ?)",
        (store_id, now_text),
    )
    conn.execute(
        "INSERT INTO promo_plan_items (store_id, campaign_id, item_id, item_title, updated_at) "
        "VALUES (?, 'real-roi-plan', 'real-roi-item', '真实ROI宝贝', ?)",
        (store_id, now_text),
    )
    conn.execute(
        "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at) "
        "VALUES (?, 'real-roi-plan', 'realtime', 80, 40, 0.5, 12, ?)",
        (store_id, now_text),
    )
    conn.execute(
        "INSERT INTO store_item_realtime (store_id, item_id, item_title, sales, updated_at) "
        "VALUES (?, 'real-roi-item', '真实ROI宝贝', 96, ?)",
        (store_id, now_text),
    )
    conn.execute(
        "INSERT INTO store_hourly_data (store_id, data_date, hour, sales, created_at) VALUES (?, ?, ?, ?, ?)",
        (store_id, today, current_hour, 160, now_text),
    )
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/promotions/plans?store_id={store_id}&mode=realtime",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    item = next(item for item in response.json()["items"] if item["campaign_id"] == "real-roi-plan")
    assert item["real_roi"] == 1.2


def test_plans_return_null_real_roi_without_item_sales(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('真实ROI无数据店', 'active', ?)", (now,))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, status, updated_at) "
        "VALUES (?, 'keyword', '关键词推广', 'real-roi-empty', '无成交数据计划', '在投', ?)",
        (store_id, now),
    )
    conn.execute(
        "INSERT INTO promo_plan_items (store_id, campaign_id, item_id, item_title, updated_at) "
        "VALUES (?, 'real-roi-empty', 'real-roi-empty-item', '无成交数据宝贝', ?)",
        (store_id, now),
    )
    conn.execute(
        "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at) "
        "VALUES (?, 'real-roi-empty', 'realtime', 50, 20, 0.4, 4, ?)",
        (store_id, now),
    )
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/promotions/plans?store_id={store_id}&mode=realtime",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    item = next(item for item in response.json()["items"] if item["campaign_id"] == "real-roi-empty")
    assert item["real_roi"] is None


def test_plans_return_real_roi_from_item_sales_for_yesterday_mode(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    now = datetime.now().astimezone()
    now_text = now.isoformat(timespec="seconds")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('真实ROI历史测试店', 'active', ?)", (now_text,))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, status, updated_at) "
        "VALUES (?, 'keyword', '关键词推广', 'real-roi-yesterday', '历史真实ROI计划', '在投', ?)",
        (store_id, now_text),
    )
    conn.execute(
        "INSERT INTO promo_plan_items (store_id, campaign_id, item_id, item_title, updated_at) "
        "VALUES (?, 'real-roi-yesterday', 'real-roi-yesterday-item', '历史真实ROI宝贝', ?)",
        (store_id, now_text),
    )
    conn.execute(
        "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at) "
        "VALUES (?, 'real-roi-yesterday', 'yesterday', 100, 30, 0.3, 10, ?)",
        (store_id, now_text),
    )
    conn.execute(
        "INSERT INTO store_item_daily (store_id, item_id, item_title, data_date, sales, created_at) "
        "VALUES (?, 'real-roi-yesterday-item', '历史真实ROI宝贝', ?, 250, ?)",
        (store_id, yesterday, now_text),
    )
    conn.execute(
        "INSERT INTO store_daily_data (store_id, data_date, sales, created_at) VALUES (?, ?, 999, ?)",
        (store_id, yesterday, now_text),
    )
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/promotions/plans?store_id={store_id}&mode=yesterday",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    item = next(item for item in response.json()["items"] if item["campaign_id"] == "real-roi-yesterday")
    assert item["real_roi"] == 2.5


def test_promotion_data_supports_channel_filter_and_channel_groups(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    target_date = (date.today() - timedelta(days=1)).isoformat()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('渠道数据店', 'active', ?)", (now,))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    for scene, scene_name, spend, sales in (
        ("wholesite", "货品全站推广", 100, 200),
        ("keyword", "关键词推广", 60, 180),
    ):
        conn.execute(
            "INSERT INTO promo_daily_data (store_id, scene, scene_name, data_date, spend, sales, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (store_id, scene, scene_name, target_date, spend, sales, now),
        )
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/promotions/data?mode=yesterday&store_id={store_id}&channel=search",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["spend"] == 60
    assert [item["channel"] for item in payload["scenes"]] == ["search"]
    assert payload["channels"] == [{
        "channel": "search",
        "channel_name": "搜索推广",
        "impressions": 0,
        "clicks": 0,
        "spend": 60.0,
        "sales": 180.0,
        "orders": 0,
        "add_cart": 0,
        "ctr": 0.0,
        "roi": 3.0,
    }]


def test_diagnostics_find_growth_and_fast_pacing_without_auto_execution(client, admin_token):
    db_path = os.environ["TAOBAO_DB_PATH"]
    now_dt = datetime(2026, 8, 28, 16, 0).astimezone()
    now = now_dt.isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO stores (name, status, created_at) VALUES ('节奏测试店', 'active', ?)", (now,))
    store_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    plans = (
        ("pacing-growth", 1000, 100, 400, 4, 60, 240, 4),
        ("pacing-fast", 100, 80, 160, 2, 50, 100, 2),
    )
    for campaign, budget, spend, sales, roi, ye_spend, ye_sales, ye_roi in plans:
        conn.execute(
            "INSERT INTO promo_plans (store_id, scene, scene_name, campaign_id, plan_name, status, day_budget, updated_at) "
            "VALUES (?, 'keyword', '关键词推广', ?, ?, '在投', ?, ?)",
            (store_id, campaign, campaign, budget, now),
        )
        conn.execute(
            "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at) VALUES (?, ?, 'realtime', ?, ?, ?, 80, ?)",
            (store_id, campaign, spend, sales, roi, now),
        )
        conn.execute(
            "INSERT INTO promo_plan_stats (store_id, campaign_id, mode, spend, sales, roi, clicks, updated_at) VALUES (?, ?, 'yesterday', ?, ?, ?, 80, ?)",
            (store_id, campaign, ye_spend, ye_sales, ye_roi, now),
        )
    conn.commit()
    conn.close()

    from backend.app.api.promotions.diagnostics import detect_promotion_anomalies
    from backend.app.core.db import connect_db

    db = connect_db()
    user = dict(db.execute("SELECT * FROM users WHERE username = 'bootadmin'").fetchone())
    payload = detect_promotion_anomalies(db, user, store_id, "search", now=now_dt)
    db.close()
    codes = {item["rule_code"] for item in payload["items"]}
    assert "high_roi_low_spend" in codes
    assert "spend_too_fast" in codes
    assert {item["channel"] for item in payload["items"]} == {"search"}
    growth = next(item for item in payload["items"] if item["rule_code"] == "high_roi_low_spend")
    assert growth["pacing"]["budget_role"] == "spend_ceiling"
    assert growth["recommendation"]["requires_confirmation"] is True
    assert growth["recommendation"]["auto_execute"] is False
    assert payload["thresholds"]["budget_role"] == "spend_ceiling"
