from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.api.auth import get_current_user, visible_store_ids
from backend.app.core.db import get_db
from backend.app.core.logs import log_op
from backend.app.core.qianniu import fetch_on_sale_products
from backend.app.core.sycm import PROFILE_MISSING_MSG, has_profile

router = APIRouter()


class ProductAliasIn(BaseModel):
    store_id: int
    alias: str = Field(min_length=1, max_length=60)
    note: str = Field(default="", max_length=200)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _visible_store_clause(user: dict, alias: str = "p") -> tuple[str, list[int]]:
    visible = visible_store_ids(user)
    if visible is None:
        return "", []
    column = f"{alias}.store_id" if alias else "store_id"
    if not visible:
        return f" AND {column} IN (0)", []
    placeholders = ",".join("?" for _ in visible)
    return f" AND {column} IN ({placeholders})", list(visible)


def _ensure_store_access(user: dict, store_id: int) -> None:
    visible = visible_store_ids(user)
    if visible is not None and store_id not in visible:
        raise HTTPException(status_code=403, detail="无权查看该店铺商品")


@router.get("/aliases")
def list_product_aliases(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    visible = visible_store_ids(user)
    params: list[int] = []
    where = ""
    if visible is not None:
        if not visible:
            return {"items": [], "total": 0}
        where = f" WHERE pa.store_id IN ({','.join('?' for _ in visible)})"
        params.extend(sorted(visible))
    rows = db.execute(
        """SELECT pa.*, p.title AS original_title, s.name AS store_name
        FROM product_aliases pa
        LEFT JOIN store_products p ON p.store_id = pa.store_id AND p.item_id = pa.item_id
        LEFT JOIN stores s ON s.id = pa.store_id""" + where + " ORDER BY datetime(pa.updated_at) DESC",
        params,
    ).fetchall()
    return {"items": [dict(row) for row in rows], "total": len(rows)}


@router.put("/aliases/{item_id}")
def save_product_alias(item_id: str, body: ProductAliasIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    _ensure_store_access(user, body.store_id)
    product = db.execute("SELECT title FROM store_products WHERE store_id = ? AND item_id = ?", (body.store_id, item_id)).fetchone()
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在，请先同步在售商品")
    alias = body.alias.strip()
    if not alias:
        raise HTTPException(status_code=400, detail="请输入商品备注名")
    now = _now()
    db.execute(
        """INSERT INTO product_aliases (store_id, item_id, alias, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(store_id, item_id) DO UPDATE SET alias = excluded.alias,
        note = excluded.note, updated_at = excluded.updated_at""",
        (body.store_id, item_id, alias, body.note.strip(), now, now),
    )
    row = db.execute(
        """SELECT pa.*, p.title AS original_title, s.name AS store_name
        FROM product_aliases pa JOIN store_products p ON p.store_id = pa.store_id AND p.item_id = pa.item_id
        JOIN stores s ON s.id = pa.store_id WHERE pa.store_id = ? AND pa.item_id = ?""",
        (body.store_id, item_id),
    ).fetchone()
    return {"item": dict(row)}


@router.delete("/aliases/{item_id}")
def delete_product_alias(item_id: str, store_id: int, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    _ensure_store_access(user, store_id)
    db.execute("DELETE FROM product_aliases WHERE store_id = ? AND item_id = ?", (store_id, item_id))
    return {"ok": True}


def _save_store_products(db, store_id: int, products: list[dict], synced_at: str) -> None:
    db.execute("SAVEPOINT store_product_sync")
    try:
        db.execute("DELETE FROM store_products WHERE store_id = ?", (store_id,))
        db.executemany(
            """
            INSERT INTO store_products
                (store_id, item_id, category_id, title, image, price, stock,
                 sold_quantity, monthly_sold, quality_score, shelf_at, status,
                 detail_url, edit_url, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    store_id,
                    item["item_id"],
                    item["category_id"],
                    item["title"],
                    item["image"],
                    item["price"],
                    item["stock"],
                    item["sold_quantity"],
                    item["monthly_sold"],
                    item["quality_score"],
                    item["shelf_at"],
                    item["status"],
                    item["detail_url"],
                    item["edit_url"],
                    synced_at,
                )
                for item in products
            ],
        )
        db.execute("RELEASE SAVEPOINT store_product_sync")
    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT store_product_sync")
        db.execute("RELEASE SAVEPOINT store_product_sync")
        raise


def sync_catalog_all(db, store_id: int | None = None, user: dict | None = None) -> dict:
    params: list[int] = []
    where = " WHERE 1=1"
    if store_id is not None:
        if user is not None:
            _ensure_store_access(user, store_id)
        where += " AND id = ?"
        params.append(store_id)
    elif user is not None:
        visible = visible_store_ids(user)
        if visible is not None:
            if not visible:
                return {"results": [], "total": 0, "ok": 0}
            where += " AND id IN (" + ",".join("?" for _ in visible) + ")"
            params.extend(visible)
    stores = db.execute("SELECT * FROM stores" + where + " ORDER BY id", params).fetchall()
    results = []
    for store in stores:
        if not has_profile(store["id"]):
            results.append(
                {
                    "store_id": store["id"],
                    "store_name": store["name"],
                    "ok": False,
                    "error": PROFILE_MISSING_MSG,
                }
            )
            continue
        try:
            items = fetch_on_sale_products(dict(store))
            synced_at = _now()
            _save_store_products(db, store["id"], items, synced_at)
            results.append(
                {
                    "store_id": store["id"],
                    "store_name": store["name"],
                    "ok": True,
                    "count": len(items),
                    "synced_at": synced_at,
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "store_id": store["id"],
                    "store_name": store["name"],
                    "ok": False,
                    "error": str(exc),
                }
            )
    return {
        "results": results,
        "total": len(stores),
        "ok": sum(1 for item in results if item["ok"]),
    }


@router.get("")
def list_products(
    store_id: int | None = None,
    q: str = "",
    stock_status: str = "all",
    sales_status: str = "all",
    sort_by: str = Query("sold_quantity", pattern="^(sold_quantity|shelf_at)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if store_id is not None:
        _ensure_store_access(user, store_id)
    where = " WHERE 1=1"
    params: list = []
    visible_clause, visible_params = _visible_store_clause(user)
    where += visible_clause
    params.extend(visible_params)
    if store_id is not None:
        where += " AND p.store_id = ?"
        params.append(store_id)
    keyword = q.strip()
    if keyword:
        where += " AND (p.title LIKE ? OR p.item_id LIKE ? OR pa.alias LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
    summary_where = where
    if stock_status == "low":
        where += " AND p.stock BETWEEN 1 AND 10"
    elif stock_status == "zero":
        where += " AND p.stock <= 0"
    elif stock_status == "normal":
        where += " AND p.stock > 10"
    elif stock_status != "all":
        raise HTTPException(status_code=400, detail="库存筛选不正确")
    if sales_status == "no_sales":
        where += " AND p.monthly_sold <= 0"
    elif sales_status == "low_quality":
        where += " AND p.quality_score < 70"
    elif sales_status != "all":
        raise HTTPException(status_code=400, detail="经营状态筛选不正确")

    total = db.execute("SELECT COUNT(*) AS c FROM store_products p LEFT JOIN product_aliases pa ON pa.store_id = p.store_id AND pa.item_id = p.item_id" + where, params).fetchone()["c"]
    summary = db.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN p.stock BETWEEN 1 AND 10 THEN 1 ELSE 0 END) AS low_stock,
               SUM(CASE WHEN p.stock <= 0 THEN 1 ELSE 0 END) AS zero_stock,
               COALESCE(SUM(p.sold_quantity), 0) AS sold_quantity,
               MIN(p.synced_at) AS last_sync
        FROM store_products p
        LEFT JOIN product_aliases pa ON pa.store_id = p.store_id AND pa.item_id = p.item_id
        """
        + summary_where,
        params,
    ).fetchone()
    if sort_by == "shelf_at":
        order_sql = (
            "CASE WHEN TRIM(COALESCE(p.shelf_at, '')) = '' THEN 1 ELSE 0 END, "
            f"p.shelf_at {sort_order.upper()}, p.item_id DESC"
        )
    else:
        order_sql = f"p.sold_quantity {sort_order.upper()}, p.item_id DESC"
    rows = db.execute(
        """
        SELECT p.*, s.name AS store_name, pa.alias AS product_alias, pa.note AS alias_note,
               p.title AS original_title
        FROM store_products p
        JOIN stores s ON s.id = p.store_id
        LEFT JOIN product_aliases pa ON pa.store_id = p.store_id AND pa.item_id = p.item_id
        """
        + where
        + f" ORDER BY {order_sql} LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    last_sync = summary["last_sync"]
    try:
        stale = datetime.now() - datetime.fromisoformat(last_sync) > timedelta(minutes=20)
    except (TypeError, ValueError):
        stale = True
    return {
        "items": [{**dict(row), "title": row["product_alias"] or row["title"]} for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": {
            "total": summary["total"],
            "low_stock": summary["low_stock"] or 0,
            "zero_stock": summary["zero_stock"] or 0,
            "sold_quantity": summary["sold_quantity"],
            "last_sync": last_sync,
            "stale": stale,
        },
    }


@router.post("/sync")
def sync_products(
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    result = sync_catalog_all(db, store_id=store_id, user=user)
    log_op(
        db,
        user,
        "products",
        "同步在售商品",
        detail=f"成功 {result['ok']} / 共 {result['total']} 家店铺",
    )
    return result
