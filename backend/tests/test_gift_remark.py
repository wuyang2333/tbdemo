from datetime import datetime, timezone

from backend.app.core import gift_remark
from backend.app.core.db import connect_db


def _seed_pending_gift(
    conn,
    *,
    order_no: str = "5127193587359094839",
    wangwang: str = "旺旺",
    price: float = 10,
) -> int:
    conn.execute(
        """
        INSERT OR IGNORE INTO stores
        (id, name, owner, category, level, location, status, created_at)
        VALUES (99, '自动备注测试店', '', '', '', '', 'active', '2026-08-25T00:00:00+00:00')
        """
    )
    created = conn.execute(
        """
        INSERT INTO gifts
        (store_id, order_no, recipient, gift_name, quantity, price, status, created_at,
         keyword, spec, commission, wangwang, review_status, settle_status, remark_status,
         order_time, image, remark_auto_pending)
        VALUES
        (99, ?, '', '', 1, ?, 'pending', '2026-08-25T00:00:00+00:00',
         '测试', '一件', 2, ?, 'none', 'unsettled', 'unremarked',
         '2026-08-25T00:00:00+00:00', '', 1)
        """,
        (order_no, price, wangwang),
    )
    conn.commit()
    return int(created.lastrowid)


def test_pending_gift_changes_status_only_after_qianniu_success(client, monkeypatch):
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        gift_id = _seed_pending_gift(conn)
        gift_remark.update_config(conn, enabled=True)
        calls = []

        def fake_remark(store, order_no, memo, flag):
            calls.append((store["id"], order_no, memo, flag))
            return {"ok": True, "changed": True}

        monkeypatch.setattr(gift_remark.qianniu, "remark_sold_order", fake_remark)
        result = gift_remark.sync_pending(conn)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()

        assert result["remarked"] == 1
        assert calls == [(99, "5127193587359094839", "SD", 1)]
        assert row["remark_status"] == "remarked"
        assert row["remark_auto_pending"] == 0
        assert row["remarked_at"]
        assert row["remark_error"] == ""
    finally:
        conn.close()


def test_qianniu_failure_keeps_gift_unremarked(client, monkeypatch):
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        gift_id = _seed_pending_gift(conn)
        gift_remark.update_config(conn, enabled=True)

        def fail_remark(store, order_no, memo, flag):
            raise gift_remark.qianniu.QianniuError("测试失败")

        monkeypatch.setattr(gift_remark.qianniu, "remark_sold_order", fail_remark)
        result = gift_remark.sync_pending(conn)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()

        assert result["failed"] == 1
        assert row["remark_status"] == "remark_failed"
        assert row["remark_auto_pending"] == 1
        assert row["remark_error"] == "测试失败"
        assert row["remark_next_retry_at"]
    finally:
        conn.close()


def test_order_not_found_retries_after_three_minutes(client, monkeypatch):
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        gift_id = _seed_pending_gift(conn)
        gift_remark.update_config(conn, enabled=True)

        def fail_not_found(*args, **kwargs):
            raise gift_remark.qianniu.QianniuOrderNotFound("订单未找到")

        monkeypatch.setattr(gift_remark.qianniu, "remark_sold_order", fail_not_found)
        before = datetime.now(timezone.utc)
        gift_remark.sync_pending(conn)
        after = datetime.now(timezone.utc)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()
        retry_at = datetime.fromisoformat(row["remark_next_retry_at"])

        assert row["remark_status"] == "order_not_found"
        assert before.timestamp() + 180 <= retry_at.timestamp() <= after.timestamp() + 180
    finally:
        conn.close()


def test_waiting_payment_is_deferred_without_remark(client, monkeypatch):
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        gift_id = _seed_pending_gift(conn)
        gift_remark.update_config(conn, enabled=True)

        monkeypatch.setattr(
            gift_remark.qianniu,
            "remark_sold_order",
            lambda *args, **kwargs: {
                "ok": True,
                "changed": False,
                "outcome": "awaiting_payment",
                "order_status": "等待买家付款",
            },
        )
        result = gift_remark.sync_pending(conn)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()

        assert result["deferred"] == 1
        assert row["remark_status"] == "awaiting_payment"
        assert row["remark_auto_pending"] == 1
        assert row["remark_next_retry_at"]
    finally:
        conn.close()


def test_closed_order_is_terminal_without_remark(client, monkeypatch):
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        gift_id = _seed_pending_gift(conn, wangwang="")
        gift_remark.update_config(conn, enabled=True)

        monkeypatch.setattr(
            gift_remark.qianniu,
            "remark_sold_order",
            lambda *args, **kwargs: {
                "ok": True,
                "changed": False,
                "outcome": "order_closed",
                "order_status": "交易关闭",
            },
        )
        result = gift_remark.sync_pending(conn)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()

        assert result["closed"] == 1
        assert row["remark_status"] == "order_closed"
        assert row["remark_auto_pending"] == 0
    finally:
        conn.close()


