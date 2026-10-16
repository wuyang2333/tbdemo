import csv
import io
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_review_csv_import_summary_and_process(client, admin_token):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["评价ID", "商品ID", "商品名称", "评价内容", "评价时间"])
    writer.writeheader()
    writer.writerow({"评价ID": "review-test-1", "商品ID": "item-test-1", "商品名称": "测试商品", "评价内容": "包装破损，物流太慢，申请退款", "评价时间": "2026-08-24 10:00:00"})
    writer.writerow({"评价ID": "review-test-2", "商品ID": "item-test-1", "商品名称": "测试商品", "评价内容": "质量很好，满意，会回购", "评价时间": "2026-08-23 10:00:00"})
    response = client.post(
        "/api/customers/reviews/import",
        headers=_headers(admin_token),
        data={"store_id": "1"},
        files={"file": ("reviews.csv", output.getvalue().encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 2

    summary = client.get("/api/customers/reviews/summary?store_id=1&days=30", headers=_headers(admin_token))
    assert summary.status_code == 200, summary.text
    assert summary.json()["total"] >= 2
    assert summary.json()["negative"] >= 1
    assert any(item["aspect"] == "包装" for item in summary.json()["top_aspects"])

    reviews = client.get("/api/customers/reviews?store_id=1&sentiment=negative", headers=_headers(admin_token))
    assert reviews.status_code == 200, reviews.text
    review = next(item for item in reviews.json()["items"] if item["review_id"] == "review-test-1")
    assert review["sentiment"] == "negative"
    assert review["process_status"] == "pending"

    updated = client.put(
        f"/api/customers/reviews/{review['id']}/process",
        headers=_headers(admin_token),
        json={"status": "ignored", "note": "无需继续处理"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "ignored"


def test_review_endpoints_require_auth(client):
    assert client.get("/api/customers/reviews").status_code in (401, 403)


def test_review_list_can_filter_reviews_waiting_for_sentiment_confirmation(client, admin_token):
    synced = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={"store_id": 1, "items": [{"review_id": "needs-review-filter-1", "content": "包装还行，但是味道不太好"}]},
    )
    assert synced.status_code == 200, synced.text
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    conn.execute(
        "UPDATE review_analysis SET review_status = 'needs_review' WHERE review_id = (SELECT id FROM product_reviews WHERE review_id = ?)",
        ("needs-review-filter-1",),
    )
    conn.commit()
    conn.close()

    response = client.get(
        "/api/customers/reviews?store_id=1&review_status=needs_review&q=needs-review-filter-1",
        headers=_headers(admin_token),
    )
    assert response.status_code == 200, response.text
    assert [item["review_id"] for item in response.json()["items"]] == ["needs-review-filter-1"]


def test_review_list_supports_date_sorting(client, admin_token):
    synced = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "items": [
                {"review_id": "date-sort-old", "content": "旧评论", "review_time": "2026-09-01 10:00:00"},
                {"review_id": "date-sort-new", "content": "新评论", "review_time": "2026-10-08 10:00:00"},
            ],
        },
    )
    assert synced.status_code == 200, synced.text

    newest = client.get(
        "/api/customers/reviews?store_id=1&q=date-sort&order_by=recent&order_dir=desc",
        headers=_headers(admin_token),
    )
    assert newest.status_code == 200, newest.text
    assert [item["review_id"] for item in newest.json()["items"]] == ["date-sort-new", "date-sort-old"]

    oldest = client.get(
        "/api/customers/reviews?store_id=1&q=date-sort&order_by=recent&order_dir=asc",
        headers=_headers(admin_token),
    )
    assert oldest.status_code == 200, oldest.text
    assert [item["review_id"] for item in oldest.json()["items"]] == ["date-sort-old", "date-sort-new"]


def test_review_batch_process_updates_pending_and_ignored(client, admin_token):
    synced = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "items": [
                {"review_id": "batch-process-1", "content": "包装有点破损"},
                {"review_id": "batch-process-2", "content": "质量很好"},
            ],
        },
    )
    assert synced.status_code == 200, synced.text
    listed = client.get("/api/customers/reviews?store_id=1&q=batch-process", headers=_headers(admin_token))
    ids = [item["id"] for item in listed.json()["items"]]
    assert len(ids) == 2

    ignored = client.post(
        "/api/customers/reviews/batch-process",
        headers=_headers(admin_token),
        json={"review_ids": ids, "status": "ignored"},
    )
    assert ignored.status_code == 200, ignored.text
    assert ignored.json()["updated"] == 2
    refreshed = client.get("/api/customers/reviews?store_id=1&q=batch-process&process_status=ignored", headers=_headers(admin_token))
    assert len(refreshed.json()["items"]) == 2

    restored = client.post(
        "/api/customers/reviews/batch-process",
        headers=_headers(admin_token),
        json={"review_ids": ids, "status": "pending"},
    )
    assert restored.status_code == 200, restored.text


def test_review_quality_overview_requires_auth(client):
    response = client.get("/api/customers/reviews/quality-overview")
    assert response.status_code in (401, 403)


