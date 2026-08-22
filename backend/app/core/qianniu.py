"""千牛工作台实时经营状态抓取。"""

from __future__ import annotations

import hashlib
import json
import time

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


class QianniuError(Exception):
    """带用户可读信息的千牛抓取错误。"""


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