def test_closed_order_keeps_querying_by_buyer_for_new_order(client, monkeypatch):
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        gift_id = _seed_pending_gift(conn, order_no="5127193587359094839", wangwang="后续下单旺旺")
        gift_remark.update_config(conn, enabled=True)
        calls = []

        def closed(*args, **kwargs):
            return {"ok": True, "changed": False, "outcome": "order_closed", "order_status": "交易关闭"}

        def new_order(*args, **kwargs):
            calls.append(args[2] if len(args) > 2 else kwargs.get("order_date"))
            if len(calls) == 1:
                raise gift_remark.qianniu.QianniuOrderNotFound("尚未重新下单")
            return {"ok": True, "changed": True, "outcome": "remarked", "order_no": "9876543210123456", "actual_paid": 10}

        monkeypatch.setattr(gift_remark.qianniu, "remark_sold_order", closed)
        monkeypatch.setattr(gift_remark.qianniu, "remark_sold_order_by_buyer", new_order)
        first = gift_remark.sync_pending(conn)
        assert first["failed"] == 1
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()
        assert row["remark_status"] == "order_not_found"

        conn.execute("UPDATE gifts SET remark_next_retry_at = NULL WHERE id = ?", (gift_id,))
        conn.commit()
        second = gift_remark.sync_pending(conn)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()
        assert second["remarked"] == 1
        assert row["remark_status"] == "remarked"
        assert row["order_no"] == "9876543210123456"
        assert calls == ["", ""]
    finally:
        conn.close()


def test_exact_match_calibrates_price_and_records_history(client, monkeypatch):
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        gift_id = _seed_pending_gift(conn)
        gift_remark.update_config(conn, enabled=True)

        monkeypatch.setattr(
            gift_remark.qianniu,
            "remark_sold_order",
            lambda *args, **kwargs: {
                "ok": True,
                "changed": True,
                "outcome": "remarked",
                "order_status": "买家已付款",
                "actual_paid": 12.34,
            },
        )
        result = gift_remark.sync_pending(conn)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()
        history = conn.execute(
            "SELECT * FROM gift_price_sync_logs WHERE gift_id = ? ORDER BY id DESC LIMIT 1",
            (gift_id,),
        ).fetchone()

        assert result["price_updated"] == 1
        assert row["price"] == 12.34
        assert row["price_before_qianniu"] == 10
        assert row["qianniu_price"] == 12.34
        assert row["price_synced_at"]
        assert history["system_price_before"] == 10
        assert history["qianniu_price"] == 12.34
    finally:
        conn.close()


def test_qianniu_error_does_not_change_price(client, monkeypatch):
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        gift_id = _seed_pending_gift(conn)
        gift_remark.update_config(conn, enabled=True)

        def fail_remark(*args, **kwargs):
            raise gift_remark.qianniu.QianniuError("接口异常")

        monkeypatch.setattr(gift_remark.qianniu, "remark_sold_order", fail_remark)
        gift_remark.sync_pending(conn)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()
        history_count = conn.execute(
            "SELECT COUNT(*) FROM gift_price_sync_logs WHERE gift_id = ?",
            (gift_id,),
        ).fetchone()[0]

        assert row["price"] == 10
        assert row["qianniu_price"] is None
        assert history_count == 0
    finally:
        conn.close()


def test_wangwang_only_exact_match_remarks_and_records_lookup_order(client, monkeypatch):
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        gift_id = _seed_pending_gift(conn, order_no="", wangwang="精确旺旺")
        gift_remark.update_config(conn, enabled=True)
        calls = []

        def fake_remark(store, buyer_nick, order_date, expected_amount, memo, flag):
            calls.append((store["id"], buyer_nick, order_date, expected_amount, memo, flag))
            return {
                "ok": True,
                "changed": True,
                "outcome": "remarked",
                "order_no": "9876543210123456789",
                "actual_paid": 10,
            }

        monkeypatch.setattr(gift_remark.qianniu, "remark_sold_order_by_buyer", fake_remark)
        result = gift_remark.sync_pending(conn)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()

        assert calls == [(99, "精确旺旺", "2026-08-25", 10, "SD", 1)]
        assert result["matched_by_wangwang"] == 1
        assert result["remarked"] == 1
        assert row["remark_lookup_order_no"] == "9876543210123456789"
        assert row["remark_match_source"] == "wangwang"
        assert row["remark_status"] == "remarked"
        assert row["remark_auto_pending"] == 0
    finally:
        conn.close()


