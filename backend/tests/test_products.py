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
