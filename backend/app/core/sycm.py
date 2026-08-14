"""生意参谋数据抓取适配：使用店铺保存的登录凭证调用生意参谋接口，解析为每日指标。"""

from __future__ import annotations

from datetime import date

import httpx

SYCM_HOME = "https://sycm.taobao.com"


class SycmError(Exception):
    """带用户可读信息的抓取错误。"""


def _headers(store: dict) -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Cookie": (store.get("sycm_cookie") or "").strip(),
        "Referer": f"{SYCM_HOME}/",
    }


def check_sycm_login(store: dict) -> dict:
    """用保存的 Cookie 访问生意参谋首页，验证登录态是否有效。"""
    cookie = (store.get("sycm_cookie") or "").strip()
    if not cookie:
        raise SycmError("还没有配置生意参谋登录凭证（Cookie），请先在店铺管理填写")
    try:
        resp = httpx.get(f"{SYCM_HOME}/", headers=_headers(store), timeout=30, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise SycmError(f"无法连接生意参谋：{exc}") from exc
    text = resp.text
    if resp.status_code >= 400 or ("login" in resp.url.path.lower() and "portal" not in resp.url.path.lower()):
        raise SycmError("登录凭证已失效，请到店铺管理重新粘贴生意参谋 Cookie")
    if "登录" in text and "工作台" not in text:
        raise SycmError("登录凭证已失效（页面显示需要登录），请重新粘贴 Cookie")
    return {"ok": True}


def fetch_store_daily(store: dict, target_date: str | None = None) -> dict:
    """抓取单个店铺指定日期的核心指标。

    返回 {date, visitors, pv, sales, orders, conversion_rate}
    真实生意参谋接口需要签名参数且接口地址不对外公开；接入时请用浏览器抓包
    拿到的地址/参数替换下方 url 与解析逻辑（或把抓包请求发给我来对接）。
    """
    check_sycm_login(store)
    target = target_date or date.today().isoformat()

    # TODO: 用真实抓包地址替换。下方先请求数据服务入口，验证连通性。
    url = f"{SYCM_HOME}/mc/portal/dwq/index.htm"
    try:
        resp = httpx.get(url, headers=_headers(store), timeout=30, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise SycmError(f"无法连接生意参谋数据服务：{exc}") from exc
    if resp.status_code >= 400:
        raise SycmError(f"生意参谋数据服务返回错误（HTTP {resp.status_code}）")

    # 真实接口返回 JSON；字段名以实际抓包为准。这里做防御性解析。
    try:
        data = resp.json()
    except ValueError as exc:
        raise SycmError(
            "生意参谋数据服务返回的不是 JSON（接口地址或参数待对接）。"
            "请在浏览器开发者工具 → 网络 里找到生意参谋的数据请求，"
            "右键 Copy as cURL 发给我，我把它接上即可。"
        ) from exc

    # TODO: 按真实返回结构映射字段
    return {
        "date": target,
        "visitors": 0,
        "pv": 0,
        "sales": 0.0,
        "orders": 0,
        "conversion_rate": 0.0,
    }
