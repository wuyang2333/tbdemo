"""礼品单订单回传后的千牛自动插旗备注。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from backend.app.core import qianniu


CONFIG_KEY = "gift_qianniu_remark"
DEFAULT_CONFIG = {
    "enabled": False,
    "flag": 1,
    "memo": "SD",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_text() -> str:
    return _now().isoformat()


def get_config(db) -> dict:
    row = db.execute("SELECT value FROM meta WHERE key = ?", (CONFIG_KEY,)).fetchone()
    config = dict(DEFAULT_CONFIG)
    if row and row["value"]:
        try:
            saved = json.loads(row["value"])
        except (TypeError, ValueError):
            saved = {}
        if isinstance(saved, dict):
            config.update(saved)
    config["enabled"] = bool(config.get("enabled"))
    config["flag"] = 1
    config["memo"] = "SD"
    return config


def update_config(db, *, enabled: bool) -> dict:
    config = get_config(db)
    config["enabled"] = bool(enabled)
    db.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (CONFIG_KEY, json.dumps(config, ensure_ascii=False)),
    )
    db.commit()
    return config


def public_config(db) -> dict:
    config = get_config(db)
    pending = db.execute(
        "SELECT COUNT(*) FROM gifts WHERE remark_auto_pending = 1 AND remark_status != 'remarked'"
    ).fetchone()[0]
    failed = db.execute(
        "SELECT COUNT(*) FROM gifts WHERE remark_auto_pending = 1 AND remark_error != ''"
    ).fetchone()[0]
    return {**config, "pending": int(pending), "failed": int(failed)}


def _record_failure(db, gift_id: int, status: str, message: str, retry_minutes: int) -> None:
    next_retry = (_now() + timedelta(minutes=retry_minutes)).isoformat()
    db.execute(
        """
        UPDATE gifts
        SET remark_status = ?, remark_error = ?, remark_next_retry_at = ?
        WHERE id = ? AND remark_auto_pending = 1
        """,
        (status, message[:500], next_retry, gift_id),
    )
    db.commit()


def _record_terminal_failure(db, gift_id: int, message: str) -> None:
    db.execute(
        """
        UPDATE gifts
        SET remark_status = 'remark_failed', remark_auto_pending = 0,
            remark_error = ?, remark_next_retry_at = NULL
        WHERE id = ? AND remark_auto_pending = 1
        """,
        (message[:500], gift_id),
    )
    db.commit()


def _record_waiting_payment(db, gift_id: int, status_text: str) -> None:
    next_retry = (_now() + timedelta(minutes=2)).isoformat()
    db.execute(
        """
        UPDATE gifts
        SET remark_status = 'awaiting_payment', remark_error = ?, remark_next_retry_at = ?
        WHERE id = ? AND remark_auto_pending = 1
        """,
        ((status_text or "订单等待买家付款")[:500], next_retry, gift_id),
    )
    db.commit()


def _record_closed(db, gift_id: int, *, continue_by_buyer: bool) -> None:
    # 关闭可能只是用户下错单后的中间状态；只有存在旺旺号时才继续观察新订单。
    next_retry = (_now() + timedelta(minutes=3)).isoformat() if continue_by_buyer else None
    db.execute(
        """
        UPDATE gifts
        SET remark_status = 'order_closed', remark_auto_pending = ?,
            remark_error = ?, remark_next_retry_at = ?
        WHERE id = ? AND remark_auto_pending = 1
        """,
        (1 if continue_by_buyer else 0,
         '原订单已关闭，系统将继续按旺旺号查找新订单' if continue_by_buyer else '',
         next_retry, gift_id),
    )
    db.commit()


def _sync_price(db, gift: dict, actual_paid, matched_order_no: str = "") -> bool:
    synced_at = _now_text()
    if actual_paid is None:
        db.execute(
            "UPDATE gifts SET price_sync_error = ?, price_synced_at = ? WHERE id = ?",
            ("千牛未返回有效实付金额", synced_at, gift["id"]),
        )
        db.commit()
        return False
    try:
        system_price = Decimal(str(gift["price"])).quantize(Decimal("0.01"))
        qianniu_price = Decimal(str(actual_paid)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        db.execute(
            "UPDATE gifts SET price_sync_error = ?, price_synced_at = ? WHERE id = ?",
            ("千牛实付金额格式异常", synced_at, gift["id"]),
        )
        db.commit()
        return False
    changed = abs(system_price - qianniu_price) >= Decimal("0.01")
    if changed:
        db.execute(
            """
            INSERT INTO gift_price_sync_logs
            (gift_id, order_no, system_price_before, qianniu_price, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (gift["id"], gift["order_no"] or matched_order_no, float(system_price), float(qianniu_price), synced_at),
        )
        db.execute(
            """
            UPDATE gifts
            SET price = ?, price_before_qianniu = ?, qianniu_price = ?,
                price_synced_at = ?, price_sync_error = ''
            WHERE id = ?
            """,
            (float(qianniu_price), float(system_price), float(qianniu_price), synced_at, gift["id"]),
        )
    else:
        db.execute(
            """
            UPDATE gifts
            SET qianniu_price = ?, price_synced_at = ?, price_sync_error = ''
            WHERE id = ?
            """,
            (float(qianniu_price), synced_at, gift["id"]),
        )
    db.commit()
    return changed


