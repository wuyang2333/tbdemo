"""礼品单：礼品订单管理（不区分店铺），带操作日志。"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import get_current_user
from backend.app.core.db import get_db
from backend.app.core.logs import log_op

router = APIRouter()

GIFT_STATUSES = ("pending", "shipped", "delivered", "refunded")
STATUS_LABELS = {
    "pending": "待发货",
    "shipped": "已发货",
    "delivered": "已完成",
    "refunded": "已退款",
}


class GiftIn(BaseModel):
    recipient: str
    gift_name: str
    quantity: int = 1
    price: float = 0


class GiftStatusIn(BaseModel):
    status: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_gift_or_404(db, gift_id: int):
    row = db.execute(
        """
        SELECT g.*, COALESCE(s.name, '') AS store_name
        FROM gifts g
        LEFT JOIN stores s ON s.id = g.store_id
        WHERE g.id = ?
        """,
        (gift_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="礼品单不存在")
    return row


def _payload(row) -> dict:
    return {
        "id": row["id"],
        "store_id": row["store_id"],
        "store_name": row["store_name"] or "未关联店铺",
        "order_no": row["order_no"],
        "recipient": row["recipient"],
        "gift_name": row["gift_name"],
        "quantity": row["quantity"],
        "price": row["price"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


@router.get("")
def list_gifts(
    store_id: int | None = None,
    status: str | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    query = """
        SELECT g.*, COALESCE(s.name, '') AS store_name
        FROM gifts g
        LEFT JOIN stores s ON s.id = g.store_id
        WHERE 1 = 1
    """
    params: list = []
    if store_id is not None:
        query += " AND g.store_id = ?"
        params.append(store_id)
    if status:
        query += " AND g.status = ?"
        params.append(status)
    query += " ORDER BY g.id DESC"
    rows = db.execute(query, params).fetchall()
    return {"items": [_payload(row) for row in rows]}


@router.post("")
def create_gift(
    body: GiftIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    recipient = body.recipient.strip()
    gift_name = body.gift_name.strip()
    if not recipient:
        raise HTTPException(status_code=400, detail="收礼人不能为空")
    if not gift_name:
        raise HTTPException(status_code=400, detail="礼品名称不能为空")
    if not (1 <= body.quantity <= 999):
        raise HTTPException(status_code=400, detail="数量需在 1-999 之间")
    if not (0 <= body.price <= 999999):
        raise HTTPException(status_code=400, detail="单价超出范围")

    order_no = f"G{datetime.now().strftime('%y%m%d')}{secrets.token_hex(3).upper()}"
    cur = db.execute(
        """
        INSERT INTO gifts (store_id, order_no, recipient, gift_name, quantity, price, status, created_at)
        VALUES (0, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (order_no, recipient, gift_name, body.quantity, body.price, _now()),
    )
    item = _payload(_get_gift_or_404(db, cur.lastrowid))
    log_op(db, user, "gifts", "create", f"{recipient} · {gift_name}", f"新增礼品单 {order_no}")
    return {"item": item}


@router.post("/{gift_id}/status")
def update_gift_status(
    gift_id: int,
    body: GiftStatusIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if body.status not in GIFT_STATUSES:
        raise HTTPException(status_code=400, detail="状态不正确")
    row = _get_gift_or_404(db, gift_id)
    db.execute("UPDATE gifts SET status = ? WHERE id = ?", (body.status, gift_id))
    item = _payload(_get_gift_or_404(db, gift_id))
    log_op(
        db,
        user,
        "gifts",
        "status",
        row["order_no"],
        f"状态更新为「{STATUS_LABELS[body.status]}」",
    )
    return {"item": item}


@router.delete("/{gift_id}")
def delete_gift(
    gift_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    row = _get_gift_or_404(db, gift_id)
    db.execute("DELETE FROM gifts WHERE id = ?", (gift_id,))
    log_op(db, user, "gifts", "delete", row["order_no"], f"删除礼品单 {row['order_no']}")
    return {"ok": True}
