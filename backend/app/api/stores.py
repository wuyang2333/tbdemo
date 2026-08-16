"""店铺管理：多店铺绑定、健康状态、授权管理与当前操作店铺。"""

from __future__ import annotations

import math
import random
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import get_current_user
from backend.app.core.db import get_db
from backend.app.core.logs import log_op
from backend.app.core.sycm import (
    SycmError,
    bind_login,
    check_sycm_login,
    fetch_store_daily,
    has_profile,
)

router = APIRouter()

STATUSES = ("active", "auth_error", "stopped")
CATEGORIES = ("女装", "男装", "美妆", "食品", "数码", "家居", "母婴", "其他")
LEVELS = ("天猫旗舰店", "天猫专卖店", "金冠店", "皇冠店", "五钻店", "四钻店", "其他")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(value: datetime) -> str:
    return value.isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _display_status(row) -> str:
    if row["status"] == "stopped":
        return "stopped"
    expires = row["auth_expires_at"]
    if expires:
        try:
            if _parse(expires) < _now():
                return "auth_expired"
        except ValueError:
            pass
    return row["status"]


def _payload(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "owner": row["owner"],
        "category": row["category"],
        "level": row["level"],
        "location": row["location"],
        "dsr_desc": row["dsr_desc"],
        "dsr_service": row["dsr_service"],
        "dsr_logistics": row["dsr_logistics"],
        "status": row["status"],
        "display_status": _display_status(row),
        "auth_expires_at": row["auth_expires_at"],
        "created_at": row["created_at"],
        "sycm_username": row["sycm_username"],
        "sycm_configured": has_profile(row["id"]),
        "sycm_cookie_masked": _mask_cookie(row["sycm_cookie"]),
    }


def _meta_get(db, key: str):
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _meta_set(db, key: str, value: str) -> None:
    db.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _log(db, user: dict, action: str, target_name: str = "", detail: str = "") -> None:
    log_op(db, user, "stores", action, target_name, detail)


def can_access_store(user: dict, store_id: int) -> bool:
    if user["role"] in ("admin", "super_admin"):
        return True
    allowed = user.get("allowed_store_ids")
    return allowed is None or store_id in allowed


def _visible_rows(rows, user: dict):
    if user["role"] in ("admin", "super_admin") or user.get("allowed_store_ids") is None:
        return list(rows)
    allowed = set(user["allowed_store_ids"])
    return [row for row in rows if row["id"] in allowed]


def _metrics_for(store_id: int, day: date_cls) -> dict:
    """确定性演示指标：同一店铺同一天结果一致，后续可替换为生意参谋真实数据。"""
    rnd = random.Random(store_id * 100000 + day.toordinal())
    base = 8000 + store_id * 2600
    weekend = 1.28 if day.weekday() >= 5 else 1.0
    season = 1 + 0.18 * math.sin(day.toordinal() / 9)
    sales = round(base * weekend * season * (0.85 + rnd.random() * 0.3), 2)
    orders = int(sales / (120 + rnd.random() * 60))
    visitors = int(orders * (18 + rnd.random() * 14))
    refund_rate = round(2 + rnd.random() * 7 + (store_id % 3) * 1.1, 1)
    return {
        "sales": sales,
        "orders": orders,
        "visitors": visitors,
        "refund_rate": refund_rate,
    }


def _metrics_for_day(db, store_id: int, day: date_cls) -> dict:
    """按真实同步数据返回某天指标；没有数据时返回 0。"""
    row = db.execute(
        "SELECT sales, orders, visitors, conversion_rate FROM store_daily_data "
        "WHERE store_id = ? AND data_date = ?",
        (store_id, day.isoformat()),
    ).fetchone()
    if not row:
        return {"sales": 0.0, "orders": 0, "visitors": 0, "refund_rate": 0.0}
    return {
        "sales": round(row["sales"] or 0.0, 2),
        "orders": int(row["orders"] or 0),
        "visitors": int(row["visitors"] or 0),
        "refund_rate": 0.0,
    }


