"""礼品单：订单台账管理（日期/下单时间/店铺/关键词/规格/金额/佣金/旺旺号/订单号/评论/结款）。"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import get_current_user
from backend.app.core.db import get_db
from backend.app.core.logs import log_op

router = APIRouter()

REVIEW_STATUSES = ("none", "reviewed")
SETTLE_STATUSES = ("unsettled", "settled")
REVIEW_LABELS = {"none": "未评论", "reviewed": "已评论"}
SETTLE_LABELS = {"unsettled": "未结款", "settled": "已结款"}


class GiftIn(BaseModel):
    order_no: str = ""
    store_id: int = 0
    keyword: str = ""
    spec: str = ""
    price: float = 0
    commission: float = 0
    wangwang: str = ""
    order_time: str = ""
    review_status: str = "none"
    settle_status: str = "unsettled"


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
        "keyword": row["keyword"],
        "spec": row["spec"],
        "price": row["price"],
        "commission": row["commission"],
        "wangwang": row["wangwang"],
        "order_time": row["order_time"],
        "review_status": row["review_status"],
        "settle_status": row["settle_status"],
        "status": row["status"],
        "recipient": row["recipient"],
        "gift_name": row["gift_name"],
        "quantity": row["quantity"],
        "created_at": row["created_at"],
    }


def _validate(body: GiftIn) -> dict:
    keyword = body.keyword.strip()
    spec = body.spec.strip()
    wangwang = body.wangwang.strip()
    if not (0 <= body.price <= 999999):
        raise HTTPException(status_code=400, detail="金额超出范围")
    if not (0 <= body.commission <= 999999):
        raise HTTPException(status_code=400, detail="佣金超出范围")
    if body.review_status not in REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="评论状态不正确")
    if body.settle_status not in SETTLE_STATUSES:
        raise HTTPException(status_code=400, detail="结款状态不正确")
    return {"keyword": keyword, "spec": spec, "wangwang": wangwang}


def _resolve_order_no(db, body: GiftIn, exclude_id: int | None = None) -> str:
    order_no = body.order_no.strip()
    if order_no:
        if len(order_no) > 40:
            raise HTTPException(status_code=400, detail="订单号过长（最多 40 个字符）")
        if exclude_id is not None:
            exists = db.execute(
                "SELECT id FROM gifts WHERE order_no = ? AND id != ?",
                (order_no, exclude_id),
            ).fetchone()
        else:
            exists = db.execute("SELECT id FROM gifts WHERE order_no = ?", (order_no,)).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail=f"订单号「{order_no}」已存在，请检查后重试")
        return order_no
    return f"G{datetime.now().strftime('%y%m%d')}{secrets.token_hex(3).upper()}"


@router.get("")
def list_gifts(
    store_id: int | None = None,
    review_status: str | None = None,
    settle_status: str | None = None,
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
    if review_status:
        query += " AND g.review_status = ?"
        params.append(review_status)
    if settle_status:
        query += " AND g.settle_status = ?"
        params.append(settle_status)
    query += " ORDER BY COALESCE(g.order_time, g.created_at) DESC, g.id DESC"
    rows = db.execute(query, params).fetchall()
    return {"items": [_payload(row) for row in rows]}


@router.post("")
def create_gift(
    body: GiftIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    fields = _validate(body)
    if body.store_id != 0:
        store = db.execute("SELECT id FROM stores WHERE id = ?", (body.store_id,)).fetchone()
        if not store:
            raise HTTPException(status_code=400, detail="所选店铺不存在")
    order_no = _resolve_order_no(db, body)
    order_time = body.order_time.strip() or _now()
    cur = db.execute(
        """
        INSERT INTO gifts (store_id, order_no, keyword, spec, price, commission, wangwang, order_time,
                           review_status, settle_status, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            body.store_id,
            order_no,
            fields["keyword"],
            fields["spec"],
            body.price,
            body.commission,
            fields["wangwang"],
            order_time,
            body.review_status,
            body.settle_status,
            _now(),
        ),
    )
    item = _payload(_get_gift_or_404(db, cur.lastrowid))
    log_op(db, user, "gifts", "create", order_no, f"新增礼品单 {order_no}")
    return {"item": item}


@router.put("/{gift_id}")
def update_gift(
    gift_id: int,
    body: GiftIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    row = _get_gift_or_404(db, gift_id)
    fields = _validate(body)
    if body.store_id != 0:
        store = db.execute("SELECT id FROM stores WHERE id = ?", (body.store_id,)).fetchone()
        if not store:
            raise HTTPException(status_code=400, detail="所选店铺不存在")
    order_no = body.order_no.strip() or row["order_no"]
    if len(order_no) > 40:
        raise HTTPException(status_code=400, detail="订单号过长（最多 40 个字符）")
    exists = db.execute(
        "SELECT id FROM gifts WHERE order_no = ? AND id != ?",
        (order_no, gift_id),
    ).fetchone()
    if exists:
        raise HTTPException(status_code=400, detail=f"订单号「{order_no}」已存在，请检查后重试")
    order_time = body.order_time.strip() or row["order_time"] or row["created_at"]
    db.execute(
        """
        UPDATE gifts
        SET store_id = ?, order_no = ?, keyword = ?, spec = ?, price = ?, commission = ?,
            wangwang = ?, order_time = ?, review_status = ?, settle_status = ?
        WHERE id = ?
        """,
        (
            body.store_id,
            order_no,
            fields["keyword"],
            fields["spec"],
            body.price,
            body.commission,
            fields["wangwang"],
            order_time,
            body.review_status,
            body.settle_status,
            gift_id,
        ),
    )
    item = _payload(_get_gift_or_404(db, gift_id))
    log_op(db, user, "gifts", "update", order_no, f"编辑礼品单 {row['order_no']}")
    return {"item": item}


@router.post("/{gift_id}/review")
def update_gift_review(
    gift_id: int,
    body: GiftStatusIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if body.status not in REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="评论状态不正确")
    row = _get_gift_or_404(db, gift_id)
    db.execute("UPDATE gifts SET review_status = ? WHERE id = ?", (body.status, gift_id))
    item = _payload(_get_gift_or_404(db, gift_id))
    log_op(db, user, "gifts", "review", row["order_no"], f"评论状态改为「{REVIEW_LABELS[body.status]}」")
    return {"item": item}


@router.post("/{gift_id}/settle")
def update_gift_settle(
    gift_id: int,
    body: GiftStatusIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if body.status not in SETTLE_STATUSES:
        raise HTTPException(status_code=400, detail="结款状态不正确")
    row = _get_gift_or_404(db, gift_id)
    db.execute("UPDATE gifts SET settle_status = ? WHERE id = ?", (body.status, gift_id))
    item = _payload(_get_gift_or_404(db, gift_id))
    log_op(db, user, "gifts", "settle", row["order_no"], f"结款状态改为「{SETTLE_LABELS[body.status]}」")
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