def sync_pending(db, limit: int = 10) -> dict:
    config = get_config(db)
    if not config["enabled"]:
        return {"ok": True, "skipped": True, "reason": "千牛自动备注未启用", "processed": 0, "remarked": 0, "failed": 0}
    now = _now_text()
    rows = db.execute(
        """
        SELECT g.id, g.store_id, g.order_no, g.wangwang, g.order_time, g.price,
               g.remark_status, g.remark_lookup_order_no, g.remark_match_source, s.name AS store_name
        FROM gifts g
        JOIN stores s ON s.id = g.store_id
        WHERE g.remark_auto_pending = 1
          AND g.remark_status != 'remarked'
          AND (g.order_no != '' OR TRIM(g.wangwang) != '')
          AND g.store_id > 0
          AND (g.remark_next_retry_at IS NULL OR g.remark_next_retry_at = '' OR g.remark_next_retry_at <= ?)
        ORDER BY g.id
        LIMIT ?
        """,
        (now, max(1, min(int(limit), 50))),
    ).fetchall()
    result = {
        "ok": True,
        "skipped": False,
        "processed": 0,
        "remarked": 0,
        "deferred": 0,
        "closed": 0,
        "price_updated": 0,
        "price_deferred": 0,
        "matched_by_wangwang": 0,
        "failed": 0,
        "errors": [],
    }
    for row in rows:
        gift = dict(row)
        attempted_at = _now_text()
        db.execute(
            """
            UPDATE gifts
            SET remark_attempted_at = ?, remark_attempts = remark_attempts + 1, remark_error = ''
            WHERE id = ? AND remark_auto_pending = 1
            """,
            (attempted_at, gift["id"]),
        )
        db.commit()
        result["processed"] += 1
        if gift["order_no"] and gift["remark_lookup_order_no"] and gift["order_no"] != gift["remark_lookup_order_no"]:
            message = (
                f"回填订单号 {gift['order_no']} 与旺旺预匹配订单 {gift['remark_lookup_order_no']} 不一致，已停止自动备注"
            )
            _record_terminal_failure(db, gift["id"], message)
            result["failed"] += 1
            result["errors"].append(message)
            continue
        try:
            store = {"id": gift["store_id"], "name": gift["store_name"]}
            if gift["order_no"] and gift["remark_status"] != "order_closed":
                remark_result = qianniu.remark_sold_order(
                    store,
                    gift["order_no"],
                    memo=config["memo"],
                    flag=config["flag"],
                )
                if remark_result.get("outcome") == "order_closed" and str(gift["wangwang"] or "").strip():
                    # 原订单关闭后，不再限定原下单日期，按旺旺号继续寻找后续新单。
                    remark_result = qianniu.remark_sold_order_by_buyer(
                        store,
                        gift["wangwang"],
                        "",
                        gift["price"],
                        memo=config["memo"],
                        flag=config["flag"],
                    )
            else:
                remark_result = qianniu.remark_sold_order_by_buyer(
                    store,
                    gift["wangwang"],
                    "" if gift["remark_status"] == "order_closed" else str(gift["order_time"] or "")[:10],
                    gift["price"],
                    memo=config["memo"],
                    flag=config["flag"],
                )
        except qianniu.QianniuOrderNotFound as exc:
            message = str(exc)
            _record_failure(db, gift["id"], "order_not_found", message, 3)
            result["failed"] += 1
            result["errors"].append(message)
        except qianniu.QianniuAmbiguousOrder as exc:
            message = str(exc)
            _record_terminal_failure(db, gift["id"], message)
            result["failed"] += 1
            result["errors"].append(message)
        except qianniu.QianniuError as exc:
            message = str(exc)
            _record_failure(db, gift["id"], "remark_failed", message, 5)
            result["failed"] += 1
            result["errors"].append(message)
        except Exception as exc:  # noqa: BLE001
            message = f"千牛自动备注异常：{exc}"
            _record_failure(db, gift["id"], "remark_failed", message, 5)
            result["failed"] += 1
            result["errors"].append(message)
        else:
            matched_order_no = str(remark_result.get("order_no") or "")
            if matched_order_no and (not gift["order_no"] or matched_order_no != gift["order_no"]):
                db.execute(
                    """
                    UPDATE gifts
                    SET order_no = ?, remark_lookup_order_no = ?, remark_match_source = 'wangwang'
                    WHERE id = ?
                    """,
                    (matched_order_no, matched_order_no, gift["id"]),
                )
                db.commit()
                result["matched_by_wangwang"] += 1
            if _sync_price(db, gift, remark_result.get("actual_paid"), matched_order_no):
                result["price_updated"] += 1
            outcome = remark_result.get("outcome")
            if outcome == "price_mismatch":
                _record_failure(
                    db,
                    gift["id"],
                    "unremarked",
                    "旺旺匹配订单金额已校准，等待下次金额一致后自动备注",
                    1,
                )
                result["price_deferred"] += 1
            elif outcome == "awaiting_payment":
                _record_waiting_payment(db, gift["id"], str(remark_result.get("order_status") or ""))
                result["deferred"] += 1
            elif outcome == "order_closed":
                _record_closed(
                    db,
                    gift["id"],
                    continue_by_buyer=bool(str(gift["wangwang"] or "").strip()),
                )
                result["closed"] += 1
            else:
                remarked_at = _now_text()
                db.execute(
                    """
                    UPDATE gifts
                    SET remark_status = 'remarked', remark_auto_pending = 0,
                        remarked_at = ?, remark_error = '', remark_next_retry_at = ''
                    WHERE id = ? AND remark_auto_pending = 1
                    """,
                    (remarked_at, gift["id"]),
                )
                db.commit()
                result["remarked"] += 1
    result["ok"] = result["failed"] == 0
    return result