def _compute_alerts(db) -> list[dict]:
    items = []
    now = _now()
    rows = db.execute("SELECT * FROM stores ORDER BY id ASC").fetchall()
    for row in rows:
        name = row["name"]
        base = {"store_id": row["id"], "store_name": name, "created_at": _fmt(now)}
        status = _display_status(row)

        if status == "auth_expired":
            items.append(
                {
                    **base,
                    "id": f"al_{row['id']}_expired",
                    "type": "auth_expired",
                    "level": "error",
                    "message": f"「{name}」店铺授权已过期，请尽快刷新授权",
                }
            )
        elif status == "stopped":
            items.append(
                {
                    **base,
                    "id": f"al_{row['id']}_stopped",
                    "type": "stopped",
                    "level": "info",
                    "message": f"「{name}」店铺已停用",
                }
            )
        else:
            expires = row["auth_expires_at"]
            if expires:
                try:
                    days_left = (_parse(expires) - now).days
                    if days_left <= 7:
                        items.append(
                            {
                                **base,
                                "id": f"al_{row['id']}_expiring",
                                "type": "auth_expiring",
                                "level": "warn",
                                "message": f"「{name}」授权将于 {max(days_left, 0)} 天后到期，请提前续期",
                            }
                        )
                except ValueError:
                    pass


        if 0 < min(row["dsr_desc"], row["dsr_service"], row["dsr_logistics"]) < 4.5:
            items.append(
                {
                    **base,
                    "id": f"al_{row['id']}_dsr",
                    "type": "dsr",
                    "level": "warn",
                    "message": f"「{name}」存在低于 4.5 的 DSR 评分，建议关注服务体验",
                }
            )


    order_map = {"error": 0, "warn": 1, "info": 2}
    items.sort(key=lambda item: (order_map[item["level"]], item["store_id"]))
    return items


def run_inspect_once() -> int:
    """巡检一次：把授权已过期的店铺落库，并更新巡检时间。返回状态更新的店铺数。"""
    import sqlite3

    from backend.app.core.db import DB_PATH

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM stores").fetchall()
        updated = 0
        for row in rows:
            if row["status"] == "active" and _display_status(row) == "auth_expired":
                conn.execute("UPDATE stores SET status = 'auth_expired' WHERE id = ?", (row["id"],))
                updated += 1
        _meta_set(conn, "stores_last_inspect", _fmt(_now()))
        conn.commit()
        return updated
    finally:
        conn.close()


class StoreIn(BaseModel):
    name: str
    owner: str = ""
    category: str = ""
    level: str = ""
    location: str = ""
    dsr_desc: float = 0
    dsr_service: float = 0
    dsr_logistics: float = 0
    auth_expires_at: str = ""


class StatusIn(BaseModel):
    status: str


class CurrentIn(BaseModel):
    store_id: int | None = None


class SycmConfigIn(BaseModel):
    username: str = ""
    password: str = ""
    cookie: str = ""


def _get_store_or_404(db, store_id: int):
    row = db.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="店铺不存在")
    return row


def _validate(body: StoreIn) -> str:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="店铺名称不能为空")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="店铺名称不能超过 50 个字符")
    if body.category and body.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="主营类目不正确")
    if body.level and body.level not in LEVELS:
        raise HTTPException(status_code=400, detail="店铺等级不正确")
    for label, value in (("描述", body.dsr_desc), ("服务", body.dsr_service), ("物流", body.dsr_logistics)):
        if not (0 <= value <= 5):
            raise HTTPException(status_code=400, detail=f"DSR{label}评分需在 0-5 之间")
    expires = body.auth_expires_at.strip()
    if expires:
        try:
            _parse(expires)
        except ValueError:
            raise HTTPException(status_code=400, detail="授权到期时间格式不正确")
    return expires


def _mask_cookie(cookie: str) -> str:
    if not cookie:
        return ""
    if len(cookie) <= 12:
        return "****"
    return cookie[:6] + "****" + cookie[-6:]


