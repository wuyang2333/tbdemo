def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_product_snapshot_diff_creates_events(client, admin_token):
    headers = auth_headers(admin_token)
    shop = client.post("/api/monitoring/shops", headers=headers, json={"name": "测试竞品店"})
    assert shop.status_code == 200
    shop_id = shop.json()["item"]["id"]
    product = client.post("/api/monitoring/products", headers=headers, json={"shop_id": shop_id, "title": "原始商品", "price": 100, "review_count": 10})
    assert product.status_code == 200
    product_id = product.json()["item"]["id"]

    baseline = client.post(f"/api/monitoring/products/{product_id}/snapshots", headers=headers, json={"title": "原始商品", "price": 100, "review_count": 10, "status": "active"})
    assert baseline.status_code == 200
    assert baseline.json()["baseline"] is True
    assert baseline.json()["event_count"] == 0

    changed = client.post(f"/api/monitoring/products/{product_id}/snapshots", headers=headers, json={"title": "升级商品", "price": 80, "review_count": 15, "status": "inactive"})
    assert changed.status_code == 200
    assert changed.json()["baseline"] is False
    assert changed.json()["event_count"] == 4

    events = client.get("/api/monitoring/events", headers=headers)
    assert events.status_code == 200
    event_types = {item["event_type"] for item in events.json()["items"]}
    assert {"price_changed", "title_changed", "review_growth", "status_changed"}.issubset(event_types)

    unchanged = client.post(f"/api/monitoring/products/{product_id}/snapshots", headers=headers, json={"title": "升级商品", "price": 80, "review_count": 15, "status": "inactive"})
    assert unchanged.status_code == 200
    assert unchanged.json()["event_count"] == 0


def test_snapshot_missing_product_returns_404(client, admin_token):
    response = client.post("/api/monitoring/products/999999/snapshots", headers=auth_headers(admin_token), json={"title": "不存在", "status": "active"})
    assert response.status_code == 404


def test_product_intelligence_changes_create_events(client, admin_token):
    headers = auth_headers(admin_token)
    shop_id = client.post("/api/monitoring/shops", headers=headers, json={"name": "商品情报测试店"}).json()["item"]["id"]
    product_id = client.post("/api/monitoring/products", headers=headers, json={"shop_id": shop_id, "title": "测试商品"}).json()["item"]["id"]
    first = {"title": "测试商品", "stock_status": "in_stock", "sku_options": [{"name": "颜色", "values": ["白色"]}], "sku_prices": [{"label": "白色", "price": 20, "list_price": 25}], "promotion_tags": ["满99减10"], "negative_keywords": [], "status": "active"}
    second = {"title": "测试商品", "stock_status": "out_of_stock", "sku_options": [{"name": "颜色", "values": ["白色", "黑色"]}], "sku_prices": [{"label": "白色", "price": 22, "list_price": 25}, {"label": "黑色", "price": 24, "list_price": 28}], "promotion_tags": ["满99减20"], "negative_keywords": [{"label": "包装破损", "count": 2}], "status": "active"}
    assert client.post(f"/api/monitoring/products/{product_id}/snapshots", headers=headers, json=first).status_code == 200
    changed = client.post(f"/api/monitoring/products/{product_id}/snapshots", headers=headers, json=second)
    assert changed.status_code == 200
    assert changed.json()["event_count"] == 3
    events = client.get("/api/monitoring/events", headers=headers).json()["items"]
    event_types = {item["event_type"] for item in events if item["product_id"] == product_id}
    assert {"sku_price_changed", "promotion_changed", "review_risk_changed"}.issubset(event_types)


def test_batch_products_deduplicates_links(client, admin_token, monkeypatch):
    from backend.app.api import monitoring

    headers = auth_headers(admin_token)
    shop = client.post("/api/monitoring/shops", headers=headers, json={"name": "批量竞品店"})
    shop_id = shop.json()["item"]["id"]

    def fake_collect(db, product_id):
        db.execute("UPDATE competitor_products SET collection_status='success',last_success_at=? WHERE id=?", ("2026-09-09T00:00:00+00:00", product_id))
        return {"event_count": 0}

    monkeypatch.setattr(monitoring, "collect_product_now", fake_collect)
    response = client.post("/api/monitoring/products/batch", headers=headers, json={"shop_id": shop_id, "urls": ["https://item.taobao.com/item.htm?id=1", "https://item.taobao.com/item.htm?id=1", "https://item.taobao.com/item.htm?id=2"]})
    assert response.status_code == 200
    assert response.json()["created"] == 2
    assert response.json()["collected"] == 2


