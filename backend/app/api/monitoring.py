from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.api.auth import get_current_user
from backend.app.core.competitor_scraper import CompetitorScrapeError, browser_status, collect_product, collect_shop_catalog, open_collection_browser
from backend.app.core.db import get_db

router = APIRouter()
SECTIONS = [{"id": k, "name": n} for k, n in (("overview", "竞品总览"), ("shops", "竞店管理"), ("products", "竞品管理"), ("reports", "竞品报告"))]

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _platform_item_id(url: str) -> str:
    match = re.search(r"(?:[?&]|&amp;)id=(\d+)", str(url or ""))
    return match.group(1) if match else ""

class ShopIn(BaseModel):
    name: str
    url: str = ""
    competitor_type: str = "direct"
    priority: str = "重点"
    category: str = ""
    price_band: str = ""
    notes: str = ""
    monitor_frequency: str = "每日"

class ProductIn(BaseModel):
    shop_id: int
    title: str = ""
    url: str = ""
    own_product: str = ""
    price: float | None = None
    coupon_price: float | None = None
    review_count: int | None = None
    review_count_text: str = ""
    rating: float | None = None
    good_rate: float | None = None
    review_tags: list[dict] = Field(default_factory=list)
    review_samples: list[str] = Field(default_factory=list)
    review_highlights: dict[str, list[str]] = Field(default_factory=dict)
    negative_keywords: list[dict] = Field(default_factory=list)
    negative_review_samples: list[str] = Field(default_factory=list)
    sku_options: list[dict] = Field(default_factory=list)
    sku_prices: list[dict] = Field(default_factory=list)
    stock_status: str = "unknown"
    promotion_tags: list[str] = Field(default_factory=list)
    service_tags: list[str] = Field(default_factory=list)
    selling_points: list[str] = Field(default_factory=list)
    sales_text: str = ""
    image_url: str = ""


class ProductUpdateIn(BaseModel):
    alias: str = Field(default="", max_length=80)
    own_product: str = Field(default="", max_length=200)


class EventStatusIn(BaseModel):
    status: str = Field(pattern="^(new|read|ignored|actioned)$")

class ProductBatchIn(BaseModel):
    shop_id: int
    urls: list[str]
    own_product: str = ""

class EventIn(BaseModel):
    shop_id: int | None = None
    product_id: int | None = None
    event_type: str
    title: str
    detail: str = ""
    severity: str = "medium"

class SnapshotIn(BaseModel):
    title: str
    url: str = ""
    price: float | None = None
    coupon_price: float | None = None
    review_count: int | None = None
    review_count_text: str = ""
    rating: float | None = None
    good_rate: float | None = None
    review_tags: list[dict] = Field(default_factory=list)
    review_samples: list[str] = Field(default_factory=list)
    review_highlights: dict[str, list[str]] = Field(default_factory=dict)
    negative_keywords: list[dict] = Field(default_factory=list)
    negative_review_samples: list[str] = Field(default_factory=list)
    sku_options: list[dict] = Field(default_factory=list)
    sku_prices: list[dict] = Field(default_factory=list)
    stock_status: str = "unknown"
    promotion_tags: list[str] = Field(default_factory=list)
    service_tags: list[str] = Field(default_factory=list)
    selling_points: list[str] = Field(default_factory=list)
    sales_text: str = ""
    image_url: str = ""
    status: str = "active"


def _event_severity(event_type: str, old_value, new_value) -> str:
    if event_type == "price_changed" and old_value not in (None, 0) and new_value is not None:
        if abs((float(new_value) - float(old_value)) / float(old_value)) >= 0.1:
            return "high"
        return "medium"
    if event_type in {"status_changed", "image_changed", "title_changed", "sku_price_changed", "promotion_changed", "review_risk_changed"}:
        return "medium"
    return "low"


def _append_snapshot_event(db, product, event_type: str, title: str, old_value, new_value, observed_at: str) -> None:
    detail = json.dumps({"old": old_value, "new": new_value}, ensure_ascii=False)
    severity = _event_severity(event_type, old_value, new_value)
    db.execute(
        "INSERT INTO competitor_events (shop_id,product_id,event_type,title,detail,severity,observed_at) VALUES (?,?,?,?,?,?,?)",
        (product["shop_id"], product["id"], event_type, title, detail, severity, observed_at),
    )