def test_review_quality_overview_returns_empty_scope(client, admin_token):
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    cursor = conn.execute(
        "INSERT INTO stores (name, created_at) VALUES (?, ?)",
        ("商品质量空数据测试店", datetime.now(timezone.utc).isoformat()),
    )
    store_id = cursor.lastrowid
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/customers/reviews/quality-overview?store_id={store_id}&days=30",
        headers=_headers(admin_token),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["total"] == 0
    assert payload["products"] == []
    assert payload["topics"] == []


def test_topic_data_uses_only_negative_evidence_and_ranks_products_by_negative_count():
    from backend.app.api import customers

    def row(review_id, item_id, item_title, content, sentiment, aspect_sentiment):
        return {
            "id": review_id,
            "store_id": 1,
            "item_id": item_id,
            "item_title": item_title,
            "content": content,
            "append_content": "",
            "sentiment": sentiment,
            "aspects_json": json.dumps(
                [{"aspect": "质量", "sentiment": aspect_sentiment, "keywords": ["质量"]}],
                ensure_ascii=False,
            ),
            "keywords_json": "[]",
        }

    rows = [
        row(1, "positive-hot", "好评很多的商品", "质量很好，使用舒服", "positive", "positive"),
        row(2, "positive-hot", "好评很多的商品", "做工不错，很满意", "positive", "positive"),
        row(3, "positive-hot", "好评很多的商品", "质量稳定，会回购", "positive", "positive"),
        row(7, "stale-manual", "人工纠正后的商品", "质量很好，已人工确认是好评", "positive", "negative"),
        row(4, "negative-main", "质量差评商品 A", "刚用就断了", "negative", "negative"),
        row(5, "negative-main", "质量差评商品 A", "有瑕疵，质量不好", "negative", "negative"),
        row(6, "negative-other", "质量差评商品 B", "用一次就坏了", "negative", "negative"),
    ]

    quality = next(item for item in customers._topic_data(rows)["items"] if item["topic"] == "质量")

    assert quality["count"] == 7
    assert quality["negative"] == 3
    assert [example["id"] for example in quality["examples"]] == [4, 5, 6]
    assert quality["products"] == [
        {"store_id": 1, "item_id": "negative-main", "name": "质量差评商品 A", "count": 2},
        {"store_id": 1, "item_id": "negative-other", "name": "质量差评商品 B", "count": 1},
    ]


