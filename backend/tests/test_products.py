import os
import sqlite3

from backend.app.api import products as products_api


def _product(item_id: str, title: str) -> dict:
    return {
        "item_id": item_id,
        "category_id": "500",
        "title": title,
        "image": "https://img.example/item.jpg",
        "price": 29.9,
        "stock": 8,
        "sold_quantity": 99,
        "monthly_sold": 12,
        "quality_score": 95.0,
        "shelf_at": "2026-08-22 10:00",
        "status": "出售中",
        "detail_url": f"https://detail.tmall.com/item.htm?id={item_id}",
        "edit_url": f"https://sell.publish.tmall.com/edit?itemId={item_id}",
    }


def test_product_catalog_sync_replaces_only_after_success(client, monkeypatch):
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    conn.row_factory = sqlite3.Row
    store_id = conn.execute(
        "INSERT INTO stores (name, status, created_at) VALUES (?, 'active', ?)",
        ("商品同步测试店", "2026-08-22T00:00:00"),
    ).lastrowid
    conn.commit()

    monkeypatch.setattr(products_api, "has_profile", lambda _store_id: True)
    monkeypatch.setattr(
        products_api,
        "fetch_on_sale_products",
        lambda _store: [_product("p-1", "商品甲"), _product("p-2", "商品乙")],
    )
    result = products_api.sync_catalog_all(conn, store_id=store_id)
    conn.commit()
    assert result["ok"] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM store_products WHERE store_id = ?", (store_id,)
    ).fetchone()[0] == 2

    def fail(_store):
        raise RuntimeError("淘宝接口暂时失败")

    monkeypatch.setattr(products_api, "fetch_on_sale_products", fail)
    result = products_api.sync_catalog_all(conn, store_id=store_id)
    assert result["ok"] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM store_products WHERE store_id = ?", (store_id,)
    ).fetchone()[0] == 2
    conn.close()


def test_product_list_api(client, admin_token):
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    store_id = conn.execute(
        "INSERT INTO stores (name, status, created_at) VALUES (?, 'active', ?)",
        ("商品列表测试店", "2026-08-22T00:00:00"),
    ).lastrowid
    item = _product("unique-product-123", "唯一商品关键词")
    products_api._save_store_products(conn, store_id, [item], "2026-08-22T12:00:00")
    conn.commit()
    conn.close()

    response = client.get(
        "/api/products?q=唯一商品关键词",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["item_id"] == "unique-product-123"
    assert data["summary"]["low_stock"] == 1

    no_sales = client.get(
        "/api/products?sales_status=no_sales",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert no_sales.status_code == 200
    assert no_sales.json()["total"] == 0

    invalid = client.get(
        "/api/products?sales_status=unknown",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert invalid.status_code == 400


def test_product_alias_survives_sync_and_supports_product_and_review_search(client, admin_token):
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    store_id = conn.execute(
        "INSERT INTO stores (name, status, created_at) VALUES (?, 'active', ?)",
        ("商品备注测试店", "2026-09-14T00:00:00"),
    ).lastrowid
    products_api._save_store_products(
        conn,
        store_id,
        [_product("alias-product-1", "淘宝原始长标题")],
        "2026-09-14T10:00:00",
    )
    conn.commit()
    conn.close()
    headers = {"Authorization": f"Bearer {admin_token}"}

    saved = client.put(
        "/api/products/aliases/alias-product-1",
        headers=headers,
        json={"store_id": store_id, "alias": "主推牙刷", "note": "绿盒装"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["item"]["original_title"] == "淘宝原始长标题"

    listed = client.get(
        f"/api/products?store_id={store_id}&q=主推牙刷",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    item = listed.json()["items"][0]
    assert item["title"] == "主推牙刷"
    assert item["original_title"] == "淘宝原始长标题"
    assert item["product_alias"] == "主推牙刷"
    assert item["alias_note"] == "绿盒装"

    synced_review = client.post(
        "/api/customers/reviews/sync",
        headers=headers,
        json={
            "store_id": store_id,
            "items": [
                {
                    "review_id": "alias-review-1",
                    "item_id": "alias-product-1",
                    "item_title": "淘宝原始长标题",
                    "content": "刷头有点硬",
                }
            ],
        },
    )
    assert synced_review.status_code == 200, synced_review.text
    review_search = client.get(
        f"/api/customers/reviews?store_id={store_id}&q=主推牙刷",
        headers=headers,
    )
    assert review_search.status_code == 200, review_search.text
    assert [row["review_id"] for row in review_search.json()["items"]] == ["alias-review-1"]

    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    products_api._save_store_products(
        conn,
        store_id,
        [_product("alias-product-1", "淘宝同步后的新标题")],
        "2026-09-14T11:00:00",
    )
    conn.commit()
    conn.close()

    after_sync = client.get(
        f"/api/products?store_id={store_id}&q=主推牙刷",
        headers=headers,
    ).json()["items"][0]
    assert after_sync["title"] == "主推牙刷"
    assert after_sync["original_title"] == "淘宝同步后的新标题"

    cleared = client.delete(
        f"/api/products/aliases/alias-product-1?store_id={store_id}",
        headers=headers,
    )
    assert cleared.status_code == 200, cleared.text
    restored = client.get(
        f"/api/products?store_id={store_id}&q=淘宝同步后的新标题",
        headers=headers,
    ).json()["items"][0]
    assert restored["title"] == "淘宝同步后的新标题"
    assert restored["product_alias"] is None


def test_product_list_sorts_all_pages_by_shelf_time(client, admin_token):
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    store_id = conn.execute(
        "INSERT INTO stores (name, status, created_at) VALUES (?, 'active', ?)",
        ("上架时间排序店", "2026-08-26T00:00:00"),
    ).lastrowid
    oldest = _product("shelf-oldest", "最早上架")
    oldest["shelf_at"] = "2024-01-09 18:27"
    newest = _product("shelf-newest", "最近上架")
    newest["shelf_at"] = "2026-08-26 09:30"
    missing = _product("shelf-missing", "无上架时间")
    missing["shelf_at"] = ""
    products_api._save_store_products(
        conn, store_id, [oldest, newest, missing], "2026-08-26T10:00:00"
    )
    conn.commit()
    conn.close()
    headers = {"Authorization": f"Bearer {admin_token}"}

    ascending = client.get(
        f"/api/products?store_id={store_id}&sort_by=shelf_at&sort_order=asc&page_size=2",
        headers=headers,
    )
    assert ascending.status_code == 200, ascending.text
    assert [item["item_id"] for item in ascending.json()["items"]] == [
        "shelf-oldest",
        "shelf-newest",
    ]

    descending = client.get(
        f"/api/products?store_id={store_id}&sort_by=shelf_at&sort_order=desc",
        headers=headers,
    )
    assert descending.status_code == 200, descending.text
    assert [item["item_id"] for item in descending.json()["items"]] == [
        "shelf-newest",
        "shelf-oldest",
        "shelf-missing",
    ]