def _store_snapshot(db, product, values: dict, *, source: str) -> dict:
    title = str(values.get("title") or "").strip()
    if not title:
        raise ValueError("未读取到商品标题")
    status = str(values.get("status") or "active")
    if status not in {"active", "inactive"}:
        raise ValueError("商品状态只能是在售或下架")
    previous = db.execute("SELECT * FROM competitor_product_snapshots WHERE product_id=? ORDER BY observed_at DESC,id DESC LIMIT 1", (product["id"],)).fetchone()
    observed_at = _now()
    review_count = values.get("review_count") if values.get("review_count") is not None else product["review_count"]
    review_count_text = str(values.get("review_count_text") or product["review_count_text"] or "").strip()
    rating = values.get("rating") if values.get("rating") is not None else product["rating"]
    good_rate = values.get("good_rate") if values.get("good_rate") is not None else product["good_rate"]
    review_tags_value = values.get("review_tags")
    review_samples_value = values.get("review_samples")
    review_highlights_value = values.get("review_highlights")
    def json_value(name: str, default: str = "[]", *, preserve_empty: bool = True) -> str:
        value = values.get(name)
        if value or (not preserve_empty and name in values):
            return json.dumps(value or [], ensure_ascii=False)
        return product[name] or default

    stock_status = str(values.get("stock_status") or "unknown")
    if stock_status == "unknown" and product["stock_status"] not in (None, "", "unknown"):
        stock_status = product["stock_status"]
    rich_page_loaded = str(values.get("stock_status") or "unknown") != "unknown"
    current = {
        "title": title,
        "url": str(values.get("url") or product["url"] or "").strip(),
        "price": values.get("price"),
        "coupon_price": values.get("coupon_price"),
        "review_count": review_count,
        "review_count_text": review_count_text,
        "rating": rating,
        "good_rate": good_rate,
        "review_tags": json.dumps(review_tags_value, ensure_ascii=False) if review_tags_value else (product["review_tags"] or "[]"),
        "review_samples": json.dumps(review_samples_value, ensure_ascii=False) if review_samples_value else (product["review_samples"] or "[]"),
        "review_highlights": json.dumps(review_highlights_value, ensure_ascii=False) if review_highlights_value and any(review_highlights_value.values()) else (product["review_highlights"] or "{}"),
        "negative_keywords": json_value("negative_keywords"),
        "negative_review_samples": json_value("negative_review_samples"),
        "sku_options": json_value("sku_options", preserve_empty=not rich_page_loaded),
        "sku_prices": json_value("sku_prices", preserve_empty=not rich_page_loaded),
        "stock_status": stock_status,
        "promotion_tags": json_value("promotion_tags", preserve_empty=not rich_page_loaded),
        "service_tags": json_value("service_tags", preserve_empty=not rich_page_loaded),
        "selling_points": json_value("selling_points", preserve_empty=not rich_page_loaded),
        "sales_text": str(values.get("sales_text") or "").strip(),
        "image_url": str(values.get("image_url") or "").strip(),
        "status": status,
    }
    cur = db.execute(
        "INSERT INTO competitor_product_snapshots (product_id,title,url,price,coupon_price,review_count,review_count_text,rating,good_rate,review_tags,review_samples,review_highlights,negative_keywords,negative_review_samples,sku_options,sku_prices,stock_status,promotion_tags,service_tags,selling_points,sales_text,image_url,status,observed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (product["id"], current["title"], current["url"], current["price"], current["coupon_price"], current["review_count"], current["review_count_text"], current["rating"], current["good_rate"], current["review_tags"], current["review_samples"], current["review_highlights"], current["negative_keywords"], current["negative_review_samples"], current["sku_options"], current["sku_prices"], current["stock_status"], current["promotion_tags"], current["service_tags"], current["selling_points"], current["sales_text"], current["image_url"], current["status"], observed_at),
    )
    if previous:
        fields = (
            ("price", "price_changed", "价格变化"), ("coupon_price", "coupon_price_changed", "券后价变化"),
            ("title", "title_changed", "标题变化"), ("image_url", "image_changed", "主图变化"),
            ("review_count", "review_growth", "评价数增长"), ("rating", "rating_changed", "评分变化"),
            ("good_rate", "good_rate_changed", "好评率变化"), ("status", "status_changed", "上下架状态变化"),
            ("sku_prices", "sku_price_changed", "SKU价格变化"),
            ("promotion_tags", "promotion_changed", "活动优惠变化"), ("service_tags", "service_changed", "服务承诺变化"),
            ("selling_points", "selling_points_changed", "商品卖点变化"), ("negative_keywords", "review_risk_changed", "差评风险变化"),
        )
        old = dict(previous)
        for field, event_type, label in fields:
            old_value, new_value = old.get(field), current[field]
            if field == "review_count":
                changed = old_value is not None and new_value is not None and new_value > old_value
            elif field == "status":
                changed = new_value != old_value
            else:
                changed = old_value != new_value and not (old_value is None and new_value is None)
            if changed:
                _append_snapshot_event(db, product, event_type, label, old_value, new_value, observed_at)
    success_fields = ",last_success_at=?" if source == "auto" else ""
    params = [current["title"], current["url"], current["price"], current["coupon_price"], current["review_count"], current["review_count_text"], current["rating"], current["good_rate"], current["review_tags"], current["review_samples"], current["review_highlights"], current["negative_keywords"], current["negative_review_samples"], current["sku_options"], current["sku_prices"], current["stock_status"], current["promotion_tags"], current["service_tags"], current["selling_points"], current["sales_text"], current["image_url"], current["status"], observed_at, observed_at, source]
    if source == "auto":
        params.append(observed_at)
    params.append(product["id"])
    db.execute(
        f"UPDATE competitor_products SET title=?,url=?,price=?,coupon_price=?,review_count=?,review_count_text=?,rating=?,good_rate=?,review_tags=?,review_samples=?,review_highlights=?,negative_keywords=?,negative_review_samples=?,sku_options=?,sku_prices=?,stock_status=?,promotion_tags=?,service_tags=?,selling_points=?,sales_text=?,image_url=?,status=?,last_snapshot_at=?,updated_at=?,collection_source=?,collection_status='success',collection_error=''{success_fields} WHERE id=?",
        params,
    )
    event_count = int(db.execute("SELECT COUNT(*) FROM competitor_events WHERE product_id=? AND observed_at=?", (product["id"], observed_at)).fetchone()[0])
    return {"item": dict(db.execute("SELECT * FROM competitor_product_snapshots WHERE id=?", (cur.lastrowid,)).fetchone()), "event_count": event_count, "baseline": previous is None}


