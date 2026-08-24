from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from backend.app.api.auth import get_current_user, visible_store_ids
from backend.app.api.model_configs import get_default_config
from backend.app.core.ai_client import AIError, chat_completion
from backend.app.core.db import get_db

router = APIRouter()

PROCESS_STATUSES = {"pending", "contacted", "resolved", "ignored"}
POSITIVE_WORDS = {"满意", "喜欢", "推荐", "不错", "很好", "超值", "正品", "漂亮", "给力", "回购", "五星", "惊喜", "好用", "实惠", "快"}
NEGATIVE_WORDS = {"差", "失望", "破损", "破了", "漏", "坏", "假", "慢", "薄", "臭", "掉", "退款", "退货", "不值", "不满意", "态度差", "不回复", "色差", "质量问题", "开胶", "瑕疵", "难用", "不推荐", "太小", "太大", "发错", "少件", "脏"}
POSITIVE_PHRASES = {"效果明显", "口气清新", "温和不刺激", "不刺激牙龈", "不会刺激牙龈", "不酸牙", "不辣嘴", "不刺痛牙龈", "不易炸毛", "不掉毛", "没有异味", "贴合稳固", "干净透亮", "性价比高", "值得回购", "物流很快"}
NEGATIVE_PHRASES = {"没有效果", "没效果", "效果不明显", "好用才怪", "不怎么样", "也就那样", "一般般", "酸牙", "辣嘴", "刺激牙龈", "掉毛", "严重破损", "漏液", "货不对板"}
NEUTRAL_PHRASES = {"一般", "还行", "凑合", "无功无过", "中规中矩"}
NEGATIONS = {"不", "没", "无", "未", "不会", "并非", "不是"}
CONTRAST_WORDS = ("但是", "不过", "然而", "可惜", "但")
SARCASM_MARKERS = {"好用才怪", "真是服了", "呵呵", "就这", "谢谢你让我踩雷", "谢谢让我踩雷", "可真行"}
SARCASTIC_POSITIVE_PHRASES = {"真不错", "真好", "真棒", "真厉害", "厉害了", "真贴心"}
ASPECT_WORDS = {
    "质量": {"质量", "破损", "坏", "开胶", "瑕疵", "掉"},
    "尺码": {"尺码", "大小", "偏小", "偏大", "太小", "太大", "尺寸"},
    "材质": {"材质", "面料", "薄", "厚", "手感"},
    "颜色": {"颜色", "色差", "掉色", "色彩"},
    "包装": {"包装", "盒子", "破了", "压坏", "包裹"},
    "物流": {"物流", "快递", "发货", "送货", "慢"},
    "客服": {"客服", "态度", "回复", "不回复", "售后"},
    "性价比": {"价格", "贵", "便宜", "性价比", "不值", "超值"},
}


class ReviewProcessIn(BaseModel):
    status: str
    note: str = Field(default="", max_length=500)


class ReviewSyncIn(BaseModel):
    """外部采集器提交的评论批次。

    采集器可以是平台适配器、浏览器扩展或定时任务；服务端只负责
    校验、去重和分析，不保存登录态或买家隐私凭证。
    """

    store_id: int
    source: str = Field(default="browser", max_length=40)
    items: list[dict] = Field(default_factory=list, max_length=5000)


class ReviewAutoSyncIn(BaseModel):
    store_id: int | None = None
    days: int = Field(default=7, ge=1, le=30)


class ReviewAlertStatusIn(BaseModel):
    status: str = Field(pattern="^(open|acknowledged|resolved|ignored)$")


class ReviewAiIn(BaseModel):
    days: int = Field(default=30, ge=1, le=365)
    store_id: int | None = None


class ReviewReplyDraftIn(BaseModel):
    template_id: int | None = None


class ReviewReplyApproveIn(BaseModel):
    content: str = Field(min_length=1, max_length=500)


class ReviewReplyTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    category: str = Field(default="通用", max_length=20)
    content: str = Field(min_length=1, max_length=1000)


class ReviewSentimentIn(BaseModel):
    sentiment: str = Field(pattern="^(positive|neutral|negative)$")
    reason: str = Field(default="人工确认", max_length=200)


class ReviewAiReviewIn(BaseModel):
    store_id: int | None = None
    days: int = Field(default=30, ge=1, le=365)
    limit: int = Field(default=30, ge=1, le=50)


class ReviewCustomTermIn(BaseModel):
    store_id: int = Field(default=0, ge=0)
    term: str = Field(min_length=1, max_length=30)
    sentiment: str = Field(pattern="^(positive|neutral|negative)$")
    weight: float = Field(default=1.5, ge=0.5, le=4)
    enabled: bool = True


class ReviewAskIn(BaseModel):
    question: str = Field(min_length=2, max_length=300)
    store_id: int | None = None
    days: int = Field(default=30, ge=1, le=365)


class ReviewKnowledgeIn(BaseModel):
    store_id: int = Field(default=0, ge=0)
    title: str = Field(min_length=1, max_length=80)
    category: str = Field(default="通用", max_length=30)
    problem_terms: list[str] = Field(default_factory=list, max_length=30)
    solution: str = Field(min_length=1, max_length=2000)
    reply_template: str = Field(default="", max_length=1000)
    enabled: bool = True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(content: str, append_content: str = "") -> str:
    normalized = re.sub(r"\s+", "", f"{content}{append_content}")
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _ensure_store_access(user: dict, store_id: int, db=None) -> None:
    visible = visible_store_ids(user)
    if visible is not None and store_id not in visible:
        raise HTTPException(status_code=403, detail="无权查看该店铺评论")
    if db is not None and not db.execute("SELECT 1 FROM stores WHERE id = ?", (store_id,)).fetchone():
        raise HTTPException(status_code=400, detail="店铺不存在")


def _visible_clause(user: dict) -> tuple[list[str], list]:
    visible = visible_store_ids(user)
    if visible is None:
        return [], []
    if not visible:
        return ["1 = 0"], []
    return [f"r.store_id IN ({','.join('?' for _ in visible)})"], list(visible)


def _parse_time(raw: object) -> str:
    value = str(raw or "").strip().replace("/", "-")
    if not value:
        return _now()
    if value.isdigit() and len(value) >= 10:
        try:
            timestamp = int(value)
            if len(value) >= 13:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return _now()
    value = value.replace("年", "-").replace("月", "-").replace("日", "")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return _now()


