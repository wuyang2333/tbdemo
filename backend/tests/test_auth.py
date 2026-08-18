import re

from backend.app.api.auth import USERNAME_PATTERN, hash_password


def test_username_pattern():
    assert USERNAME_PATTERN.fullmatch("demo_ops") is None  # 下划线不允许
    assert USERNAME_PATTERN.fullmatch("abc") is not None
    assert USERNAME_PATTERN.fullmatch("abc123") is not None
    assert USERNAME_PATTERN.fullmatch("123abc") is None  # 数字开头不允许
    assert USERNAME_PATTERN.fullmatch("中文") is None
    assert USERNAME_PATTERN.fullmatch("ab") is None  # 太短


def test_hash_password_salt_sensitive():
    salt = b"salt-bytes"
    assert hash_password("secret123", salt) != hash_password("secret123", b"other-salt")
    assert re.fullmatch(r"[0-9a-f]{64}", hash_password("secret123", salt))


def test_register_login_me_flow(client, admin_token):
    reg = client.post(
        "/api/auth/register",
        json={"username": "tester01", "password": "pass123456", "nickname": "测试花名"},
    )
    assert reg.status_code == 200
    assert reg.json().get("pending") is True  # 无邀请码默认进入待审核

    # 待审核期间不能登录
    pending_login = client.post("/api/auth/login", json={"username": "tester01", "password": "pass123456"})
    assert pending_login.status_code == 403

    # 管理员在「待审核」列表里通过
    pending = client.get("/api/accounts/pending", headers={"Authorization": f"Bearer {admin_token}"})
    assert pending.status_code == 200
    item = next(u for u in pending.json()["items"] if u["username"] == "tester01")
    ok = client.post(f"/api/accounts/{item['id']}/approve", headers={"Authorization": f"Bearer {admin_token}"})
    assert ok.status_code == 200

    login = client.post("/api/auth/login", json={"username": "tester01", "password": "pass123456"})
    assert login.status_code == 200
    token = login.json()["token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["nickname"] == "测试花名"

    bad = client.post("/api/auth/login", json={"username": "tester01", "password": "wrong"})
    assert bad.status_code == 401

    dup = client.post(
        "/api/auth/register",
        json={"username": "tester01", "password": "pass123456", "nickname": "重复"},
    )
    assert dup.status_code == 400

def test_register_validation(client):
    r = client.post(
        "/api/auth/register",
        json={"username": "bad name", "password": "pass123456", "nickname": "x"},
    )
    assert r.status_code == 400
    r2 = client.post(
        "/api/auth/register",
        json={"username": "okuser01", "password": "pass123456", "nickname": ""},
    )
    assert r2.status_code == 400  # 花名必填


def test_protected_route_requires_login(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 401