def collect_product_now(db, product_id: int) -> dict:
    product = db.execute("SELECT * FROM competitor_products WHERE id=? AND status != 'archived'", (product_id,)).fetchone()
    if not product:
        raise LookupError("竞品商品不存在")
    attempted_at = _now()
    db.execute("UPDATE competitor_products SET collection_status='collecting',collection_error='',last_collected_at=? WHERE id=?", (attempted_at, product_id))
    db.commit()
    try:
        values = collect_product(product["url"])
        collection_method = str(values.get("_collection_method") or "request")
        result = _store_snapshot(db, product, values, source="auto")
        db.execute("UPDATE competitor_products SET collection_source=? WHERE id=?", (collection_method, product_id))
        db.commit()
        return {**result, "collection_status": "success", "collection_method": collection_method}
    except Exception as exc:
        error = str(exc) or "商品采集失败"
        db.execute("UPDATE competitor_products SET collection_status='failed',collection_error=?,last_collected_at=? WHERE id=?", (error[:500], attempted_at, product_id))
        db.commit()
        raise CompetitorScrapeError(error) from exc


def scan_shop_now(db, shop_id: int) -> dict:
    shop = db.execute("SELECT * FROM competitor_shops WHERE id=? AND status='active'", (shop_id,)).fetchone()
    if not shop:
        raise LookupError("竞品店铺不存在")
    if not str(shop["url"] or "").strip():
        raise ValueError("请先为竞店补充淘宝或天猫店铺链接")
    started_at = _now()
    baseline = not bool(shop["last_scanned_at"])
    db.execute(
        "UPDATE competitor_shops SET last_scan_attempt_at=?,last_scan_status='scanning',last_scan_error='' WHERE id=?",
        (started_at, shop_id),
    )
    db.commit()
    try:
        catalog = collect_shop_catalog(str(shop["url"]))
        if not catalog:
            raise CompetitorScrapeError("店铺页面没有读取到商品，未修改现有商品池")
        created: list[dict] = []
        existing_count = 0
        for catalog_item in catalog:
            item_id = str(catalog_item.get("item_id") or "").strip()
            if not item_id:
                continue
            existing = db.execute(
                "SELECT * FROM competitor_products WHERE shop_id=? AND (platform_item_id=? OR url LIKE ? OR url LIKE ?)",
                (shop_id, item_id, f"%?id={item_id}", f"%?id={item_id}&%"),
            ).fetchone()
            title = str(catalog_item.get("title") or "").strip() or f"待采集商品 {item_id}"
            url = str(catalog_item.get("url") or "").strip()
            image_url = str(catalog_item.get("image_url") or "").strip()
            if existing:
                existing_count += 1
                next_title = title if not str(existing["title"] or "").strip() or str(existing["title"]).startswith("待采集商品") else existing["title"]
                db.execute(
                    "UPDATE competitor_products SET platform_item_id=?,title=?,url=CASE WHEN url='' THEN ? ELSE url END,image_url=CASE WHEN image_url='' THEN ? ELSE image_url END,first_seen_at=COALESCE(first_seen_at,created_at,?),last_seen_at=?,updated_at=? WHERE id=?",
                    (item_id, next_title, url, image_url, started_at, started_at, started_at, existing["id"]),
                )
                continue
            cursor = db.execute(
                """INSERT INTO competitor_products
                (shop_id,title,url,own_product,price,coupon_price,review_count,sales_text,image_url,last_snapshot_at,alias,discovery_source,platform_item_id,first_seen_at,last_seen_at,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (shop_id, title, url, "", None, None, None, "", image_url, None, "", "shop_scan", item_id, started_at, started_at, started_at, started_at),
            )
            created.append({"id": cursor.lastrowid, "item_id": item_id, "title": title, "url": url})
        if not baseline:
            for item in created:
                db.execute(
                    "INSERT INTO competitor_events (shop_id,product_id,event_type,title,detail,severity,observed_at) VALUES (?,?,?,?,?,?,?)",
                    (shop_id, item["id"], "new_product", "竞店发现新商品", json.dumps({"title": item["title"], "url": item["url"], "first_seen_at": started_at}, ensure_ascii=False), "medium", started_at),
                )
        db.execute(
            "UPDATE competitor_shops SET last_scanned_at=?,last_scan_status='success',last_scan_error='',last_scan_product_count=?,last_new_product_count=?,updated_at=? WHERE id=?",
            (started_at, len(catalog), 0 if baseline else len(created), started_at, shop_id),
        )
        db.commit()
        return {"shop_id": shop_id, "baseline": baseline, "scanned": len(catalog), "created": len(created), "existing": existing_count, "new_products": 0 if baseline else len(created), "items": created[:50], "scanned_at": started_at}
    except Exception as exc:
        error = str(exc) or "竞店目录扫描失败"
        db.execute("UPDATE competitor_shops SET last_scan_status='failed',last_scan_error=?,updated_at=? WHERE id=?", (error[:500], _now(), shop_id))
        db.commit()
        raise CompetitorScrapeError(error) from exc


def scan_due_shops(db, *, force: bool = False) -> dict:
    rows = db.execute(
        "SELECT id,last_scanned_at,last_scan_attempt_at,monitor_frequency FROM competitor_shops WHERE status='active' AND TRIM(url) != ''"
    ).fetchall()
    now = datetime.now(timezone.utc)
    intervals = {"每小时": 3600, "每日": 86400, "每周": 604800}
    due = []
    for row in rows:
        last_attempt = _as_datetime(row["last_scan_attempt_at"]) or _as_datetime(row["last_scanned_at"])
        elapsed = (now - last_attempt).total_seconds() if last_attempt else float("inf")
        if force or elapsed >= intervals.get(row["monitor_frequency"], 86400):
            due.append(row["id"])
    ok, failed, discovered, errors = 0, 0, 0, []
    for shop_id in due:
        try:
            result = scan_shop_now(db, int(shop_id))
            ok += 1
            discovered += int(result["new_products"])
        except Exception as exc:
            failed += 1
            errors.append({"shop_id": shop_id, "error": str(exc)})
    return {"total": len(due), "ok": ok, "failed": failed, "new_products": discovered, "errors": errors}


def collect_due_products(db, *, force: bool = False) -> dict:
    rows = db.execute(
        "SELECT p.id,p.last_collected_at,s.monitor_frequency FROM competitor_products p JOIN competitor_shops s ON s.id=p.shop_id WHERE p.status != 'archived' AND TRIM(p.url) != '' AND s.status='active'"
    ).fetchall()
    now = datetime.now(timezone.utc)
    intervals = {"每小时": 3600, "每日": 86400, "每周": 604800}
    due = []
    for row in rows:
        try:
            elapsed = (now - datetime.fromisoformat(row["last_collected_at"])).total_seconds()
        except (TypeError, ValueError):
            elapsed = float("inf")
        if force or elapsed >= intervals.get(row["monitor_frequency"], 86400):
            due.append(row["id"])
    ok, failed, errors = 0, 0, []
    for product_id in due:
        try:
            collect_product_now(db, product_id)
            ok += 1
        except Exception as exc:
            failed += 1
            errors.append({"product_id": product_id, "error": str(exc)})
    return {"total": len(due), "ok": ok, "failed": failed, "errors": errors}


def _parse_sales_count(value: str | None) -> int | None:
    raw = str(value or "").replace(",", "").strip()
    if not raw:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*万", raw)
    if match:
        return int(float(match.group(1)) * 10000)
    match = re.search(r"(\d+(?:\.\d+)?)", raw)
    return int(float(match.group(1))) if match else None


def _as_datetime(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _product_intelligence(product, snapshots: list | None = None, events: list | None = None) -> dict:
    item = dict(product)
    ordered = sorted((dict(row) for row in (snapshots or [])), key=lambda row: row.get("observed_at") or "")
    related_events = [dict(row) for row in (events or [])]
    latest_at = _as_datetime(ordered[-1].get("observed_at")) if ordered else _as_datetime(item.get("last_snapshot_at"))
    cutoff = (latest_at or datetime.now(timezone.utc)) - timedelta(days=7)
    recent = [row for row in ordered if (_as_datetime(row.get("observed_at")) or cutoff) >= cutoff]
    baseline = recent[0] if recent else (ordered[0] if ordered else {})
    latest = ordered[-1] if ordered else item

    latest_sales = _parse_sales_count(latest.get("sales_text"))
    baseline_sales = _parse_sales_count(baseline.get("sales_text"))
    sales_delta = max(0, latest_sales - baseline_sales) if latest_sales is not None and baseline_sales is not None else None
    latest_reviews = latest.get("review_count")
    baseline_reviews = baseline.get("review_count")
    review_delta = max(0, int(latest_reviews) - int(baseline_reviews)) if latest_reviews is not None and baseline_reviews is not None else None
    first_seen_at = _as_datetime(item.get("first_seen_at")) or _as_datetime(item.get("created_at"))
    age_days = max(0, (datetime.now(timezone.utc) - first_seen_at).days) if first_seen_at else None
    # “新品”只代表目录复扫后真正新出现的商品。手工添加和首次扫描建立的
    # 基线都没有 new_product 事件，不能因为刚录入系统就被误报为竞店新品。
    is_new = age_days is not None and age_days <= 30 and any(
        row.get("event_type") == "new_product" for row in related_events
    )
    recent_event_types = {
        row.get("event_type")
        for row in related_events
        if (_as_datetime(row.get("observed_at")) or cutoff) >= cutoff
    }

    score = 0
    reasons: list[str] = []
    if sales_delta is not None and sales_delta > 0:
        score += min(40, 18 + int(sales_delta ** 0.5))
        reasons.append(f"近7天销量增加约 {sales_delta}")
    if review_delta is not None and review_delta > 0:
        score += min(30, 12 + review_delta * 2)
        reasons.append(f"近7天评价增加 {review_delta}")
    if is_new:
        score += 15
        reasons.append(f"首次发现 {age_days} 天")
    if recent_event_types.intersection({"price_changed", "coupon_price_changed", "promotion_changed"}):
        score += 8
        reasons.append("近期调整价格或活动")
    if recent_event_types.intersection({"title_changed", "image_changed", "sku_changed", "sku_price_changed"}):
        score += 7
        reasons.append("近期调整商品表达或规格")
    has_observed_growth = bool((sales_delta or 0) > 0 or (review_delta or 0) > 0)
    if not has_observed_growth:
        score = min(score, 24)
        reasons.append("尚未观察到销量或评价增长")
    score = min(score, 100)
    level = "快速起量" if score >= 70 else "持续增长" if score >= 45 else "疑似起量" if score >= 25 else "观察中"
    confidence = "high" if len(ordered) >= 7 and (sales_delta is not None or review_delta is not None) else "medium" if len(ordered) >= 2 else "low"
    item.update({
        "display_name": item.get("alias") or item.get("title") or "未命名竞品",
        "first_seen_at": item.get("first_seen_at") or item.get("created_at"),
        "age_days": age_days,
        "is_new": is_new,
        "snapshot_count": len(ordered),
        "sales_count": latest_sales,
        "sales_delta_7d": sales_delta,
        "review_delta_7d": review_delta,
        "growth_score": score,
        "growth_level": level,
        "growth_confidence": confidence,
        "growth_reasons": reasons or ["暂无明确增长信号，继续积累快照"],
    })
    return item


def _monitoring_intelligence(db) -> dict:
    products = db.execute(
        "SELECT p.*,s.name AS shop_name,s.priority FROM competitor_products p JOIN competitor_shops s ON s.id=p.shop_id WHERE p.status != 'archived' AND s.status='active'"
    ).fetchall()
    snapshots = db.execute(
        "SELECT * FROM competitor_product_snapshots ORDER BY observed_at ASC,id ASC"
    ).fetchall()
    events = db.execute(
        "SELECT e.*,s.name AS shop_name,p.title AS product_title FROM competitor_events e LEFT JOIN competitor_shops s ON s.id=e.shop_id LEFT JOIN competitor_products p ON p.id=e.product_id ORDER BY e.observed_at DESC,e.id DESC"
    ).fetchall()
    snapshots_by_product: dict[int, list] = {}
    events_by_product: dict[int, list] = {}
    for row in snapshots:
        snapshots_by_product.setdefault(int(row["product_id"]), []).append(row)
    for row in events:
        if row["product_id"] is not None:
            events_by_product.setdefault(int(row["product_id"]), []).append(row)
    enriched = [
        _product_intelligence(row, snapshots_by_product.get(int(row["id"]), []), events_by_product.get(int(row["id"]), []))
        for row in products
    ]
    enriched.sort(key=lambda row: (row["growth_score"], row.get("review_delta_7d") or 0, row.get("sales_delta_7d") or 0), reverse=True)
    new_products = sorted((row for row in enriched if row["is_new"]), key=lambda row: row.get("first_seen_at") or "", reverse=True)
    shops = []
    for shop in db.execute("SELECT * FROM competitor_shops WHERE status='active'").fetchall():
        shop_products = [row for row in enriched if row["shop_id"] == shop["id"]]
        successful = [row.get("last_success_at") for row in shop_products if row.get("last_success_at")]
        shops.append({
            **dict(shop),
            "product_count": len(shop_products),
            "new_product_count": sum(bool(row["is_new"]) for row in shop_products),
            "rising_product_count": sum(row["growth_score"] >= 25 and ((row.get("sales_delta_7d") or 0) > 0 or (row.get("review_delta_7d") or 0) > 0) for row in shop_products),
            "failed_collection_count": sum(row.get("collection_status") == "failed" for row in shop_products),
            "last_success_at": max(successful) if successful else None,
        })
    return {
        "products": enriched,
        "rising_products": [row for row in enriched if row["growth_score"] >= 25 and ((row.get("sales_delta_7d") or 0) > 0 or (row.get("review_delta_7d") or 0) > 0)],
        "new_products": new_products,
        "shops": shops,
        "events": [dict(row) for row in events],
    }

@router.get("")
def monitoring_overview(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    shops = int(db.execute("SELECT COUNT(*) FROM competitor_shops WHERE status='active'").fetchone()[0])
    products = int(db.execute("SELECT COUNT(*) FROM competitor_products WHERE status != 'archived'").fetchone()[0])
    events = int(db.execute("SELECT COUNT(*) FROM competitor_events WHERE status='new'").fetchone()[0])
    today_events = int(db.execute("SELECT COUNT(*) FROM competitor_events WHERE observed_at >= ?", (datetime.now().date().isoformat(),)).fetchone()[0])
    latest = db.execute("SELECT MAX(observed_at) FROM competitor_events").fetchone()[0]
    failed = int(db.execute("SELECT COUNT(*) FROM competitor_products WHERE collection_status='failed' AND status != 'archived'").fetchone()[0])
    return {"name": "竞品监控", "status": "ready", "sections": SECTIONS, "summary": {"shops": shops, "products": products, "new_events": events, "today_events": today_events, "failed_collections": failed, "latest_event_at": latest}}


@router.get("/intelligence")
def monitoring_intelligence(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    data = _monitoring_intelligence(db)
    return {
        **data,
        "summary": {
            "shops": len(data["shops"]),
            "products": len(data["products"]),
            "new_products": len(data["new_products"]),
            "rising_products": len(data["rising_products"]),
            "unread_events": sum((row.get("status") or "new") == "new" for row in data["events"]),
            "failed_collections": sum(row.get("collection_status") == "failed" for row in data["products"]),
        },
    }

@router.get("/shops")
def list_shops(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    data = _monitoring_intelligence(db)
    rows = sorted(data["shops"], key=lambda row: ({"核心": 0, "重点": 1}.get(row["priority"], 2), row["name"]))
    return {"items": rows}

@router.post("/shops")
def create_shop(body: ShopIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    name = body.name.strip()
    if not name: raise HTTPException(status_code=400, detail="请输入竞品店铺名称")
    now = _now()
    cur = db.execute("INSERT INTO competitor_shops (name,url,competitor_type,priority,category,price_band,notes,monitor_frequency,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (name, body.url.strip(), body.competitor_type, body.priority, body.category.strip(), body.price_band.strip(), body.notes.strip(), body.monitor_frequency, now, now))
    db.commit()
    return {"item": dict(db.execute("SELECT * FROM competitor_shops WHERE id=?", (cur.lastrowid,)).fetchone())}

@router.put("/shops/{shop_id}")
def update_shop(shop_id: int, body: ShopIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if not db.execute("SELECT id FROM competitor_shops WHERE id=?", (shop_id,)).fetchone(): raise HTTPException(status_code=404, detail="竞品店铺不存在")
    db.execute("UPDATE competitor_shops SET name=?,url=?,competitor_type=?,priority=?,category=?,price_band=?,notes=?,monitor_frequency=?,updated_at=? WHERE id=?", (body.name.strip(), body.url.strip(), body.competitor_type, body.priority, body.category.strip(), body.price_band.strip(), body.notes.strip(), body.monitor_frequency, _now(), shop_id))
    db.commit()
    return {"item": dict(db.execute("SELECT * FROM competitor_shops WHERE id=?", (shop_id,)).fetchone())}


@router.get("/shops/{shop_id}")
def get_shop_detail(shop_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    data = _monitoring_intelligence(db)
    shop = next((row for row in data["shops"] if row["id"] == shop_id), None)
    if not shop:
        raise HTTPException(status_code=404, detail="竞品店铺不存在")
    products = [row for row in data["products"] if row["shop_id"] == shop_id]
    events = [row for row in data["events"] if row.get("shop_id") == shop_id]
    return {"item": shop, "products": products, "events": events[:50]}


@router.post("/shops/{shop_id}/scan")
def scan_shop(shop_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    try:
        return scan_shop_now(db, shop_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CompetitorScrapeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/shops/{shop_id}/collector/open")
def open_shop_collector(shop_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    shop = db.execute("SELECT url FROM competitor_shops WHERE id=? AND status='active'", (shop_id,)).fetchone()
    if not shop:
        raise HTTPException(status_code=404, detail="竞品店铺不存在")
    if not str(shop["url"] or "").strip():
        raise HTTPException(status_code=400, detail="请先为竞店补充淘宝或天猫店铺链接")
    return open_collection_browser(str(shop["url"]))

@router.delete("/shops/{shop_id}")
def delete_shop(shop_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if not db.execute("SELECT id FROM competitor_shops WHERE id=?", (shop_id,)).fetchone(): raise HTTPException(status_code=404, detail="竞品店铺不存在")
    db.execute("UPDATE competitor_shops SET status='archived',updated_at=? WHERE id=?", (_now(), shop_id)); db.execute("UPDATE competitor_products SET status='archived',updated_at=? WHERE shop_id=?", (_now(), shop_id)); db.commit(); return {"ok": True}

@router.get("/products")
def list_products(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    rows = db.execute("SELECT p.*,s.name AS shop_name,s.priority FROM competitor_products p JOIN competitor_shops s ON s.id=p.shop_id WHERE p.status != 'archived' ORDER BY p.updated_at DESC,p.id DESC").fetchall()
    return {"items": [dict(row) for row in rows]}

@router.post("/products")
def create_product(body: ProductIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if not body.url.strip() and not body.title.strip(): raise HTTPException(status_code=400, detail="请粘贴商品链接，或先填写商品标题")
    if not db.execute("SELECT id FROM competitor_shops WHERE id=? AND status='active'", (body.shop_id,)).fetchone(): raise HTTPException(status_code=400, detail="请选择有效的竞品店铺")
    now = _now(); cur = db.execute("INSERT INTO competitor_products (shop_id,title,url,own_product,price,coupon_price,review_count,sales_text,image_url,last_snapshot_at,discovery_source,platform_item_id,first_seen_at,last_seen_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (body.shop_id,body.title.strip() or "待采集商品",body.url.strip(),body.own_product.strip(),body.price,body.coupon_price,body.review_count,body.sales_text.strip(),body.image_url.strip(),None,"manual",_platform_item_id(body.url),now,now,now,now)); db.commit()
    warning = ""
    if body.url.strip():
        try:
            collect_product_now(db, cur.lastrowid)
        except CompetitorScrapeError as exc:
            warning = str(exc)
    else:
        warning = "尚未采集：请补充商品链接后再采集"
    item = db.execute("SELECT p.*,s.name AS shop_name,s.priority FROM competitor_products p JOIN competitor_shops s ON s.id=p.shop_id WHERE p.id=?", (cur.lastrowid,)).fetchone()
    return {"item": dict(item), "collected": not warning, "warning": warning}

@router.post("/products/batch")
def create_products_batch(body: ProductBatchIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if not db.execute("SELECT id FROM competitor_shops WHERE id=? AND status='active'", (body.shop_id,)).fetchone():
        raise HTTPException(status_code=400, detail="请选择有效的竞品店铺")
    urls = list(dict.fromkeys(line.strip() for line in body.urls if line.strip()))
    if not urls:
        raise HTTPException(status_code=400, detail="请至少粘贴一条商品链接")
    created, failed = [], []
    for url in urls:
        now = _now()
        item_id = _platform_item_id(url)
        existing = db.execute("SELECT id FROM competitor_products WHERE shop_id=? AND platform_item_id=? AND platform_item_id != ''", (body.shop_id, item_id)).fetchone() if item_id else None
        if existing:
            failed.append({"id": existing["id"], "url": url, "error": "该竞品商品已在商品池中"})
            continue
        cur = db.execute("INSERT INTO competitor_products (shop_id,title,url,own_product,last_snapshot_at,discovery_source,platform_item_id,first_seen_at,last_seen_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (body.shop_id, "待采集商品", url, body.own_product.strip(), None, "manual", item_id, now, now, now, now))
        try:
            result = collect_product_now(db, cur.lastrowid)
            created.append({"id": cur.lastrowid, "collected": True, "event_count": result["event_count"]})
        except CompetitorScrapeError as exc:
            failed.append({"id": cur.lastrowid, "url": url, "error": str(exc)})
    db.commit()
    return {"created": len(created) + len(failed), "collected": len(created), "failed": len(failed), "errors": failed}

@router.post("/products/{product_id}/collect")
def collect_one_product(product_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    try:
        return collect_product_now(db, product_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CompetitorScrapeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

@router.post("/products/collect")
def collect_all_products(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    return collect_due_products(db, force=True)

@router.get("/collector/status")
def collector_status(user: dict = Depends(get_current_user)) -> dict:
    return browser_status()

@router.post("/collector/open")
def open_collector(user: dict = Depends(get_current_user)) -> dict:
    return open_collection_browser()

@router.get("/products/{product_id}/snapshots")
def list_snapshots(product_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if not db.execute("SELECT id FROM competitor_products WHERE id=?", (product_id,)).fetchone():
        raise HTTPException(status_code=404, detail="竞品商品不存在")
    rows = db.execute("SELECT * FROM competitor_product_snapshots WHERE product_id=? ORDER BY observed_at DESC,id DESC LIMIT 50", (product_id,)).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.get("/products/{product_id}/detail")
def get_product_detail(product_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    product = db.execute(
        "SELECT p.*,s.name AS shop_name,s.priority FROM competitor_products p JOIN competitor_shops s ON s.id=p.shop_id WHERE p.id=? AND p.status != 'archived'",
        (product_id,),
    ).fetchone()
    if not product:
        raise HTTPException(status_code=404, detail="竞品商品不存在")
    snapshots = db.execute(
        "SELECT * FROM competitor_product_snapshots WHERE product_id=? ORDER BY observed_at ASC,id ASC LIMIT 100",
        (product_id,),
    ).fetchall()
    events = db.execute(
        "SELECT e.*,s.name AS shop_name,p.title AS product_title FROM competitor_events e LEFT JOIN competitor_shops s ON s.id=e.shop_id LEFT JOIN competitor_products p ON p.id=e.product_id WHERE e.product_id=? ORDER BY e.observed_at DESC,e.id DESC LIMIT 100",
        (product_id,),
    ).fetchall()
    return {
        "item": _product_intelligence(product, list(snapshots), list(events)),
        "snapshots": [dict(row) for row in snapshots],
        "events": [dict(row) for row in events],
    }


@router.put("/products/{product_id}")
def update_product(product_id: int, body: ProductUpdateIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if not db.execute("SELECT id FROM competitor_products WHERE id=? AND status != 'archived'", (product_id,)).fetchone():
        raise HTTPException(status_code=404, detail="竞品商品不存在")
    db.execute(
        "UPDATE competitor_products SET alias=?,own_product=?,updated_at=? WHERE id=?",
        (body.alias.strip(), body.own_product.strip(), _now(), product_id),
    )
    db.commit()
    return {"item": dict(db.execute("SELECT * FROM competitor_products WHERE id=?", (product_id,)).fetchone())}

@router.post("/products/{product_id}/snapshots")
def create_snapshot(product_id: int, body: SnapshotIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    product = db.execute("SELECT * FROM competitor_products WHERE id=? AND status != 'archived'", (product_id,)).fetchone()
    if not product:
        raise HTTPException(status_code=404, detail="竞品商品不存在")
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="请输入本次快照中的商品标题")
    if body.status not in {"active", "inactive"}:
        raise HTTPException(status_code=400, detail="商品状态只能是在售或下架")
    result = _store_snapshot(db, product, body.model_dump(), source="manual")
    db.commit()
    return result

@router.get("/events")
def list_events(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    rows = db.execute("SELECT e.*,s.name AS shop_name,p.title AS product_title FROM competitor_events e LEFT JOIN competitor_shops s ON s.id=e.shop_id LEFT JOIN competitor_products p ON p.id=e.product_id ORDER BY e.observed_at DESC,e.id DESC LIMIT 100").fetchall()
    return {"items": [dict(row) for row in rows]}


@router.put("/events/{event_id}")
def update_event_status(event_id: int, body: EventStatusIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if not db.execute("SELECT id FROM competitor_events WHERE id=?", (event_id,)).fetchone():
        raise HTTPException(status_code=404, detail="竞品变化不存在")
    db.execute("UPDATE competitor_events SET status=? WHERE id=?", (body.status, event_id))
    db.commit()
    return {"ok": True, "status": body.status}

@router.post("/events")
def create_event(body: EventIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if not body.title.strip(): raise HTTPException(status_code=400, detail="请输入变化标题")
    cur = db.execute("INSERT INTO competitor_events (shop_id,product_id,event_type,title,detail,severity,observed_at) VALUES (?,?,?,?,?,?,?)", (body.shop_id,body.product_id,body.event_type,body.title.strip(),body.detail.strip(),body.severity,_now())); db.commit(); return {"item": dict(db.execute("SELECT * FROM competitor_events WHERE id=?", (cur.lastrowid,)).fetchone())}

@router.get("/{section_id}")
def monitoring_section(section_id: str, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    section = next((item for item in SECTIONS if item["id"] == section_id), None)
    if section is None: raise HTTPException(status_code=404, detail="竞品监控页面不存在")
    return {"workspace": "竞品监控", "section": section, "status": "ready", "summary": monitoring_overview(user, db)["summary"]}