def sync_store_row(db, row) -> dict:
    """抓取单个店铺数据并写入 store_daily_data，返回保存后的记录。"""
    metrics = fetch_store_daily(dict(row))
    data_date = metrics["date"]
    db.execute(
        """
        INSERT INTO store_daily_data (store_id, data_date, visitors, pv, sales, orders, conversion_rate, repeat_rate, old_buyer_cnt, repeat_sales, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(store_id, data_date) DO UPDATE SET
            visitors = excluded.visitors, pv = excluded.pv, sales = excluded.sales,
            orders = excluded.orders, conversion_rate = excluded.conversion_rate,
            repeat_rate = excluded.repeat_rate, old_buyer_cnt = excluded.old_buyer_cnt,
            repeat_sales = excluded.repeat_sales
        """,
        (
            row["id"],
            data_date,
            metrics["visitors"],
            metrics["pv"],
            metrics["sales"],
            metrics["orders"],
            metrics["conversion_rate"],
            metrics.get("repeat_rate", 0),
            metrics.get("old_buyer_cnt", 0),
            metrics.get("repeat_sales", 0),
            _fmt(_now()),
        ),
    )
    saved = db.execute(
        "SELECT * FROM store_daily_data WHERE store_id = ? AND data_date = ?",
        (row["id"], data_date),
    ).fetchone()
    return {
        "store_id": row["id"],
        "store_name": row["name"],
        "data_date": saved["data_date"],
        "visitors": saved["visitors"],
        "pv": saved["pv"],
        "sales": saved["sales"],
        "orders": saved["orders"],
        "conversion_rate": saved["conversion_rate"],
    }


def sync_all_stores(db, user=None) -> dict:
    """同步所有配置了生意参谋凭证的店铺，逐店容错。"""
    rows = db.execute("SELECT * FROM stores ORDER BY id ASC").fetchall()
    rows = [row for row in rows if has_profile(row["id"])]
    results = []
    for row in rows:
        try:
            item = sync_store_row(db, row)
            results.append(
                {"store_id": item["store_id"], "store_name": item["store_name"], "ok": True, "data_date": item["data_date"]}
            )
        except Exception as exc:  # noqa: BLE001
            results.append({"store_id": row["id"], "store_name": row["name"], "ok": False, "error": str(exc)})
    return {"results": results, "total": len(rows), "ok": sum(1 for r in results if r["ok"])}


