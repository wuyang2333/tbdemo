def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_settings_route_exists(client, admin_token):
    """设置模块：/api/settings/brand 为管理员级路由，未登录即拦截。"""
    anon = client.get("/api/settings/brand")
    assert anon.status_code in (401, 403)  # 管理员级，未登录即拦截

    r = client.get("/api/settings/brand", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert "brand" in r.json()
    assert r.json()["brand"]["name"]


def test_logs_route_admin_only(client, admin_token):
    r = client.get("/api/logs", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200


def test_modules_exclude_admin_modules_for_member(client, admin_token):
    # 第一个注册的用户是超管；再造一个普通账号验证模块过滤
    created = client.post(
        "/api/accounts",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": "member01", "password": "pass123456", "nickname": "普通", "role": "member"},
    )
    assert created.status_code == 200, created.text
    m = client.post("/api/auth/login", json={"username": "member01", "password": "pass123456"})
    assert m.status_code == 200, m.text
    items = client.get(
        "/api/modules", headers={"Authorization": f"Bearer {m.json()['token']}"}
    ).json()["items"]
    ids = {item["id"] for item in items}
    assert "settings" not in ids
    assert "accounts" not in ids
    assert "logs" not in ids
    assert "dashboard" in ids
