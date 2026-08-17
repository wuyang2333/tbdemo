"""pytest 全局配置：把数据库指向临时文件，避免测试污染真实数据。"""

import os
import secrets
import sqlite3
import tempfile

os.environ["TAOBAO_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="tbw-test-"), "test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client():
    """不进入上下文管理器：避免触发 lifespan 的后台循环（它们会连真实淘宝接口）。"""
    from backend.app.main import app

    return TestClient(app)


@pytest.fixture()
def admin_token(client):
    """预置一个固定超管账号：与注册顺序无关，任何测试都能拿到管理员 token。"""
    from backend.app.api.auth import hash_password

    conn = sqlite3.connect(os.environ["TAOBAO_DB_PATH"])
    salt = secrets.token_bytes(16)
    conn.execute(
        """
        INSERT OR IGNORE INTO users
        (username, password_hash, salt, nickname, created_at, role, status)
        VALUES (?, ?, ?, ?, ?, 'super_admin', 'active')
        """,
        (
            "bootadmin",
            hash_password("admin123456", salt),
            salt.hex(),
            "测试管理员",
            "2026-08-17T00:00:00",
        ),
    )
    conn.commit()
    conn.close()

    r = client.post("/api/auth/login", json={"username": "bootadmin", "password": "admin123456"})
    assert r.status_code == 200, r.text
    return r.json()["token"]