def test_competitor_intelligence_separates_shops_and_rising_products(client, admin_token):
    headers = auth_headers(admin_token)
    shop = client.post(
        "/api/monitoring/shops",
        headers=headers,
        json={"name": "增长雷达测试店", "priority": "核心", "monitor_frequency": "每日"},
    )
    assert shop.status_code == 200, shop.text
    shop_id = shop.json()["item"]["id"]
    product = client.post(
        "/api/monitoring/products",
        headers=headers,
        json={"shop_id": shop_id, "title": "正在起量的新品", "own_product": "自家对标款"},
    )
    assert product.status_code == 200, product.text
    product_id = product.json()["item"]["id"]

    first = client.post(
        f"/api/monitoring/products/{product_id}/snapshots",
        headers=headers,
        json={"title": "正在起量的新品", "sales_text": "已售100件", "review_count": 10, "price": 59, "status": "active"},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/api/monitoring/products/{product_id}/snapshots",
        headers=headers,
        json={"title": "正在起量的新品", "sales_text": "已售180件", "review_count": 20, "price": 49, "promotion_tags": ["限时优惠"], "status": "active"},
    )
    assert second.status_code == 200, second.text

    intelligence = client.get("/api/monitoring/intelligence", headers=headers)
    assert intelligence.status_code == 200, intelligence.text
    payload = intelligence.json()
    rising = next(item for item in payload["rising_products"] if item["id"] == product_id)
    assert rising["growth_score"] >= 45
    assert rising["growth_level"] == "持续增长"
    assert rising["sales_delta_7d"] == 80
    assert rising["review_delta_7d"] == 10
    assert rising["is_new"] is False
    shop_summary = next(item for item in payload["shops"] if item["id"] == shop_id)
    assert shop_summary["product_count"] == 1
    assert shop_summary["new_product_count"] == 0
    assert shop_summary["rising_product_count"] == 1

    watch_only = client.post(
        "/api/monitoring/products",
        headers=headers,
        json={"shop_id": shop_id, "title": "只有运营动作没有增长"},
    ).json()["item"]["id"]
    client.post(
        f"/api/monitoring/products/{watch_only}/snapshots",
        headers=headers,
        json={"title": "只有运营动作没有增长", "sales_text": "已售100件", "review_count": 10, "price": 59, "status": "active"},
    )
    client.post(
        f"/api/monitoring/products/{watch_only}/snapshots",
        headers=headers,
        json={"title": "只有运营动作没有增长", "sales_text": "已售100件", "review_count": 10, "price": 49, "promotion_tags": ["限时优惠"], "status": "active"},
    )
    refreshed = client.get("/api/monitoring/intelligence", headers=headers).json()
    watch_item = next(item for item in refreshed["products"] if item["id"] == watch_only)
    assert watch_item["growth_level"] == "观察中"
    assert all(item["id"] != watch_only for item in refreshed["rising_products"])

    updated = client.put(
        f"/api/monitoring/products/{product_id}",
        headers=headers,
        json={"alias": "竞品A起量款", "own_product": "自家宽头款"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["item"]["alias"] == "竞品A起量款"

    detail = client.get(f"/api/monitoring/products/{product_id}/detail", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["item"]["display_name"] == "竞品A起量款"
    assert len(detail.json()["snapshots"]) == 2
    assert detail.json()["events"]

    event_id = detail.json()["events"][0]["id"]
    read = client.put(f"/api/monitoring/events/{event_id}", headers=headers, json={"status": "read"})
    assert read.status_code == 200, read.text
    assert read.json()["status"] == "read"


def test_competitor_shop_detail_returns_its_products(client, admin_token):
    headers = auth_headers(admin_token)
    shop_id = client.post("/api/monitoring/shops", headers=headers, json={"name": "竞店详情测试"}).json()["item"]["id"]
    product_id = client.post(
        "/api/monitoring/products",
        headers=headers,
        json={"shop_id": shop_id, "title": "店内商品"},
    ).json()["item"]["id"]
    detail = client.get(f"/api/monitoring/shops/{shop_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["item"]["id"] == shop_id
    assert [item["id"] for item in detail.json()["products"]] == [product_id]


def test_shop_catalog_scan_builds_baseline_then_discovers_new_products(client, admin_token, monkeypatch):
    from backend.app.api import monitoring

    headers = auth_headers(admin_token)
    shop_id = client.post(
        "/api/monitoring/shops",
        headers=headers,
        json={"name": "自动发现新品测试店", "url": "https://new-items.taobao.com/search.htm"},
    ).json()["item"]["id"]
    catalog = [
        {"item_id": "100001", "url": "https://item.taobao.com/item.htm?id=100001", "title": "基线商品A", "image_url": "https://img.example/a.jpg"},
        {"item_id": "100002", "url": "https://item.taobao.com/item.htm?id=100002", "title": "基线商品B", "image_url": ""},
    ]
    monkeypatch.setattr(monitoring, "collect_shop_catalog", lambda _url: catalog)

    baseline = client.post(f"/api/monitoring/shops/{shop_id}/scan", headers=headers)
    assert baseline.status_code == 200, baseline.text
    assert baseline.json()["baseline"] is True
    assert baseline.json()["created"] == 2
    assert baseline.json()["new_products"] == 0
    assert not any(item["event_type"] == "new_product" for item in client.get("/api/monitoring/events", headers=headers).json()["items"])
    baseline_intelligence = client.get("/api/monitoring/intelligence", headers=headers).json()
    assert baseline_intelligence["new_products"] == []
    assert all(item["is_new"] is False for item in baseline_intelligence["products"] if item["shop_id"] == shop_id)

    catalog.append({"item_id": "100003", "url": "https://detail.tmall.com/item.htm?id=100003", "title": "第二次扫描发现的新品", "image_url": "https://img.example/c.jpg"})
    discovered = client.post(f"/api/monitoring/shops/{shop_id}/scan", headers=headers)
    assert discovered.status_code == 200, discovered.text
    assert discovered.json()["baseline"] is False
    assert discovered.json()["created"] == 1
    assert discovered.json()["new_products"] == 1

    products = client.get("/api/monitoring/intelligence", headers=headers).json()["products"]
    new_item = next(item for item in products if item["platform_item_id"] == "100003")
    assert new_item["discovery_source"] == "shop_scan"
    assert new_item["first_seen_at"]
    assert new_item["last_seen_at"]
    assert new_item["is_new"] is True

    events = client.get("/api/monitoring/events", headers=headers).json()["items"]
    new_event = next(item for item in events if item["event_type"] == "new_product")
    assert new_event["product_id"] == new_item["id"]

    repeated = client.post(f"/api/monitoring/shops/{shop_id}/scan", headers=headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["created"] == 0
    assert len([item for item in client.get("/api/monitoring/intelligence", headers=headers).json()["products"] if item["shop_id"] == shop_id]) == 3


def test_shop_scan_requires_shop_url(client, admin_token):
    headers = auth_headers(admin_token)
    shop_id = client.post("/api/monitoring/shops", headers=headers, json={"name": "缺少店铺链接"}).json()["item"]["id"]
    response = client.post(f"/api/monitoring/shops/{shop_id}/scan", headers=headers)
    assert response.status_code == 400
    assert "补充" in response.json()["detail"]


def test_failed_shop_scan_records_attempt_without_marking_baseline_complete(client, admin_token, monkeypatch):
    from backend.app.api import monitoring

    headers = auth_headers(admin_token)
    shop_id = client.post(
        "/api/monitoring/shops",
        headers=headers,
        json={"name": "扫描失败测试店", "url": "https://scan-failed.taobao.com/search.htm"},
    ).json()["item"]["id"]

    def fail_scan(_url):
        raise monitoring.CompetitorScrapeError("淘宝要求安全验证")

    monkeypatch.setattr(monitoring, "collect_shop_catalog", fail_scan)
    response = client.post(f"/api/monitoring/shops/{shop_id}/scan", headers=headers)
    assert response.status_code == 502

    detail = client.get(f"/api/monitoring/shops/{shop_id}", headers=headers).json()["item"]
    assert detail["last_scan_status"] == "failed"
    assert detail["last_scan_attempt_at"]
    assert detail["last_scanned_at"] is None
