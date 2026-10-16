"""公开竞品商品页采集：只读取页面公开信息，不绕过登录、验证码或风控。"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from curl_cffi import requests
from websocket import create_connection

from backend.app.core.scrape_guard import exclusive_scrape
from backend.app.core.scrape_resilience import retry_with_backoff


class CompetitorScrapeError(Exception):
    """给用户展示的竞品采集错误。"""


_BROWSER_ROOT = Path(os.environ.get("COMPETITOR_BROWSER_DIR") or (Path.home() / ".taobao-cli" / "competitor-browser"))
_PROFILE_DIR = _BROWSER_ROOT / "profile"
_PORT_FILE = _BROWSER_ROOT / "cdp-port"
_PID_FILE = _BROWSER_ROOT / "browser-pid"
_MODE_FILE = _BROWSER_ROOT / "browser-mode"
_READY_FILE = _BROWSER_ROOT / "login-ready"
_LOGIN_URL = "https://login.taobao.com/"


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CompetitorScrapeError("商品链接无效，请粘贴完整的淘宝/天猫商品链接")


def _canonical_product_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    params = urllib.parse.parse_qs(parsed.query)
    item_id = (params.get("id") or [""])[0]
    host = (parsed.hostname or "").lower()
    if item_id.isdigit() and ("taobao.com" in host or "tmall.com" in host):
        domain = "detail.tmall.com" if "tmall.com" in host else "item.taobao.com"
        return f"https://{domain}/item.htm?id={item_id}"
    return url


def _validate_shop_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host or not any(domain in host for domain in ("taobao.com", "tmall.com")):
        raise CompetitorScrapeError("店铺链接无效，请粘贴完整的淘宝或天猫店铺链接")


def _catalog_item_id(url: str) -> str:
    parsed = urllib.parse.urlsplit(html.unescape(url))
    return (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0]


def _catalog_item(url: str, title: str = "", image_url: str = "") -> dict[str, str] | None:
    absolute = urllib.parse.urljoin("https://www.taobao.com/", html.unescape(url).replace("\\/", "/"))
    item_id = _catalog_item_id(absolute)
    if not item_id.isdigit():
        return None
    return {
        "item_id": item_id,
        "url": _canonical_product_url(absolute),
        "title": re.sub(r"\s+", " ", html.unescape(title)).strip()[:300] or f"待采集商品 {item_id}",
        "image_url": urllib.parse.urljoin(absolute, html.unescape(image_url).replace("\\/", "/")) if image_url else "",
    }


def parse_shop_catalog(html_text: str, shop_url: str) -> list[dict[str, str]]:
    """Extract public product cards from a Taobao/Tmall shop response."""
    _validate_shop_url(shop_url)
    decoded = html.unescape(html_text.replace("\\/", "/"))
    found: dict[str, dict[str, str]] = {}
    link_pattern = re.compile(r"(?:href|url)\s*[=:]\s*[\"']([^\"']*(?:item\.taobao\.com|detail\.tmall\.com)[^\"']*item\.htm[^\"']*id=\d+[^\"']*)[\"']", re.I)
    for match in link_pattern.finditer(decoded):
        window = decoded[max(0, match.start() - 350):min(len(decoded), match.end() + 700)]
        title = _first_text([r'alt\s*=\s*["\']([^"\']{2,300})["\']', r'(?:title|itemTitle|rawTitle|name)\s*[=:]\s*["\']([^"\']{2,300})["\']'], window)
        image_url = _first_text([r'(?:src|data-src|picUrl|imageUrl)\s*[=:]\s*["\']([^"\']+)["\']'], window)
        item = _catalog_item(match.group(1), title, image_url)
        if item:
            found.setdefault(item["item_id"], item)
    for match in re.finditer(r'["\'](?:itemId|item_id|auctionId|nid)["\']\s*:\s*["\']?(\d{6,})', decoded, re.I):
        item_id = match.group(1)
        window = decoded[max(0, match.start() - 500):min(len(decoded), match.end() + 900)]
        title = _first_text([r'["\'](?:title|itemTitle|rawTitle|name)["\']\s*:\s*["\']([^"\']{2,300})["\']'], window)
        image_url = _first_text([r'["\'](?:picUrl|imageUrl|image|pic)["\']\s*:\s*["\']([^"\']+)["\']'], window)
        item = _catalog_item(f"https://item.taobao.com/item.htm?id={item_id}", title, image_url)
        if item and item_id not in found:
            found[item_id] = item
    return list(found.values())[:300]


def _first_text(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            value = html.unescape(match.group(1)).strip()
            if value:
                return value
    return ""


def _jsonld_product(html_text: str) -> dict[str, Any]:
    for raw in re.findall(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", html_text, re.I | re.S):
        try:
            payload = json.loads(html.unescape(raw.strip()))
        except (TypeError, ValueError):
            continue
        values = payload if isinstance(payload, list) else payload.get("@graph", []) if isinstance(payload, dict) else []
        if isinstance(payload, dict) and payload.get("@type") == "Product":
            values = [payload]
        for item in values:
            if not isinstance(item, dict) or item.get("@type") != "Product":
                continue
            offers = item.get("offers") if isinstance(item.get("offers"), dict) else {}
            rating = item.get("aggregateRating") if isinstance(item.get("aggregateRating"), dict) else {}
            image = item.get("image")
            if isinstance(image, list):
                image = image[0] if image else ""
            return {
                "title": str(item.get("name") or ""),
                "price": offers.get("price"),
                "review_count": rating.get("reviewCount"),
                "review_count_text": str(rating.get("reviewCount") or ""),
                "rating": rating.get("ratingValue"),
                "image_url": str(image or ""),
            }
    return {}


def _number(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return None
    number = float(match.group(0))
    return int(number) if number.is_integer() else number


def _count_number(value: Any) -> int | None:
    """解析评价/销量类数量，兼容 1.2万、800+ 等展示。"""
    if value is None or value == "":
        return None
    raw = str(value).replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", raw)
    if not match:
        return None
    number = float(match.group(0))
    if "万" in raw:
        number *= 10000
    return int(number)


def _review_section(text: str) -> str:
    matches = list(re.finditer(r"(?:用户评价|累计评价|商品评价)", text))
    if not matches:
        return text
    start = next((match for match in matches if re.match(r"\s*[·:：]?\s*\d", text[match.end():])), matches[-1])
    tail = text[start.start():]
    end_positions = [pos for pos in (tail.find("参数信息"), tail.find("图文详情")) if pos > 0]
    return tail[: min(end_positions)] if end_positions else tail


def _review_tags(text: str) -> list[dict[str, Any]]:
    section = _review_section(text)
    first_date = re.search(r"(?m)^\d{4}[-/]\d{1,2}[-/]\d{1,2}$", section)
    if first_date:
        section = section[:first_date.start()]
    tags: list[dict[str, Any]] = []
    for line in section.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        match = re.match(r"^([^\d\n]{2,24}?)(\d{1,5})$", line)
        if not match:
            continue
        label = match.group(1).strip(" ·:：")
        if label in {"用户评价", "累计评价", "商品评价"} or not label:
            continue
        tags.append({"label": label, "count": int(match.group(2))})
    return tags[:20]


def _review_samples(text: str) -> list[str]:
    section = _review_section(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in section.splitlines()]
    samples: list[str] = []
    date_pattern = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")
    for index, line in enumerate(lines):
        if not date_pattern.match(line):
            continue
        for candidate in lines[index + 1:index + 4]:
            if len(candidate) >= 8 and re.search(r"[\u4e00-\u9fff]", candidate) and not date_pattern.match(candidate):
                samples.append(candidate[:240])
                break
        if len(samples) >= 5:
            break
    return samples


_CONCERN_WORDS = ("差", "刺", "破损", "慢", "失望", "不好", "漏", "问题", "异味", "掉", "硬", "疼", "贵", "小", "少", "一般", "不值", "瑕疵")


def _negative_review_data(tags: list[dict[str, Any]], samples: list[str]) -> dict[str, list[Any]]:
    """从公开评价标签和近期评价中提取可复核的风险，不虚构情绪分数。"""
    keywords = [item for item in tags if any(word in str(item.get("label") or "") for word in _CONCERN_WORDS)]
    negative_samples = [sample for sample in samples if any(word in sample for word in _CONCERN_WORDS)]
    return {"negative_keywords": keywords[:10], "negative_review_samples": negative_samples[:5]}


def _review_highlights(tags: list[dict[str, Any]]) -> dict[str, list[str]]:
    positive_words = ("好", "棒", "高", "满意", "推荐", "舒服", "清洁", "护龈", "柔软", "质量", "体验", "方便", "回购", "赞")
    positive, concerns = [], []
    for item in tags:
        label = str(item.get("label") or "")
        if any(word in label for word in _CONCERN_WORDS):
            concerns.append(label)
        elif any(word in label for word in positive_words):
            positive.append(label)
    return {"positive": positive[:10], "concerns": concerns[:10]}


def _review_data(text: str, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    source = existing or {}
    section = _review_section(text)
    review_match = _first_text(
        [
            r"(?:用户评价|累计评价|商品评价|评价数|评论数)\s*[·:：]?\s*([0-9]+(?:\.[0-9]+)?万?\+?)",
            r"([0-9]+(?:\.[0-9]+)?万?\+?)\s*(?:人)?评价",
        ],
        section,
    )
    review_count_text = review_match or str(source.get("review_count_text") or "")
    review_count = _count_number(review_count_text) or _count_number(source.get("review_count"))
    rating = _number(
        _first_text(
            [r"(?:店铺评分|商品评分|评分)\s*[：:·]?\s*([0-5](?:\.[0-9])?)", r"旗舰店\s*\n\s*([0-5](?:\.[0-9])?)"],
            text,
        )
    ) or _number(source.get("rating"))
    good_rate = _number(_first_text([r"(?:好评率|好评)\s*([0-9]+(?:\.[0-9]+)?)%"], text)) or _number(source.get("good_rate"))
    tags = _review_tags(text) or source.get("review_tags") or []
    samples = _review_samples(text) or source.get("review_samples") or []
    highlights = _review_highlights(tags)
    if not highlights["positive"] and not highlights["concerns"]:
        highlights = source.get("review_highlights") or highlights
    risk_data = _negative_review_data(tags, samples)
    return {
        "review_count": review_count,
        "review_count_text": review_count_text,
        "rating": rating,
        "good_rate": good_rate,
        "review_tags": tags,
        "review_samples": samples,
        "review_highlights": highlights,
        **risk_data,
    }


def _clean_lines(text: str) -> list[str]:
    lines, seen = [], set()
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", html.unescape(raw)).strip(" ·|｜")
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


def _sku_options(text: str) -> list[dict[str, Any]]:
    """提取商品页当前公开展示的规格组和值；不模拟购买，也不猜测隐藏库存。"""
    lines = _clean_lines(text)
    header_pattern = re.compile(r"^(颜色分类|颜色|规格|款式|套餐(?:类型)?|尺码|尺寸|净含量|容量|版本|数量规格)[：:]?$")
    stop_pattern = re.compile(r"^(数量|配送|服务|保障|立即购买|加入购物车|用户评价|累计评价|商品评价|参数信息|图文详情)")
    noise_pattern = re.compile(r"可开发票|回头客|加购|平台|优惠|领券|满减|限时|预计|快递|发货|运费|退货|退款|支付|切换|免费试用|已享受|热卖|下单|服务|保障")
    options: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        header = header_pattern.match(lines[index])
        if not header:
            index += 1
            continue
        values: list[str] = []
        index += 1
        while index < len(lines) and len(values) < 20:
            line = lines[index]
            if header_pattern.match(line) or stop_pattern.match(line) or len(line) > 40 or noise_pattern.search(line):
                break
            if 1 <= len(line) <= 40 and not re.search(r"[￥¥]|已售|评价|优惠|领券|月销|库存", line):
                values.append(line)
            index += 1
        if values:
            options.append({"name": header.group(1), "values": values})
        if len(options) >= 8:
            break
    return options


def _product_intelligence(text: str) -> dict[str, Any]:
    lines = _clean_lines(text)
    promotion_pattern = re.compile(r"满减|满折|优惠券|店铺券|跨店|限时|会员价|赠品|买一送|第二件|第2件|多件|淘金币|官方立减|平台加补|以旧换新|券.{0,12}减|满\d+(?:\.\d+)?(?:元)?减")
    promotions = [
        line for line in lines
        if 2 <= len(line) <= 60 and (promotion_pattern.search(line) or ("88VIP" in line and re.search(r"价|折|减|优惠|券", line)))
    ]

    service_patterns = (
        r"7天无理由", r"七天无理由", r"运费险", r"破损包退", r"极速退款", r"极速退货",
        r"假一赔(?:三|四|十)", r"正品保障", r"全国包邮", r"包邮", r"送货入户", r"晚发必赔", r"过敏包退",
    )
    services = []
    for pattern in service_patterns:
        match = re.search(pattern, text, re.I)
        if match and match.group(0) not in services:
            services.append(match.group(0))

    selling_points: list[str] = []
    for index, line in enumerate(lines):
        if re.fullmatch(r"(?:核心|产品|商品)?卖点[：:]?", line):
            for candidate in lines[index + 1:index + 7]:
                if re.match(r"^(参数信息|图文详情|用户评价|累计评价|服务|保障)", candidate):
                    break
                if 3 <= len(candidate) <= 60:
                    selling_points.append(candidate)
            break

    if re.search(r"(?:已售罄|暂时缺货|暂时无货|该地区无货|无货)", text):
        stock_status = "out_of_stock"
    elif re.search(r"(?:仅剩|库存紧张|即将售罄)\s*\d*", text):
        stock_status = "low_stock"
    elif re.search(r"(?:现货|有货|立即购买|加入购物车)", text):
        stock_status = "in_stock"
    else:
        stock_status = "unknown"
    return {
        "sku_options": _sku_options(text),
        "stock_status": stock_status,
        "promotion_tags": promotions[:15],
        "service_tags": services[:12],
        "selling_points": selling_points[:8],
    }


def _visible_text(html_text: str) -> str:
    text = re.sub(r"<(?:script|style)[^>]*>.*?</(?:script|style)>", "\n", html_text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", "\n", text)
    return html.unescape(text)


def parse_product_page(html_text: str, url: str) -> dict[str, Any]:
    data = _jsonld_product(html_text)
    title = data.get("title") or _first_text([r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', r'<title[^>]*>(.*?)</title>', r'"(?:title|itemTitle|subject)"\s*:\s*"(.*?)"'], html_text)
    title = re.sub(r"\s+", " ", html.unescape(title)).strip()
    if not title:
        raise CompetitorScrapeError("页面未读取到商品标题，可能需要登录或触发了安全验证")
    price = _number(data.get("price")) or _number(_first_text([r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\'](.*?)["\']', r'"(?:price|skuPrice|currentPrice)"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)'], html_text))
    review_data = _review_data(html_text, data)
    intelligence = _product_intelligence(_visible_text(html_text))
    review_count = review_data["review_count"]
    image_url = data.get("image_url") or _first_text([r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']', r'"(?:picUrl|image|imgUrl)"\s*:\s*"(https?[^"\\]+)"'], html_text)
    status = "inactive" if any(marker in html_text for marker in ("商品已下架", "宝贝不存在", "该商品已失效", "已售罄")) else "active"
    sales_text = _first_text([r'"(?:sellCount|soldCount)"\s*:\s*"?([^,}\"]+)', r'已售\s*([0-9万+.]+)'], html_text)
    return {"title": title, "url": url, "price": price, "coupon_price": None, "review_count": review_count, "review_count_text": review_data["review_count_text"], "rating": review_data["rating"], "good_rate": review_data["good_rate"], "review_tags": review_data["review_tags"], "review_samples": review_data["review_samples"], "review_highlights": review_data["review_highlights"], "negative_keywords": review_data["negative_keywords"], "negative_review_samples": review_data["negative_review_samples"], **intelligence, "sales_text": sales_text, "image_url": html.unescape(image_url).strip(), "status": status}


def _browser_path() -> Path:
    candidates = []
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.extend((Path(base) / "Google/Chrome/Application/chrome.exe", Path(base) / "Microsoft/Edge/Application/msedge.exe"))
    for name in ("chrome.exe", "msedge.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise CompetitorScrapeError("未找到 Chrome 或 Edge，无法启动竞品采集浏览器")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _targets(port: int) -> list[dict[str, Any]]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:  # nosec B310 - localhost only
            data = json.loads(response.read().decode("utf-8"))
            return data if isinstance(data, list) else []
    except (OSError, ValueError, urllib.error.URLError):
        return []


def _probe_login_ready(port: int) -> bool:
    """检查可见采集浏览器是否已离开淘宝登录页。只读取页面状态，不操作页面。"""
    for target in _targets(port):
        if target.get("type") != "page" or not target.get("webSocketDebuggerUrl"):
            continue
        ws = None
        try:
            ws = create_connection(str(target["webSocketDebuggerUrl"]), timeout=2, suppress_origin=True)
            result = _cdp_call(ws, int(time.time() * 1000) % 1000000, "Runtime.evaluate", {
                "expression": "JSON.stringify({url:location.href,title:document.title,text:(document.body?.innerText||'').slice(0,5000)})",
                "returnByValue": True,
            })
            raw = (result.get("result") or {}).get("value")
            data = json.loads(raw) if raw else {}
            current_url = str(data.get("url") or "")
            body = str(data.get("text") or "")
            title = str(data.get("title") or "")
            is_login = "login.taobao.com" in current_url or any(marker in body for marker in ("手机扫码登录", "密码登录", "短信登录"))
            needs_verification = any(marker in body for marker in ("滑块", "安全验证", "访问过于频繁", "操作过于频繁", "验证码"))
            looks_like_product = any(marker in body for marker in ("用户评价", "累计评价", "商品评价", "已售", "加入购物车", "立即购买"))
            if not is_login and not needs_verification and (looks_like_product or (title and "淘宝" not in title and "登录" not in title and "验证" not in title)):
                return True
        except (OSError, ValueError, TypeError, CompetitorScrapeError):
            continue
        finally:
            if ws is not None:
                try:
                    ws.close()
                except OSError:
                    pass
    return False


def browser_status() -> dict[str, Any]:
    login_ready = _READY_FILE.exists()
    try:
        mode = _MODE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        mode = ""
    try:
        port = int(_PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        connected = False
        port = None
    else:
        pages = [item for item in _targets(port) if item.get("type") == "page"]
        connected = bool(pages)
        port = port if connected else None
    if connected and not login_ready and port and _probe_login_ready(port):
        try:
            _READY_FILE.touch()
            login_ready = True
        except OSError:
            pass
    if login_ready:
        state = "ready"
        message = "已具备后台自动采集条件"
    elif connected:
        state = "login_required"
        message = "采集浏览器已打开，完成首次淘宝登录后即可后台采集"
    else:
        state = "not_configured"
        message = "尚未保存采集登录状态；只有遇到需要登录或安全验证时才需要打开窗口"
    return {"connected": connected, "login_ready": login_ready, "headless": mode == "headless", "state": state, "message": message, "port": port}


def _stop_managed_browser() -> None:
    """停止本模块启动的浏览器，释放 profile 供可见登录窗口使用。"""
    try:
        pid = int(_PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = 0
    if pid > 0:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill.exe", "/PID", str(pid), "/T", "/F"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.kill(pid, 15)
        except (OSError, subprocess.SubprocessError):
            pass
    for path in (_PID_FILE, _PORT_FILE, _MODE_FILE):
        try:
            path.unlink()
        except OSError:
            pass


def _start_browser(destination: str, *, headless: bool) -> dict[str, Any]:
    _BROWSER_ROOT.mkdir(parents=True, exist_ok=True)
    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    browser = _browser_path()
    args = [str(browser), f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1", "--remote-allow-origins=*", f"--user-data-dir={_PROFILE_DIR}", "--no-first-run", "--no-default-browser-check"]
    if headless:
        args.extend(("--headless=new", "--disable-extensions"))
    else:
        args.extend(("--new-window",))
    args.append(destination)
    process = subprocess.Popen(  # nosec B603 - resolved local browser executable
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _PORT_FILE.write_text(str(port), encoding="utf-8")
    _PID_FILE.write_text(str(process.pid), encoding="utf-8")
    _MODE_FILE.write_text("headless" if headless else "visible", encoding="utf-8")
    deadline = time.time() + 10
    while time.time() < deadline:
        if _targets(port):
            return {
                "opened": True,
                "connected": True,
                "port": port,
                "login_ready": _READY_FILE.exists(),
                "headless": headless,
                "state": "ready" if _READY_FILE.exists() else "login_required",
                "message": "后台采集浏览器已启动" if headless else "采集浏览器已打开，请完成淘宝登录；后续采集可后台运行",
            }
        time.sleep(0.25)
    _stop_managed_browser()
    raise CompetitorScrapeError("采集浏览器启动超时，请稍后重试")


def open_collection_browser(url: str = "") -> dict[str, Any]:
    status = browser_status()
    destination = url or _LOGIN_URL
    if status.get("connected") and status.get("headless"):
        _stop_managed_browser()
        status = browser_status()
    try:
        _READY_FILE.unlink()
    except OSError:
        pass
    if status.get("connected"):
        port = int(status["port"])
        request = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(destination, safe='')}", method="PUT")
        try:
            urllib.request.urlopen(request, timeout=3).close()  # nosec B310 - localhost only
        except OSError:
            pass
        return {
            "opened": True,
            "connected": True,
            "login_ready": _READY_FILE.exists(),
            "headless": False,
            "state": "ready" if _READY_FILE.exists() else "login_required",
            "message": "采集浏览器已打开，请完成淘宝登录；后续采集可后台运行",
        }
    return _start_browser(destination, headless=False)


def _cdp_call(ws, message_id: int, method: str, params: dict | None = None) -> dict:
    ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
    while True:
        message = json.loads(ws.recv())
        if message.get("id") == message_id:
            if message.get("error"):
                raise CompetitorScrapeError(f"浏览器采集失败：{message['error']}")
            return message.get("result") or {}


_CATALOG_PAGE_STATE_EXPRESSION = r"""
JSON.stringify((() => {
  const links = Array.from(document.querySelectorAll('a[href*="item.htm"],a[href*="detail.tmall.com"]'));
  const active = document.querySelector(
    '.next-pagination-item-active,.pagination-item-active,[class*="pagination"] [class*="active"],[aria-current="page"]'
  );
  return {
    ready: document.readyState,
    signature: location.href + '|' + (active?.textContent || '').trim() + '|' + links.slice(0, 5).map(link => link.href || link.getAttribute('href') || '').join('|'),
    link_count: links.length,
  };
})())
"""


def _wait_for_catalog_page_change(ws, message_id: int, previous_signature: str, *, attempts: int = 10, interval: float = 0.8) -> tuple[int, bool]:
    """Wait until the next catalog page actually replaces the current product grid."""
    for _ in range(attempts):
        time.sleep(interval)
        message_id += 1
        result = _cdp_call(
            ws,
            message_id,
            "Runtime.evaluate",
            {"expression": _CATALOG_PAGE_STATE_EXPRESSION, "returnByValue": True},
        )
        value = (result.get("result") or {}).get("value")
        state = json.loads(value) if value else {}
        if state.get("ready") in {"interactive", "complete"} and int(state.get("link_count") or 0) > 0 and str(state.get("signature") or "") != previous_signature:
            return message_id, True
    return message_id, False


def _clean_sku_label(value: str) -> str:
    value = re.sub(r"^(?:免费试用[⭐★]?\s*)+", "", value).strip()
    return re.sub(r"\s+", " ", value)


def _collect_sku_prices(ws, message_id: int) -> list[dict[str, Any]]:
    """逐个选择公开 SKU 并读取页面展示价；仅操作规格选择，不触发购买。"""
    expression = r"""
    (async () => {
      const groupEls = Array.from(document.querySelectorAll('#skuOptionsArea [class*="skuItem--"]'))
        .filter(group => group.querySelector('[class*="valueItem--"][data-vid]'));
      const groups = groupEls.map(group => ({
        name: (group.querySelector('[class*="ItemLabel--"]')?.innerText || '规格').trim(),
        values: Array.from(group.querySelectorAll('[class*="valueItem--"][data-vid]'))
          .filter(option => option.dataset.disabled !== 'true')
          .map(option => ({
            vid: option.dataset.vid,
            label: (option.querySelector('span[title]')?.getAttribute('title') || option.innerText || '').trim(),
          })),
      })).filter(group => group.values.length);
      let combinations = [[]];
      for (const group of groups) {
        combinations = combinations.flatMap(combo => group.values.map(value => [...combo, { group: group.name, ...value }])).slice(0, 40);
      }
      const amount = text => {
        const match = String(text || '').replace(/,/g, '').match(/\d+(?:\.\d+)?/);
        return match ? Number(match[0]) : null;
      };
      const readAmount = async selector => {
        for (let attempt = 0; attempt < 8; attempt += 1) {
          const value = amount(document.querySelector(selector)?.textContent || '');
          if (value !== null) return value;
          await new Promise(resolve => setTimeout(resolve, 150));
        }
        return null;
      };
      const items = [];
      for (const combination of combinations) {
        let valid = true;
        for (const choice of combination) {
          const option = document.querySelector(`#skuOptionsArea [class*="valueItem--"][data-vid="${choice.vid}"]`);
          if (!option || option.dataset.disabled === 'true') { valid = false; break; }
          option.click();
          await new Promise(resolve => setTimeout(resolve, 250));
        }
        if (!valid) continue;
        const price = await readAmount('[class*="highlightPrice--"]');
        const listPrice = await readAmount('[class*="subPrice--"]');
        items.push({
          options: Object.fromEntries(combination.map(choice => [choice.group, choice.label])),
          price,
          list_price: listPrice,
        });
      }
      return JSON.stringify(items);
    })()
    """
    try:
        result = _cdp_call(ws, message_id, "Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        raw = (result.get("result") or {}).get("value")
        items = json.loads(raw) if raw else []
    except (CompetitorScrapeError, TypeError, ValueError):
        return []
    cleaned = []
    for item in items if isinstance(items, list) else []:
        options = {str(name): _clean_sku_label(str(value)) for name, value in (item.get("options") or {}).items()}
        label = " / ".join(value for value in options.values() if value)
        if not label:
            continue
        cleaned.append({"label": label, "options": options, "price": _number(item.get("price")), "list_price": _number(item.get("list_price"))})
    return cleaned


def _parse_browser_data(data: dict[str, Any], url: str) -> dict[str, Any]:
    current_url = str(data.get("url") or "")
    body = str(data.get("text") or "")
    if "login.taobao.com" in current_url or "手机扫码登录" in body or "密码登录" in body:
        raise CompetitorScrapeError("竞品采集浏览器尚未登录淘宝，请先点击“打开采集浏览器”完成登录")
    if any(marker in body for marker in ("滑块", "安全验证", "访问过于频繁")):
        raise CompetitorScrapeError("淘宝要求安全验证，请在采集浏览器完成验证后重试")
    raw_title = str(data.get("title") or "")
    title = re.sub(r"-(?:tmall\.com天猫|淘宝网).*$", "", raw_title, flags=re.I).strip()
    if not title or title in {"登录", "商品详情", "页面加载中", "淘宝网 - 淘！我喜欢"} or len(body) < 20:
        raise CompetitorScrapeError("采集浏览器未读取到商品信息，请确认商品页已正常打开")
    coupon_price = _number(_first_text([r"(?:平台加补后|券后|到手价)\s*[￥¥]\s*([0-9]+(?:\.[0-9]+)?)"], body))
    price = _number(_first_text([r"(?:新品抢购|活动价|价格)\s*[￥¥]\s*([0-9]+(?:\.[0-9]+)?)", r"[￥¥]\s*([0-9]+(?:\.[0-9]+)?)"], body))
    sales = _first_text([r"(已售\s*[0-9万+.]+)"], body)
    review_data = _review_data(body)
    intelligence = _product_intelligence(body)
    sku_prices = data.get("sku_prices") if isinstance(data.get("sku_prices"), list) else []
    if sku_prices and sku_prices[0].get("price") is None and coupon_price is not None:
        sku_prices[0]["price"] = coupon_price
    if sku_prices and sku_prices[0].get("list_price") is None and price is not None:
        sku_prices[0]["list_price"] = price
    review_count = review_data["review_count"]
    status = "inactive" if any(marker in body for marker in ("商品已下架", "宝贝不存在", "该商品已失效", "已售罄")) else "active"
    return {"title": title, "url": url, "price": price, "coupon_price": coupon_price, "review_count": review_count, "review_count_text": review_data["review_count_text"], "rating": review_data["rating"], "good_rate": review_data["good_rate"], "review_tags": review_data["review_tags"], "review_samples": review_data["review_samples"], "review_highlights": review_data["review_highlights"], "negative_keywords": review_data["negative_keywords"], "negative_review_samples": review_data["negative_review_samples"], "sku_prices": sku_prices, **intelligence, "sales_text": sales, "image_url": str(data.get("image") or ""), "status": status}


def collect_product_from_browser(url: str) -> dict[str, Any]:
    _validate_url(url)
    url = _canonical_product_url(url)
    status = browser_status()
    started_headless = False
    if status.get("connected") and status.get("headless") and not status.get("login_ready"):
        _stop_managed_browser()
        status = browser_status()
    if not status.get("connected"):
        if not status.get("login_ready"):
            raise CompetitorScrapeError("淘宝限制了后台直连，请点击“打开采集浏览器”，登录一次后系统即可自动采集")
        status = _start_browser(url, headless=True)
        started_headless = True
    port = int(status["port"])
    request = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(url, safe='')}", method="PUT")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310 - localhost only
            target = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise CompetitorScrapeError("无法连接竞品采集浏览器，请重新打开采集浏览器") from exc
    ws_url = str(target.get("webSocketDebuggerUrl") or "")
    if not ws_url:
        raise CompetitorScrapeError("采集浏览器没有返回商品页连接")
    ws = create_connection(ws_url, timeout=20, suppress_origin=True)
    try:
        deadline = time.time() + 15
        data: dict[str, Any] = {}
        message_id = 0
        while time.time() < deadline:
            time.sleep(1)
            message_id += 1
            result = _cdp_call(ws, message_id, "Runtime.evaluate", {"expression": "JSON.stringify({title:document.title,url:location.href,text:(document.body?.innerText||'').slice(0,60000),image:document.querySelector('img[id*=mainPic],img[class*=mainPic],[class*=picGallery] img')?.src||''})", "returnByValue": True})
            value = (result.get("result") or {}).get("value")
            if value:
                data = json.loads(value)
                body_text = str(data.get("text") or "")
                review_loaded = bool(re.search(r"(?:用户评价|累计评价|商品评价)\s*[·:：]?\s*\d", body_text))
                if data.get("title") and len(body_text) > 100 and (review_loaded or message_id >= 8):
                    break
        data["sku_prices"] = _collect_sku_prices(ws, message_id + 100)
        try:
            result = _parse_browser_data(data, url)
        except CompetitorScrapeError as exc:
            needs_attention = any(marker in str(exc) for marker in ("尚未登录", "安全验证", "未读取到商品信息"))
            if needs_attention:
                try:
                    _READY_FILE.unlink()
                except OSError:
                    pass
            if started_headless and needs_attention:
                raise CompetitorScrapeError("后台采集需要确认淘宝登录或安全验证，请打开采集浏览器处理一次；处理后会继续后台采集") from exc
            raise
        _READY_FILE.touch()
        result["_collection_method"] = "hidden_browser" if status.get("headless") else "browser"
        return result
    finally:
        ws.close()
        target_id = str(target.get("id") or "")
        if target_id:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{target_id}", timeout=2).close()  # nosec B310 - localhost only
            except OSError:
                pass


def collect_shop_catalog_from_browser(url: str) -> list[dict[str, str]]:
    """Read visible product cards from a managed browser shop page."""
    _validate_shop_url(url)
    status = browser_status()
    started_headless = False
    if status.get("connected") and status.get("headless") and not status.get("login_ready"):
        _stop_managed_browser()
        status = browser_status()
    if not status.get("connected"):
        if not status.get("login_ready"):
            raise CompetitorScrapeError("淘宝限制了店铺目录访问，请点击“打开采集浏览器”，登录一次后系统即可自动扫描")
        status = _start_browser(url, headless=True)
        started_headless = True
    port = int(status["port"])
    request = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(url, safe='')}", method="PUT")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310 - localhost only
            target = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise CompetitorScrapeError("无法连接竞品采集浏览器，请重新打开采集浏览器") from exc
    ws_url = str(target.get("webSocketDebuggerUrl") or "")
    if not ws_url:
        raise CompetitorScrapeError("采集浏览器没有返回店铺页面连接")
    ws = create_connection(ws_url, timeout=25, suppress_origin=True)
    try:
        found: dict[str, dict[str, str]] = {}
        signatures: set[str] = set()
        message_id = 0
        expression = r"""
        (async () => {
          let previousHeight = 0;
          let stableRounds = 0;
          for (let index = 0; index < 10; index += 1) {
            window.scrollTo(0, document.body.scrollHeight);
            await new Promise(resolve => setTimeout(resolve, 450));
            const currentHeight = document.body.scrollHeight;
            stableRounds = currentHeight === previousHeight ? stableRounds + 1 : 0;
            previousHeight = currentHeight;
            if (stableRounds >= 2) break;
          }
          const links = Array.from(document.querySelectorAll('a[href*="item.htm"],a[href*="detail.tmall.com"]')).map(anchor => ({
            url: anchor.href || anchor.getAttribute('href') || '',
            title: (anchor.getAttribute('title') || anchor.querySelector('[title]')?.getAttribute('title') || anchor.innerText || anchor.querySelector('img')?.alt || '').trim(),
            image_url: anchor.querySelector('img')?.currentSrc || anchor.querySelector('img')?.src || '',
          }));
          window.scrollTo(0, 0);
          const candidates = Array.from(document.querySelectorAll('a[rel="next"],a,button'));
          const next = candidates.find(element => {
            const text = (element.innerText || element.getAttribute('aria-label') || '').trim();
            const disabled = element.disabled || element.getAttribute('aria-disabled') === 'true' || /disabled/.test(element.className || '');
            const pagination = element.closest('[class*="pagination"],[class*="pager"],.J_Pager');
            const looksLikeNext = /^(下一页|下页|Next|>|›|»|下一页>?)$/i.test(text) || element.getAttribute('rel') === 'next' || (pagination && /(?:^|[-_\s])next(?:$|[-_\s])/.test(String(element.className || '')));
            return element.offsetParent !== null && !disabled && looksLikeNext;
          });
          const active = document.querySelector('.next-pagination-item-active,.pagination-item-active,[class*="pagination"] [class*="active"],[aria-current="page"]');
          return JSON.stringify({url: location.href, title: document.title, text: (document.body?.innerText || '').slice(0, 12000), html: document.documentElement.outerHTML.slice(0, 500000), signature: location.href + '|' + (active?.textContent || '').trim() + '|' + links.slice(0,5).map(x => x.url).join('|'), links, has_next: Boolean(next)});
        })()
        """
        for page_index in range(8):
            time.sleep(1 if page_index else 2)
            message_id += 1
            result = _cdp_call(ws, message_id, "Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
            value = (result.get("result") or {}).get("value")
            data = json.loads(value) if value else {}
            current_url = str(data.get("url") or "")
            body = str(data.get("text") or "")
            if "login.taobao.com" in current_url or any(marker in body for marker in ("手机扫码登录", "密码登录", "短信登录")):
                raise CompetitorScrapeError("竞品采集浏览器尚未登录淘宝，请先完成登录")
            if any(marker in body for marker in ("滑块", "安全验证", "访问过于频繁")):
                raise CompetitorScrapeError("淘宝要求安全验证，请在采集浏览器完成验证后重试")
            signature = str(data.get("signature") or "")
            if signature in signatures:
                break
            signatures.add(signature)
            for raw in data.get("links") or []:
                item = _catalog_item(str(raw.get("url") or ""), str(raw.get("title") or ""), str(raw.get("image_url") or ""))
                if item:
                    found.setdefault(item["item_id"], item)
            if not found:
                for item in parse_shop_catalog(str(data.get("html") or ""), url):
                    found.setdefault(item["item_id"], item)
            if not data.get("has_next"):
                break
            message_id += 1
            click_result = _cdp_call(ws, message_id, "Runtime.evaluate", {"expression": r"""(() => { const next=Array.from(document.querySelectorAll('a[rel="next"],a,button')).find(element => { const text=(element.innerText||element.getAttribute('aria-label')||'').trim(); const disabled=element.disabled||element.getAttribute('aria-disabled')==='true'||/disabled/.test(element.className||''); const pagination=element.closest('[class*="pagination"],[class*="pager"],.J_Pager'); const looksLikeNext=/^(下一页|下页|Next|>|›|»|下一页>?)$/i.test(text)||element.getAttribute('rel')==='next'||(pagination&&/(?:^|[-_\s])next(?:$|[-_\s])/.test(String(element.className||''))); return element.offsetParent!==null&&!disabled&&looksLikeNext; }); if(next){next.scrollIntoView({block:'center'});next.click();return true;} return false;})()""", "returnByValue": True})
            clicked = bool((click_result.get("result") or {}).get("value"))
            if not clicked:
                break
            message_id, changed = _wait_for_catalog_page_change(ws, message_id, signature)
            if not changed:
                raise CompetitorScrapeError("店铺翻页后商品列表没有更新，请稍后重试或检查店铺分页")
        if not found:
            raise CompetitorScrapeError("店铺页面暂未读取到商品列表，请确认链接能打开店铺全部商品页面")
        _READY_FILE.touch()
        return list(found.values())[:300]
    except CompetitorScrapeError as exc:
        needs_attention = any(marker in str(exc) for marker in ("尚未登录", "安全验证", "未读取到"))
        if needs_attention:
            try:
                _READY_FILE.unlink()
            except OSError:
                pass
        if started_headless and needs_attention:
            raise CompetitorScrapeError("后台扫描需要确认淘宝登录或安全验证，请打开采集浏览器处理一次") from exc
        raise
    finally:
        ws.close()
        target_id = str(target.get("id") or "")
        if target_id:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{target_id}", timeout=2).close()  # nosec B310 - localhost only
            except OSError:
                pass


def collect_shop_catalog(url: str, timeout: float = 20.0) -> list[dict[str, str]]:
    """Collect a shop's currently visible public catalog, falling back to the managed browser."""
    _validate_shop_url(url)

    def request() -> str:
        with exclusive_scrape():
            response = requests.get(url, impersonate="chrome120", headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"}, timeout=timeout)
        if response.status_code in {401, 403, 429}:
            raise CompetitorScrapeError(f"店铺页面暂时无法访问（HTTP {response.status_code}）")
        if response.status_code >= 400:
            raise CompetitorScrapeError(f"店铺页面返回异常（HTTP {response.status_code}）")
        return response.content.decode(response.encoding or "utf-8", errors="replace")

    public_items: list[dict[str, str]] = []
    try:
        content = retry_with_backoff(request, delays=(1, 3), sleep=lambda _delay: None)
        public_items = parse_shop_catalog(content, url)
    except Exception:
        pass
    if browser_status().get("login_ready"):
        return collect_shop_catalog_from_browser(url)
    if public_items:
        return public_items
    return collect_shop_catalog_from_browser(url)


def collect_product(url: str, timeout: float = 20.0) -> dict[str, Any]:
    _validate_url(url)

    def request() -> str:
        with exclusive_scrape():
            response = requests.get(url, impersonate="chrome120", headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"}, timeout=timeout)
        if response.status_code in {401, 403, 429}:
            raise CompetitorScrapeError(f"商品页暂时无法访问（HTTP {response.status_code}），请稍后再试")
        if response.status_code >= 400:
            raise CompetitorScrapeError(f"商品页返回异常（HTTP {response.status_code}）")
        return response.content.decode(response.encoding or "utf-8", errors="replace")

    try:
        content = retry_with_backoff(request, delays=(1, 3), sleep=lambda _delay: None)
        result = parse_product_page(content, url)
        if not result.get("sku_prices") and browser_status().get("login_ready"):
            return collect_product_from_browser(url)
        result["_collection_method"] = "request"
        return result
    except Exception:
        return collect_product_from_browser(url)
