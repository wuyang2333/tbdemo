import json

import pytest

from backend.app.core import qianniu
from backend.app.core.qianniu import QianniuError, _parse_dashboard_counts, _parse_product_page


def _sold_html(orders: list[dict], buyer_nick: str = "") -> bytes:
    payload = json.dumps(
        {"error": "", "mainOrders": orders, "query": {"buyerNick": buyer_nick}},
        ensure_ascii=False,
    )
    escaped = json.dumps(payload, ensure_ascii=False)[1:-1]
    return f"<script>var data = JSON.parse('{escaped}');</script>".encode("gb18030")


def _sold_order(
    order_no: str,
    flag: int,
    status_text: str = "买家已付款",
    actual_fee: str = "10.00",
    buyer_nick: str = "测试旺旺",
    create_time: str = "2026-08-25 10:00:00",
) -> dict:
    return {
        "id": order_no,
        "buyer": {"nick": buyer_nick},
        "orderInfo": {"createTime": create_time},
        "extra": {"sellerFlag": flag},
        "statusInfo": {"text": status_text},
        "payInfo": {"actualFee": actual_fee},
        "operations": [
            {
                "id": "flag",
                "dataUrl": f"/trade/json/memoInfo.htm?orderid={order_no}",
                "url": f"/trade/memo/update_sell_memo.htm?biz_order_id={order_no}",
            }
        ],
    }


class _Response:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code


class _Cookies:
    def get(self, name: str):
        return "token" if name == "_tb_token_" else None


class _TradeSession:
    def __init__(self, order_no: str, initial_flag: int = 0, initial_memo: str = "", status_text: str = "买家已付款"):
        self.order_no = order_no
        self.flag = initial_flag
        self.memo = initial_memo
        self.status_text = status_text
        self.cookies = _Cookies()
        self.submissions: list[dict] = []

    def get(self, url, **kwargs):
        return _Response(_sold_html([_sold_order(self.order_no, self.flag, self.status_text)]))

    def post(self, url, data=None, **kwargs):
        if "/trade/json/memoInfo.htm" in url:
            return _Response(json.dumps({"tip": self.memo}).encode("gb18030"))
        self.submissions.append(data)
        self.flag = int(data["flag"])
        self.memo = data["memo"]
        return _Response(b"ok")

    def close(self):
        pass


class _BuyerTradeSession(_TradeSession):
    def __init__(self, orders: list[dict], query_buyer_nick: str | None = None):
        super().__init__(str(orders[0]["id"]) if orders else "")
        self.orders = orders
        self.query_buyer_nick = query_buyer_nick

    def get(self, url, **kwargs):
        params = kwargs.get("params") or {}
        order_no = str(params.get("orderId") or "")
        orders = [order for order in self.orders if str(order.get("id") or "") == order_no] if order_no else self.orders
        orders = [
            {**order, "extra": {**(order.get("extra") or {}), "sellerFlag": self.flag}}
            if str(order.get("id") or "") == self.order_no
            else order
            for order in orders
        ]
        requested_buyer = str(params.get("buyerNick") or "")
        echoed_buyer = self.query_buyer_nick if self.query_buyer_nick is not None else requested_buyer
        return _Response(_sold_html(orders, echoed_buyer))


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


def test_remark_sold_order_submits_red_flag_and_sd(monkeypatch):
    session = _TradeSession("5127193587359094839")
    monkeypatch.setattr(qianniu, "_new_session", lambda store_id: session)

    result = qianniu._remark_sold_order_once(1, session.order_no, "SD", 1, 30)

    assert result == {
        "ok": True,
        "changed": True,
        "outcome": "remarked",
        "order_no": session.order_no,
        "order_status": "买家已付款",
        "actual_paid": 10.0,
        "flag": 1,
        "memo": "SD",
    }
    assert len(session.submissions) == 1
    assert session.submissions[0]["biz_order_id"] == session.order_no
    assert session.submissions[0]["flag"] == "1"
    assert session.submissions[0]["memo"] == "SD"


def test_remark_sold_order_is_idempotent(monkeypatch):
    session = _TradeSession("5127193587359094839", initial_flag=1, initial_memo="SD")
    monkeypatch.setattr(qianniu, "_new_session", lambda store_id: session)

    result = qianniu._remark_sold_order_once(1, session.order_no, "SD", 1, 30)

    assert result["changed"] is False
    assert result["outcome"] == "remarked"
    assert session.submissions == []


@pytest.mark.parametrize(
    ("status_text", "outcome"),
    [("等待买家付款", "awaiting_payment"), ("交易关闭", "order_closed")],
)
def test_remark_sold_order_skips_unremarkable_trade_status(monkeypatch, status_text, outcome):
    session = _TradeSession("5127193587359094839", status_text=status_text)
    monkeypatch.setattr(qianniu, "_new_session", lambda store_id: session)

    result = qianniu._remark_sold_order_once(1, session.order_no, "SD", 1, 30)

    assert result["outcome"] == outcome
    assert result["order_status"] == status_text
    assert result["actual_paid"] == 10.0
    assert session.submissions == []


def test_remark_sold_order_by_buyer_requires_exact_unique_match(monkeypatch):
    session = _BuyerTradeSession([_sold_order("5127193587359094839", 0, buyer_nick="精**")])
    monkeypatch.setattr(qianniu, "_new_session", lambda store_id: session)

    result = qianniu._remark_sold_order_by_buyer_once(
        1,
        "精确旺旺",
        "2026-08-25",
        10,
        "SD",
        1,
        30,
    )

    assert result["outcome"] == "remarked"
    assert result["order_no"] == "5127193587359094839"
    assert len(session.submissions) == 1


def test_remark_sold_order_by_buyer_rejects_ignored_query(monkeypatch):
    session = _BuyerTradeSession(
        [_sold_order("5127193587359094839", 0, buyer_nick="精**")],
        query_buyer_nick="其他旺旺",
    )
    monkeypatch.setattr(qianniu, "_new_session", lambda store_id: session)

    with pytest.raises(qianniu.QianniuError, match="查询条件未生效"):
        qianniu._remark_sold_order_by_buyer_once(
            1,
            "精确旺旺",
            "2026-08-25",
            10,
            "SD",
            1,
            30,
        )

    assert session.submissions == []


def test_remark_sold_order_by_buyer_defers_when_price_differs(monkeypatch):
    session = _BuyerTradeSession(
        [_sold_order("5127193587359094839", 0, actual_fee="12.34", buyer_nick="精确旺旺")]
    )
    monkeypatch.setattr(qianniu, "_new_session", lambda store_id: session)

    result = qianniu._remark_sold_order_by_buyer_once(
        1,
        "精确旺旺",
        "2026-08-25",
        10,
        "SD",
        1,
        30,
    )

    assert result["outcome"] == "price_mismatch"
    assert result["actual_paid"] == 12.34
    assert session.submissions == []


def test_remark_sold_order_by_buyer_rejects_ambiguous_orders(monkeypatch):
    session = _BuyerTradeSession(
        [
            _sold_order("5127193587359094839", 0, buyer_nick="精确旺旺"),
            _sold_order("5127193587359094840", 0, buyer_nick="精确旺旺"),
        ]
    )
    monkeypatch.setattr(qianniu, "_new_session", lambda store_id: session)

    with pytest.raises(qianniu.QianniuAmbiguousOrder):
        qianniu._remark_sold_order_by_buyer_once(
            1,
            "精确旺旺",
            "2026-08-25",
            10,
            "SD",
            1,
            30,
        )

    assert session.submissions == []
