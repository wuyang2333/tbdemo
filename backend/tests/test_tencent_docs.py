from urllib.parse import parse_qs, urlparse

from backend.app.core import tencent_docs
from backend.app.core.db import DB_PATH, connect_db


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _cells(values: list[str]) -> dict:
    return {"values": [{"cellValue": {"text": value}} for value in values]}


def test_gift_values_formats_order_time_as_hour_and_minute():
    values = tencent_docs._gift_values(
        {
            "id": 1,
            "order_time": "2026-08-25T14:35:42+08:00",
            "store_name": "测试店铺",
            "price": 10,
            "commission": 2,
            "owner_nickname": "测试负责人",
        },
        include_cloud_fields=False,
    )
    assert values[1] == "2026-08-25"
    assert values[2] == "14:35"
    assert values[12] == "测试负责人"


def test_layout_assignments_leaves_three_blank_rows_between_dates():
    assignments = tencent_docs._layout_assignments(
        [
            {"id": 3, "order_time": "2026-08-26 09:00:00"},
            {"id": 2, "order_time": "2026-08-25 11:00:00"},
            {"id": 1, "order_time": "2026-08-25 10:00:00"},
        ]
    )

    assert [(row_number, gift["id"]) for row_number, gift in assignments] == [
        (2, 1),
        (3, 2),
        (7, 3),
    ]


