from backend.app.core.db import connect_db


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_gift_remark_status_defaults_and_can_toggle(client, admin_token):
    created = client.post(
        "/api/gifts/batch-create",
        headers=_headers(admin_token),
        json={
            "date": "2026-08-25",
            "start_time": "15:00",
            "store_id": 0,
            "store_name": "测试店铺",
            "keyword": "备注状态测试",
            "spec": "一件",
            "price": 10,
            "commission": 2,
            "quantity": 1,
            "image": "",
        },
    )
    assert created.status_code == 200, created.text
    gift = created.json()["items"][0]
    assert gift["remark_status"] == "unremarked"
    assert gift["owner_nickname"] == "测试管理员"

    updated = client.post(
        f"/api/gifts/{gift['id']}/remark",
        headers=_headers(admin_token),
        json={"status": "remarked"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["item"]["remark_status"] == "remarked"

    conn = connect_db()
    try:
        row = conn.execute("SELECT remark_status FROM gifts WHERE id = ?", (gift["id"],)).fetchone()
        assert row["remark_status"] == "remarked"
    finally:
        conn.close()


def test_gift_owner_is_creator_nickname_and_cannot_be_changed(client, admin_token):
    created = client.post(
        "/api/gifts/batch-create",
        headers=_headers(admin_token),
        json={
            "date": "2026-08-25",
            "start_time": "16:00",
            "store_id": 0,
            "store_name": "负责人测试店铺",
            "keyword": "负责人测试",
            "spec": "一件",
            "price": 10,
            "commission": 2,
            "quantity": 1,
            "image": "",
        },
    )
    assert created.status_code == 200, created.text
    gift = created.json()["items"][0]
    assert gift["owner_nickname"] == "测试管理员"

    updated = client.put(
        f"/api/gifts/{gift['id']}",
        headers=_headers(admin_token),
        json={
            "order_no": "",
            "store_id": 0,
            "store_name": "负责人测试店铺",
            "keyword": "负责人测试已编辑",
            "spec": "一件",
            "price": 10,
            "commission": 2,
            "wangwang": "",
            "order_time": "2026-08-25 16:00:00",
            "review_status": "none",
            "settle_status": "unsettled",
            "remark_status": "unremarked",
            "image": "",
            "owner_nickname": "伪造负责人",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["item"]["owner_nickname"] == "测试管理员"
