from backend.app.core.db import DB_PATH, connect_db


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


def _create_gifts_with_shared_image(client, admin_token, quantity: int = 2):
    uploaded = client.post(
        "/api/gifts/image-upload",
        headers=_headers(admin_token),
        files={"file": ("shared.png", b"shared-image", "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    image_url = uploaded.json()["url"]
    created = client.post(
        "/api/gifts/batch-create",
        headers=_headers(admin_token),
        json={
            "date": "2026-09-16",
            "start_time": "09:00",
            "store_id": 0,
            "store_name": "共享图片测试店铺",
            "keyword": "",
            "spec": "一件",
            "price": 10,
            "commission": 2,
            "quantity": quantity,
            "image": image_url,
        },
    )
    assert created.status_code == 200, created.text
    return image_url, created.json()["items"]


def test_clearing_shared_gift_image_keeps_file_until_last_reference(client, admin_token):
    image_url, gifts = _create_gifts_with_shared_image(client, admin_token)
    image_path = DB_PATH.parent / "images" / image_url.rsplit("/", 1)[-1]
    try:
        assert image_path.is_file()

        first = client.post(f"/api/gifts/{gifts[0]['id']}/image/clear", headers=_headers(admin_token))
        assert first.status_code == 200, first.text
        assert image_path.is_file()

        second = client.post(f"/api/gifts/{gifts[1]['id']}/image/clear", headers=_headers(admin_token))
        assert second.status_code == 200, second.text
        assert not image_path.exists()
    finally:
        image_path.unlink(missing_ok=True)


def test_replacing_shared_gift_image_does_not_delete_other_gifts_source(client, admin_token):
    image_url, gifts = _create_gifts_with_shared_image(client, admin_token)
    shared_path = DB_PATH.parent / "images" / image_url.rsplit("/", 1)[-1]
    replacement_paths = []
    try:
        first = client.post(
            f"/api/gifts/{gifts[0]['id']}/image",
            headers=_headers(admin_token),
            files={"file": ("replacement-1.png", b"replacement-one", "image/png")},
        )
        assert first.status_code == 200, first.text
        replacement_paths.append(DB_PATH.parent / "images" / first.json()["item"]["image"].rsplit("/", 1)[-1])
        assert shared_path.is_file()

        second = client.post(
            f"/api/gifts/{gifts[1]['id']}/image",
            headers=_headers(admin_token),
            files={"file": ("replacement-2.png", b"replacement-two", "image/png")},
        )
        assert second.status_code == 200, second.text
        replacement_paths.append(DB_PATH.parent / "images" / second.json()["item"]["image"].rsplit("/", 1)[-1])
        assert not shared_path.exists()
    finally:
        shared_path.unlink(missing_ok=True)
        for path in replacement_paths:
            path.unlink(missing_ok=True)
