import json

import pytest

from backend.app.core import competitor_scraper
from backend.app.core.competitor_scraper import CompetitorScrapeError, _canonical_product_url, _parse_browser_data, _wait_for_catalog_page_change, parse_product_page, parse_shop_catalog


def test_parse_public_product_jsonld():
    html = '''
    <html><head><title>页面标题</title>
    <script type="application/ld+json">{"@type":"Product","name":"公开商品标题","image":"https://img.example/a.jpg","offers":{"price":"29.90"},"aggregateRating":{"reviewCount":"123"}}</script>
    </head></html>
    '''
    result = parse_product_page(html, "https://item.taobao.com/item.htm?id=1")
    assert result["title"] == "公开商品标题"
    assert result["price"] == 29.9
    assert result["review_count"] == 123
    assert result["status"] == "active"


def test_parse_unavailable_product_marks_inactive():
    result = parse_product_page("<title>商品已下架</title>", "https://item.taobao.com/item.htm?id=1")
    assert result["status"] == "inactive"


def test_parse_rendered_tmall_product():
    result = _parse_browser_data(
        {
            "url": "https://detail.tmall.com/item.htm?id=1",
            "title": "德国进口宽头软毛牙刷-tmall.com天猫",
            "text": "德国进口宽头软毛牙刷\n已售 1万+\n平台加补后 ￥ 38.61 起\n新品抢购 ￥ 52 起",
            "image": "https://img.example/main.jpg",
        },
        "https://detail.tmall.com/item.htm?id=1",
    )
    assert result["title"] == "德国进口宽头软毛牙刷"
    assert result["price"] == 52
    assert result["coupon_price"] == 38.61
    assert result["sales_text"] == "已售 1万+"


def test_rendered_tmall_review_summary_is_parsed():
    result = _parse_browser_data(
        {
            "url": "https://detail.tmall.com/item.htm?id=1",
            "title": "测试牙刷-tmall.com天猫",
            "text": "测试牙刷\nRUROME旗舰店\n4.8\n88VIP好评率97%\n用户评价·800+\n清洁效果很好27\n使用体验很好26\n质量挺好19\n2026-09-02\n这个牙刷很舒服，清洁到位又不刺激\n查看全部评价\n参数信息",
            "image": "",
        },
        "https://detail.tmall.com/item.htm?id=1",
    )
    assert result["review_count"] == 800
    assert result["review_count_text"] == "800+"
    assert result["rating"] == 4.8
    assert result["good_rate"] == 97
    assert {tag["label"] for tag in result["review_tags"]} == {"清洁效果很好", "使用体验很好", "质量挺好"}
    assert result["review_samples"] == ["这个牙刷很舒服，清洁到位又不刺激"]
    assert "清洁效果很好" in result["review_highlights"]["positive"]


def test_rendered_sku_prices_are_kept_with_the_product():
    result = _parse_browser_data(
        {
            "url": "https://detail.tmall.com/item.htm?id=1",
            "title": "测试商品-tmall.com天猫",
            "text": "测试商品\n平台加补后 ￥ 38.61 起\n新品抢购 ￥ 52 起\n立即购买",
            "image": "",
            "sku_prices": [{"label": "家庭装", "price": 38.61, "list_price": 52}],
        },
        "https://detail.tmall.com/item.htm?id=1",
    )
    assert result["sku_prices"] == [{"label": "家庭装", "price": 38.61, "list_price": 52}]


def test_rendered_product_intelligence_is_parsed():
    result = _parse_browser_data(
        {
            "url": "https://detail.tmall.com/item.htm?id=1",
            "title": "测试商品-tmall.com天猫",
            "text": "测试商品\n颜色分类\n经典白\n曜石黑\n套餐类型\n单支装\n家庭装\n数量\n立即购买\n88VIP会员价再减5元\n88VIP好评率97%\n店铺券满99减10\n88VIP退货包运费假一赔四极速退款7天无理由退换\n7天无理由\n运费险\n核心卖点\n超软刷毛不伤牙龈\n小刷头深入清洁\n参数信息\n用户评价·20\n刷毛太硬3\n2026-09-02\n刷毛有点硬，用着牙龈疼\n图文详情",
            "image": "",
        },
        "https://detail.tmall.com/item.htm?id=1",
    )
    assert result["stock_status"] == "in_stock"
    assert result["sku_options"] == [
        {"name": "颜色分类", "values": ["经典白", "曜石黑"]},
        {"name": "套餐类型", "values": ["单支装", "家庭装"]},
    ]
    assert "88VIP会员价再减5元" in result["promotion_tags"]
    assert "88VIP好评率97%" not in result["promotion_tags"]
    assert not any("退货包运费" in item for item in result["promotion_tags"])
    assert {"7天无理由", "运费险"}.issubset(result["service_tags"])
    assert result["selling_points"] == ["超软刷毛不伤牙龈", "小刷头深入清洁"]
    assert result["negative_keywords"] == [{"label": "刷毛太硬", "count": 3}]
    assert result["negative_review_samples"] == ["刷毛有点硬，用着牙龈疼"]