def _split_images(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [x.strip() for x in re.split(r"[|,;\n]", str(raw or "")) if x.strip()]


def _review_value(row: dict, *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _upsert_review(db, store_id: int, row: dict, source: str, now: str) -> tuple[str, str | None]:
    """写入一条评论并返回 (新增/更新, 错误)。"""
    content = _review_value(row, "content", "review_content", "评价内容", "评论内容", "买家评价")
    append_content = _review_value(row, "append_content", "追评内容", "追加评价")
    item_id = _review_value(row, "item_id", "商品ID", "商品id", "宝贝ID")
    review_time = _parse_time(_review_value(row, "review_time", "评价时间", "评论时间", "创建时间"))
    review_id = _review_value(row, "review_id", "评价ID", "评价id", "id")
    if not review_id:
        review_id = hashlib.sha1(f"{store_id}|{item_id}|{review_time}|{content}|{append_content}".encode()).hexdigest()[:32]
    if not content and not append_content:
        return "", "评价内容为空"
    before = db.execute("SELECT id FROM product_reviews WHERE store_id = ? AND review_id = ?", (store_id, review_id)).fetchone()
    db.execute(
        """
        INSERT INTO product_reviews
            (store_id, review_id, item_id, item_title, sku_id, rating, content, append_content, image_urls, review_time, source, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(store_id, review_id) DO UPDATE SET
            item_id = excluded.item_id, item_title = excluded.item_title, sku_id = excluded.sku_id,
            rating = excluded.rating, content = excluded.content, append_content = excluded.append_content,
            image_urls = excluded.image_urls, review_time = excluded.review_time, source = excluded.source, updated_at = excluded.updated_at
        """,
        (store_id, review_id, item_id, _review_value(row, "item_title", "商品名称", "宝贝标题", "商品标题"), _review_value(row, "sku_id", "规格ID", "SKU"), 0, content, append_content, json.dumps(_split_images(row.get("image_urls") or row.get("评价图片") or row.get("图片")), ensure_ascii=False), review_time, source, now, now),
    )
    review = db.execute("SELECT id FROM product_reviews WHERE store_id = ? AND review_id = ?", (store_id, review_id)).fetchone()
    _analyse_and_save(db, review["id"], store_id, content, append_content)
    _ensure_review_alert(db, store_id, review["id"], content, append_content, now)
    return ("updated" if before else "imported"), None


def _negative_hits(text: str) -> list[str]:
    ignored_phrases = {
        "慢": ("慢慢", "不慢", "变慢"),
        "掉": ("去掉", "去除掉", "淡掉"),
        "臭": ("口臭没了", "没有口臭", "去口臭", "除口臭", "不臭"),
        "酸": ("不酸", "无酸", "没有酸"),
        "刺激": ("不刺激", "无刺激", "没有刺激", "温和不刺激"),
    }
    hits = []
    for word in NEGATIVE_WORDS:
        if word not in text:
            continue
        if any(phrase in text for phrase in ignored_phrases.get(word, ())):
            continue
        hits.append(word)
    return hits


def _ensure_review_alert(db, store_id: int, review_id: int, content: str, append_content: str, now: str) -> None:
    text = f"{content} {append_content}".strip()
    hits = _negative_hits(text)
    if len(hits) < 2:
        db.execute("DELETE FROM review_alerts WHERE review_id = ? AND alert_type = 'negative_review' AND status = 'open'", (review_id,))
        return
    title = "评论出现问题关键词"
    message = f"命中关键词：{'、'.join(hits[:6])}"
    db.execute(
        "INSERT INTO review_alerts (store_id, review_id, alert_type, title, message, created_at) VALUES (?, ?, 'negative_review', ?, ?, ?) ON CONFLICT(review_id, alert_type) DO UPDATE SET title=excluded.title, message=excluded.message",
        (store_id, review_id, title, message, now),
    )


def _push_new_review_alerts(db, store_id: int) -> int:
    rows = db.execute(
        """SELECT a.id, a.title, a.message, r.item_title, r.item_id, r.content
        FROM review_alerts a JOIN product_reviews r ON r.id = a.review_id
        WHERE a.store_id = ? AND a.status = 'open' AND a.notified_at IS NULL
        ORDER BY a.created_at DESC LIMIT 20""",
        (store_id,),
    ).fetchall()
    if not rows:
        return 0
    try:
        from backend.app.api.alerts import _hourly_push_config, hourly_channel_ready, send_hourly_push

        cfg = _hourly_push_config(db)
        if not cfg.get("enabled") or not hourly_channel_ready(cfg):
            return 0
        lines = [f"{row['title']}｜{row['item_title'] or row['item_id']}\n{row['message']}\n{row['content'][:80]}" for row in rows]
        send_hourly_push(cfg, f"评论预警（{len(rows)} 条）", "\n\n".join(lines))
        ids = [row["id"] for row in rows]
        db.execute(f"UPDATE review_alerts SET notified_at = ? WHERE id IN ({','.join('?' for _ in ids)})", [_now(), *ids])
        return len(rows)
    except Exception:
        return 0


def _normalise_platform_review(row: dict) -> dict:
    """兼容生意参谋不同版本评价明细字段名。"""
    def value(*names: str) -> str:
        return _review_value(row, *names)

    auction = row.get("auction") if isinstance(row.get("auction"), dict) else {}
    item_info = row.get("itemInfo") if isinstance(row.get("itemInfo"), dict) else {}
    rate_content = row.get("rateContent") if isinstance(row.get("rateContent"), dict) else {}
    main_rate = rate_content.get("mainRate") if isinstance(rate_content.get("mainRate"), dict) else {}
    append_rate = rate_content.get("appendRate") if isinstance(rate_content.get("appendRate"), dict) else {}
    item_id = value("item_id", "itemId", "商品ID", "宝贝ID") or str(item_info.get("itemId") or auction.get("aucNumId") or "")
    append_list = row.get("appendList") if isinstance(row.get("appendList"), list) else []
    append_content = value("appendContent", "additionalContent", "append_content", "追评内容", "追加评价")
    if not append_content and append_list and isinstance(append_list[0], dict):
        append_content = str(append_list[0].get("content") or "")
    if not append_content:
        append_content = str(append_rate.get("content") or "")
    photos = row.get("photos") if isinstance(row.get("photos"), list) else []
    image_urls = row.get("imageUrls") or row.get("images") or row.get("评价图片") or []
    if not image_urls:
        image_urls = [photo.get("url") or photo.get("thumbnail") for photo in photos if isinstance(photo, dict)]
    if not image_urls:
        image_urls = [media.get("url") or media.get("thumbnail") for media in (main_rate.get("mediaList") or []) if isinstance(media, dict)]
    return {
        "review_id": value("review_id", "reviewId", "评价ID", "dataId", "rateId", "id", "feedId") or str(main_rate.get("feedId") or ""),
        "item_id": item_id,
        "item_title": value("item_title", "itemTitle", "商品名称", "宝贝标题") or str(item_info.get("title") or auction.get("title") or ""),
        "sku_id": value("sku_id", "skuId", "SKU", "规格ID"),
        "content": value("content", "reviewContent", "evaluationContent", "evaluateContent", "buyerComment", "评价内容", "买家评价") or str(main_rate.get("content") or ""),
        "append_content": append_content,
        "image_urls": image_urls,
        "review_time": value("reviewTime", "servTime", "createTime", "gmtCreate", "date", "评价时间", "评论时间") or str(main_rate.get("date") or ""),
    }


def _sync_platform_rows(db, store: dict, start_date: str, end_date: str) -> dict:
    from backend.app.core.sycm import SycmError, fetch_item_review_rows, fetch_review_rows, fetch_seller_review_rows

    service_error = ""
    seller_error = ""
    try:
        rows = fetch_review_rows(store, start_date, end_date, page_size=100, max_pages=20)
        source = "sycm"
    except SycmError as exc:
        rows = []
        service_error = str(exc)
    item_errors: list[str] = []
    content_rows = [_normalise_platform_review(raw) for raw in rows]
    if not any(item["content"] or item["append_content"] for item in content_rows):
        try:
            rows = fetch_seller_review_rows(store, start_date, end_date, page_size=20, max_pages=20)
            source = "seller-review-management"
            content_rows = [_normalise_platform_review(raw) for raw in rows]
        except SycmError as exc:
            seller_error = str(exc)
            rows = []
            content_rows = []

    if not any(item["content"] or item["append_content"] for item in content_rows):
        products = db.execute(
            "SELECT item_id, title FROM store_products WHERE store_id = ? AND item_id != '' ORDER BY datetime(synced_at) DESC LIMIT 20",
            (store["id"],),
        ).fetchall()
        item_rows: list[dict] = []
        for product in products:
            try:
                fetched = fetch_item_review_rows(store, str(product["item_id"]), page_size=20, max_pages=5)
                for raw in fetched:
                    raw.setdefault("itemId", str(product["item_id"]))
                    raw.setdefault("itemTitle", str(product["title"] or ""))
                item_rows.extend(fetched)
            except SycmError as exc:
                item_errors.append(str(exc))
        rows = item_rows
        content_rows = [_normalise_platform_review(raw) for raw in rows]
        if any(item["content"] or item["append_content"] for item in content_rows):
            source = "item-reviews"
    imported, updated, errors = 0, 0, []
    now = _now()
    for index, item in enumerate(content_rows, start=1):
        if not item["content"] and not item["append_content"]:
            continue
        try:
            action, error = _upsert_review(db, store["id"], item, source, now)
            if error:
                errors.append({"index": index, "error": error})
            elif action == "imported":
                imported += 1
            else:
                updated += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"index": index, "error": str(exc)[:160]})
    if source == "sycm" and rows and content_rows and any(item["content"] for item in content_rows):
        source = "sycm"
    diagnostics = item_errors[:3] or ([seller_error] if seller_error else []) or ([service_error] if service_error else [])
    notified = _push_new_review_alerts(db, store["id"])
    trend_alert = _evaluate_trend_alert(db, store["id"])
    _generate_weekly_report(db, store["id"])
    return {"ok": True, "store_id": store["id"], "store_name": store["name"], "fetched": len(rows), "imported": imported, "updated": updated, "error_count": len(errors), "errors": errors[:20], "content_available": bool(imported or updated), "source": source, "diagnostics": diagnostics, "alerts_notified": notified, "trend_alert": trend_alert}


def _term_is_negated(text: str, index: int) -> bool:
    prefix = text[max(0, index - 4):index]
    return any(prefix.endswith(word) for word in NEGATIONS)


def _clause_sentiment(clause: str, custom_terms: list[dict] | None = None) -> tuple[float, float, list[str], list[str], bool]:
    positive, negative = 0.0, 0.0
    positive_hits: list[str] = []
    negative_hits: list[str] = []
    neutral_hint = any(phrase in clause for phrase in NEUTRAL_PHRASES)
    for phrase in POSITIVE_PHRASES:
        if phrase in clause:
            positive += 2.0
            positive_hits.append(phrase)
    for phrase in NEGATIVE_PHRASES:
        start = 0
        while True:
            index = clause.find(phrase, start)
            if index < 0:
                break
            start = index + len(phrase)
            if _term_is_negated(clause, index):
                positive += 1.5
                positive_hits.append("不" + phrase)
            else:
                negative += 2.0
                negative_hits.append(phrase)
    for word in POSITIVE_WORDS:
        start = 0
        while True:
            index = clause.find(word, start)
            if index < 0:
                break
            start = index + len(word)
            if word == "快" and not any(phrase in clause[max(0, index - 3):index + 2] for phrase in ("很快", "挺快", "真快", "发货快", "物流快", "送货快")):
                continue
            if _term_is_negated(clause, index):
                negative += 1.2
                negative_hits.append("不" + word)
            else:
                positive += 1.0
                positive_hits.append(word)
    for word in NEGATIVE_WORDS:
        start = 0
        while True:
            index = clause.find(word, start)
            if index < 0:
                break
            start = index + len(word)
            if word == "薄" and "薄荷" in clause[max(0, index - 1):index + 2]:
                continue
            if any(phrase in clause for phrase in {"慢": ("慢慢",), "掉": ("去掉", "淡掉"), "臭": ("口臭没了", "去口臭", "不臭")}.get(word, ())):
                continue
            if _term_is_negated(clause, index):
                positive += 1.0
                positive_hits.append("不" + word)
            else:
                negative += 1.0
                negative_hits.append(word)
    for item in custom_terms or []:
        term = str(item.get("term") or "").strip()
        if not term or term not in clause:
            continue
        sentiment = str(item.get("sentiment") or "neutral")
        weight = float(item.get("weight") or 1.5)
        negated = _term_is_negated(clause, clause.find(term))
        if sentiment == "positive":
            if negated:
                negative += weight
                negative_hits.append("不" + term)
            else:
                positive += weight
                positive_hits.append(term)
        elif sentiment == "negative":
            if negated:
                positive += weight
                positive_hits.append("不" + term)
            else:
                negative += weight
                negative_hits.append(term)
        else:
            neutral_hint = True
    return positive, negative, positive_hits, negative_hits, neutral_hint


def _analyse_text(content: str, append_content: str = "", custom_terms: list[dict] | None = None) -> dict:
    text = f"{content} {append_content}".strip()
    positive_score, negative_score = 0.0, 0.0
    positive_hits: list[str] = []
    negative_hits: list[str] = []
    neutral_hint = False
    contrast_conclusion = 0.0
    for sentence in [part.strip() for part in re.split(r"[。！？!?；;\n]+", text) if part.strip()]:
        parts = re.split("|".join(map(re.escape, CONTRAST_WORDS)), sentence)
        for index, clause in enumerate(parts):
            if not clause:
                continue
            weight = 1.4 if index else (0.7 if len(parts) > 1 else 1.0)
            pos, neg, pos_hits, neg_hits, clause_neutral = _clause_sentiment(clause, custom_terms)
            positive_score += pos * weight
            negative_score += neg * weight
            positive_hits.extend(pos_hits)
            negative_hits.extend(neg_hits)
            neutral_hint = neutral_hint or clause_neutral
            if len(parts) > 1 and index == len(parts) - 1:
                contrast_conclusion = pos - neg
    implicit_negative = re.search(r"(?:收到|到手|刚用|用一次|才用).{0,8}(?:破|坏|断|漏|开胶)", text)
    if implicit_negative:
        negative_score += 2.5
        negative_hits.append(implicit_negative.group(0))
    sarcasm_hits = [phrase for phrase in SARCASM_MARKERS if phrase in text]
    ironic_positive_hits = [phrase for phrase in SARCASTIC_POSITIVE_PHRASES if phrase in text]
    if ironic_positive_hits and negative_hits:
        sarcasm_hits.extend(ironic_positive_hits)
    if sarcasm_hits:
        negative_score += max(3.5, positive_score + 1.0)
        negative_hits.extend(sarcasm_hits)
    difference = positive_score - negative_score
    conflict = positive_score > 0 and negative_score > 0
    if neutral_hint and abs(difference) < 1.5:
        sentiment = "neutral"
        confidence = 0.78
    elif difference >= 0.8:
        sentiment = "positive"
        confidence = min(0.96, 0.62 + abs(difference) * 0.1)
    elif difference <= -0.8:
        sentiment = "negative"
        confidence = min(0.96, 0.62 + abs(difference) * 0.1)
    elif conflict and abs(contrast_conclusion) >= 0.8:
        sentiment = "positive" if contrast_conclusion > 0 else "negative"
        confidence = 0.64
    else:
        sentiment = "neutral"
        confidence = 0.48 if not positive_hits and not negative_hits else 0.6
    if conflict:
        confidence = max(0.5, confidence - 0.12)
    confidence = round(confidence, 2)
    review_status = "needs_review" if confidence < 0.72 or (conflict and abs(difference) < 2) or bool(sarcasm_hits) else "auto"
    aspects = []
    for aspect, words in ASPECT_WORDS.items():
        hits = [word for word in words if word in text]
        if hits:
            aspects.append({"aspect": aspect, "sentiment": "negative" if any(word in negative_hits for word in hits) else sentiment, "keywords": hits[:5]})
    severity = "high" if any(word in text for word in ("安全", "欺诈", "假货", "严重破损", "退款")) else "normal"
    if sentiment == "negative" and len(negative_hits) >= 2:
        severity = "high" if severity == "high" else "medium"
    if severity == "high":
        review_status = "needs_review"
    reasons = []
    if positive_hits:
        reasons.append("正向表达：" + "、".join(dict.fromkeys(positive_hits)))
    if negative_hits:
        reasons.append("负向表达：" + "、".join(dict.fromkeys(negative_hits)))
    if conflict:
        reasons.append("同时存在正负表达")
    if sarcasm_hits:
        reasons.append("疑似反讽：" + "、".join(dict.fromkeys(sarcasm_hits)))
    if not reasons:
        reasons.append("未识别到明确情绪表达")
    if sarcasm_hits:
        routing_reason = "检测到反讽或正话反说，交给 AI 复核"
    elif conflict:
        routing_reason = "正负表达冲突，交给 AI 复核"
    elif confidence < 0.72:
        routing_reason = "规则置信度较低，交给 AI 复核"
    elif severity == "high":
        routing_reason = "高风险问题，交给 AI 复核"
    else:
        routing_reason = "表达明确，由本地规则完成"
    return {"sentiment": sentiment, "confidence": confidence, "aspects": aspects, "keywords": list(dict.fromkeys(negative_hits + positive_hits))[:12], "severity": severity, "review_status": review_status, "analysis_reason": "；".join(reasons), "routing_reason": routing_reason}


