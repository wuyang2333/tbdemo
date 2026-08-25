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
        json={"status": "resolved", "note": "已联系买家"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "resolved"


def test_review_endpoints_require_auth(client):
    assert client.get("/api/customers/reviews").status_code in (401, 403)


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

    published_calls = []
    monkeypatch.setattr(sycm, "publish_seller_review_reply", lambda store, feed_id, content: published_calls.append((feed_id, content)) or {"ret": ["SUCCESS::调用成功"]})
    published = client.post(f"/api/customers/reviews/{review['id']}/reply/publish", headers=_headers(admin_token))
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert published_calls == [("feed-publish-1", "很抱歉包装影响了体验，请联系我们处理。")]

    refreshed = client.get("/api/customers/reviews?store_id=1&q=feed-publish-1", headers=_headers(admin_token)).json()["items"][0]
    assert refreshed["reply_status"] == "published"
    assert refreshed["reply_published_at"]


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