def test_wangwang_price_mismatch_calibrates_and_defers_remark(client, monkeypatch):
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        gift_id = _seed_pending_gift(conn, order_no="", wangwang="金额旺旺", price=10)
        gift_remark.update_config(conn, enabled=True)
        monkeypatch.setattr(
            gift_remark.qianniu,
            "remark_sold_order_by_buyer",
            lambda *args, **kwargs: {
                "ok": True,
                "changed": False,
                "outcome": "price_mismatch",
                "order_no": "1111222233334444555",
                "actual_paid": 12.34,
            },
        )

        result = gift_remark.sync_pending(conn)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()
        history = conn.execute(
            "SELECT * FROM gift_price_sync_logs WHERE gift_id = ? ORDER BY id DESC LIMIT 1",
            (gift_id,),
        ).fetchone()

        assert result["price_updated"] == 1
        assert result["price_deferred"] == 1
        assert result["remarked"] == 0
        assert row["price"] == 12.34
        assert row["remark_lookup_order_no"] == "1111222233334444555"
        assert row["remark_status"] == "unremarked"
        assert row["remark_auto_pending"] == 1
        assert row["remark_next_retry_at"]
        assert history["order_no"] == "1111222233334444555"
        assert history["system_price_before"] == 10
        assert history["qianniu_price"] == 12.34
    finally:
        conn.close()


def test_later_matching_order_number_is_rechecked_and_remarked(client, monkeypatch):
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        gift_id = _seed_pending_gift(conn, order_no="", wangwang="二次核验旺旺", price=12.34)
        conn.execute(
            "UPDATE gifts SET order_no = ?, remark_lookup_order_no = ?, remark_match_source = 'wangwang' WHERE id = ?",
            ("2222333344445555666", "2222333344445555666", gift_id),
        )
        conn.commit()
        gift_remark.update_config(conn, enabled=True)
        calls = []

        def fake_remark(store, order_no, memo, flag):
            calls.append((store["id"], order_no, memo, flag))
            return {
                "ok": True,
                "changed": True,
                "outcome": "remarked",
                "order_no": order_no,
                "actual_paid": 12.34,
            }

        monkeypatch.setattr(gift_remark.qianniu, "remark_sold_order", fake_remark)
        result = gift_remark.sync_pending(conn)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()

        assert calls == [(99, "2222333344445555666", "SD", 1)]
        assert result["remarked"] == 1
        assert row["remark_status"] == "remarked"
        assert row["remark_auto_pending"] == 0
    finally:
        conn.close()


def test_later_mismatching_order_number_stops_automatic_remark(client, monkeypatch):
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        gift_id = _seed_pending_gift(conn, order_no="3333444455556666777", wangwang="冲突旺旺")
        conn.execute(
            "UPDATE gifts SET remark_lookup_order_no = ?, remark_match_source = 'wangwang' WHERE id = ?",
            ("9999000011112222333", gift_id),
        )
        conn.commit()
        gift_remark.update_config(conn, enabled=True)
        monkeypatch.setattr(
            gift_remark.qianniu,
            "remark_sold_order",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应调用千牛备注")),
        )

        result = gift_remark.sync_pending(conn)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()

        assert result["failed"] == 1
        assert row["remark_status"] == "remark_failed"
        assert row["remark_auto_pending"] == 0
        assert "与旺旺预匹配订单" in row["remark_error"]
    finally:
        conn.close()


def test_ambiguous_wangwang_match_stops_automatic_remark(client, monkeypatch):
    conn = connect_db()
    try:
        conn.execute("DELETE FROM gifts")
        gift_id = _seed_pending_gift(conn, order_no="", wangwang="重复旺旺")
        gift_remark.update_config(conn, enabled=True)

        def fail_ambiguous(*args, **kwargs):
            raise gift_remark.qianniu.QianniuAmbiguousOrder("同日匹配到多条订单")

        monkeypatch.setattr(gift_remark.qianniu, "remark_sold_order_by_buyer", fail_ambiguous)
        result = gift_remark.sync_pending(conn)
        row = conn.execute("SELECT * FROM gifts WHERE id = ?", (gift_id,)).fetchone()

        assert result["failed"] == 1
        assert row["remark_status"] == "remark_failed"
        assert row["remark_auto_pending"] == 0
        assert row["remark_error"] == "同日匹配到多条订单"
    finally:
        conn.close()


def test_gift_remark_setting_can_be_disabled(client, admin_token):
    response = client.put(
        "/api/settings/gift-qianniu-remark",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"enabled": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False
    assert response.json()["flag"] == 1
    assert response.json()["memo"] == "SD"
