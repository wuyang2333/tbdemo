from backend.app.api.alerts import _norm_hourly_rule


def test_norm_hourly_rule_defaults():
    rule = _norm_hourly_rule({"field": "sales", "operator": "lt", "threshold": 100})
    assert rule is not None
    assert rule["enabled"] is True
    assert rule["field"] == "sales"
    assert rule["threshold"] == 100


def test_norm_hourly_rule_rejects_invalid_field():
    assert _norm_hourly_rule({"field": "not-a-field", "operator": "lt", "threshold": 1.0}) is None
    assert _norm_hourly_rule({"field": "sales", "operator": "bad-op", "threshold": 1.0}) is None


def test_hourly_push_test_without_token_returns_400(client):
    """回归测试：alerts.py 曾因未导入 HTTPException 在此时抛 NameError 500。"""
    token = _login(client)
    r = client.post(
        "/api/alerts/hourly-push/test",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert "token" in r.json()["detail"]


def test_hourly_push_channel_config_roundtrip(client):
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    saved = client.put(
        "/api/alerts/hourly-push-config",
        headers=headers,
        json={"enabled": True, "token": "tok-1", "webhook": "https://example.com/hook", "channel": "both"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["channel"] == "both"
    assert saved.json()["webhook"] == "https://example.com/hook"

    got = client.get("/api/alerts/hourly-push-config", headers=headers).json()
    assert got["channel"] == "both"
    assert got["webhook"] == "https://example.com/hook"


def test_hourly_push_invalid_channel_rejected(client):
    token = _login(client)
    r = client.put(
        "/api/alerts/hourly-push-config",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": "sms"},
    )
    assert r.status_code == 400


def test_hourly_push_test_webhook_missing(client):
    token = _login(client)
    client.put(
        "/api/alerts/hourly-push-config",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": "webhook", "webhook": ""},
    )
    r = client.post(
        "/api/alerts/hourly-push/test",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert "webhook" in r.json()["detail"]


_token_cache: str | None = None


def _login(client) -> str:
    global _token_cache
    if _token_cache is None:
        reg = client.post(
            "/api/auth/register",
            json={"username": "alertuser", "password": "pass123456", "nickname": "告警测试"},
        )
        assert reg.status_code == 200, reg.text
        _token_cache = reg.json()["token"]
    return _token_cache