def test_manual_positive_review_is_removed_from_negative_topic_evidence(client, admin_token):
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    cursor = conn.execute(
        "INSERT INTO stores (name, created_at) VALUES (?, ?)",
        ("人工情绪主题一致性测试店", datetime.now(timezone.utc).isoformat()),
    )
    store_id = cursor.lastrowid
    conn.commit()
    conn.close()

    imported = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": store_id,
            "items": [{"review_id": "manual-positive-topic-1", "item_id": "manual-positive-item", "item_title": "人工纠正商品", "content": "质量差，用一次就坏了"}],
        },
    )
    assert imported.status_code == 200, imported.text

    listed = client.get(
        f"/api/customers/reviews?store_id={store_id}&q=manual-positive-topic-1",
        headers=_headers(admin_token),
    )
    review_id = listed.json()["items"][0]["id"]

    before = client.get(
        f"/api/customers/reviews/topics?store_id={store_id}&days=3650",
        headers=_headers(admin_token),
    )
    quality_before = next(item for item in before.json()["items"] if item["topic"] == "质量")
    assert quality_before["negative"] == 1
    assert [item["id"] for item in quality_before["examples"]] == [review_id]

    corrected = client.put(
        f"/api/customers/reviews/{review_id}/sentiment",
        headers=_headers(admin_token),
        json={"sentiment": "positive", "reason": "人工核对原文"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["item"]["sentiment"] == "positive"

    after = client.get(
        f"/api/customers/reviews/topics?store_id={store_id}&days=3650",
        headers=_headers(admin_token),
    )
    quality_after = next(item for item in after.json()["items"] if item["topic"] == "质量")
    assert quality_after["negative"] == 0
    assert quality_after["examples"] == []
    assert quality_after["products"] == []

    summary = client.get(
        f"/api/customers/reviews/summary?store_id={store_id}&days=3650",
        headers=_headers(admin_token),
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["top_aspects"] == []

    overview = client.get(
        f"/api/customers/reviews/quality-overview?store_id={store_id}&days=3650",
        headers=_headers(admin_token),
    )
    assert overview.status_code == 200, overview.text
    overview_product = next(item for item in overview.json()["products"] if item["item_id"] == "manual-positive-item")
    assert overview_product["negative"] == 0
    assert overview_product["top_aspects"] == []


def test_review_quality_overview_aggregates_products_and_evidence(client, admin_token):
    now = datetime.now(timezone.utc)
    items = [
        {"review_id": "quality-current-negative-1", "item_id": "quality-item-1", "item_title": "质量看板商品", "content": "包装破损，物流太慢", "review_time": (now - timedelta(days=1)).isoformat()},
        {"review_id": "quality-current-negative-2", "item_id": "quality-item-1", "item_title": "质量看板商品", "content": "包装破损，质量问题", "review_time": (now - timedelta(days=2)).isoformat()},
        {"review_id": "quality-current-negative-3", "item_id": "quality-item-1", "item_title": "质量看板商品", "content": "质量太差，申请退款", "review_time": (now - timedelta(days=3)).isoformat()},
        {"review_id": "quality-current-positive-1", "item_id": "quality-item-1", "item_title": "质量看板商品", "content": "质量很好，满意", "review_time": (now - timedelta(days=4)).isoformat()},
        {"review_id": "quality-current-positive-2", "item_id": "quality-item-1", "item_title": "质量看板商品", "content": "很满意，会回购", "review_time": (now - timedelta(days=5)).isoformat()},
        {"review_id": "quality-previous-negative-1", "item_id": "quality-item-1", "item_title": "质量看板商品", "content": "质量问题", "review_time": (now - timedelta(days=31)).isoformat()},
    ]
    synced = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={"store_id": 1, "items": items},
    )
    assert synced.status_code == 200, synced.text

    response = client.get(
        "/api/customers/reviews/quality-overview?store_id=1&days=30",
        headers=_headers(admin_token),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    product = next(item for item in payload["products"] if item["item_id"] == "quality-item-1")
    assert product["total"] == 5
    assert product["negative"] == 3
    assert product["negative_rate"] == 60.0
    assert product["previous_total"] == 1
    assert product["previous_negative"] == 1
    assert product["negative_change"] == 2
    assert product["negative_rate_change"] == -40.0
    assert product["risk_level"] == "high"
    assert product["sample_warning"] == ""
    assert any(aspect["aspect"] == "质量" for aspect in product["top_aspects"])

    topic = next(item for item in payload["topics"] if item["topic"] == "包装")
    assert topic["negative"] >= 2
    assert topic["examples"]
    assert any(
        example["store_id"] == 1
        and example["item_id"] == "quality-item-1"
        and example["item_title"] == "质量看板商品"
        for example in topic["examples"]
    )
    assert any(product["item_id"] == "quality-item-1" for product in topic["products"])


def test_review_summary_applies_product_search_filter(client, admin_token):
    synced = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "items": [
                {"review_id": "summary-filter-a", "item_id": "summary-item-a", "item_title": "筛选商品 A", "content": "质量很好"},
                {"review_id": "summary-filter-b", "item_id": "summary-item-b", "item_title": "其他商品 B", "content": "包装破损"},
            ],
        },
    )
    assert synced.status_code == 200, synced.text

    response = client.get(
        "/api/customers/reviews/summary?store_id=1&days=30&q=summary-item-a",
        headers=_headers(admin_token),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 1
    assert payload["positive"] == 1
    assert payload["negative"] == 0


def test_review_improvement_actions_require_auth(client):
    assert client.get("/api/customers/reviews/improvement-actions").status_code in (401, 403)
    assert client.post(
        "/api/customers/reviews/improvement-actions",
        json={"store_id": 1, "title": "未授权事项"},
    ).status_code in (401, 403)


def test_review_improvement_actions_create_update_and_filter(client, admin_token):
    headers = _headers(admin_token)
    created = client.post(
        "/api/customers/reviews/improvement-actions",
        headers=headers,
        json={
            "store_id": 1,
            "item_id": "improvement-item-1",
            "item_title": "改进测试商品",
            "topic": "包装",
            "title": "优化外箱防护",
            "description": "确认破损集中在运输环节",
            "owner": "运营",
            "plan": "更换加厚外箱并观察一周",
            "started_at": "2026-09-11",
            "due_at": "2026-09-18",
            "before_negative_rate": 18.5,
            "note": "关联包装破损主题",
        },
    )
    assert created.status_code == 200, created.text
    action = created.json()["item"]
    action_id = action["id"]
    assert action["status"] == "pending"
    assert action["before_negative_rate"] == 18.5
    assert action["after_negative_rate"] is None

    updated = client.put(
        f"/api/customers/reviews/improvement-actions/{action_id}",
        headers=headers,
        json={"status": "observing", "after_negative_rate": 9.2, "note": "已完成首轮调整"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["item"]["status"] == "observing"
    assert updated.json()["item"]["after_negative_rate"] == 9.2
    assert updated.json()["item"]["note"] == "已完成首轮调整"

    filtered = client.get(
        "/api/customers/reviews/improvement-actions?store_id=1&status=observing&item_id=improvement-item-1",
        headers=headers,
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] >= 1
    assert filtered.json()["items"][0]["id"] == action_id

    invalid = client.put(
        f"/api/customers/reviews/improvement-actions/{action_id}",
        headers=headers,
        json={"status": "unknown"},
    )
    assert invalid.status_code == 422


def test_review_improvement_actions_enforce_cross_store_permissions(client, admin_token):
    from backend.app.api import customers

    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    cursor = conn.execute(
        "INSERT INTO stores (name, created_at) VALUES (?, ?)",
        ("改进事项权限测试店", datetime.now(timezone.utc).isoformat()),
    )
    other_store_id = cursor.lastrowid
    conn.commit()
    conn.close()
    headers = _headers(admin_token)
    created = client.post(
        "/api/customers/reviews/improvement-actions",
        headers=headers,
        json={"store_id": other_store_id, "title": "跨店事项", "status": "diagnosed"},
    )
    assert created.status_code == 200, created.text
    action_id = created.json()["item"]["id"]

    original_visible_store_ids = customers.visible_store_ids
    customers.visible_store_ids = lambda user: {1}
    try:
        forbidden_list = client.get(
            f"/api/customers/reviews/improvement-actions?store_id={other_store_id}",
            headers=headers,
        )
        assert forbidden_list.status_code == 403
        forbidden_update = client.put(
            f"/api/customers/reviews/improvement-actions/{action_id}",
            headers=headers,
            json={"status": "ignored"},
        )
        assert forbidden_update.status_code == 403
        hidden = client.get("/api/customers/reviews/improvement-actions", headers=headers)
        assert hidden.status_code == 200, hidden.text
        assert all(item["store_id"] == 1 for item in hidden.json()["items"])
    finally:
        customers.visible_store_ids = original_visible_store_ids


def test_ai_review_explains_missing_model_config(client, admin_token):
    response = client.post(
        "/api/customers/reviews/ai-review",
        headers=_headers(admin_token),
        json={"store_id": 1, "days": 30, "limit": 10},
    )
    assert response.status_code == 400, response.text
    assert "配置 AI 模型" in response.json()["detail"]


def test_review_sync_upserts_and_reports_empty_source(client, admin_token):
    response = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "source": "browser-adapter",
            "items": [{
                "review_id": "sync-1",
                "item_id": "item-sync",
                "item_title": "同步商品",
                "content": "包装破损，物流太慢",
                "review_time": "2026-08-24 12:00:00",
            }],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 1

    duplicate = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={"store_id": 1, "items": [{"review_id": "sync-1", "content": "仍然破损"}]},
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["updated"] == 1

    empty = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={"store_id": 1, "items": []},
    )
    assert empty.status_code == 200, empty.text
    assert empty.json()["ok"] is False
    assert empty.json()["capabilities"]["review_text"] is False


def test_review_auto_sync_maps_platform_rows(client, admin_token, monkeypatch):
    from backend.app.core import sycm

    monkeypatch.setattr(
        sycm,
        "fetch_review_rows",
        lambda store, start_date, end_date, **kwargs: [{
            "dataId": "platform-1",
            "itemId": "item-platform",
            "itemTitle": "平台商品",
            "lstEvaScore": "1",
            "evaluationContent": "质量问题，包装破损",
            "servTime": "2026-08-24 12:00:00",
        }],
    )
    response = client.post(
        "/api/customers/reviews/sync-auto",
        headers=_headers(admin_token),
        json={"store_id": 1, "days": 7},
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["imported"] == 1

    reviews = client.get("/api/customers/reviews?store_id=1&q=platform-1", headers=_headers(admin_token))
    assert reviews.status_code == 200, reviews.text
    assert reviews.json()["items"][0]["content"] == "质量问题，包装破损"


def test_negative_review_automatically_creates_draft_for_approval(client, admin_token, monkeypatch):
    from backend.app.api import customers

    monkeypatch.setattr(customers, "get_default_config", lambda db: None)
    response = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "items": [
                {"review_id": "auto-draft-negative", "content": "包装严重破损，商品也坏了"},
                {"review_id": "auto-draft-positive", "content": "质量很好，很满意"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["auto_reply_drafts"]["generated"] >= 1

    negative = client.get(
        "/api/customers/reviews?store_id=1&q=auto-draft-negative",
        headers=_headers(admin_token),
    ).json()["items"][0]
    positive = client.get(
        "/api/customers/reviews?store_id=1&q=auto-draft-positive",
        headers=_headers(admin_token),
    ).json()["items"][0]
    assert negative["reply_status"] == "draft"
    assert negative["reply_content"]
    assert positive["reply_status"] == "none"

    filtered = client.get(
        "/api/customers/reviews?store_id=1&q=auto-draft&reply_status=draft",
        headers=_headers(admin_token),
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["review_id"] for item in filtered.json()["items"]] == ["auto-draft-negative"]


def test_negative_reply_drafts_use_one_batched_ai_request(client, admin_token, monkeypatch):
    from backend.app.api import customers

    calls = []

    def fake_completion(cfg, messages, **kwargs):
        calls.append(messages[0]["content"])
        samples = json.loads(messages[0]["content"].split("。\n", 1)[1])
        return json.dumps([{"id": item["id"], "reply": f"很抱歉，关于{item['product']}的问题请联系我们处理。"} for item in samples], ensure_ascii=False)

    monkeypatch.setattr(customers, "get_default_config", lambda db: {"api_key": "test-key"})
    monkeypatch.setattr(customers, "chat_completion", fake_completion)
    response = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "items": [
                {"review_id": "auto-ai-draft-1", "item_title": "商品甲", "content": "质量太差，已经坏了"},
                {"review_id": "auto-ai-draft-2", "item_title": "商品乙", "content": "包装破损，还漏液"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert response.json()["auto_reply_drafts"]["ai"] == 2


def test_review_sentiment_ignores_positive_business_phrases():
    from backend.app.api.customers import _analyse_text

    result = _analyse_text("口臭没了，牙结石和黑渍都去掉了，温和不刺激，效果很好")
    assert result["sentiment"] == "positive"
    assert "臭" not in result["keywords"]
    assert "掉" not in result["keywords"]

    gentle = _analyse_text("用着很温和，完全不酸牙、不刺激牙龈，也不辣嘴")
    assert gentle["sentiment"] == "positive"
    assert "酸牙" not in gentle["keywords"]
    assert "刺激牙龈" not in gentle["keywords"]
    assert "辣嘴" not in gentle["keywords"]


def test_review_sentiment_handles_contrast_negation_and_ambiguity():
    from backend.app.api.customers import _analyse_text

    contrast = _analyse_text("物流慢，但是产品很好")
    assert contrast["sentiment"] == "positive"
    assert contrast["review_status"] == "needs_review"

    negated = _analyse_text("不好用")
    assert negated["sentiment"] == "negative"
    assert "不好用" in negated["keywords"]

    ambiguous = _analyse_text("收到货了")
    assert ambiguous["sentiment"] == "neutral"
    assert ambiguous["review_status"] == "needs_review"


def test_review_sentiment_detects_sarcasm_and_routes_to_ai():
    from backend.app.api.customers import _analyse_text

    for content in ("这质量可真行，用一次就坏了", "呵呵，谢谢你让我踩雷", "真不错，收到就是破的"):
        result = _analyse_text(content)
        assert result["sentiment"] == "negative"
        assert result["review_status"] == "needs_review"
        assert "反讽" in result["routing_reason"]

    clear_positive = _analyse_text("质量很好，很满意，会继续回购")
    assert clear_positive["sentiment"] == "positive"
    assert clear_positive["review_status"] == "auto"
    assert "本地规则" in clear_positive["routing_reason"]


def test_manual_sentiment_survives_rule_reanalysis(client, admin_token):
    imported = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "items": [{"review_id": "manual-sentiment-1", "content": "质量很好，会回购"}],
        },
    )
    assert imported.status_code == 200, imported.text

    listed = client.get(
        "/api/customers/reviews?store_id=1&q=manual-sentiment-1",
        headers=_headers(admin_token),
    )
    review_id = listed.json()["items"][0]["id"]

    corrected = client.put(
        f"/api/customers/reviews/{review_id}/sentiment",
        headers=_headers(admin_token),
        json={"sentiment": "negative", "reason": "人工核对原文"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["item"]["analysis_source"] == "manual"

    reanalyzed = client.post(
        f"/api/customers/reviews/{review_id}/analyze",
        headers=_headers(admin_token),
    )
    assert reanalyzed.status_code == 200, reanalyzed.text
    assert reanalyzed.json()["item"]["sentiment"] == "negative"
    assert reanalyzed.json()["item"]["analysis_source"] == "manual"
    assert reanalyzed.json()["item"]["review_status"] == "confirmed"


def test_ai_review_batches_and_updates_ambiguous_review(client, admin_token, monkeypatch):
    from backend.app.api import customers

    imported = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "items": [{"review_id": "ai-review-1", "content": "收到货了"}],
        },
    )
    assert imported.status_code == 200, imported.text
    listed = client.get(
        "/api/customers/reviews?store_id=1&q=ai-review-1",
        headers=_headers(admin_token),
    )
    review_id = listed.json()["items"][0]["id"]

    monkeypatch.setattr(customers, "get_default_config", lambda db: {"api_key": "test-key"})
    monkeypatch.setattr(
        customers,
        "chat_completion",
        lambda *args, **kwargs: "```json\n" + json.dumps({"results": [
                {
                    "id": review_id,
                    "sentiment": "中性",
                    "confidence": "91%",
                    "reason": "只有收货事实，没有明确褒贬",
                    "aspects": "物流,包装",
                }
            ]}, ensure_ascii=False) + "\n```",
    )

    reviewed = client.post(
        "/api/customers/reviews/ai-review",
        headers=_headers(admin_token),
        json={"store_id": 1, "days": 30, "limit": 50},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["updated"] == 1

    refreshed = client.get(
        "/api/customers/reviews?store_id=1&q=ai-review-1",
        headers=_headers(admin_token),
    ).json()["items"][0]
    assert refreshed["sentiment"] == "neutral"
    assert refreshed["confidence"] == 0.91
    assert refreshed["review_status"] == "auto"
    assert refreshed["analysis_source"] == "ai"


def test_ai_review_parser_recovers_truncated_and_json_like_results():
    from backend.app.api.customers import _parse_ai_review_result

    truncated = '[{"id":1,"sentiment":"positive","confidence":0.9},{"id":2,"sentiment":"negative","confidence":0.8}'
    assert [item["id"] for item in _parse_ai_review_result(truncated)] == [1, 2]

    json_like = "{'items': [{'id': 3, 'sentiment': 'neutral', 'confidence': 0.7,},],}"
    assert _parse_ai_review_result(json_like)[0]["id"] == 3


def test_review_templates(client, admin_token):
    created = client.post(
        "/api/customers/reviews/reply-templates",
        headers=_headers(admin_token),
        json={"name": "测试安抚模板", "category": "质量", "content": "非常抱歉，请联系我们处理。"},
    )
    assert created.status_code == 200, created.text
    template_id = created.json()["item"]["id"]

    listed = client.get("/api/customers/reviews/reply-templates", headers=_headers(admin_token))
    assert listed.status_code == 200
    assert any(item["id"] == template_id for item in listed.json()["items"])

    deleted = client.delete(f"/api/customers/reviews/reply-templates/{template_id}", headers=_headers(admin_token))
    assert deleted.status_code == 200


def test_review_knowledge_matches_and_guides_reply(client, admin_token, monkeypatch):
    from backend.app.api import customers

    created = client.post(
        "/api/customers/reviews/knowledge",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "title": "特殊卡扣故障",
            "category": "质量",
            "problem_terms": ["卡扣断裂", "卡扣坏了"],
            "solution": "核对卡扣批次并优先安排补发。",
            "reply_template": "很抱歉卡扣出现问题，我们会尽快补发。",
            "enabled": True,
        },
    )
    assert created.status_code == 200, created.text
    article_id = created.json()["item"]["id"]

    synced = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={"store_id": 1, "items": [{"review_id": "knowledge-review", "content": "刚用卡扣就断裂了"}]},
    )
    assert synced.status_code == 200, synced.text
    review = client.get("/api/customers/reviews?store_id=1&q=knowledge-review", headers=_headers(admin_token)).json()["items"][0]

    matched = client.get(f"/api/customers/reviews/{review['id']}/knowledge", headers=_headers(admin_token))
    assert matched.status_code == 200, matched.text
    assert matched.json()["items"][0]["id"] == article_id
    assert "卡扣断裂" in matched.json()["items"][0]["matched_terms"]

    prompts = []
    monkeypatch.setattr(customers, "get_default_config", lambda db: {"api_key": "test-key"})
    monkeypatch.setattr(customers, "chat_completion", lambda cfg, messages, **kwargs: prompts.append(messages[0]["content"]) or "很抱歉给您带来困扰，请联系我们补发。")
    drafted = client.post(f"/api/customers/reviews/{review['id']}/reply-draft", headers=_headers(admin_token), json={})
    assert drafted.status_code == 200, drafted.text
    assert "核对卡扣批次" in prompts[0]
    assert drafted.json()["knowledge"][0]["id"] == article_id

    deleted = client.delete(f"/api/customers/reviews/knowledge/{article_id}", headers=_headers(admin_token))
    assert deleted.status_code == 200, deleted.text


def test_reply_draft_uses_original_product_title_not_internal_alias(client, admin_token, monkeypatch):
    from backend.app.api import customers

    synced = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "items": [
                {
                    "review_id": "alias-prompt-review",
                    "item_id": "alias-prompt-item",
                    "item_title": "淘宝买家可见原始标题",
                    "content": "包装有点压坏了",
                }
            ],
        },
    )
    assert synced.status_code == 200, synced.text
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    conn.execute(
        """INSERT INTO product_aliases
        (store_id, item_id, alias, note, created_at, updated_at)
        VALUES (?, ?, ?, '', ?, ?)""",
        (1, "alias-prompt-item", "内部主推款简称", "2026-09-14T10:00:00", "2026-09-14T10:00:00"),
    )
    conn.commit()
    conn.close()

    review = client.get(
        "/api/customers/reviews?store_id=1&q=alias-prompt-review",
        headers=_headers(admin_token),
    ).json()["items"][0]
    prompts = []
    monkeypatch.setattr(customers, "get_default_config", lambda db: {"api_key": "test-key"})
    monkeypatch.setattr(
        customers,
        "chat_completion",
        lambda cfg, messages, **kwargs: prompts.append(messages[0]["content"]) or "很抱歉给您带来不便。",
    )

    drafted = client.post(
        f"/api/customers/reviews/{review['id']}/reply-draft",
        headers=_headers(admin_token),
        json={},
    )
    assert drafted.status_code == 200, drafted.text
    assert "淘宝买家可见原始标题" in prompts[0]
    assert "内部主推款简称" not in prompts[0]


def test_batch_review_reply_draft_supports_partial_success_and_skips_published(client, admin_token, monkeypatch):
    from backend.app.api import customers

    synced = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "source": "seller-review-management",
            "items": [
                {"review_id": "batch-draft-ok", "content": "包装有点破损"},
                {"review_id": "batch-draft-fail", "content": "质量不满意"},
                {"review_id": "batch-draft-published", "content": "物流太慢"},
            ],
        },
    )
    assert synced.status_code == 200, synced.text
    listed = client.get("/api/customers/reviews?store_id=1&q=batch-draft-", headers=_headers(admin_token))
    assert listed.status_code == 200, listed.text
    by_review_id = {item["review_id"]: item for item in listed.json()["items"]}
    assert set(by_review_id) == {"batch-draft-ok", "batch-draft-fail", "batch-draft-published"}

    published = client.put(
        f"/api/customers/reviews/{by_review_id['batch-draft-published']['id']}/reply",
        headers=_headers(admin_token),
        json={"content": "很抱歉给您带来不便，请联系我们处理。"},
    )
    assert published.status_code == 200, published.text
    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    conn.execute(
        "UPDATE product_reviews SET reply_status = 'published', process_status = 'replied' WHERE id = ?",
        (by_review_id["batch-draft-published"]["id"],),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(customers, "get_default_config", lambda db: {"api_key": "test-key"})
    calls = []

    def fake_completion(cfg, messages, **kwargs):
        prompt = messages[0]["content"]
        calls.append(prompt)
        if "质量不满意" in prompt:
            raise customers.AIError("模型暂时不可用")
        return "很抱歉给您带来困扰，请联系我们处理。"

    monkeypatch.setattr(customers, "chat_completion", fake_completion)
    response = client.post(
        "/api/customers/reviews/batch-reply-draft",
        headers=_headers(admin_token),
        json={"review_ids": [item["id"] for item in by_review_id.values()]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["generated"] == 1
    assert payload["failed"] == 1
    assert payload["skipped"] == 1
    assert {item["status"] for item in payload["results"]} == {"generated", "failed", "skipped"}
    assert len(calls) == 2

    refreshed = client.get("/api/customers/reviews?store_id=1&q=batch-draft-", headers=_headers(admin_token)).json()["items"]
    refreshed_by_id = {item["review_id"]: item for item in refreshed}
    assert refreshed_by_id["batch-draft-ok"]["reply_status"] == "draft"
    assert refreshed_by_id["batch-draft-published"]["reply_status"] == "published"


def test_review_knowledge_suggestions_require_confirmation(client, admin_token):
    synced = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "items": [
                {"review_id": "knowledge-suggest-1", "content": "质量问题，坏了"},
                {"review_id": "knowledge-suggest-2", "content": "质量问题，开胶"},
                {"review_id": "knowledge-suggest-3", "content": "质量问题，有瑕疵"},
            ],
        },
    )
    assert synced.status_code == 200, synced.text
    refreshed = client.post(
        "/api/customers/reviews/knowledge-suggestions/refresh?store_id=1",
        headers=_headers(admin_token),
    )
    assert refreshed.status_code == 200, refreshed.text
    suggestions = client.get(
        "/api/customers/reviews/knowledge-suggestions?store_id=1",
        headers=_headers(admin_token),
    )
    assert suggestions.status_code == 200, suggestions.text
    suggestion = next(item for item in suggestions.json()["items"] if item["evidence_count"] >= 3)
    assert suggestion["status"] == "pending"
    assert suggestion["evidence_count"] >= 3

    approved = client.put(
        f"/api/customers/reviews/knowledge-suggestions/{suggestion['id']}",
        headers=_headers(admin_token),
        json={"status": "approved"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    knowledge = client.get("/api/customers/reviews/knowledge?store_id=1", headers=_headers(admin_token))
    assert any(item["id"] == approved.json()["item"]["id"] for item in knowledge.json()["items"])


def test_review_reply_requires_approval_and_publishes_to_taobao(client, admin_token, monkeypatch):
    from backend.app.core import sycm

    synced = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "source": "seller-review-management",
            "items": [{"review_id": "feed-publish-1", "content": "包装破损了"}],
        },
    )
    assert synced.status_code == 200, synced.text
    review = client.get("/api/customers/reviews?store_id=1&q=feed-publish-1", headers=_headers(admin_token)).json()["items"][0]

    not_approved = client.post(f"/api/customers/reviews/{review['id']}/reply/publish", headers=_headers(admin_token))
    assert not_approved.status_code == 400

    approved = client.put(
        f"/api/customers/reviews/{review['id']}/reply",
        headers=_headers(admin_token),
        json={"content": "很抱歉包装影响了体验，请联系我们处理。"},
    )
    assert approved.status_code == 200, approved.text

    manual_replied = client.put(
        f"/api/customers/reviews/{review['id']}/process",
        headers=_headers(admin_token),
        json={"status": "replied"},
    )
    assert manual_replied.status_code == 400

    published_calls = []
    monkeypatch.setattr(sycm, "publish_seller_review_reply", lambda store, feed_id, content: published_calls.append((feed_id, content)) or {"ret": ["SUCCESS::调用成功"]})
    published = client.post(f"/api/customers/reviews/{review['id']}/reply/publish", headers=_headers(admin_token))
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert published_calls == [("feed-publish-1", "很抱歉包装影响了体验，请联系我们处理。")]

    refreshed = client.get("/api/customers/reviews?store_id=1&q=feed-publish-1", headers=_headers(admin_token)).json()["items"][0]
    assert refreshed["reply_status"] == "published"
    assert refreshed["process_status"] == "replied"
    assert refreshed["reply_published_at"]

    cannot_reopen = client.put(
        f"/api/customers/reviews/{review['id']}/process",
        headers=_headers(admin_token),
        json={"status": "pending"},
    )
    assert cannot_reopen.status_code == 400


def test_taobao_reply_adapter_uses_verified_seller_api(monkeypatch):
    from contextlib import nullcontext

    from backend.app.core import qianniu, sycm

    captured = {}

    class FakeSession:
        def close(self):
            captured["closed"] = True

    def fake_request(session, api, data, timeout, referer):
        captured.update({"api": api, "data": data, "referer": referer})
        return {"ret": ["SUCCESS::调用成功"]}

    monkeypatch.setattr(sycm, "_ensure_profile", lambda store: None)
    monkeypatch.setattr(sycm, "exclusive_scrape", nullcontext)
    monkeypatch.setattr(qianniu, "_new_session", lambda store_id: FakeSession())
    monkeypatch.setattr(qianniu, "_request_mtop", fake_request)

    result = sycm.publish_seller_review_reply({"id": 1}, "feed-123", "感谢您的反馈")
    body = json.loads(captured["data"]["jsonBody"])
    assert result["ret"][0].startswith("SUCCESS")
    assert captured["api"] == "mtop.rm.sellercenter.operate.reply"
    assert body == {"feedId": "feed-123", "explainContent": "感谢您的反馈"}
    assert captured["closed"] is True


def test_custom_terms_learning_priority_and_insight_reports(client, admin_token):
    term = client.post(
        "/api/customers/reviews/custom-terms",
        headers=_headers(admin_token),
        json={"store_id": 1, "term": "绝绝子", "sentiment": "positive", "weight": 2.5, "enabled": True},
    )
    assert term.status_code == 200, term.text
    term_id = term.json()["item"]["id"]

    synced = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={
            "store_id": 1,
            "items": [
                {"review_id": "custom-term-review", "item_id": "learning-item", "item_title": "学习商品", "content": "这个味道绝绝子"},
                {"review_id": "learning-source", "item_id": "learning-item", "item_title": "学习商品", "content": "味道有点玄学"},
            ],
        },
    )
    assert synced.status_code == 200, synced.text

    custom_review = client.get(
        "/api/customers/reviews?store_id=1&q=custom-term-review",
        headers=_headers(admin_token),
    ).json()["items"][0]
    assert custom_review["sentiment"] == "positive"
    assert "priority_score" in custom_review
    assert custom_review["priority_level"] in {"normal", "high", "urgent"}

    source_review = client.get(
        "/api/customers/reviews?store_id=1&q=learning-source",
        headers=_headers(admin_token),
    ).json()["items"][0]
    corrected = client.put(
        f"/api/customers/reviews/{source_review['id']}/sentiment",
        headers=_headers(admin_token),
        json={"sentiment": "positive", "reason": "该商品语境中是正向表达"},
    )
    assert corrected.status_code == 200, corrected.text

    duplicate = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={"store_id": 1, "items": [{"review_id": "learning-target", "content": "味道有点玄学"}]},
    )
    assert duplicate.status_code == 200, duplicate.text
    learned = client.get(
        "/api/customers/reviews?store_id=1&q=learning-target",
        headers=_headers(admin_token),
    ).json()["items"][0]
    assert learned["sentiment"] == "positive"
    assert learned["analysis_source"] == "learned"

    topics = client.get("/api/customers/reviews/topics?store_id=1&days=3650", headers=_headers(admin_token))
    accuracy = client.get("/api/customers/reviews/accuracy?store_id=1&days=3650", headers=_headers(admin_token))
    weekly = client.get("/api/customers/reviews/weekly-report?store_id=1", headers=_headers(admin_token))
    assert topics.status_code == 200 and "emerging_terms" in topics.json()
    assert accuracy.status_code == 200 and accuracy.json()["confirmed_sample"] >= 1
    assert weekly.status_code == 200 and weekly.json()["actions"]
    assert all("store_id" in product and "item_id" in product for product in weekly.json()["products"])

    deleted = client.delete(f"/api/customers/reviews/custom-terms/{term_id}", headers=_headers(admin_token))
    assert deleted.status_code == 200, deleted.text