def test_tencent_docs_config_masks_secret_and_builds_oauth_url(client, admin_token):
    saved = client.put(
        "/api/settings/tencent-docs",
        headers=_headers(admin_token),
        json={
            "enabled": False,
            "document_url": "https://docs.qq.com/sheet/DTG1YaFV2eUhMRGdF",
            "sheet_id": "",
            "client_id": "client-test",
            "client_secret": "secret-test",
            "redirect_uri": "https://example.com/api/settings/tencent-docs/oauth/callback",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["client_secret_configured"] is True
    assert "client_secret" not in saved.json()
    assert "access_token" not in saved.json()

    authorize = client.get("/api/settings/tencent-docs/oauth-url", headers=_headers(admin_token))
    assert authorize.status_code == 200, authorize.text
    parsed = urlparse(authorize.json()["url"])
    params = parse_qs(parsed.query)
    assert parsed.path == "/oauth/v2/authorize"
    assert params["client_id"] == ["client-test"]
    assert params["scope"] == ["all"]
    assert params["state"][0]


def test_tencent_docs_accepts_manual_access_credentials(client, admin_token):
    saved = client.put(
        "/api/settings/tencent-docs",
        headers=_headers(admin_token),
        json={
            "enabled": False,
            "document_url": "https://docs.qq.com/sheet/DTG1YaFV2eUhMRGdF",
            "sheet_id": "",
            "client_id": "manual-client",
            "client_secret": "",
            "access_token": "manual-access-token",
            "open_id": "manual-open-id",
            "redirect_uri": "",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["authorized"] is True
    assert saved.json()["access_token_configured"] is True
    assert saved.json()["poll_minutes"] == 1
    assert "access_token" not in saved.json()
    assert "open_id" not in saved.json()

    conn = connect_db()
    try:
        configured = tencent_docs.TencentDocsClient(conn)
        assert configured.config["access_token"] == "manual-access-token"
        assert configured.config["open_id"] == "manual-open-id"
    finally:
        conn.close()


def test_tencent_docs_rejects_non_https_callback(client, admin_token):
    client.put(
        "/api/settings/tencent-docs",
        headers=_headers(admin_token),
        json={
            "enabled": False,
            "document_url": "https://docs.qq.com/sheet/DTG1YaFV2eUhMRGdF",
            "sheet_id": "",
            "client_id": "client-test",
            "client_secret": "secret-test",
            "redirect_uri": "http://127.0.0.1/callback",
        },
    )
    response = client.get("/api/settings/tencent-docs/oauth-url", headers=_headers(admin_token))
    assert response.status_code == 400
    assert "HTTPS" in response.json()["detail"]


def test_sync_pulls_cloud_fields_and_preserves_them_on_push():
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        tencent_docs.update_config(
            conn,
            {
                "enabled": True,
                "document_url": "https://docs.qq.com/sheet/DTG1YaFV2eUhMRGdF",
                "sheet_id": "sheet-1",
            },
        )
        created = conn.execute(
            """INSERT INTO gifts
            (store_id, store_name, order_no, recipient, gift_name, quantity, price, status, created_at,
             keyword, spec, commission, wangwang, review_status, settle_status, order_time, image, owner_nickname)
            VALUES (0, '测试店铺', '', '', '', 1, 9.9, 'pending', '2026-08-25T10:00:00+00:00',
                    '测试关键词', '测试规格', 2.5, '', 'none', 'unsettled', '2026-08-25 10:00:00', '', '系统负责人')"""
        )
        gift_id = created.lastrowid

        class FakeClient:
            requests: list[dict]

            def __init__(self):
                self.requests = []

            def get_sheets(self):
                return [{"sheetId": "sheet-1", "title": "工作表1", "rowCount": 2, "rowTotal": 200}]

            def get_range(self, sheet_id: str, range_a1: str):
                assert sheet_id == "sheet-1"
                return {
                    "startRow": 0,
                    "rows": [
                        _cells(tencent_docs.HEADERS),
                        _cells([str(gift_id), "2026-08-25", "10:00", "测试店铺", "测试关键词", "测试规格", "9.9", "2.5", "云端旺旺", "9876543210123456", "未评论", "未结款", "云端修改负责人"]),
                    ],
                }

            def batch_update(self, requests: list[dict]):
                self.requests.extend(requests)

        fake = FakeClient()
        result = tencent_docs.sync_gifts(conn, client=fake)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()
        assert row["wangwang"] == "云端旺旺"
        assert row["order_no"] == "9876543210123456"
        assert row["owner_nickname"] == "系统负责人"
        assert row["remark_status"] == "unremarked"
        assert row["remark_auto_pending"] == 1
        assert row["tencent_row"] == 2
        assert result["pulled"] == 1
        assert result["pushed"] == 0

        updates = [item["updateRangeRequest"] for item in fake.requests]
        existing_updates = [item for item in updates if item["gridData"]["startRow"] == 1]
        assert {item["gridData"]["startColumn"] for item in existing_updates} == {0, 4, 10}
        assert all(item["gridData"]["startColumn"] not in {8, 9} for item in existing_updates)
        owner_update = next(item for item in existing_updates if item["gridData"]["startColumn"] == 10)
        assert owner_update["gridData"]["rows"][0]["values"][2]["cellValue"]["text"] == "系统负责人"

        conn.execute("UPDATE gifts SET price = 12.34 WHERE id = ?", (gift_id,))
        conn.commit()
        fake.requests.clear()
        tencent_docs.sync_gifts(conn, client=fake)
        business_update = next(
            item["updateRangeRequest"]
            for item in fake.requests
            if item["updateRangeRequest"]["gridData"]["startColumn"] == 4
        )
        price_cell = business_update["gridData"]["rows"][0]["values"][2]
        assert price_cell["cellValue"]["text"] == "12.34"
    finally:
        conn.rollback()
        conn.close()


def test_wangwang_only_cloud_update_enables_automatic_remark():
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        created = conn.execute(
            """INSERT INTO gifts
            (store_id, store_name, order_no, recipient, gift_name, quantity, price, status, created_at,
             keyword, spec, commission, wangwang, review_status, settle_status, order_time, image)
            VALUES (0, '测试店铺', '', '', '', 1, 9.9, 'pending', '2026-08-25T10:00:00+00:00',
                    '测试关键词', '测试规格', 2.5, '', 'none', 'unsettled', '2026-08-25 10:00:00', '')"""
        )
        gift_id = int(created.lastrowid)
        gift = dict(conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone())
        values = [str(gift_id), "2026-08-25", "10:00", "测试店铺", "测试关键词", "测试规格", "9.9", "2.5", "云端旺旺", "", "未评论", "未结款", ""]

        errors = tencent_docs._update_cloud_fields(conn, gift, values)
        conn.commit()
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()

        assert errors == []
        assert row["wangwang"] == "云端旺旺"
        assert row["order_no"] == ""
        assert row["remark_status"] == "unremarked"
        assert row["remark_auto_pending"] == 1
    finally:
        conn.close()


def test_sync_releases_database_lock_before_cloud_write():
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        tencent_docs.update_config(
            conn,
            {
                "enabled": True,
                "document_url": "https://docs.qq.com/sheet/DTG1YaFV2eUhMRGdF",
                "sheet_id": "sheet-1",
            },
        )
        created = conn.execute(
            """INSERT INTO gifts
            (store_id, store_name, order_no, recipient, gift_name, quantity, price, status, created_at,
             keyword, spec, commission, wangwang, review_status, settle_status, order_time, image)
            VALUES (0, '测试店铺', '', '', '', 1, 9.9, 'pending', '2026-08-25T10:00:00+00:00',
                    '测试关键词', '测试规格', 2.5, '', 'none', 'unsettled', '2026-08-25 10:00:00', '')"""
        )
        gift_id = created.lastrowid
        conn.commit()

        class LockCheckingClient:
            def get_sheets(self):
                return [{"sheetId": "sheet-1", "title": "工作表1", "rowCount": 2, "rowTotal": 200}]

            def get_range(self, sheet_id: str, range_a1: str):
                return {
                    "startRow": 0,
                    "rows": [
                        _cells(tencent_docs.HEADERS),
                        _cells([str(gift_id), "2026-08-25", "2026-08-25 10:00:00", "测试店铺", "测试关键词", "测试规格", "9.9", "2.5", "云端旺旺", "", "未评论", "未结款"]),
                    ],
                }

            def batch_update(self, requests: list[dict]):
                concurrent = connect_db()
                try:
                    concurrent.execute("PRAGMA busy_timeout = 100")
                    concurrent.execute("UPDATE gifts SET status = 'processing' WHERE id = ?", (gift_id,))
                    concurrent.commit()
                finally:
                    concurrent.close()

        result = tencent_docs.sync_gifts(conn, client=LockCheckingClient())
        assert result["pulled"] == 1
        assert conn.execute("SELECT status FROM gifts WHERE id = ?", (gift_id,)).fetchone()["status"] == "processing"
    finally:
        conn.rollback()
        conn.close()


def test_batch_create_commits_before_background_sync(client, admin_token, monkeypatch):
    def background_write() -> None:
        concurrent = connect_db()
        try:
            concurrent.execute("PRAGMA busy_timeout = 100")
            concurrent.execute("UPDATE gifts SET status = 'processing' WHERE keyword = '提交锁测试'")
            concurrent.commit()
        finally:
            concurrent.close()

    from backend.app.api import gifts

    monkeypatch.setattr(gifts, "_sync_tencent_docs_background", background_write)
    response = client.post(
        "/api/gifts/batch-create",
        headers=_headers(admin_token),
        json={
            "date": "2026-08-25",
            "start_time": "13:24",
            "store_id": 0,
            "store_name": "测试店铺",
            "keyword": "提交锁测试",
            "spec": "一支",
            "price": 16,
            "commission": 6,
            "quantity": 2,
            "image": "",
        },
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 2

    conn = connect_db()
    try:
        statuses = conn.execute("SELECT status FROM gifts WHERE keyword = '提交锁测试'").fetchall()
        assert statuses
        assert all(row["status"] == "processing" for row in statuses)
    finally:
        conn.close()


def test_sync_uploads_keyword_image_once_and_inserts_into_keyword_cell():
    images_dir = DB_PATH.parent / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    image_path = images_dir / "sync-test.png"
    image_path.write_bytes(b"test-image")
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        tencent_docs.update_config(
            conn,
            {
                "enabled": True,
                "document_url": "https://docs.qq.com/sheet/DTG1YaFV2eUhMRGdF",
                "sheet_id": "sheet-1",
            },
        )
        created = conn.execute(
            """INSERT INTO gifts
            (store_id, store_name, order_no, recipient, gift_name, quantity, price, status, created_at,
             keyword, spec, commission, wangwang, review_status, settle_status, order_time, image)
            VALUES (0, '测试店铺', '', '', '', 1, 9.9, 'pending', '2026-08-25T10:00:00+00:00',
                    '', '测试规格', 2.5, '', 'none', 'unsettled', '2026-08-25 10:00:00', '/api/images/sync-test.png')"""
        )
        gift_id = created.lastrowid
        conn.commit()

        class ImageClient:
            uploads = 0
            inserted: list[dict]

            def __init__(self):
                self.inserted = []
                self.cleared = []

            def get_sheets(self):
                return [{"sheetId": "sheet-1", "title": "工作表1", "rowCount": 1, "rowTotal": 200}]

            def get_range(self, sheet_id: str, range_a1: str):
                return {"startRow": 0, "rows": [_cells(tencent_docs.HEADERS)]}

            def batch_update(self, requests: list[dict]):
                return None

            def upload_image(self, path):
                assert path == image_path
                self.uploads += 1
                return "image-id"

            def convert_file_id(self):
                return "300000000$FILE"

            def insert_cell_images(self, file_id: str, sheet_id: str, images: list[dict]):
                assert file_id == "300000000$FILE"
                assert sheet_id == "sheet-1"
                self.inserted.extend(images)

            def clear_range(self, file_id: str, range_a1: str):
                self.cleared.append(range_a1)

        fake = ImageClient()
        first = tencent_docs.sync_gifts(conn, client=fake)
        assert first["errors"] == []
        assert fake.uploads == 1
        assert fake.inserted == [
            {
                "type": 1,
                "imageID": "image-id",
                "width": 100,
                "height": 100,
                "row": 2,
                "col": 5,
                "offsetX": None,
                "offsetY": None,
                "clipInfo": None,
            }
        ]
        assert conn.execute("SELECT tencent_image_synced FROM gifts WHERE id = ?", (gift_id,)).fetchone()["tencent_image_synced"] == "/api/images/sync-test.png#cell-r2-c5"

        fake.inserted.clear()
        second = tencent_docs.sync_gifts(conn, client=fake)
        assert second["errors"] == []
        assert fake.uploads == 1
        assert fake.inserted == []
        assert fake.cleared == []
    finally:
        conn.rollback()
        conn.close()
        image_path.unlink(missing_ok=True)


def test_sync_clears_replaced_keyword_image_before_inserting_new_one():
    images_dir = DB_PATH.parent / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    image_path = images_dir / "replacement.png"
    image_path.write_bytes(b"replacement")
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        tencent_docs.update_config(conn, {"enabled": True, "sheet_id": "sheet-1"})
        created = conn.execute(
            """INSERT INTO gifts
            (store_id, store_name, order_no, recipient, gift_name, quantity, price, status, created_at,
             keyword, spec, commission, wangwang, review_status, settle_status, order_time, image, tencent_image_synced)
            VALUES (0, '测试店铺', '', '', '', 1, 9.9, 'pending', '2026-08-25T10:00:00+00:00',
                    '', '测试规格', 2.5, '', 'none', 'unsettled', '2026-08-25 10:00:00',
                    '/api/images/replacement.png', '/api/images/old.png#cell-col5')"""
        )
        gift_id = created.lastrowid
        conn.commit()

        class ReplacingClient:
            cleared = []

            def get_sheets(self):
                return [{"sheetId": "sheet-1", "title": "工作表1", "rowCount": 2, "rowTotal": 200}]

            def get_range(self, sheet_id: str, range_a1: str):
                return {"startRow": 0, "rows": [_cells(tencent_docs.HEADERS), _cells([str(gift_id)] + [""] * 11)]}

            def convert_file_id(self):
                return "300000000$FILE"

            def clear_range(self, file_id: str, range_a1: str):
                self.cleared.append(range_a1)

            def batch_update(self, requests: list[dict]):
                return None

            def upload_image(self, path):
                return "new-image-id"

            def insert_cell_images(self, file_id: str, sheet_id: str, images: list[dict]):
                return None

        fake = ReplacingClient()
        result = tencent_docs.sync_gifts(conn, client=fake)
        assert result["errors"] == []
        assert fake.cleared == ["sheet-1!E1:E1"]
    finally:
        conn.rollback()
        conn.close()
        image_path.unlink(missing_ok=True)


def test_sync_is_noop_until_enabled():
    conn = connect_db()
    try:
        tencent_docs.update_config(conn, {"enabled": False})
        result = tencent_docs.sync_gifts(conn)
        assert result["skipped"] is True
        assert result["pushed"] == 0
    finally:
        conn.rollback()
        conn.close()
