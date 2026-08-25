"""千牛工作台实时经营状态抓取。"""

from __future__ import annotations

import hashlib
import json
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from curl_cffi import requests

from backend.app.core.scrape_guard import exclusive_scrape
from backend.app.core.scrape_resilience import (
    ensure_login_available,
    is_login_error,
    retry_with_backoff,
    trip_login_circuit,
)
from backend.app.core.sycm import profile_path


_TODO_API = "mtop.tmall.tmallwork.todoList"
_PRODUCT_LIST_API = "mtop.tmall.sell.pc.manage.async"
_APP_KEY = "12574478"
_VERSION = "1.0"
_REFERER = "https://myseller.taobao.com/home.htm/QnworkbenchHome/"
_PRODUCT_REFERER = "https://myseller.taobao.com/home.htm/SellManage/on_sale"
_PRODUCT_LIST_URL = "/tmall/manager/table.htm"
_TTID = "11320@taobao_WEB_9.9.99"
_PRODUCT_PAGE_SIZE = 20
_SOLD_LIST_URL = "https://trade.taobao.com/trade/itemlist/list_sold_items.htm"
_SOLD_QUERY_ACTION = "itemlist/SoldQueryAction"
_SELL_MEMO_ACTION = "memo/UpdateSellMemoAction"


class QianniuError(Exception):
    """带用户可读信息的千牛抓取错误。"""


class QianniuOrderNotFound(QianniuError):
    """千牛已卖出商品中没有精确匹配的订单。"""


class QianniuAmbiguousOrder(QianniuError):
    """旺旺号匹配到多条无法安全区分的订单。"""


def _load_cookies(store_id: int) -> dict[str, str]:
    path = profile_path(store_id)
    if not path.exists():
        raise QianniuError("该店铺还没有绑定淘宝登录，请先在店铺管理完成登录")
    try:
        cookies = json.loads(path.read_text(encoding="utf-8")).get("cookies") or {}
    except (OSError, ValueError) as exc:
        raise QianniuError("淘宝登录档案读取失败，请重新登录") from exc
    if "_tb_token_" not in cookies:
        raise QianniuError("淘宝登录档案已失效，请重新登录")
    return {str(key): str(value) for key, value in cookies.items()}


def _h5_token(session: requests.Session) -> str:
    tokens = [
        cookie.value
        for cookie in session.cookies.jar
        if cookie.name == "_m_h5_tk" and "taobao.com" in cookie.domain
    ]
    return (tokens[-1] if tokens else "x_0").split("_", 1)[0]


def _new_session(store_id: int) -> requests.Session:
    session = requests.Session(impersonate="chrome120")
    for name, value in _load_cookies(store_id).items():
        session.cookies.set(name, value, domain=".taobao.com", path="/")
    return session


