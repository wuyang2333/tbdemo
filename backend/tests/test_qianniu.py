import json

import pytest

from backend.app.core.qianniu import QianniuError, _parse_dashboard_counts, _parse_product_page


def test_parse_dashboard_counts():
    payload = {
        "data": {
            "result": [
                {
                    "todoId": 1,
                    "todoListDetail": [
                        {"count": 433, "uiCode": "notDelivery", "url": "/sold"},
                    ],
                },
                {
                    "todoId": 4,
                    "todoListDetail": [
                        {"count": 180, "url": "/sell-manage-tm/all?current=1"},
                        {"count": 9, "url": "/sell-manage-tm/in_stock?current=1"},
                    ],
                },
            ]
        }
    }

    assert _parse_dashboard_counts(payload) == {
        "pending_shipments": 433,
        "product_count": 180,
    }


def test_parse_dashboard_counts_rejects_incomplete_payload():
    with pytest.raises(QianniuError):
        _parse_dashboard_counts({"data": {"result": []}})


def test_parse_product_page():
    result = {
        "success": True,
        "data": {
            "pagination": {"current": 1, "pageSize": 20, "total": 1},
            "table": {
                "dataSource": [
                    {
                        "itemId": "123",
                        "catId": 456,
                        "itemDesc": {
                            "img": "//img.example/item.jpg",
                            "imgLink": {"href": "https://detail.tmall.com/item.htm?id=123"},
                            "desc": [{"uiType": "link", "text": "测试商品"}],
                        },
                        "managerPrice": {"currentPrice": "¥ 59.90"},
                        "managerQuantityNew": {"text": 12},
                        "soldQuantity_m": 88,
                        "monthlySoldQuantity": {"value": "20"},
                        "diagnoseInfoV3": {"basicScore": 96.5},
                        "upShelfDate_m": {
                            "value": "2026-08-22 12:00",
                            "status": {"text": "出售中"},
                        },
                        "operator_m": [
                            {
                                "name": "editProduct",
                                "href": "//sell.publish.tmall.com/edit?itemId=123",
                            }
                        ],
                    }
                ]
            },
        },
    }
    items, total = _parse_product_page({"data": {"result": json.dumps(result)}})

    assert total == 1
    assert items[0]["item_id"] == "123"
    assert items[0]["title"] == "测试商品"
    assert items[0]["price"] == 59.9
    assert items[0]["stock"] == 12
    assert items[0]["image"].startswith("https:")
    assert items[0]["edit_url"].startswith("https:")