@router.get("")
def list_stores(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    rows = _visible_rows(db.execute("SELECT * FROM stores ORDER BY id ASC").fetchall(), user)
    return {"items": [_payload(row) for row in rows]}


@router.post("")
def create_store(
    body: StoreIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    expires = _validate(body)
    if not expires:
        expires = _fmt(_now() + timedelta(days=90))
    now = _fmt(_now())
    cur = db.execute(
        """
        INSERT INTO stores (name, owner, category, level, location, dsr_desc, dsr_service, dsr_logistics, status, auth_expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (
            body.name.strip(),
            body.owner.strip(),
            body.category.strip(),
            body.level.strip(),
            body.location.strip(),
            body.dsr_desc,
            body.dsr_service,
            body.dsr_logistics,
            expires,
            now,
        ),
    )
    item = _payload(_get_store_or_404(db, cur.lastrowid))
    _log(db, user, "bind", item["name"], "绑定店铺")
    return {"item": item}


@router.put("/{store_id}")
def update_store(
    store_id: int,
    body: StoreIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    target = _get_store_or_404(db, store_id)
    if not can_access_store(user, store_id):
        raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
    expires = _validate(body) or target["auth_expires_at"]
    db.execute(
        """
        UPDATE stores
        SET name=?, owner=?, category=?, level=?, location=?, dsr_desc=?, dsr_service=?, dsr_logistics=?, auth_expires_at=?
        WHERE id=?
        """,
        (
            body.name.strip(),
            body.owner.strip(),
            body.category.strip(),
            body.level.strip(),
            body.location.strip(),
            body.dsr_desc,
            body.dsr_service,
            body.dsr_logistics,
            expires,
            store_id,
        ),
    )
    item = _payload(_get_store_or_404(db, store_id))
    _log(db, user, "edit", item["name"], "编辑店铺信息")
    return {"item": item}


@router.delete("/{store_id}")
def delete_store(
    store_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    target = _get_store_or_404(db, store_id)
    if not can_access_store(user, store_id):
        raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
    db.execute("UPDATE users SET current_store_id = NULL WHERE current_store_id = ?", (store_id,))
    db.execute("DELETE FROM stores WHERE id = ?", (store_id,))
    _log(db, user, "unbind", target["name"], "解绑店铺")
    return {"ok": True}


@router.post("/{store_id}/auth")
def refresh_auth(
    store_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    target = _get_store_or_404(db, store_id)
    if not can_access_store(user, store_id):
        raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
    db.execute(
        "UPDATE stores SET status = 'active', auth_expires_at = ? WHERE id = ?",
        (_fmt(_now() + timedelta(days=90)), store_id),
    )
    item = _payload(_get_store_or_404(db, store_id))
    _log(db, user, "refresh_auth", item["name"], "刷新授权（90 天）")
    return {"item": item}


@router.post("/{store_id}/status")
def set_status(
    store_id: int,
    body: StatusIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if body.status not in STATUSES:
        raise HTTPException(status_code=400, detail="状态只能是 active、auth_error 或 stopped")
    target = _get_store_or_404(db, store_id)
    if not can_access_store(user, store_id):
        raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
    db.execute("UPDATE stores SET status = ? WHERE id = ?", (body.status, store_id))
    label = {"active": "启用", "stopped": "停用", "auth_error": "标记授权异常"}[body.status]
    item = _payload(_get_store_or_404(db, store_id))
    _log(db, user, "status", item["name"], label)
    return {"item": item}


@router.put("/{store_id}/sycm")
def update_store_sycm(
    store_id: int,
    body: SycmConfigIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    row = _get_store_or_404(db, store_id)
    username = body.username.strip() or row["sycm_username"]
    password = body.password.strip() or row["sycm_password"]
    cookie = body.cookie.strip() or row["sycm_cookie"]
    db.execute(
        "UPDATE stores SET sycm_username = ?, sycm_password = ?, sycm_cookie = ? WHERE id = ?",
        (username, password, cookie, store_id),
    )
    _log(db, user, "配置生意参谋", row["name"], "更新生意参谋凭证")
    return {"item": _payload(_get_store_or_404(db, store_id))}


@router.post("/{store_id}/sycm/test")
def test_store_sycm(
    store_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    row = _get_store_or_404(db, store_id)
    try:
        check_sycm_login(dict(row))
    except SycmError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/{store_id}/sycm/bind")
def bind_store_sycm(
    store_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """打开专用 Chrome 等待用户登录该店铺生意参谋，成功后保存登录档案。"""
    row = _get_store_or_404(db, store_id)
    if not can_access_store(user, store_id):
        raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
    try:
        result = bind_login(dict(row))
    except SycmError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _log(db, user, "sycm_bind", row["name"], "打开浏览器绑定生意参谋登录")
    return {"ok": True, "store_id": row["id"], "metrics": result.get("metrics")}


@router.post("/{store_id}/sync")
def sync_store(
    store_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    row = _get_store_or_404(db, store_id)
    try:
        item = sync_store_row(db, row)
    except SycmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _log(db, user, "同步生意参谋", row["name"], f"同步 {item['data_date']}")
    return {"item": item}


@router.post("/sync-all")
def sync_all(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    result = sync_all_stores(db, user)
    _log(db, user, "同步生意参谋", "全部店铺", f"同步完成：成功 {result['ok']} / 共 {result['total']}")
    return result


@router.post("/sync-hourly")
def sync_hourly(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """同步生意参谋今日/昨日分时数据到 store_hourly_data。"""
    from backend.app.core.sycm import SycmError, fetch_hourly

    stores = [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY id").fetchall() if has_profile(r["id"])]
    results = []
    for store in stores:
        try:
            items = fetch_hourly(store)
            now = _fmt(_now())
            for it in items:
                db.execute(
                    "INSERT INTO store_hourly_data (store_id, data_date, hour, visitors, pv, sales, orders, buyers, conversion_rate, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(store_id, data_date, hour) DO UPDATE SET "
                    "visitors = excluded.visitors, pv = excluded.pv, sales = excluded.sales, "
                    "orders = excluded.orders, buyers = excluded.buyers, conversion_rate = excluded.conversion_rate",
                    (
                        store["id"],
                        it["date"],
                        it["hour"],
                        it["visitors"],
                        it["pv"],
                        it["sales"],
                        it["orders"],
                        it["buyers"],
                        it["conversion_rate"],
                        now,
                    ),
                )
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": True, "rows": len(items)})
        except SycmError as exc:
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": str(exc)})
    _log(db, user, "同步分时数据", "", f"成功 {sum(1 for r in results if r['ok'])} / {len(results)} 家")
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"])}


@router.post("/sync-items")
def sync_items(
    date: str = "",
    days: int = 1,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """同步商品销售排行到 store_item_daily：单日（date）或近 N 天（days，默认昨天起往前）。"""
    from datetime import date as date_cls
    from backend.app.core.sycm import SycmError, fetch_item_sales

    if not (1 <= days <= 30):
        days = 1
    today = date_cls.today()
    if date:
        dates = [date]
        try:
            date_cls.fromisoformat(date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="日期格式不正确（应为 YYYY-MM-DD）") from exc
    else:
        dates = [(today - timedelta(days=offset)).isoformat() for offset in range(1, days + 1)]
    stores = [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY id").fetchall() if has_profile(r["id"])]
    results = []
    for store in stores:
        total_rows = 0
        err = None
        for target in dates:
            try:
                items = fetch_item_sales(store, target)
                now = _fmt(_now())
                for it in items:
                    db.execute(
                        "INSERT INTO store_item_daily (store_id, item_id, item_title, image, data_date, sales, orders, buyers, visitors, pv, conversion_rate, add_cart, refund_amount, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(store_id, item_id, data_date) DO UPDATE SET "
                        "item_title = excluded.item_title, image = excluded.image, sales = excluded.sales, "
                        "orders = excluded.orders, buyers = excluded.buyers, visitors = excluded.visitors, "
                        "pv = excluded.pv, conversion_rate = excluded.conversion_rate, "
                        "add_cart = excluded.add_cart, refund_amount = excluded.refund_amount",
                        (
                            store["id"], it["item_id"], it["item_title"], it.get("image", ""), target,
                            it["sales"], it["orders"], it["buyers"], it.get("visitors", 0), it.get("pv", 0),
                            it.get("conversion_rate", 0), it.get("add_cart", 0), it.get("refund_amount", 0), now,
                        ),
                    )
                total_rows += len(items)
            except SycmError as exc:
                err = str(exc)
                break
        results.append({"store_id": store["id"], "store_name": store["name"], "ok": err is None, "rows": total_rows, "error": err})
    _log(db, user, "同步商品数据", "", f"{len(dates)} 天 成功 {sum(1 for r in results if r['ok'])} / {len(results)} 家")
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"]), "days": len(dates)}


@router.post("/sync-items-realtime")
def sync_items_realtime(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """同步今日实时商品排行到 store_item_realtime。"""
    from backend.app.core.sycm import SycmError, fetch_item_realtime

    stores = [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY id").fetchall() if has_profile(r["id"])]
    results = []
    for store in stores:
        try:
            items = fetch_item_realtime(store)
            now = _fmt(_now())
            for it in items:
                db.execute(
                    "INSERT INTO store_item_realtime (store_id, item_id, item_title, image, visitors, pv, buyers, orders, sales, conversion_rate, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(store_id, item_id) DO UPDATE SET "
                    "item_title = excluded.item_title, image = excluded.image, visitors = excluded.visitors, "
                    "pv = excluded.pv, buyers = excluded.buyers, orders = excluded.orders, "
                    "sales = excluded.sales, conversion_rate = excluded.conversion_rate, updated_at = excluded.updated_at",
                    (store["id"], it["item_id"], it["item_title"], it["image"], it["visitors"], it["pv"], it["buyers"], it["orders"], it["sales"], it["conversion_rate"], now),
                )
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": True, "rows": len(items)})
        except SycmError as exc:
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": str(exc)})
    _log(db, user, "同步实时商品", "", f"成功 {sum(1 for r in results if r['ok'])} / {len(results)} 家")
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"])}


@router.get("/current")
def get_current_store(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    row = db.execute(
        "SELECT s.* FROM stores s JOIN users u ON u.current_store_id = s.id WHERE u.id = ?",
        (user["id"],),
    ).fetchone()
    if row and not can_access_store(user, row["id"]):
        row = None
    return {"store": _payload(row) if row else None}


@router.post("/current")
def set_current_store(
    body: CurrentIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if body.store_id is not None:
        target = _get_store_or_404(db, body.store_id)
        if not can_access_store(user, body.store_id):
            raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
    db.execute("UPDATE users SET current_store_id = ? WHERE id = ?", (body.store_id, user["id"]))
    if body.store_id is not None:
        _log(db, user, "current", target["name"], "切换当前店铺")
    return {"ok": True}


@router.get("/alerts")
def get_alerts(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    items = [item for item in _compute_alerts(db) if can_access_store(user, item["store_id"])]
    return {"items": items, "inspected_at": _meta_get(db, "stores_last_inspect")}


@router.post("/inspect")
def inspect_stores(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    updated = run_inspect_once()
    alerts = _compute_alerts(db)
    _log(db, user, "inspect", "", f"巡检：更新 {updated} 家店铺，共 {len(alerts)} 条提醒")
    return {
        "ok": True,
        "inspected_at": _meta_get(db, "stores_last_inspect"),
        "updated": updated,
        "alerts_count": len(alerts),
    }


@router.get("/compare")
def compare_stores(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    today = date_cls.today()
    rows = _visible_rows(db.execute("SELECT * FROM stores ORDER BY id ASC").fetchall(), user)
    items = []
    for row in rows:
        items.append(
            {
                "store_id": row["id"],
                "name": row["name"],
                "display_status": _display_status(row),
                **_metrics_for_day(db, row["id"], today),
            }
        )
    return {"items": items}


@router.get("/{store_id}/metrics")
def store_metrics(
    store_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    row = _get_store_or_404(db, store_id)
    if not can_access_store(user, store_id):
        raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
    today = date_cls.today()
    trend = []
    for offset in range(13, -1, -1):
        day = today - timedelta(days=offset)
        trend.append({"date": day.isoformat(), **_metrics_for_day(db, store_id, day)})

    sales_7d = sum(_metrics_for_day(db, store_id, today - timedelta(days=offset))["sales"] for offset in range(7))
    orders_7d = sum(_metrics_for_day(db, store_id, today - timedelta(days=offset))["orders"] for offset in range(7))
    prev_sales_7d = sum(
        _metrics_for_day(db, store_id, today - timedelta(days=offset))["sales"] for offset in range(7, 14)
    )
    today_metrics = _metrics_for_day(db, store_id, today)
    change = (
        round((sales_7d - prev_sales_7d) / prev_sales_7d * 100, 1)
        if prev_sales_7d
        else 0.0
    )

    return {
        "store": _payload(row),
        "today": today_metrics,
        "summary": {
            "sales_7d": round(sales_7d, 2),
            "orders_7d": orders_7d,
            "avg_refund_rate": 0.0,
            "sales_change_7d": change,
        },
        "trend": trend,
    }


@router.get("/logs")
def list_logs(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    rows = db.execute(
        "SELECT * FROM op_logs WHERE module = 'stores' ORDER BY id DESC LIMIT 100"
    ).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "username": row["username"],
                "action": row["action"],
                "target_name": row["target_name"],
                "detail": row["detail"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    }