def _request_mtop(
    session: requests.Session,
    api: str,
    data_obj: dict,
    timeout: float,
    referer: str,
) -> dict:
    data = json.dumps(data_obj, separators=(",", ":"), ensure_ascii=False)
    url = f"https://h5api.m.taobao.com/h5/{api.lower()}/{_VERSION}/"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
        "User-Agent": "Mozilla/5.0",
    }
    for _ in range(3):
        timestamp = str(int(time.time() * 1000))
        sign_text = f"{_h5_token(session)}&{timestamp}&{_APP_KEY}&{data}"
        params = {
            "jsv": "2.6.1",
            "appKey": _APP_KEY,
            "t": timestamp,
            "sign": hashlib.md5(sign_text.encode("utf-8")).hexdigest(),  # nosec B324
            "api": api,
            "v": _VERSION,
            "type": "originaljson",
            "dataType": "json",
            "ttid": _TTID,
            "data": data,
        }
        try:
            response = session.get(url, params=params, headers=headers, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            raise QianniuError("千牛工作台请求失败，请稍后重试") from exc
        if response.status_code != 200:
            raise QianniuError(f"千牛工作台接口异常（HTTP {response.status_code}）")
        try:
            payload = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise QianniuError("千牛工作台返回异常，请稍后重试") from exc
        ret = payload.get("ret") or []
        if any(str(item).startswith("SUCCESS") for item in ret):
            return payload
        if any("TOKEN" in str(item) for item in ret):
            continue
        message = str(ret[0]).split("::", 1)[-1] if ret else "未知错误"
        raise QianniuError(f"千牛工作台返回失败：{message}")
    raise QianniuError("千牛登录已过期，请重新登录")


def _request_todo_list(store_id: int, timeout: float) -> dict:
    session = _new_session(store_id)
    try:
        with exclusive_scrape():
            return _request_mtop(
                session,
                _TODO_API,
                {"bizParams": "{}"},
                timeout,
                _REFERER,
            )
    finally:
        session.close()


def _trade_headers(referer: str = _SOLD_LIST_URL) -> dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml,application/json,*/*",
        "Referer": referer,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    }


def _parse_sold_page(content: bytes) -> dict:
    text = content.decode("gb18030", errors="replace")
    match = re.search(r"var data = JSON\.parse\('(.*?)'\);", text, re.DOTALL)
    if not match:
        if "login.taobao.com" in text or "登录" in text:
            raise QianniuError("千牛登录已过期，请重新登录")
        raise QianniuError("千牛已卖出商品页面返回异常")
    try:
        serialized = json.loads(f'"{match.group(1)}"')
        payload = json.loads(serialized)
    except (TypeError, ValueError) as exc:
        raise QianniuError("千牛订单查询结果解析失败") from exc
    if not isinstance(payload, dict):
        raise QianniuError("千牛订单查询结果格式异常")
    error = str(payload.get("error") or "").strip()
    if error:
        raise QianniuError(f"千牛订单查询失败：{error}")
    return payload


def _query_sold_order(session: requests.Session, order_no: str, timeout: float) -> dict | None:
    try:
        response = session.get(
            _SOLD_LIST_URL,
            params={
                "action": _SOLD_QUERY_ACTION,
                "event_submit_do_query": "1",
                "orderId": order_no,
                "_input_charset": "utf8",
            },
            headers=_trade_headers(),
            timeout=timeout,
        )
    except requests.exceptions.RequestException as exc:
        raise QianniuError("千牛订单查询请求失败，请稍后重试") from exc
    if response.status_code != 200:
        raise QianniuError(f"千牛订单查询接口异常（HTTP {response.status_code}）")
    payload = _parse_sold_page(response.content)
    matches = [item for item in payload.get("mainOrders") or [] if str(item.get("id") or "") == order_no]
    if len(matches) > 1:
        raise QianniuError(f"千牛返回了多条相同订单号：{order_no}")
    return matches[0] if matches else None


def _query_sold_orders_by_buyer(session: requests.Session, buyer_nick: str, timeout: float) -> list[dict]:
    try:
        response = session.get(
            _SOLD_LIST_URL,
            params={
                "action": _SOLD_QUERY_ACTION,
                "event_submit_do_query": "1",
                "orderId": "",
                "buyerNick": buyer_nick,
                "_input_charset": "utf8",
            },
            headers=_trade_headers(),
            timeout=timeout,
        )
    except requests.exceptions.RequestException as exc:
        raise QianniuError("千牛旺旺号查询请求失败，请稍后重试") from exc
    if response.status_code != 200:
        raise QianniuError(f"千牛旺旺号查询接口异常（HTTP {response.status_code}）")
    payload = _parse_sold_page(response.content)
    query = payload.get("query") or {}
    if not isinstance(query, dict) or str(query.get("buyerNick") or "").strip() != buyer_nick:
        raise QianniuError("千牛旺旺号查询条件未生效，已停止自动备注")
    return [item for item in payload.get("mainOrders") or [] if isinstance(item, dict)]


def _order_date(order: dict) -> str:
    created_at = str((order.get("orderInfo") or {}).get("createTime") or "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", created_at)
    return match.group(0) if match else ""


def _amount_matches(actual_paid, expected_amount) -> bool:
    try:
        actual = Decimal(str(actual_paid)).quantize(Decimal("0.01"))
        expected = Decimal(str(expected_amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return abs(actual - expected) < Decimal("0.01")


def _memo_operation(order: dict) -> dict:
    operation = next(
        (
            item
            for item in order.get("operations") or []
            if item.get("id") == "flag" and item.get("url") and item.get("dataUrl")
        ),
        None,
    )
    if not operation:
        raise QianniuError("该千牛订单不支持卖家备注")
    return operation


def _order_status_outcome(order: dict) -> tuple[str, str]:
    status_text = str((order.get("statusInfo") or {}).get("text") or "").strip()
    compact = re.sub(r"\s+", "", status_text)
    if "交易关闭" in compact or "订单关闭" in compact:
        return "order_closed", status_text
    if "等待买家付款" in compact or "待买家付款" in compact or "等待付款" in compact:
        return "awaiting_payment", status_text
    return "", status_text


def _actual_paid_amount(order: dict) -> float | None:
    value = (order.get("payInfo") or {}).get("actualFee")
    if value is None or str(value).strip() == "":
        return None
    try:
        amount = float(str(value).replace("¥", "").replace("￥", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if amount < 0 or amount > 999999:
        return None
    return round(amount, 2)


def _read_seller_memo(session: requests.Session, operation: dict, timeout: float) -> str:
    url = urljoin(_SOLD_LIST_URL, str(operation["dataUrl"]))
    try:
        response = session.post(url, headers=_trade_headers(), timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise QianniuError("千牛卖家备注读取失败，请稍后重试") from exc
    if response.status_code != 200:
        raise QianniuError(f"千牛卖家备注读取异常（HTTP {response.status_code}）")
    try:
        payload = json.loads(response.content.decode("gb18030", errors="replace"))
    except ValueError as exc:
        raise QianniuError("千牛卖家备注返回格式异常") from exc
    return str(payload.get("tip") or "")


def _submit_seller_memo(
    session: requests.Session,
    operation: dict,
    order_no: str,
    memo: str,
    flag: int,
    timeout: float,
) -> None:
    url = urljoin(_SOLD_LIST_URL, str(operation["url"]))
    form = {
        "_tb_token_": session.cookies.get("_tb_token_") or "",
        "event_submit_do_query": "1",
        "action": _SELL_MEMO_ACTION,
        "user_type": "1",
        "pageNum": "1",
        "auctionTitle": "",
        "dateBegin": "0",
        "dateEnd": "0",
        "commentStatus": "",
        "buyerNick": "",
        "auctionStatus": "",
        "returnUrl": "",
        "logisticsService": "",
        "from_flag": "",
        "biz_order_id": order_no,
        "flag": str(flag),
        "memo": memo,
    }
    try:
        response = session.post(url, data=form, headers=_trade_headers(), timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise QianniuError("千牛插旗备注提交失败，请稍后重试") from exc
    if response.status_code != 200:
        raise QianniuError(f"千牛插旗备注接口异常（HTTP {response.status_code}）")


def _remark_matched_order(
    session: requests.Session,
    order: dict,
    memo: str,
    flag: int,
    timeout: float,
) -> dict:
    order_no = str(order.get("id") or "")
    outcome, order_status = _order_status_outcome(order)
    actual_paid = _actual_paid_amount(order)
    if outcome:
        return {
            "ok": True,
            "changed": False,
            "outcome": outcome,
            "order_no": order_no,
            "order_status": order_status,
            "actual_paid": actual_paid,
            "flag": flag,
            "memo": memo,
        }
    operation = _memo_operation(order)
    current_memo = _read_seller_memo(session, operation, timeout)
    current_flag = int((order.get("extra") or {}).get("sellerFlag") or 0)
    if current_flag == flag and current_memo == memo:
        return {
            "ok": True,
            "changed": False,
            "outcome": "remarked",
            "order_no": order_no,
            "order_status": order_status,
            "actual_paid": actual_paid,
            "flag": flag,
            "memo": memo,
        }
    _submit_seller_memo(session, operation, order_no, memo, flag, timeout)
    verified = _query_sold_order(session, order_no, timeout)
    if not verified:
        raise QianniuError("千牛插旗备注后无法再次确认订单")
    verified_operation = _memo_operation(verified)
    verified_memo = _read_seller_memo(session, verified_operation, timeout)
    verified_flag = int((verified.get("extra") or {}).get("sellerFlag") or 0)
    if verified_flag != flag or verified_memo != memo:
        raise QianniuError("千牛插旗备注结果校验失败")
    return {
        "ok": True,
        "changed": True,
        "outcome": "remarked",
        "order_no": order_no,
        "order_status": order_status,
        "actual_paid": _actual_paid_amount(verified),
        "flag": flag,
        "memo": memo,
    }


def _remark_sold_order_once(
    store_id: int,
    order_no: str,
    memo: str,
    flag: int,
    timeout: float,
) -> dict:
    session = _new_session(store_id)
    try:
        with exclusive_scrape():
            order = _query_sold_order(session, order_no, timeout)
            if not order:
                raise QianniuOrderNotFound(f"千牛已卖出商品中未找到订单 {order_no}")
            return _remark_matched_order(session, order, memo, flag, timeout)
    finally:
        session.close()


def _remark_sold_order_by_buyer_once(
    store_id: int,
    buyer_nick: str,
    order_date: str,
    expected_amount,
    memo: str,
    flag: int,
    timeout: float,
) -> dict:
    session = _new_session(store_id)
    try:
        with exclusive_scrape():
            candidates = [
                order
                for order in _query_sold_orders_by_buyer(session, buyer_nick, timeout)
                if _order_date(order) == order_date
            ]
            if not candidates:
                raise QianniuOrderNotFound(f"千牛已卖出商品中未找到旺旺号 {buyer_nick} 在 {order_date} 的订单")
            amount_matches = [
                order for order in candidates if _amount_matches(_actual_paid_amount(order), expected_amount)
            ]
            if len(amount_matches) == 1:
                selected = amount_matches[0]
            elif len(candidates) == 1:
                selected = candidates[0]
            else:
                raise QianniuAmbiguousOrder(f"旺旺号 {buyer_nick} 在 {order_date} 匹配到多条订单，已停止自动备注")
            actual_paid = _actual_paid_amount(selected)
            outcome, order_status = _order_status_outcome(selected)
            if outcome:
                return _remark_matched_order(session, selected, memo, flag, timeout)
            if not _amount_matches(actual_paid, expected_amount):
                return {
                    "ok": True,
                    "changed": False,
                    "outcome": "price_mismatch",
                    "order_no": str(selected.get("id") or ""),
                    "order_status": order_status,
                    "actual_paid": actual_paid,
                    "flag": flag,
                    "memo": memo,
                }
            return _remark_matched_order(session, selected, memo, flag, timeout)
    finally:
        session.close()


def _parse_dashboard_counts(payload: dict) -> dict[str, int]:
    groups = ((payload.get("data") or {}).get("result") or [])
    pending_shipments: int | None = None
    product_count: int | None = None
    for group in groups:
        if not isinstance(group, dict):
            continue
        details = group.get("todoListDetail") or []
        for detail in details:
            if not isinstance(detail, dict):
                continue
            if detail.get("uiCode") == "notDelivery":
                pending_shipments = int(detail.get("count") or 0)
            url = str(detail.get("url") or "")
            if int(group.get("todoId") or 0) == 4 and (
                "/sell-manage-tm/all" in url or "status=item_on_sale" in url
            ):
                product_count = int(detail.get("count") or 0)
    if pending_shipments is None:
        raise QianniuError("千牛接口未返回待发货数量")
    if product_count is None:
        raise QianniuError("千牛接口未返回在售商品数量")
    return {
        "pending_shipments": pending_shipments,
        "product_count": product_count,
    }


def _number(value, default: float = 0.0) -> float:
    try:
        return float(str(value).replace("¥", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _product_title(item: dict) -> str:
    desc = (item.get("itemDesc") or {}).get("desc") or []
    for part in desc:
        if isinstance(part, dict) and part.get("uiType") == "link" and part.get("text"):
            return str(part["text"])
    return str(item.get("title") or "")


def _product_edit_url(item: dict) -> str:
    for operation in item.get("operator_m") or []:
        if isinstance(operation, dict) and operation.get("name") == "editProduct":
            url = str(operation.get("href") or "")
            return "https:" + url if url.startswith("//") else url
    return ""


def _parse_product_page(payload: dict) -> tuple[list[dict], int]:
    result = (payload.get("data") or {}).get("result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError as exc:
            raise QianniuError("千牛商品列表返回异常，请稍后重试") from exc
    if not isinstance(result, dict) or result.get("success") is not True:
        message = str((result or {}).get("msg") or "商品列表加载失败")
        raise QianniuError(f"千牛商品列表返回失败：{message}")
    data = result.get("data") or {}
    table = data.get("table") or {}
    rows = table.get("dataSource")
    pagination = data.get("pagination") or {}
    if not isinstance(rows, list) or "total" not in pagination:
        raise QianniuError("千牛商品列表接口结构已变化")
    products: list[dict] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("itemId"):
            continue
        item_desc = row.get("itemDesc") or {}
        image = str(item_desc.get("img") or "")
        if image.startswith("//"):
            image = "https:" + image
        detail_url = str((item_desc.get("imgLink") or {}).get("href") or "")
        if detail_url.startswith("//"):
            detail_url = "https:" + detail_url
        shelf_info = row.get("upShelfDate_m") or {}
        products.append(
            {
                "item_id": str(row["itemId"]),
                "category_id": str(row.get("catId") or ""),
                "title": _product_title(row),
                "image": image,
                "price": round(_number((row.get("managerPrice") or {}).get("currentPrice")), 2),
                "stock": int(_number((row.get("managerQuantityNew") or {}).get("text"))),
                "sold_quantity": int(_number(row.get("soldQuantity_m"))),
                "monthly_sold": int(_number((row.get("monthlySoldQuantity") or {}).get("value"))),
                "quality_score": round(_number((row.get("diagnoseInfoV3") or {}).get("basicScore")), 1),
                "shelf_at": str(shelf_info.get("value") or ""),
                "status": str((shelf_info.get("status") or {}).get("text") or "出售中"),
                "detail_url": detail_url,
                "edit_url": _product_edit_url(row),
            }
        )
    return products, int(_number(pagination.get("total")))


def _fetch_on_sale_products_once(store_id: int, timeout: float) -> list[dict]:
    session = _new_session(store_id)
    products: list[dict] = []
    page = 1
    total = 0
    try:
        with exclusive_scrape():
            while True:
                json_body = {
                    "tab": "on_sale",
                    "pagination": {"current": page, "pageSize": _PRODUCT_PAGE_SIZE},
                    "filtertab": "",
                    "filter": {},
                    "table": {},
                }
                payload = _request_mtop(
                    session,
                    _PRODUCT_LIST_API,
                    {
                        "url": _PRODUCT_LIST_URL,
                        "jsonBody": json.dumps(json_body, separators=(",", ":"), ensure_ascii=False),
                    },
                    timeout,
                    _PRODUCT_REFERER,
                )
                rows, total = _parse_product_page(payload)
                products.extend(rows)
                if len(products) >= total or len(rows) < _PRODUCT_PAGE_SIZE:
                    break
                page += 1
                if page > 500:
                    raise QianniuError("千牛商品列表分页异常")
    finally:
        session.close()
    deduped = {item["item_id"]: item for item in products}
    if len(deduped) != total:
        raise QianniuError(f"千牛商品列表不完整（抓取 {len(deduped)} / 应有 {total}）")
    return list(deduped.values())


def fetch_dashboard_counts(store: dict, timeout: float = 30) -> dict[str, int]:
    """读取千牛首页的待发货与出售中商品数量。"""
    store_id = int(store["id"])
    profile = profile_path(store_id)
    ensure_login_available("qianniu", store_id, profile, QianniuError)

    def _fetch() -> dict[str, int]:
        return _parse_dashboard_counts(_request_todo_list(store_id, timeout))

    try:
        return retry_with_backoff(_fetch)
    except QianniuError as exc:
        if is_login_error(exc):
            trip_login_circuit("qianniu", store_id, profile, str(exc))
        raise


def fetch_on_sale_products(store: dict, timeout: float = 30) -> list[dict]:
    """读取千牛“我的商品-出售中”完整商品列表。"""
    store_id = int(store["id"])
    profile = profile_path(store_id)
    ensure_login_available("qianniu", store_id, profile, QianniuError)
    try:
        return retry_with_backoff(lambda: _fetch_on_sale_products_once(store_id, timeout))
    except QianniuError as exc:
        if is_login_error(exc):
            trip_login_circuit("qianniu", store_id, profile, str(exc))
        raise


def remark_sold_order(
    store: dict,
    order_no: str,
    memo: str = "SD",
    flag: int = 1,
    timeout: float = 30,
) -> dict:
    """在千牛已卖出商品中精确匹配订单，并设置卖家备注与旗子。"""
    store_id = int(store["id"])
    order_no = str(order_no or "").strip()
    if not order_no.isdigit():
        raise QianniuError("千牛订单号格式不正确")
    if not memo or len(memo) > 500:
        raise QianniuError("千牛卖家备注内容不正确")
    if flag not in (1, 2, 3, 4, 5):
        raise QianniuError("千牛插旗颜色不正确")
    profile = profile_path(store_id)
    ensure_login_available("qianniu", store_id, profile, QianniuError)
    try:
        return retry_with_backoff(lambda: _remark_sold_order_once(store_id, order_no, memo, flag, timeout))
    except QianniuError as exc:
        if is_login_error(exc):
            trip_login_circuit("qianniu", store_id, profile, str(exc))
        raise


def remark_sold_order_by_buyer(
    store: dict,
    buyer_nick: str,
    order_date: str,
    expected_amount,
    memo: str = "SD",
    flag: int = 1,
    timeout: float = 30,
) -> dict:
    """无订单号时按旺旺号、日期和金额唯一匹配订单，再设置备注与旗子。"""
    store_id = int(store["id"])
    buyer_nick = str(buyer_nick or "").strip()
    order_date = str(order_date or "").strip()
    if not buyer_nick or len(buyer_nick) > 100:
        raise QianniuError("千牛旺旺号格式不正确")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", order_date):
        raise QianniuError("礼品单下单日期格式不正确，无法按旺旺号查询")
    if not memo or len(memo) > 500:
        raise QianniuError("千牛卖家备注内容不正确")
    if flag not in (1, 2, 3, 4, 5):
        raise QianniuError("千牛插旗颜色不正确")
    profile = profile_path(store_id)
    ensure_login_available("qianniu", store_id, profile, QianniuError)
    try:
        return retry_with_backoff(
            lambda: _remark_sold_order_by_buyer_once(
                store_id,
                buyer_nick,
                order_date,
                expected_amount,
                memo,
                flag,
                timeout,
            )
        )
    except QianniuError as exc:
        if is_login_error(exc):
            trip_login_circuit("qianniu", store_id, profile, str(exc))
        raise