def test_negative_trend_alert_is_created(client, admin_token):
    db = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    cursor = db.execute("INSERT INTO stores (name, created_at) VALUES (?, ?)", ("趋势测试店", datetime.now(timezone.utc).isoformat()))
    store_id = cursor.lastrowid
    db.commit()
    db.close()

    now = datetime.now(timezone.utc)
    items = [
        {"review_id": f"trend-base-{index}", "content": "质量很好，非常满意", "review_time": (now - timedelta(days=6)).isoformat()}
        for index in range(8)
    ]
    items.extend(
        {"review_id": f"trend-current-{index}", "content": "包装破损，物流太慢，申请退款", "review_time": (now - timedelta(hours=index + 1)).isoformat()}
        for index in range(3)
    )
    synced = client.post(
        "/api/customers/reviews/sync",
        headers=_headers(admin_token),
        json={"store_id": store_id, "items": items},
    )
    assert synced.status_code == 200, synced.text

    alerts = client.get(f"/api/customers/reviews/trend-alerts?store_id={store_id}", headers=_headers(admin_token))
    assert alerts.status_code == 200, alerts.text
    assert alerts.json()["items"]
    assert alerts.json()["items"][0]["current_rate"] == 100.0


def test_review_question_answer_uses_filtered_comments(client, admin_token, monkeypatch):
    from backend.app.api import customers

    monkeypatch.setattr(customers, "get_default_config", lambda db: {"api_key": "test-key"})
    monkeypatch.setattr(customers, "chat_completion", lambda *args, **kwargs: "客户主要反馈包装和物流问题。")
    response = client.post(
        "/api/customers/reviews/ask",
        headers=_headers(admin_token),
        json={"store_id": 1, "days": 365, "question": "客户最不满意什么？"},
    )
    assert response.status_code == 200, response.text
    assert "包装和物流" in response.json()["answer"]
    assert response.json()["review_count"] > 0