def _custom_terms_for_store(db, store_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT term, sentiment, weight FROM review_custom_terms WHERE enabled = 1 AND store_id IN (0, ?) ORDER BY store_id DESC, length(term) DESC",
        (store_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _analyse_with_db(db, store_id: int, content: str, append_content: str = "") -> tuple[dict, str]:
    data = _analyse_text(content, append_content, _custom_terms_for_store(db, store_id))
    remembered = db.execute(
        """SELECT corrected_sentiment, reason FROM review_sentiment_corrections
        WHERE store_id = ? AND content_hash = ? ORDER BY datetime(updated_at) DESC LIMIT 1""",
        (store_id, _content_hash(content, append_content)),
    ).fetchone()
    if not remembered:
        return data, "rules"
    data.update({
        "sentiment": remembered["corrected_sentiment"],
        "confidence": 0.98,
        "review_status": "auto",
        "analysis_reason": f"参考历史人工纠错：{remembered['reason'] or '相同表达'}",
        "routing_reason": "命中历史人工纠错记忆，无需调用 AI",
    })
    return data, "learned"


def _analyse_and_save(db, review_id: int, store_id: int, content: str, append_content: str = "") -> None:
    data, source = _analyse_with_db(db, store_id, content, append_content)
    _save_analysis(db, review_id, data, source=source)


def _save_analysis(db, review_id: int, data: dict, source: str = "rules") -> None:
    existing = db.execute("SELECT analysis_source FROM review_analysis WHERE review_id = ?", (review_id,)).fetchone()
    if existing and existing["analysis_source"] == "manual" and source != "manual":
        return
    status = data.get("review_status") or ("confirmed" if source == "manual" else "auto")
    model_version = "rules-v2" if source == "rules" else source
    db.execute(
        """
        INSERT INTO review_analysis
            (review_id, sentiment, confidence, aspects_json, keywords_json, severity, review_status, analysis_reason, analysis_source, routing_reason, model_version, analyzed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(review_id) DO UPDATE SET
            sentiment = excluded.sentiment, confidence = excluded.confidence,
            aspects_json = excluded.aspects_json, keywords_json = excluded.keywords_json,
            severity = excluded.severity, review_status = excluded.review_status,
            analysis_reason = excluded.analysis_reason, analysis_source = excluded.analysis_source,
            routing_reason = excluded.routing_reason,
            model_version = excluded.model_version, analyzed_at = excluded.analyzed_at
        """,
        (review_id, data["sentiment"], data["confidence"], json.dumps(data.get("aspects") or [], ensure_ascii=False), json.dumps(data.get("keywords") or [], ensure_ascii=False), data.get("severity") or "normal", status, data.get("analysis_reason") or "", source, data.get("routing_reason") or "", model_version, _now()),
    )


def _review_payload(row) -> dict:
    item = dict(row)
    for field in ("image_urls", "aspects_json", "keywords_json"):
        raw = item.pop(field, "[]")
        try:
            item[field.replace("_json", "")] = json.loads(raw or "[]")
        except (TypeError, ValueError):
            item[field.replace("_json", "")] = []
    score = int(item.get("priority_score") or 0)
    if not score:
        score += {"negative": 45, "neutral": 15}.get(item.get("sentiment"), 0)
        score += {"high": 30, "medium": 18}.get(item.get("severity"), 0)
        score += 12 if item.get("review_status") == "needs_review" else 0
        score += 8 if str(item.get("append_content") or "").strip() else 0
        score += 10 if item.get("process_status") == "pending" else 0
        sales = float(item.get("item_sales") or 0)
        score += 10 if sales >= 10000 else 5 if sales >= 1000 else 0
    item["priority_score"] = min(score, 100)
    item["priority_level"] = "urgent" if score >= 75 else "high" if score >= 50 else "normal"
    return item


def _knowledge_payload(row) -> dict:
    item = dict(row)
    try:
        item["problem_terms"] = json.loads(item.get("problem_terms") or "[]")
    except (TypeError, ValueError):
        item["problem_terms"] = []
    item["enabled"] = bool(item.get("enabled"))
    return item


def _match_review_knowledge(db, review: dict, *, persist: bool = True, limit: int = 5) -> list[dict]:
    text = f"{review.get('content') or ''} {review.get('append_content') or ''}".strip()
    rows = db.execute(
        """SELECT * FROM review_knowledge_articles
        WHERE enabled = 1 AND store_id IN (0, ?)
        ORDER BY store_id DESC, id ASC""",
        (review["store_id"],),
    ).fetchall()
    matches = []
    for row in rows:
        article = _knowledge_payload(row)
        terms = [str(term).strip() for term in article["problem_terms"] if str(term).strip()]
        normalized_text = re.sub(r"[\s的了着就]", "", text)
        matched_terms = [term for term in terms if term in text or re.sub(r"[\s的了着就]", "", term) in normalized_text]
        if not matched_terms:
            continue
        confidence = min(0.98, 0.48 + len(matched_terms) * 0.14 + (0.08 if article["store_id"] else 0))
        article.update({"confidence": round(confidence, 2), "matched_terms": matched_terms})
        matches.append(article)
    matches.sort(key=lambda item: (item["confidence"], item["store_id"], len(item["matched_terms"])), reverse=True)
    matches = matches[:limit]
    if persist:
        db.execute("DELETE FROM review_knowledge_matches WHERE review_id = ?", (review["id"],))
        for item in matches:
            db.execute(
                """INSERT INTO review_knowledge_matches
                (review_id, article_id, confidence, matched_terms_json, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                (review["id"], item["id"], item["confidence"], json.dumps(item["matched_terms"], ensure_ascii=False), _now()),
            )
    return matches


def _review_query(user: dict, store_id: int | None, item_id: str, sentiment: str, process_status: str, q: str, days: int | None, reply_status: str = "") -> tuple[str, list]:
    clauses, params = _visible_clause(user)
    if store_id is not None:
        clauses.append("r.store_id = ?")
        params.append(store_id)
    if item_id:
        clauses.append("r.item_id = ?")
        params.append(item_id)
    if sentiment:
        clauses.append("a.sentiment = ?")
        params.append(sentiment)
    if process_status:
        clauses.append("r.process_status = ?")
        params.append(process_status)
    if reply_status:
        clauses.append("r.reply_status = ?")
        params.append(reply_status)
    if q.strip():
        like = f"%{q.strip()}%"
        clauses.append("(r.review_id LIKE ? OR r.content LIKE ? OR r.append_content LIKE ? OR r.item_title LIKE ? OR r.item_id LIKE ?)")
        params.extend([like, like, like, like, like])
    if days:
        clauses.append("datetime(r.review_time) >= datetime(?)")
        params.append((datetime.now(timezone.utc) - timedelta(days=days)).isoformat())
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


@router.get("")
def list_customers() -> dict:
    return {"items": [], "message": "客户管理请使用评论接口"}


@router.get("/reviews")
def list_reviews(
    store_id: int | None = None,
    item_id: str = "",
    sentiment: str = Query("", pattern="^(|positive|neutral|negative)$"),
    process_status: str = Query("", pattern="^(|pending|contacted|resolved|ignored)$"),
    reply_status: str = Query("", pattern="^(|draft|approved|published)$"),
    q: str = "",
    days: int | None = Query(None, ge=1, le=3650),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    order_by: str = Query("priority", pattern="^(priority|recent)$"),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if store_id is not None:
        _ensure_store_access(user, store_id, db)
    where, params = _review_query(user, store_id, item_id.strip(), sentiment, process_status, q, days, reply_status)
    total = db.execute("SELECT COUNT(*) AS c FROM product_reviews r LEFT JOIN review_analysis a ON a.review_id = r.id" + where, params).fetchone()["c"]
    rows = db.execute(
        """
        SELECT r.*, a.sentiment, a.confidence, a.aspects_json, a.keywords_json, a.severity,
               a.review_status, a.analysis_reason, a.analysis_source, a.routing_reason, s.name AS store_name,
               COALESCE(rt.sales, 0) AS item_sales,
               (CASE a.sentiment WHEN 'negative' THEN 45 WHEN 'neutral' THEN 15 ELSE 0 END
                + CASE a.severity WHEN 'high' THEN 30 WHEN 'medium' THEN 18 ELSE 0 END
                + CASE WHEN a.review_status = 'needs_review' THEN 12 ELSE 0 END
                + CASE WHEN trim(r.append_content) != '' THEN 8 ELSE 0 END
                + CASE WHEN r.process_status = 'pending' THEN 10 ELSE 0 END
                + CASE WHEN COALESCE(rt.sales, 0) >= 10000 THEN 10 WHEN COALESCE(rt.sales, 0) >= 1000 THEN 5 ELSE 0 END) AS priority_score
        FROM product_reviews r
        LEFT JOIN review_analysis a ON a.review_id = r.id
        LEFT JOIN stores s ON s.id = r.store_id
        LEFT JOIN store_item_realtime rt ON rt.store_id = r.store_id AND rt.item_id = r.item_id
        """ + where + (" ORDER BY priority_score DESC, datetime(r.review_time) DESC, r.id DESC" if order_by == "priority" else " ORDER BY datetime(r.review_time) DESC, r.id DESC") + " LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    return {"items": [_review_payload(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/reviews/summary")
def review_summary(
    store_id: int | None = None,
    item_id: str = "",
    days: int = Query(30, ge=1, le=3650),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if store_id is not None:
        _ensure_store_access(user, store_id, db)
    where, params = _review_query(user, store_id, item_id.strip(), "", "", "", days)
    rows = db.execute("SELECT r.item_id, r.item_title, r.review_time, r.process_status, a.sentiment, a.aspects_json, a.severity, a.review_status FROM product_reviews r LEFT JOIN review_analysis a ON a.review_id = r.id" + where, params).fetchall()
    total = len(rows)
    sentiments = Counter((row["sentiment"] or "neutral") for row in rows)
    aspects: Counter[str] = Counter()
    negative_items: Counter[str] = Counter()
    trend: dict[str, dict] = {}
    pending = 0
    needs_review = 0
    for row in rows:
        if row["sentiment"] == "negative":
            negative_items[row["item_title"] or row["item_id"] or "未命名商品"] += 1
        if row["process_status"] == "pending" and (row["sentiment"] == "negative" or row["severity"] in ("medium", "high")):
            pending += 1
        needs_review += int(row["review_status"] == "needs_review")
        try:
            parsed = json.loads(row["aspects_json"] or "[]")
        except (TypeError, ValueError):
            parsed = []
        for aspect in parsed:
            if aspect.get("sentiment") == "negative":
                aspects[aspect.get("aspect", "其他")] += 1
        day = str(row["review_time"] or "")[:10]
        if day:
            point = trend.setdefault(day, {"date": day, "total": 0, "negative": 0})
            point["total"] += 1
            point["negative"] += int(row["sentiment"] == "negative")
    return {
        "days": days, "total": total, "positive": sentiments["positive"], "neutral": sentiments["neutral"], "negative": sentiments["negative"],
        "positive_rate": round(sentiments["positive"] / total * 100, 1) if total else 0,
        "negative_rate": round(sentiments["negative"] / total * 100, 1) if total else 0,
        "pending_count": pending, "needs_review_count": needs_review,
        "top_aspects": [{"aspect": key, "count": value} for key, value in aspects.most_common(8)],
        "negative_items": [{"item_title": key, "count": value} for key, value in negative_items.most_common(8)],
        "trend": [trend[key] for key in sorted(trend)],
    }


@router.get("/reviews/product-summary")
def review_product_summary(
    store_id: int | None = None,
    days: int = Query(30, ge=1, le=3650),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if store_id is not None:
        _ensure_store_access(user, store_id, db)
    where, params = _review_query(user, store_id, "", "", "", "", days)
    rows = db.execute(
        """SELECT r.item_id, r.item_title, COUNT(*) AS total,
        SUM(CASE WHEN a.sentiment = 'positive' THEN 1 ELSE 0 END) AS positive,
        SUM(CASE WHEN a.sentiment = 'negative' THEN 1 ELSE 0 END) AS negative
        FROM product_reviews r LEFT JOIN review_analysis a ON a.review_id = r.id""" + where +
        " GROUP BY r.store_id, r.item_id, r.item_title ORDER BY negative DESC, total DESC LIMIT 100", params).fetchall()
    return {"days": days, "items": [{"item_id": row["item_id"], "item_title": row["item_title"], "total": row["total"], "positive": row["positive"] or 0, "negative": row["negative"] or 0, "negative_rate": round((row["negative"] or 0) / row["total"] * 100, 1) if row["total"] else 0} for row in rows]}


@router.get("/reviews/alerts")
def review_alerts(
    store_id: int | None = None,
    status: str = Query("open", pattern="^(open|acknowledged|resolved|ignored|all)$"),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if store_id is not None:
        _ensure_store_access(user, store_id, db)
    clauses, params = _visible_clause(user)
    if store_id is not None:
        clauses.append("a.store_id = ?"); params.append(store_id)
    if status != "all":
        clauses.append("a.status = ?"); params.append(status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.execute("SELECT a.*, r.content, r.item_id, r.item_title, r.review_time FROM review_alerts a JOIN product_reviews r ON r.id = a.review_id" + where + " ORDER BY a.created_at DESC LIMIT 200", params).fetchall()
    return {"items": [dict(row) for row in rows], "total": len(rows)}


@router.put("/reviews/alerts/{alert_id}")
def update_review_alert(alert_id: int, body: ReviewAlertStatusIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    row = db.execute("SELECT * FROM review_alerts WHERE id = ?", (alert_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="预警不存在")
    _ensure_store_access(user, row["store_id"], db)
    db.execute("UPDATE review_alerts SET status = ? WHERE id = ?", (body.status, alert_id))
    return {"ok": True, "status": body.status}


def _review_rows_for_ai(db, user: dict, store_id: int | None, days: int) -> list[dict]:
    where, params = _review_query(user, store_id, "", "", "", "", days)
    return [dict(row) for row in db.execute("SELECT r.*, a.sentiment, a.aspects_json, a.keywords_json FROM product_reviews r LEFT JOIN review_analysis a ON a.review_id = r.id" + where + " ORDER BY datetime(r.review_time) DESC LIMIT 300", params).fetchall()]


@router.post("/reviews/ai-summary")
def review_ai_summary(body: ReviewAiIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if body.store_id is not None:
        _ensure_store_access(user, body.store_id, db)
    rows = _review_rows_for_ai(db, user, body.store_id, body.days)
    if not rows:
        raise HTTPException(status_code=400, detail="当前时间范围内没有评论")
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    excerpts = "\n".join(f"- {r['item_title'] or r['item_id']}：{r['content'][:180]}" for r in rows)
    prompt = f"请分析近{body.days}天电商评论，输出简洁中文报告，包含：客户最满意点、主要问题、涉及商品、可执行改进建议。不要编造数据。\n评论：\n{excerpts}"
    try:
        result = chat_completion(cfg, [{"role": "user", "content": prompt}], timeout=120.0, max_tokens=1200)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"summary": result.strip(), "count": len(rows), "days": body.days}


def _parse_ai_review_result(text: str) -> list[dict]:
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text.strip(), flags=re.I)
    cleaned = re.sub(r"```(?:json)?", "", cleaned, flags=re.I).replace("```", "").strip()
    normalized = cleaned.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"}))
    normalized = re.sub(r",\s*([}\]])", r"\1", normalized)

    def review_items(payload) -> list[dict]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict) and ("id" in item or "review_id" in item)]
        if isinstance(payload, dict):
            if "id" in payload or "review_id" in payload:
                return [payload]
            for key in ("results", "items", "data", "reviews", "classifications", "output"):
                if key in payload:
                    nested = review_items(payload[key])
                    if nested:
                        return nested
        if isinstance(payload, str) and payload.strip() != normalized:
            try:
                return review_items(json.loads(payload))
            except ValueError:
                return []
        return []

    for candidate in (normalized, cleaned):
        try:
            items = review_items(json.loads(candidate))
            if items:
                return items
        except ValueError:
            try:
                items = review_items(ast.literal_eval(candidate))
                if items:
                    return items
            except (SyntaxError, ValueError):
                pass

    decoder = json.JSONDecoder()
    recovered: list[dict] = []
    for index, char in enumerate(normalized):
        if char not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(normalized[index:])
        except ValueError:
            continue
        items = review_items(payload)
        if isinstance(payload, list) and items:
            return items
        recovered.extend(items)
    unique = {str(item.get("id") or item.get("review_id")): item for item in recovered if item.get("id") is not None or item.get("review_id") is not None}
    if unique:
        return list(unique.values())
    raise AIError("模型未返回可识别的情绪分类 JSON，请重试或更换模型")


def _run_ai_review_rows(db, rows: list, cfg: dict) -> int:
    if not rows:
        return 0
    store_ids = sorted({int(row["store_id"]) for row in rows})
    placeholders = ",".join("?" for _ in store_ids)
    corrections = db.execute(
        f"""SELECT c.corrected_sentiment AS sentiment, r.content, r.append_content
        FROM review_sentiment_corrections c JOIN product_reviews r ON r.id = c.review_id
        WHERE c.store_id IN ({placeholders}) ORDER BY datetime(c.updated_at) DESC LIMIT 20""",
        store_ids,
    ).fetchall()
    examples = [{"content": f"{row['content']} {row['append_content']}".strip()[:200], "sentiment": row["sentiment"]} for row in corrections]
    row_ids = {int(row["id"]) for row in rows}
    updated = 0
    review_cfg = dict(cfg)
    review_cfg["temperature"] = 0.1
    for offset in range(0, len(rows), 15):
        batch = rows[offset:offset + 15]
        samples = [{"id": row["id"], "content": f"{row['content']} {row['append_content']}".strip()[:300]} for row in batch]
        prompt = (
            "你是电商评论情绪分类器。请结合否定、转折、反讽和上下文判断每条评论。"
            "只返回完整 JSON 数组，不要 Markdown 或解释，必须包含全部输入 id。每项格式："
            '{"id":数字,"sentiment":"positive|neutral|negative","confidence":0到1,"reason":"不超过30字","aspects":["质量"]}。'
            "没有明确褒贬时判 neutral，不要因‘口臭没了、去掉牙渍、不刺激’等改善描述误判为负面。"
            f"人工纠错示例：{json.dumps(examples, ensure_ascii=False)}\n待判断评论：\n"
            + json.dumps(samples, ensure_ascii=False)
        )
        response = chat_completion(review_cfg, [{"role": "user", "content": prompt}], timeout=120.0, max_tokens=3000)
        parsed = _parse_ai_review_result(response)
        for item in parsed:
            try:
                review_id = int(item.get("id") or item.get("review_id"))
                sentiment = str(item.get("sentiment") or item.get("label") or "").lower()
                sentiment = {"正向": "positive", "积极": "positive", "好评": "positive", "中性": "neutral", "中评": "neutral", "负向": "negative", "消极": "negative", "差评": "negative"}.get(sentiment, sentiment)
                raw_confidence = str(item.get("confidence") or item.get("score") or 0).strip()
                confidence = float(raw_confidence.rstrip("%"))
                if raw_confidence.endswith("%") or confidence > 1:
                    confidence /= 100
                confidence = min(1.0, max(0.0, confidence))
            except (TypeError, ValueError):
                continue
            if review_id not in row_ids or sentiment not in {"positive", "neutral", "negative"}:
                continue
            raw_aspects = item.get("aspects") or item.get("topics") or []
            aspect_names = raw_aspects if isinstance(raw_aspects, list) else re.split(r"[,，、]", str(raw_aspects))
            data = {
                "sentiment": sentiment,
                "confidence": round(confidence, 2),
                "aspects": [{"aspect": str(name)[:20], "sentiment": sentiment, "keywords": []} for name in aspect_names[:8] if str(name).strip()],
                "keywords": [],
                "severity": "medium" if sentiment == "negative" else "normal",
                "review_status": "auto" if confidence >= 0.72 else "needs_review",
                "analysis_reason": str(item.get("reason") or item.get("explanation") or "AI 语义复核")[:300],
                "routing_reason": "规则判定为难例，已由 AI 完成语义复核",
            }
            _save_analysis(db, review_id, data, source="ai")
            updated += 1
    return updated


def _ai_review_pending_for_store(db, store_id: int, limit: int = 30) -> int:
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        return 0
    rows = db.execute(
        """SELECT r.id, r.store_id, r.content, r.append_content FROM product_reviews r
        JOIN review_analysis a ON a.review_id = r.id
        WHERE r.store_id = ? AND a.review_status = 'needs_review' AND a.analysis_source != 'manual'
        ORDER BY datetime(r.review_time) DESC LIMIT ?""",
        (store_id, limit),
    ).fetchall()
    return _run_ai_review_rows(db, rows, cfg)


def _fallback_negative_reply(db, review: dict, knowledge: list[dict]) -> str:
    for article in knowledge:
        reply = str(article.get("reply_template") or "").strip()
        if reply:
            return reply[:500]
    category = str(knowledge[0].get("category") or "") if knowledge else ""
    if category:
        template = db.execute(
            "SELECT content FROM review_reply_templates WHERE category = ? ORDER BY id LIMIT 1",
            (category,),
        ).fetchone()
        if template and str(template["content"] or "").strip():
            return str(template["content"]).strip()[:500]
    return "非常抱歉给您带来不好的体验。我们已认真记录您的反馈，请联系在线客服并提供订单信息，我们会尽快核实并妥善处理。"


def _generate_negative_reply_drafts(db, store_id: int, limit: int = 30) -> dict:
    rows = db.execute(
        """SELECT r.id, r.store_id, r.item_id, r.item_title, r.content, r.append_content
        FROM product_reviews r JOIN review_analysis a ON a.review_id = r.id
        WHERE r.store_id = ? AND a.sentiment = 'negative'
          AND r.reply_status = 'none' AND trim(r.reply_content) = ''
        ORDER BY datetime(r.review_time) DESC, r.id DESC LIMIT ?""",
        (store_id, limit),
    ).fetchall()
    if not rows:
        return {"generated": 0, "ai": 0, "fallback": 0}
    prepared = []
    fallback_replies: dict[int, str] = {}
    for raw_row in rows:
        review = dict(raw_row)
        knowledge = _match_review_knowledge(db, review)
        fallback_replies[review["id"]] = _fallback_negative_reply(db, review, knowledge)
        prepared.append({
            "id": review["id"],
            "product": review["item_title"] or review["item_id"],
            "review": f"{review['content']} {review['append_content']}".strip()[:500],
            "handling": [
                {"title": item["title"], "solution": item["solution"], "reply_template": item["reply_template"]}
                for item in knowledge[:3]
            ],
        })
    ai_replies: dict[int, str] = {}
    cfg = get_default_config(db)
    if cfg and cfg.get("api_key"):
        reply_cfg = dict(cfg)
        reply_cfg["temperature"] = 0.3
        for offset in range(0, len(prepared), 10):
            batch = prepared[offset:offset + 10]
            prompt = (
                "你是电商售后客服。请为每条差评生成一段真诚、简短、等待人工审核的中文回复草稿。"
                "先道歉并回应具体问题，引导联系在线客服，不得编造补偿、退款结果或承诺无法确认的事项。"
                "只返回完整 JSON 数组，不要 Markdown。格式："
                '[{"id":数字,"reply":"不超过120字的回复"}]。\n'
                + json.dumps(batch, ensure_ascii=False)
            )
            try:
                response = chat_completion(reply_cfg, [{"role": "user", "content": prompt}], timeout=120.0, max_tokens=2400)
                for item in _parse_ai_review_result(response):
                    try:
                        review_id = int(item.get("id") or item.get("review_id"))
                    except (TypeError, ValueError):
                        continue
                    reply = str(item.get("reply") or item.get("content") or item.get("response") or "").strip()
                    if review_id in fallback_replies and reply:
                        ai_replies[review_id] = reply[:500]
            except AIError:
                continue
    generated = 0
    ai_count = 0
    now = _now()
    for row in rows:
        review_id = int(row["id"])
        reply = ai_replies.get(review_id) or fallback_replies[review_id]
        cur = db.execute(
            """UPDATE product_reviews SET reply_status = 'draft', reply_content = ?, reply_error = '',
            reply_approved_at = NULL, updated_at = ?
            WHERE id = ? AND reply_status = 'none' AND trim(reply_content) = ''""",
            (reply, now, review_id),
        )
        if cur.rowcount:
            generated += 1
            ai_count += int(review_id in ai_replies)
    return {"generated": generated, "ai": ai_count, "fallback": generated - ai_count}


@router.post("/reviews/ai-review")
def review_ai_review(body: ReviewAiReviewIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if body.store_id is not None:
        _ensure_store_access(user, body.store_id, db)
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    where, params = _review_query(user, body.store_id, "", "", "", "", body.days)
    where += (" AND " if where else " WHERE ") + "a.review_status = 'needs_review' AND a.analysis_source != 'manual'"
    rows = db.execute(
        "SELECT r.id, r.store_id, r.content, r.append_content FROM product_reviews r JOIN review_analysis a ON a.review_id = r.id" + where + " ORDER BY datetime(r.review_time) DESC LIMIT ?",
        [*params, body.limit],
    ).fetchall()
    try:
        updated = _run_ai_review_rows(db, rows, cfg)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    store_ids = sorted({int(row["store_id"]) for row in rows})
    drafts = {"generated": 0, "ai": 0, "fallback": 0}
    for store_id in store_ids:
        result = _generate_negative_reply_drafts(db, store_id)
        for key in drafts:
            drafts[key] += result[key]
    return {"ok": True, "requested": len(rows), "updated": updated, "auto_reply_drafts": drafts}


def _reanalyze_term_matches(db, store_id: int, term: str) -> int:
    if store_id:
        rows = db.execute(
            "SELECT id, store_id, content, append_content FROM product_reviews WHERE store_id = ? AND (content LIKE ? OR append_content LIKE ?)",
            (store_id, f"%{term}%", f"%{term}%"),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, store_id, content, append_content FROM product_reviews WHERE content LIKE ? OR append_content LIKE ?",
            (f"%{term}%", f"%{term}%"),
        ).fetchall()
    for row in rows:
        _analyse_and_save(db, row["id"], row["store_id"], row["content"], row["append_content"])
    return len(rows)


@router.get("/reviews/custom-terms")
def list_review_custom_terms(store_id: int | None = None, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if store_id is not None:
        _ensure_store_access(user, store_id, db)
        rows = db.execute("SELECT * FROM review_custom_terms WHERE store_id IN (0, ?) ORDER BY store_id DESC, id DESC", (store_id,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM review_custom_terms WHERE store_id = 0 ORDER BY id DESC").fetchall()
    return {"items": [{**dict(row), "enabled": bool(row["enabled"])} for row in rows]}


@router.post("/reviews/custom-terms")
def create_review_custom_term(body: ReviewCustomTermIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if body.store_id:
        _ensure_store_access(user, body.store_id, db)
    elif user.get("role") not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="只有管理员可以维护全局词库")
    now = _now()
    try:
        cur = db.execute(
            "INSERT INTO review_custom_terms (store_id, term, sentiment, weight, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (body.store_id, body.term.strip(), body.sentiment, body.weight, int(body.enabled), now, now),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=400, detail="该词已经存在") from exc
        raise
    affected = _reanalyze_term_matches(db, body.store_id, body.term.strip())
    return {"item": dict(db.execute("SELECT * FROM review_custom_terms WHERE id = ?", (cur.lastrowid,)).fetchone()), "reanalyzed": affected}


@router.put("/reviews/custom-terms/{term_id}")
def update_review_custom_term(term_id: int, body: ReviewCustomTermIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    existing = db.execute("SELECT * FROM review_custom_terms WHERE id = ?", (term_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="词条不存在")
    for scoped_store in {int(existing["store_id"]), body.store_id}:
        if scoped_store:
            _ensure_store_access(user, scoped_store, db)
    if (not existing["store_id"] or not body.store_id) and user.get("role") not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="只有管理员可以维护全局词库")
    try:
        db.execute(
            "UPDATE review_custom_terms SET store_id = ?, term = ?, sentiment = ?, weight = ?, enabled = ?, updated_at = ? WHERE id = ?",
            (body.store_id, body.term.strip(), body.sentiment, body.weight, int(body.enabled), _now(), term_id),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=400, detail="该词已经存在") from exc
        raise
    affected = _reanalyze_term_matches(db, int(existing["store_id"]), str(existing["term"]))
    affected += _reanalyze_term_matches(db, body.store_id, body.term.strip())
    return {"item": dict(db.execute("SELECT * FROM review_custom_terms WHERE id = ?", (term_id,)).fetchone()), "reanalyzed": affected}


@router.delete("/reviews/custom-terms/{term_id}")
def delete_review_custom_term(term_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    existing = db.execute("SELECT * FROM review_custom_terms WHERE id = ?", (term_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="词条不存在")
    if existing["store_id"]:
        _ensure_store_access(user, existing["store_id"], db)
    elif user.get("role") not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="只有管理员可以维护全局词库")
    db.execute("DELETE FROM review_custom_terms WHERE id = ?", (term_id,))
    affected = _reanalyze_term_matches(db, int(existing["store_id"]), str(existing["term"]))
    return {"ok": True, "reanalyzed": affected}


def _topic_data(rows: list[dict]) -> dict:
    topics: dict[str, dict] = {}
    emerging: Counter[str] = Counter()
    for row in rows:
        try:
            aspects = json.loads(row.get("aspects_json") or "[]")
            keywords = json.loads(row.get("keywords_json") or "[]")
        except (TypeError, ValueError):
            aspects, keywords = [], []
        for keyword in keywords:
            if len(str(keyword)) >= 2:
                emerging[str(keyword)] += 1
        for aspect in aspects:
            name = str(aspect.get("aspect") or "其他")
            item = topics.setdefault(name, {"topic": name, "count": 0, "negative": 0, "products": Counter(), "examples": []})
            item["count"] += 1
            item["negative"] += int(aspect.get("sentiment") == "negative" or row.get("sentiment") == "negative")
            product = row.get("item_title") or row.get("item_id") or "未关联商品"
            item["products"][product] += 1
            if len(item["examples"]) < 3:
                item["examples"].append({"id": row["id"], "content": (row.get("content") or row.get("append_content") or "")[:100], "item_title": product})
    result = []
    for item in topics.values():
        result.append({
            "topic": item["topic"], "count": item["count"], "negative": item["negative"],
            "negative_rate": round(item["negative"] / item["count"] * 100, 1) if item["count"] else 0,
            "products": [{"name": key, "count": value} for key, value in item["products"].most_common(3)],
            "examples": item["examples"],
        })
    result.sort(key=lambda item: (item["negative"], item["count"]), reverse=True)
    return {"items": result, "emerging_terms": [{"term": key, "count": value} for key, value in emerging.most_common(12)]}


@router.get("/reviews/topics")
def review_topics(store_id: int | None = None, days: int = Query(30, ge=1, le=3650), user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if store_id is not None:
        _ensure_store_access(user, store_id, db)
    where, params = _review_query(user, store_id, "", "", "", "", days)
    rows = [dict(row) for row in db.execute(
        "SELECT r.id, r.item_id, r.item_title, r.content, r.append_content, a.sentiment, a.aspects_json, a.keywords_json FROM product_reviews r LEFT JOIN review_analysis a ON a.review_id = r.id" + where,
        params,
    ).fetchall()]
    return {"days": days, "total": len(rows), **_topic_data(rows)}


def _evaluate_trend_alert(db, store_id: int) -> dict | None:
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=3)
    baseline_start = current_start - timedelta(days=14)
    current = db.execute(
        """SELECT COUNT(*) AS total, SUM(CASE WHEN a.sentiment = 'negative' THEN 1 ELSE 0 END) AS negative
        FROM product_reviews r LEFT JOIN review_analysis a ON a.review_id = r.id
        WHERE r.store_id = ? AND datetime(r.review_time) >= datetime(?)""",
        (store_id, current_start.isoformat()),
    ).fetchone()
    baseline = db.execute(
        """SELECT COUNT(*) AS total, SUM(CASE WHEN a.sentiment = 'negative' THEN 1 ELSE 0 END) AS negative
        FROM product_reviews r LEFT JOIN review_analysis a ON a.review_id = r.id
        WHERE r.store_id = ? AND datetime(r.review_time) >= datetime(?) AND datetime(r.review_time) < datetime(?)""",
        (store_id, baseline_start.isoformat(), current_start.isoformat()),
    ).fetchone()
    current_total, baseline_total = int(current["total"] or 0), int(baseline["total"] or 0)
    current_negative, baseline_negative = int(current["negative"] or 0), int(baseline["negative"] or 0)
    current_rate = current_negative / current_total * 100 if current_total else 0
    baseline_rate = baseline_negative / baseline_total * 100 if baseline_total else 0
    if current_total < 3 or current_negative < 2 or current_rate < max(25, baseline_rate + 15):
        return None
    level = "critical" if current_rate >= max(50, baseline_rate + 30) else "warning"
    message = f"近 3 天差评率 {current_rate:.1f}%，较此前基线 {baseline_rate:.1f}% 明显上升"
    alert_date = now.date().isoformat()
    db.execute(
        """INSERT INTO review_trend_alerts
        (store_id, alert_date, current_count, current_negative, current_rate, baseline_count, baseline_rate, level, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(store_id, alert_date) DO UPDATE SET
            current_count = excluded.current_count, current_negative = excluded.current_negative,
            current_rate = excluded.current_rate, baseline_count = excluded.baseline_count,
            baseline_rate = excluded.baseline_rate, level = excluded.level, message = excluded.message""",
        (store_id, alert_date, current_total, current_negative, round(current_rate, 1), baseline_total, round(baseline_rate, 1), level, message, _now()),
    )
    return dict(db.execute("SELECT * FROM review_trend_alerts WHERE store_id = ? AND alert_date = ?", (store_id, alert_date)).fetchone())


@router.get("/reviews/trend-alerts")
def review_trend_alerts(store_id: int | None = None, status: str = Query("open", pattern="^(open|acknowledged|resolved|ignored|all)$"), user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if store_id is not None:
        _ensure_store_access(user, store_id, db)
        _evaluate_trend_alert(db, store_id)
    visible = visible_store_ids(user)
    clauses, params = [], []
    if store_id is not None:
        clauses.append("t.store_id = ?"); params.append(store_id)
    elif visible is not None:
        if not visible:
            clauses.append("1 = 0")
        else:
            clauses.append(f"t.store_id IN ({','.join('?' for _ in visible)})"); params.extend(visible)
    if status != "all":
        clauses.append("t.status = ?"); params.append(status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.execute("SELECT t.*, s.name AS store_name FROM review_trend_alerts t LEFT JOIN stores s ON s.id = t.store_id" + where + " ORDER BY t.alert_date DESC, t.id DESC", params).fetchall()
    return {"items": [dict(row) for row in rows], "total": len(rows)}


@router.put("/reviews/trend-alerts/{alert_id}")
def update_review_trend_alert(alert_id: int, body: ReviewAlertStatusIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    row = db.execute("SELECT * FROM review_trend_alerts WHERE id = ?", (alert_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="趋势预警不存在")
    _ensure_store_access(user, row["store_id"], db)
    db.execute("UPDATE review_trend_alerts SET status = ? WHERE id = ?", (body.status, alert_id))
    return {"ok": True, "status": body.status}


@router.get("/reviews/accuracy")
def review_accuracy(store_id: int | None = None, days: int = Query(90, ge=1, le=3650), user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if store_id is not None:
        _ensure_store_access(user, store_id, db)
    where, params = _review_query(user, store_id, "", "", "", "", days)
    analyses = db.execute("SELECT a.analysis_source, a.review_status, a.confidence FROM product_reviews r JOIN review_analysis a ON a.review_id = r.id" + where, params).fetchall()
    correction_where = where.replace("a.", "a.")
    corrections = db.execute(
        "SELECT c.original_sentiment, c.corrected_sentiment FROM product_reviews r JOIN review_analysis a ON a.review_id = r.id JOIN review_sentiment_corrections c ON c.review_id = r.id" + correction_where,
        params,
    ).fetchall()
    source_counts = Counter(row["analysis_source"] for row in analyses)
    transitions = Counter(f"{row['original_sentiment']}→{row['corrected_sentiment']}" for row in corrections if row["original_sentiment"] != row["corrected_sentiment"])
    changed = sum(1 for row in corrections if row["original_sentiment"] != row["corrected_sentiment"])
    confirmed = source_counts["manual"]
    evaluated = len(corrections)
    return {
        "days": days, "total": len(analyses), "confirmed_sample": confirmed, "corrected_count": changed,
        "manual_agreement_rate": round((evaluated - changed) / evaluated * 100, 1) if evaluated else None,
        "correction_rate": round(changed / evaluated * 100, 1) if evaluated else None,
        "needs_review_count": sum(1 for row in analyses if row["review_status"] == "needs_review"),
        "average_confidence": round(sum(float(row["confidence"] or 0) for row in analyses) / len(analyses) * 100, 1) if analyses else 0,
        "sources": [{"source": key, "count": value} for key, value in source_counts.most_common()],
        "corrections": [{"transition": key, "count": value} for key, value in transitions.most_common()],
    }


def _build_weekly_report(rows: list[dict], week_start: str, week_end: str) -> dict:
    sentiments = Counter(row.get("sentiment") or "neutral" for row in rows)
    topics = _topic_data(rows)
    products: dict[str, dict] = {}
    for row in rows:
        name = row.get("item_title") or row.get("item_id") or "未关联商品"
        item = products.setdefault(name, {"item_title": name, "total": 0, "negative": 0})
        item["total"] += 1
        item["negative"] += int(row.get("sentiment") == "negative")
    top_products = sorted(products.values(), key=lambda item: (item["negative"], item["total"]), reverse=True)[:5]
    action_map = {"质量": "复查高频质量问题对应批次并抽检", "包装": "复核包装材料和仓库打包流程", "物流": "核查承运商时效并优化异常件跟进", "客服": "复盘客服响应话术和处理时效", "尺码": "完善尺码说明和购买建议", "材质": "补充材质说明并核对页面描述", "颜色": "校准商品图片与实物色差", "性价比": "检查价格表达、赠品和预期管理"}
    actions = [action_map.get(item["topic"], f"跟进“{item['topic']}”相关反馈") for item in topics["items"][:4] if item["negative"]]
    total = len(rows)
    negative = sentiments["negative"]
    return {
        "week_start": week_start, "week_end": week_end, "total": total,
        "positive": sentiments["positive"], "neutral": sentiments["neutral"], "negative": negative,
        "negative_rate": round(negative / total * 100, 1) if total else 0,
        "summary": f"本周共收到 {total} 条评论，其中差评 {negative} 条，差评率 {round(negative / total * 100, 1) if total else 0}% 。",
        "topics": topics["items"][:6], "products": top_products, "actions": actions or ["本周暂无集中问题，继续观察评论变化"],
    }


def _generate_weekly_report(db, store_id: int) -> dict:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=today.weekday())
    rows = [dict(row) for row in db.execute(
        """SELECT r.id, r.item_id, r.item_title, r.content, r.append_content, a.sentiment, a.aspects_json, a.keywords_json
        FROM product_reviews r LEFT JOIN review_analysis a ON a.review_id = r.id
        WHERE r.store_id = ? AND date(r.review_time) >= date(?) AND date(r.review_time) <= date(?)""",
        (store_id, start.isoformat(), today.isoformat()),
    ).fetchall()]
    report = _build_weekly_report(rows, start.isoformat(), today.isoformat())
    now = _now()
    db.execute(
        """INSERT INTO review_weekly_reports (store_id, week_start, week_end, report_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(store_id, week_start) DO UPDATE SET
        week_end = excluded.week_end, report_json = excluded.report_json, updated_at = excluded.updated_at""",
        (store_id, start.isoformat(), today.isoformat(), json.dumps(report, ensure_ascii=False), now, now),
    )
    return report


@router.get("/reviews/weekly-report")
def review_weekly_report(store_id: int | None = None, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if store_id is not None:
        _ensure_store_access(user, store_id, db)
        return _generate_weekly_report(db, store_id)
    visible = visible_store_ids(user)
    clauses, params = [], []
    if visible is not None:
        if not visible:
            clauses.append("1 = 0")
        else:
            clauses.append(f"r.store_id IN ({','.join('?' for _ in visible)})"); params.extend(visible)
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=today.weekday())
    clauses.extend(["date(r.review_time) >= date(?)", "date(r.review_time) <= date(?)"]); params.extend([start.isoformat(), today.isoformat()])
    rows = [dict(row) for row in db.execute(
        "SELECT r.id, r.item_id, r.item_title, r.content, r.append_content, a.sentiment, a.aspects_json, a.keywords_json FROM product_reviews r LEFT JOIN review_analysis a ON a.review_id = r.id WHERE " + " AND ".join(clauses),
        params,
    ).fetchall()]
    return _build_weekly_report(rows, start.isoformat(), today.isoformat())


@router.post("/reviews/ask")
def ask_reviews(body: ReviewAskIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if body.store_id is not None:
        _ensure_store_access(user, body.store_id, db)
    rows = _review_rows_for_ai(db, user, body.store_id, body.days)
    if not rows:
        raise HTTPException(status_code=400, detail="当前时间范围内没有评论")
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    excerpts = [{"商品": row["item_title"] or row["item_id"], "评论": row["content"][:180], "情绪": row.get("sentiment") or "neutral"} for row in rows[:100]]
    prompt = f"你是电商评论分析助手。只能根据提供的评论回答，不确定时明确说明。问题：{body.question.strip()}\n评论数据：{json.dumps(excerpts, ensure_ascii=False)}"
    try:
        answer = chat_completion(cfg, [{"role": "user", "content": prompt}], timeout=120.0, max_tokens=1200)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"answer": answer.strip(), "review_count": len(rows), "days": body.days}


@router.get("/reviews/knowledge")
def list_review_knowledge(store_id: int | None = None, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if store_id is not None:
        _ensure_store_access(user, store_id, db)
        rows = db.execute(
            "SELECT * FROM review_knowledge_articles WHERE store_id IN (0, ?) ORDER BY store_id DESC, category, id",
            (store_id,),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM review_knowledge_articles WHERE store_id = 0 ORDER BY category, id").fetchall()
    return {"items": [_knowledge_payload(row) for row in rows]}


@router.post("/reviews/knowledge")
def create_review_knowledge(body: ReviewKnowledgeIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if body.store_id:
        _ensure_store_access(user, body.store_id, db)
    now = _now()
    terms = list(dict.fromkeys(term.strip() for term in body.problem_terms if term.strip()))
    try:
        cur = db.execute(
            """INSERT INTO review_knowledge_articles
            (store_id, title, category, problem_terms, solution, reply_template, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.store_id, body.title.strip(), body.category.strip() or "通用", json.dumps(terms, ensure_ascii=False), body.solution.strip(), body.reply_template.strip(), int(body.enabled), now, now),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=400, detail="同一店铺已存在同名知识条目") from exc
        raise
    return {"item": _knowledge_payload(db.execute("SELECT * FROM review_knowledge_articles WHERE id = ?", (cur.lastrowid,)).fetchone())}


@router.put("/reviews/knowledge/{article_id}")
def update_review_knowledge(article_id: int, body: ReviewKnowledgeIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    existing = db.execute("SELECT * FROM review_knowledge_articles WHERE id = ?", (article_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    if existing["store_id"]:
        _ensure_store_access(user, existing["store_id"], db)
    if body.store_id:
        _ensure_store_access(user, body.store_id, db)
    terms = list(dict.fromkeys(term.strip() for term in body.problem_terms if term.strip()))
    db.execute(
        """UPDATE review_knowledge_articles SET store_id = ?, title = ?, category = ?, problem_terms = ?,
        solution = ?, reply_template = ?, enabled = ?, updated_at = ? WHERE id = ?""",
        (body.store_id, body.title.strip(), body.category.strip() or "通用", json.dumps(terms, ensure_ascii=False), body.solution.strip(), body.reply_template.strip(), int(body.enabled), _now(), article_id),
    )
    return {"item": _knowledge_payload(db.execute("SELECT * FROM review_knowledge_articles WHERE id = ?", (article_id,)).fetchone())}


@router.delete("/reviews/knowledge/{article_id}")
def delete_review_knowledge(article_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    existing = db.execute("SELECT * FROM review_knowledge_articles WHERE id = ?", (article_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    if existing["store_id"]:
        _ensure_store_access(user, existing["store_id"], db)
    db.execute("DELETE FROM review_knowledge_matches WHERE article_id = ?", (article_id,))
    db.execute("DELETE FROM review_knowledge_articles WHERE id = ?", (article_id,))
    return {"ok": True}


@router.get("/reviews/{review_id}/knowledge")
def review_knowledge_matches(review_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    row = db.execute("SELECT * FROM product_reviews WHERE id = ?", (review_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="评论不存在")
    _ensure_store_access(user, row["store_id"], db)
    return {"items": _match_review_knowledge(db, dict(row))}


@router.get("/reviews/routing-stats")
def review_routing_stats(store_id: int | None = None, days: int = Query(30, ge=1, le=3650), user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if store_id is not None:
        _ensure_store_access(user, store_id, db)
    where, params = _review_query(user, store_id, "", "", "", "", days)
    rows = db.execute(
        "SELECT a.analysis_source, a.review_status FROM product_reviews r JOIN review_analysis a ON a.review_id = r.id" + where,
        params,
    ).fetchall()
    counts = Counter(row["analysis_source"] or "rules" for row in rows)
    total = len(rows)
    ai_calls = counts["ai"]
    rule_or_memory = counts["rules"] + counts["learned"]
    return {
        "total": total,
        "rules": counts["rules"],
        "ai": ai_calls,
        "manual": counts["manual"],
        "learned": counts["learned"],
        "pending_ai": sum(1 for row in rows if row["review_status"] == "needs_review"),
        "saved_ai_calls": rule_or_memory,
        "saved_rate": round(rule_or_memory / total * 100, 1) if total else 0,
    }


@router.get("/reviews/reply-templates")
def list_review_reply_templates(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    rows = db.execute("SELECT * FROM review_reply_templates ORDER BY category, id").fetchall()
    return {"items": [dict(row) for row in rows]}


@router.post("/reviews/reply-templates")
def create_review_reply_template(body: ReviewReplyTemplateIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    now = _now()
    try:
        cur = db.execute("INSERT INTO review_reply_templates (name, category, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (body.name.strip(), body.category.strip() or "通用", body.content.strip(), now, now))
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=400, detail="模板名称已存在") from exc
        raise
    return {"item": dict(db.execute("SELECT * FROM review_reply_templates WHERE id = ?", (cur.lastrowid,)).fetchone())}


@router.put("/reviews/reply-templates/{template_id}")
def update_review_reply_template(template_id: int, body: ReviewReplyTemplateIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if not db.execute("SELECT 1 FROM review_reply_templates WHERE id = ?", (template_id,)).fetchone():
        raise HTTPException(status_code=404, detail="回复模板不存在")
    try:
        db.execute("UPDATE review_reply_templates SET name = ?, category = ?, content = ?, updated_at = ? WHERE id = ?", (body.name.strip(), body.category.strip() or "通用", body.content.strip(), _now(), template_id))
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=400, detail="模板名称已存在") from exc
        raise
    return {"item": dict(db.execute("SELECT * FROM review_reply_templates WHERE id = ?", (template_id,)).fetchone())}


@router.delete("/reviews/reply-templates/{template_id}")
def delete_review_reply_template(template_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    cur = db.execute("DELETE FROM review_reply_templates WHERE id = ?", (template_id,))
    if not cur.rowcount:
        raise HTTPException(status_code=404, detail="回复模板不存在")
    return {"ok": True}


@router.get("/reviews/data-quality")
def review_data_quality(
    store_id: int | None = None,
    days: int = Query(30, ge=1, le=3650),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if store_id is not None:
        _ensure_store_access(user, store_id, db)
    where, params = _review_query(user, store_id, "", "", "", "", days)
    rows = [dict(row) for row in db.execute("SELECT r.id, r.review_id, r.item_id, r.item_title, r.content, r.append_content, r.review_time FROM product_reviews r LEFT JOIN review_analysis a ON a.review_id = r.id" + where, params).fetchall()]
    duplicate_counts = Counter((row["item_id"], (row["content"] or "").strip()) for row in rows if (row["content"] or "").strip())
    duplicate_keys = {key for key, count in duplicate_counts.items() if count > 1}
    now = datetime.now(timezone.utc)
    issue_rows: dict[str, list[dict]] = {key: [] for key in ("duplicate", "garbled", "missing_item", "invalid_time", "empty_content")}
    for row in rows:
        content = f"{row['content'] or ''}{row['append_content'] or ''}"
        if (row["item_id"], (row["content"] or "").strip()) in duplicate_keys:
            issue_rows["duplicate"].append(row)
        if "�" in content or "����" in content:
            issue_rows["garbled"].append(row)
        if not row["item_id"] or not row["item_title"]:
            issue_rows["missing_item"].append(row)
        if not content.strip():
            issue_rows["empty_content"].append(row)
        try:
            parsed = datetime.fromisoformat(str(row["review_time"]).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed > now + timedelta(days=1) or parsed.year < 2010:
                issue_rows["invalid_time"].append(row)
        except (TypeError, ValueError):
            issue_rows["invalid_time"].append(row)
    labels = {"duplicate": "疑似重复评论", "garbled": "正文存在乱码", "missing_item": "商品信息缺失", "invalid_time": "评价时间异常", "empty_content": "评论正文为空"}
    issues = [{"code": code, "label": labels[code], "count": len(items), "severity": "error", "examples": [{"id": item["id"], "review_id": item["review_id"], "item_title": item["item_title"], "content": item["content"][:100]} for item in items[:5]]} for code, items in issue_rows.items()]
    affected = len({item["id"] for items in issue_rows.values() for item in items})
    return {"total": len(rows), "affected": affected, "healthy": max(len(rows) - affected, 0), "health_rate": round((len(rows) - affected) / len(rows) * 100, 1) if rows else 100, "issues": issues}


@router.post("/reviews/import")
async def import_reviews(
    file: UploadFile = File(...),
    store_id: int = Form(...),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    _ensure_store_access(user, store_id, db)
    if not file.filename or not file.filename.lower().endswith((".csv", ".txt")):
        raise HTTPException(status_code=400, detail="请上传 CSV 文件")
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="CSV 文件不能超过 20MB")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("gb18030", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV 缺少表头")
    aliases = {
        "review_id": ("review_id", "评价ID", "评价id", "id"), "item_id": ("item_id", "商品ID", "商品id", "宝贝ID"),
        "item_title": ("item_title", "商品名称", "宝贝标题", "商品标题"), "sku_id": ("sku_id", "SKU", "规格ID"),
        "content": ("content", "评价内容", "评论内容", "买家评价"),
        "append_content": ("append_content", "追评内容", "追加评价"), "image_urls": ("image_urls", "评价图片", "图片"),
        "review_time": ("review_time", "评价时间", "评论时间", "创建时间"),
    }

    def value(row: dict, key: str) -> str:
        for name in aliases[key]:
            if name in row and row[name] is not None:
                return str(row[name]).strip()
        return ""

    imported, updated, errors = 0, 0, []
    now = _now()
    for index, row in enumerate(reader, start=2):
        content_text = value(row, "content")
        item_id = value(row, "item_id")
        review_time = _parse_time(value(row, "review_time"))
        review_id = value(row, "review_id") or hashlib.sha1(f"{store_id}|{item_id}|{review_time}|{content_text}".encode()).hexdigest()[:32]
        if not content_text and not value(row, "append_content"):
            errors.append({"row": index, "error": "评价内容为空"})
            continue
        try:
            before = db.execute("SELECT id FROM product_reviews WHERE store_id = ? AND review_id = ?", (store_id, review_id)).fetchone()
            db.execute(
                """
                INSERT INTO product_reviews
                    (store_id, review_id, item_id, item_title, sku_id, rating, content, append_content, image_urls, review_time, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'import', ?, ?)
                ON CONFLICT(store_id, review_id) DO UPDATE SET
                    item_id = excluded.item_id, item_title = excluded.item_title, sku_id = excluded.sku_id,
                    rating = excluded.rating, content = excluded.content, append_content = excluded.append_content,
                    image_urls = excluded.image_urls, review_time = excluded.review_time, updated_at = excluded.updated_at
                """,
                (store_id, review_id, item_id, value(row, "item_title"), value(row, "sku_id"), 0, content_text, value(row, "append_content"), json.dumps(_split_images(value(row, "image_urls")), ensure_ascii=False), review_time, now, now),
            )
            review = db.execute("SELECT id FROM product_reviews WHERE store_id = ? AND review_id = ?", (store_id, review_id)).fetchone()
            _analyse_and_save(db, review["id"], store_id, content_text, value(row, "append_content"))
            _ensure_review_alert(db, store_id, review["id"], content_text, value(row, "append_content"), now)
            if before:
                updated += 1
            else:
                imported += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"row": index, "error": str(exc)[:160]})
    _evaluate_trend_alert(db, store_id)
    _generate_weekly_report(db, store_id)
    drafts = _generate_negative_reply_drafts(db, store_id)
    return {"ok": True, "imported": imported, "updated": updated, "errors": errors[:20], "error_count": len(errors), "auto_reply_drafts": drafts}


@router.post("/reviews/sync")
def sync_reviews(
    body: ReviewSyncIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """接收外部评论采集器推送的数据。

    淘宝/天猫当前的体验分页面只稳定暴露汇总指标，未向页面开放买家
    评论正文；因此空批次不会被当作成功同步，而是返回可诊断的能力状态。
    """
    _ensure_store_access(user, body.store_id, db)
    if len(body.items) > 5000:
        raise HTTPException(status_code=400, detail="单次最多同步 5000 条评论")
    if not body.items:
        return {
            "ok": False,
            "imported": 0,
            "updated": 0,
            "error_count": 0,
            "source": body.source,
            "message": "当前平台页面未提供买家评论正文接口，请使用评论采集适配器或 CSV 作为兜底",
            "capabilities": {"review_text": False, "item": False},
        }
    imported, updated, errors = 0, 0, []
    now = _now()
    for index, item in enumerate(body.items, start=1):
        if not isinstance(item, dict):
            errors.append({"index": index, "error": "评论记录格式不正确"})
            continue
        try:
            action, error = _upsert_review(db, body.store_id, item, body.source, now)
            if error:
                errors.append({"index": index, "error": error})
            elif action == "imported":
                imported += 1
            else:
                updated += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"index": index, "error": str(exc)[:160]})
    _evaluate_trend_alert(db, body.store_id)
    _generate_weekly_report(db, body.store_id)
    drafts = _generate_negative_reply_drafts(db, body.store_id)
    return {
        "ok": not errors or imported > 0 or updated > 0,
        "imported": imported,
        "updated": updated,
        "error_count": len(errors),
        "errors": errors[:20],
        "source": body.source,
        "auto_reply_drafts": drafts,
        "capabilities": {"review_text": True, "item": True},
    }


@router.post("/reviews/sync-auto")
def sync_reviews_auto(
    body: ReviewAutoSyncIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """用店铺已绑定的生意参谋登录态自动分页同步评论正文。"""
    from datetime import date

    if body.store_id is not None:
        _ensure_store_access(user, body.store_id, db)
        rows = db.execute("SELECT * FROM stores WHERE id = ?", (body.store_id,)).fetchall()
    else:
        visible = visible_store_ids(user)
        if visible is None:
            rows = db.execute("SELECT * FROM stores ORDER BY id").fetchall()
        elif visible:
            rows = db.execute(f"SELECT * FROM stores WHERE id IN ({','.join('?' for _ in visible)}) ORDER BY id", visible).fetchall()
        else:
            rows = []
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=min(body.days, 30) - 1)).isoformat()
    results = []
    for row in rows:
        result = _sync_platform_rows(db, dict(row), start_date, end_date)
        try:
            result["ai_reviewed"] = _ai_review_pending_for_store(db, row["id"], limit=30)
        except AIError as exc:
            result.setdefault("diagnostics", []).append(f"AI 复核失败：{exc}")
            result["ai_reviewed"] = 0
        result["auto_reply_drafts"] = _generate_negative_reply_drafts(db, row["id"])
        results.append(result)
    successful = sum(1 for result in results if result.get("ok"))
    content_available = any(result.get("content_available") for result in results)
    fetched = sum(int(result.get("fetched") or 0) for result in results)
    return {
        "ok": successful == len(results) and content_available,
        "total": len(results),
        "successful": successful,
        "fetched": fetched,
        "start_date": start_date,
        "end_date": end_date,
        "results": results,
        "message": "已自动同步评论" if content_available else f"已读取 {fetched} 条平台评价明细，但当前接口未返回商品评论正文；请在千牛评价管理中导出评论，或使用 CSV 兜底",
    }


def sync_reviews_auto_all(db, days: int = 2) -> dict:
    """后台循环调用：同步所有店铺最近评论，不依赖用户请求上下文。"""
    from datetime import date

    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=max(1, days) - 1)).isoformat()
    rows = db.execute("SELECT * FROM stores ORDER BY id").fetchall()
    results = []
    for row in rows:
        latest = db.execute("SELECT MAX(review_time) AS latest FROM product_reviews WHERE store_id = ?", (row["id"],)).fetchone()["latest"]
        sync_start = start_date
        if latest:
            try:
                latest_day = datetime.fromisoformat(str(latest).replace("Z", "+00:00")).date()
                sync_start = max(latest_day - timedelta(days=1), date.today() - timedelta(days=max(1, days) - 1)).isoformat()
            except ValueError:
                pass
        result = _sync_platform_rows(db, dict(row), sync_start, end_date)
        try:
            result["ai_reviewed"] = _ai_review_pending_for_store(db, row["id"], limit=30)
        except AIError as exc:
            result.setdefault("diagnostics", []).append(f"AI 复核失败：{exc}")
            result["ai_reviewed"] = 0
        result["auto_reply_drafts"] = _generate_negative_reply_drafts(db, row["id"])
        results.append(result)
    return {"total": len(results), "ok": sum(1 for result in results if result.get("ok")), "results": results}


@router.post("/reviews/{review_id}/analyze")
def analyze_review(review_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    row = db.execute("SELECT * FROM product_reviews WHERE id = ?", (review_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="评论不存在")
    _ensure_store_access(user, row["store_id"], db)
    _analyse_and_save(db, review_id, row["store_id"], row["content"], row["append_content"])
    _ensure_review_alert(db, row["store_id"], review_id, row["content"], row["append_content"], _now())
    _generate_negative_reply_drafts(db, row["store_id"])
    result = db.execute("SELECT r.*, a.sentiment, a.confidence, a.aspects_json, a.keywords_json, a.severity, a.review_status, a.analysis_reason, a.analysis_source, a.routing_reason, s.name AS store_name FROM product_reviews r LEFT JOIN review_analysis a ON a.review_id = r.id LEFT JOIN stores s ON s.id = r.store_id WHERE r.id = ?", (review_id,)).fetchone()
    return {"item": _review_payload(result)}


@router.put("/reviews/{review_id}/sentiment")
def confirm_review_sentiment(review_id: int, body: ReviewSentimentIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    row = db.execute("SELECT * FROM product_reviews WHERE id = ?", (review_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="评论不存在")
    _ensure_store_access(user, row["store_id"], db)
    before = db.execute("SELECT sentiment FROM review_analysis WHERE review_id = ?", (review_id,)).fetchone()
    current = _analyse_text(row["content"], row["append_content"], _custom_terms_for_store(db, row["store_id"]))
    current.update({"sentiment": body.sentiment, "confidence": 1.0, "review_status": "confirmed", "analysis_reason": body.reason.strip() or "人工确认", "routing_reason": "人工确认结果"})
    _save_analysis(db, review_id, current, source="manual")
    now = _now()
    db.execute(
        """INSERT INTO review_sentiment_corrections
        (review_id, store_id, content_hash, original_sentiment, corrected_sentiment, reason, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(review_id) DO UPDATE SET
            content_hash = excluded.content_hash, original_sentiment = excluded.original_sentiment,
            corrected_sentiment = excluded.corrected_sentiment, reason = excluded.reason, updated_at = excluded.updated_at""",
        (review_id, row["store_id"], _content_hash(row["content"], row["append_content"]), before["sentiment"] if before else current["sentiment"], body.sentiment, body.reason.strip() or "人工确认", now, now),
    )
    if body.sentiment == "negative":
        _generate_negative_reply_drafts(db, row["store_id"])
    result = db.execute("SELECT r.*, a.sentiment, a.confidence, a.aspects_json, a.keywords_json, a.severity, a.review_status, a.analysis_reason, a.analysis_source, a.routing_reason, s.name AS store_name FROM product_reviews r LEFT JOIN review_analysis a ON a.review_id = r.id LEFT JOIN stores s ON s.id = r.store_id WHERE r.id = ?", (review_id,)).fetchone()
    return {"item": _review_payload(result)}


@router.put("/reviews/{review_id}/process")
def process_review(review_id: int, body: ReviewProcessIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if body.status not in PROCESS_STATUSES:
        raise HTTPException(status_code=400, detail="处理状态不正确")
    row = db.execute("SELECT * FROM product_reviews WHERE id = ?", (review_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="评论不存在")
    _ensure_store_access(user, row["store_id"], db)
    db.execute("UPDATE product_reviews SET process_status = ?, updated_at = ? WHERE id = ?", (body.status, _now(), review_id))
    return {"ok": True, "status": body.status, "note": body.note}


@router.post("/reviews/{review_id}/reply-draft")
def review_reply_draft(review_id: int, body: ReviewReplyDraftIn | None = None, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    row = db.execute("SELECT * FROM product_reviews WHERE id = ?", (review_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="评论不存在")
    _ensure_store_access(user, row["store_id"], db)
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    template = None
    if body and body.template_id:
        template = db.execute("SELECT * FROM review_reply_templates WHERE id = ?", (body.template_id,)).fetchone()
        if not template:
            raise HTTPException(status_code=400, detail="选择的回复模板不存在")
    knowledge = _match_review_knowledge(db, dict(row))
    knowledge_context = ""
    if knowledge:
        knowledge_context = "\n可参考的问题处理知识：\n" + "\n".join(
            f"- {item['title']}：处理建议：{item['solution']}；推荐话术：{item['reply_template']}"
            for item in knowledge[:3]
        )
    prompt = (
        "你是电商客服，请为下面这条买家评价生成一段真诚、简短、可直接修改后发送的中文回复。"
        "不要承诺无法兑现的补偿，不要暴露内部信息；差评先道歉并提出解决方式，好评表达感谢。"
        + (f"\n请参考下面的回复模板进行改写，不要机械照抄：{template['content']}" if template else "")
        + knowledge_context
        + f"\n商品：{row['item_title'] or row['item_id']}\n评价：{row['content']}\n追评：{row['append_content']}"
    )
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": prompt}], timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    reply = reply.strip()[:500]
    db.execute(
        """UPDATE product_reviews SET reply_status = 'draft', reply_content = ?, reply_error = '',
        reply_approved_at = NULL, updated_at = ? WHERE id = ?""",
        (reply, _now(), review_id),
    )
    return {"reply": reply, "knowledge": knowledge}


@router.put("/reviews/{review_id}/reply")
def approve_review_reply(review_id: int, body: ReviewReplyApproveIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    row = db.execute("SELECT * FROM product_reviews WHERE id = ?", (review_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="评论不存在")
    _ensure_store_access(user, row["store_id"], db)
    if row["reply_status"] == "published":
        raise HTTPException(status_code=400, detail="该评论回复已经发布，不能重复修改")
    content = body.content.strip()
    now = _now()
    db.execute(
        """UPDATE product_reviews SET reply_status = 'approved', reply_content = ?, reply_error = '',
        reply_approved_at = ?, updated_at = ? WHERE id = ?""",
        (content, now, now, review_id),
    )
    return {"ok": True, "status": "approved", "content": content, "approved_at": now}


@router.post("/reviews/{review_id}/reply/publish")
def publish_review_reply(review_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    from backend.app.core.sycm import SycmError, publish_seller_review_reply

    row = db.execute("SELECT * FROM product_reviews WHERE id = ?", (review_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="评论不存在")
    _ensure_store_access(user, row["store_id"], db)
    if row["reply_status"] == "published":
        return {"ok": True, "status": "published", "published_at": row["reply_published_at"]}
    if row["reply_status"] != "approved":
        raise HTTPException(status_code=400, detail="请先审核并保存回复内容，再发布到淘宝")
    if row["source"] != "seller-review-management":
        raise HTTPException(status_code=400, detail="这条评论不是从千牛评价管理抓取的，缺少可发布的淘宝评价标识")
    store = db.execute("SELECT * FROM stores WHERE id = ?", (row["store_id"],)).fetchone()
    now = _now()
    db.execute("UPDATE product_reviews SET reply_status = 'publishing', reply_error = '', updated_at = ? WHERE id = ?", (now, review_id))
    db.commit()
    try:
        payload = publish_seller_review_reply(dict(store), row["review_id"], row["reply_content"])
    except SycmError as exc:
        error = str(exc)[:500]
        db.execute("UPDATE product_reviews SET reply_status = 'failed', reply_error = ?, updated_at = ? WHERE id = ?", (error, _now(), review_id))
        db.commit()
        raise HTTPException(status_code=502, detail=f"淘宝回复发布失败：{error}") from exc
    published_at = _now()
    db.execute(
        """UPDATE product_reviews SET reply_status = 'published', reply_error = '', reply_published_at = ?,
        reply_platform_response = ?, process_status = CASE WHEN process_status = 'pending' THEN 'contacted' ELSE process_status END,
        updated_at = ? WHERE id = ?""",
        (published_at, json.dumps(payload, ensure_ascii=False)[:4000], published_at, review_id),
    )
    db.commit()
    return {"ok": True, "status": "published", "published_at": published_at}