def test_rendered_login_page_has_actionable_error():
    with pytest.raises(CompetitorScrapeError, match="打开采集浏览器"):
        _parse_browser_data({"url": "https://login.taobao.com/", "title": "登录", "text": "手机扫码登录"}, "https://detail.tmall.com/item.htm?id=1")


def test_security_verification_page_is_not_treated_as_login_ready(monkeypatch):
    class FakeSocket:
        def close(self):
            return None

    monkeypatch.setattr(competitor_scraper, "_targets", lambda _port: [{"type": "page", "webSocketDebuggerUrl": "ws://test"}])
    monkeypatch.setattr(competitor_scraper, "create_connection", lambda *_args, **_kwargs: FakeSocket())
    monkeypatch.setattr(
        competitor_scraper,
        "_cdp_call",
        lambda *_args, **_kwargs: {
            "result": {
                "value": json.dumps({"url": "https://sec.taobao.com/query.htm", "title": "安全验证", "text": "请拖动滑块完成安全验证"}, ensure_ascii=False)
            }
        },
    )

    assert competitor_scraper._probe_login_ready(9222) is False


def test_catalog_pagination_waits_until_product_grid_changes(monkeypatch):
    states = iter([
        {"ready": "complete", "signature": "page-1", "link_count": 20},
        {"ready": "complete", "signature": "page-1", "link_count": 20},
        {"ready": "complete", "signature": "page-2", "link_count": 18},
    ])
    calls = []

    def fake_call(_ws, message_id, _method, _params):
        calls.append(message_id)
        return {"result": {"value": json.dumps(next(states))}}

    monkeypatch.setattr(competitor_scraper, "_cdp_call", fake_call)
    monkeypatch.setattr(competitor_scraper.time, "sleep", lambda _seconds: None)

    message_id, changed = _wait_for_catalog_page_change(object(), 10, "page-1", attempts=5, interval=0)
    assert changed is True
    assert message_id == 13
    assert calls == [11, 12, 13]


def test_catalog_pagination_does_not_advance_when_grid_never_changes(monkeypatch):
    monkeypatch.setattr(
        competitor_scraper,
        "_cdp_call",
        lambda *_args, **_kwargs: {"result": {"value": json.dumps({"ready": "complete", "signature": "page-1", "link_count": 20})}},
    )
    monkeypatch.setattr(competitor_scraper.time, "sleep", lambda _seconds: None)

    message_id, changed = _wait_for_catalog_page_change(object(), 20, "page-1", attempts=4, interval=0)
    assert changed is False
    assert message_id == 24


def test_tmall_tracking_url_is_canonicalized():
    assert _canonical_product_url("https://detail.tmall.com/item.htm?b_s_f=sycm&id=1041863017264&skuId=1") == "https://detail.tmall.com/item.htm?id=1041863017264"


def test_empty_detail_shell_is_not_saved():
    with pytest.raises(CompetitorScrapeError, match="未读取到商品信息"):
        _parse_browser_data({"url": "https://detail.tmall.com/item.htm?id=1", "title": "商品详情", "text": ""}, "https://detail.tmall.com/item.htm?id=1")


def test_shop_catalog_extracts_and_deduplicates_public_product_cards():
    html = '''
    <a href="//item.taobao.com/item.htm?id=123456"><img src="//img.example/1.jpg" alt="宽头牙刷新品"></a>
    <a href="https://item.taobao.com/item.htm?id=123456&spm=test" title="重复链接">重复</a>
    <script>window.items=[{"itemId":"987654","title":"店内第二款","picUrl":"//img.example/2.jpg"}]</script>
    '''
    items = parse_shop_catalog(html, "https://example.taobao.com/search.htm")
    assert [item["item_id"] for item in items] == ["123456", "987654"]
    assert items[0]["url"] == "https://item.taobao.com/item.htm?id=123456"
    assert items[0]["title"] == "宽头牙刷新品"
    assert items[1]["title"] == "店内第二款"


def test_shop_catalog_rejects_non_taobao_domain():
    with pytest.raises(CompetitorScrapeError, match="淘宝或天猫店铺链接"):
        parse_shop_catalog("", "https://example.com/shop")
