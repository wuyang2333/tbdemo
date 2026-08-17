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
    PROFILE_MISSING_MSG,
    SycmError,
    bind_login,
    bind_login_from_browser,
    bind_login_from_cookies,
    check_sycm_login,
    fetch_store_daily,
    has_profile,
)

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(value: datetime) -> str:
    return value.isoformat()


def _display_status(row) -> str:
    return row["status"] or "active"


def _payload(row, db) -> dict:
    store_id = row["id"]
    configured = has_profile(store_id)
    if configured:
        sycm_status = _meta_get(db, f"store_{store_id}_sycm_status") or "unknown"
    else:
        sycm_status = "not_configured"
    return {
        "id": store_id,
        "name": row["name"],
        "status": row["status"],
        "display_status": _display_status(row),
        "created_at": row["created_at"],
        "sycm_configured": configured,
        "last_sync_at": _meta_get(db, f"store_{store_id}_last_sync"),
        "sycm_status": sycm_status,
        "sycm_error": _meta_get(db, f"store_{store_id}_sycm_error"),
        "sycm_checked_at": _meta_get(db, f"store_{store_id}_sycm_checked_at"),
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


def run_inspect_once() -> int:
    """巡检一次：校验各店铺生意参谋登录态，并更新巡检时间。返回状态更新的店铺数。"""
    from backend.app.core.db import connect_db
    from backend.app.core.sycm import SycmError, check_sycm_login

    conn = connect_db()
    try:
        rows = conn.execute("SELECT * FROM stores").fetchall()
        updated = 0
        for row in rows:
            # 校验生意参谋登录态（仅已配置档案的店铺，单店容错，失败不影响巡检）
            if has_profile(row["id"]):
                try:
                    check_sycm_login(dict(row))
                    _meta_set(conn, f"store_{row['id']}_sycm_status", "ok")
                    _meta_set(conn, f"store_{row['id']}_sycm_error", "")
                except SycmError as exc:
                    _meta_set(conn, f"store_{row['id']}_sycm_status", "error")
                    _meta_set(conn, f"store_{row['id']}_sycm_error", str(exc)[:300])
                _meta_set(conn, f"store_{row['id']}_sycm_checked_at", _fmt(_now()))
        _meta_set(conn, "stores_last_inspect", _fmt(_now()))
        conn.commit()
        return updated
    finally:
        conn.close()


class StoreIn(BaseModel):
    name: str


class CurrentIn(BaseModel):
    store_id: int | None = None


class SycmConfigIn(BaseModel):
    username: str = ""
    password: str = ""
    cookie: str = ""


class BindCookiesIn(BaseModel):
    cookies: str = ""


def _get_store_or_404(db, store_id: int):
    row = db.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="店铺不存在")
    return row


def _validate(body: StoreIn) -> None:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="店铺名称不能为空")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="店铺名称不能超过 50 个字符")


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
    _meta_set(db, f"store_{row['id']}_last_sync", _fmt(_now()))
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
    """同步所有店铺，未配置生意参谋档案的店铺显式记录失败原因，逐店容错。"""
    rows = db.execute("SELECT * FROM stores ORDER BY id ASC").fetchall()
    results = []
    for row in rows:
        if not has_profile(row["id"]):
            results.append({"store_id": row["id"], "store_name": row["name"], "ok": False, "error": PROFILE_MISSING_MSG})
            continue
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
    return {"items": [_payload(row, db) for row in rows]}


@router.post("")
def create_store(
    body: StoreIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    _validate(body)
    now = _fmt(_now())
    cur = db.execute(
        """
        INSERT INTO stores (name, status, created_at)
        VALUES (?, 'active', ?)
        """,
        (
            body.name.strip(),
            now,
        ),
    )
    item = _payload(_get_store_or_404(db, cur.lastrowid), db)
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
    _validate(body)
    db.execute(
        """
        UPDATE stores
        SET name=?
        WHERE id=?
        """,
        (
            body.name.strip(),
            store_id,
        ),
    )
    item = _payload(_get_store_or_404(db, store_id), db)
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
    # 清理该店铺的 meta 残留（同步时间/登录状态），避免占位店删除后留垃圾
    for key in (
        f"store_{store_id}_last_sync",
        f"store_{store_id}_sycm_status",
        f"store_{store_id}_sycm_error",
        f"store_{store_id}_sycm_checked_at",
    ):
        db.execute("DELETE FROM meta WHERE key = ?", (key,))
    _log(db, user, "unbind", target["name"], "解绑店铺")
    return {"ok": True}


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
    return {"item": _payload(_get_store_or_404(db, store_id), db)}


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
        _meta_set(db, f"store_{store_id}_sycm_status", "error")
        _meta_set(db, f"store_{store_id}_sycm_error", str(exc)[:300])
        _meta_set(db, f"store_{store_id}_sycm_checked_at", _fmt(_now()))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _meta_set(db, f"store_{store_id}_sycm_status", "ok")
    _meta_set(db, f"store_{store_id}_sycm_error", "")
    _meta_set(db, f"store_{store_id}_sycm_checked_at", _fmt(_now()))
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
        # 登录失败/取消：若该店铺尚无登录档案（=绑定流程中创建的占位店），自动删除，
        # 避免前端未关弹窗/请求中断时残留"幽灵店铺"
        if not has_profile(store_id):
            db.execute("UPDATE users SET current_store_id = NULL WHERE current_store_id = ?", (store_id,))
            db.execute("DELETE FROM stores WHERE id = ?", (store_id,))
            db.commit()  # get_db 在异常时不会自动 commit，需显式提交
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _log(db, user, "sycm_bind", row["name"], "打开浏览器绑定生意参谋登录")
    _meta_set(db, f"store_{store_id}_sycm_status", "ok")
    _meta_set(db, f"store_{store_id}_sycm_error", "")
    _meta_set(db, f"store_{store_id}_sycm_checked_at", _fmt(_now()))
    return {"ok": True, "store_id": row["id"], "metrics": result.get("metrics")}


@router.post("/{store_id}/sycm/bind-from-browser")
def bind_store_sycm_from_browser(
    store_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """不弹窗：读取当前 Chrome/Edge 已登录的生意参谋登录态并保存档案。"""
    row = _get_store_or_404(db, store_id)
    if not can_access_store(user, store_id):
        raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
    try:
        result = bind_login_from_browser(dict(row))
    except SycmError as exc:
        if not has_profile(store_id):
            db.execute("UPDATE users SET current_store_id = NULL WHERE current_store_id = ?", (store_id,))
            db.execute("DELETE FROM stores WHERE id = ?", (store_id,))
            db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _log(db, user, "sycm_bind_browser", row["name"], "从当前浏览器读取生意参谋登录态")
    _meta_set(db, f"store_{store_id}_sycm_status", "ok")
    _meta_set(db, f"store_{store_id}_sycm_error", "")
    _meta_set(db, f"store_{store_id}_sycm_checked_at", _fmt(_now()))
    return {"ok": True, "store_id": row["id"], "metrics": result.get("metrics")}


@router.post("/{store_id}/sycm/bind-from-cookies")
def bind_store_sycm_from_cookies(
    store_id: int,
    body: BindCookiesIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """不弹窗：粘贴登录态 cookie 保存档案。"""
    row = _get_store_or_404(db, store_id)
    if not can_access_store(user, store_id):
        raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
    text = (body.cookies or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="请先复制登录态再粘贴")
    try:
        result = bind_login_from_cookies(dict(row), text)
    except SycmError as exc:
        if not has_profile(store_id):
            db.execute("UPDATE users SET current_store_id = NULL WHERE current_store_id = ?", (store_id,))
            db.execute("DELETE FROM stores WHERE id = ?", (store_id,))
            db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _log(db, user, "sycm_bind_cookies", row["name"], "粘贴登录态绑定生意参谋")
    _meta_set(db, f"store_{store_id}_sycm_status", "ok")
    _meta_set(db, f"store_{store_id}_sycm_error", "")
    _meta_set(db, f"store_{store_id}_sycm_checked_at", _fmt(_now()))
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


@router.post("/sync-history")
def sync_history(
    days: int = 30,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """补拉最近 N 天（不含今天）的店铺每日数据到 store_daily_data。"""
    if not (1 <= days <= 90):
        days = 30
    today = date_cls.today()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(1, days + 1)]
    stores = [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY id").fetchall()]
    results = []
    for store in stores:
        if not has_profile(store["id"]):
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "rows": 0, "error": PROFILE_MISSING_MSG})
            continue
        total = 0
        err = None
        for target in dates:
            try:
                metrics = fetch_store_daily(store, target)
                db.execute(
                    "INSERT INTO store_daily_data (store_id, data_date, visitors, pv, sales, orders, conversion_rate, repeat_rate, old_buyer_cnt, repeat_sales, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(store_id, data_date) DO UPDATE SET "
                    "visitors = excluded.visitors, pv = excluded.pv, sales = excluded.sales, orders = excluded.orders, "
                    "conversion_rate = excluded.conversion_rate, repeat_rate = excluded.repeat_rate, "
                    "old_buyer_cnt = excluded.old_buyer_cnt, repeat_sales = excluded.repeat_sales",
                    (
                        store["id"], target, metrics["visitors"], metrics["pv"], metrics["sales"],
                        metrics["orders"], metrics["conversion_rate"], metrics.get("repeat_rate", 0),
                        metrics.get("old_buyer_cnt", 0), metrics.get("repeat_sales", 0), _fmt(_now()),
                    ),
                )
                total += 1
            except SycmError as exc:
                err = str(exc)
                break
        results.append({"store_id": store["id"], "store_name": store["name"], "ok": err is None, "rows": total, "error": err})
    _log(db, user, "补拉历史数据", "全部店铺", f"近 {days} 天 成功 {sum(1 for r in results if r['ok'])} / {len(results)} 家")
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"]), "days": len(dates)}


def sync_hourly_all(db) -> dict:
    """同步生意参谋今日/昨日分时数据到 store_hourly_data（后台定时直接调用，勿加路由装饰器）。"""
    from backend.app.core.sycm import SycmError, fetch_hourly

    stores = [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY id").fetchall()]
    results = []
    for store in stores:
        if not has_profile(store["id"]):
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": PROFILE_MISSING_MSG})
            continue
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
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"])}


@router.post("/sync-hourly")
def sync_hourly(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """同步生意参谋今日/昨日分时数据到 store_hourly_data。"""
    result = sync_hourly_all(db)
    _log(db, user, "同步分时数据", "", f"成功 {result['ok']} / 共 {result['total']} 家")
    return result


def sync_items_daily_all(db, days: int = 7) -> dict:
    """同步近 N 天商品销售排行到 store_item_daily（经营日报 TOP 商品来源）。

    后台每日定时调用（勿加路由装饰器），单店容错。返回 {"results", "total", "ok", "days"}。
    """
    from datetime import date as date_cls
    from backend.app.core.sycm import SycmError, fetch_item_sales

    if not (1 <= days <= 30):
        days = 7
    today = date_cls.today()
    dates = [(today - timedelta(days=offset)).isoformat() for offset in range(1, days + 1)]
    stores = [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY id").fetchall()]
    results = []
    for store in stores:
        if not has_profile(store["id"]):
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "rows": 0, "error": PROFILE_MISSING_MSG})
            continue
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
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"]), "days": len(dates)}


@router.post("/sync-items")
def sync_items(
    date: str = "",
    days: int = 1,
    start: str = "",
    end: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """同步商品销售排行到 store_item_daily：单日（date）/ 近 N 天（days）/ 自定义区间（start~end）。"""
    from datetime import date as date_cls
    from backend.app.core.sycm import SycmError, fetch_item_sales

    if not (1 <= days <= 30):
        days = 1
    today = date_cls.today()
    if start and end:
        try:
            s = date_cls.fromisoformat(start)
            e = date_cls.fromisoformat(end)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="日期格式不正确（应为 YYYY-MM-DD）") from exc
        if s > e:
            s, e = e, s
        dates = []
        cur = s
        while cur <= e:
            dates.append(cur.isoformat())
            cur += timedelta(days=1)
    elif date:
        dates = [date]
        try:
            date_cls.fromisoformat(date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="日期格式不正确（应为 YYYY-MM-DD）") from exc
    else:
        dates = [(today - timedelta(days=offset)).isoformat() for offset in range(1, days + 1)]
    stores = [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY id").fetchall()]
    results = []
    for store in stores:
        if not has_profile(store["id"]):
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "rows": 0, "error": PROFILE_MISSING_MSG})
            continue
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


def sync_items_realtime_all(db) -> dict:
    """同步今日实时商品排行到 store_item_realtime（后台定时直接调用，勿加路由装饰器）。"""
    from backend.app.core.sycm import SycmError, fetch_item_realtime

    stores = [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY id").fetchall()]
    results = []
    for store in stores:
        if not has_profile(store["id"]):
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": PROFILE_MISSING_MSG})
            continue
        try:
            items = fetch_item_realtime(store)
            now = _fmt(_now())
            for it in items:
                db.execute(
                    "INSERT INTO store_item_realtime (store_id, item_id, item_title, image, visitors, pv, buyers, orders, sales, conversion_rate, add_cart, refund_amount, visitors_cycle, pv_cycle, buyers_cycle, orders_cycle, sales_cycle, conversion_cycle, add_cart_cycle, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(store_id, item_id) DO UPDATE SET "
                    "item_title = excluded.item_title, image = excluded.image, visitors = excluded.visitors, "
                    "pv = excluded.pv, buyers = excluded.buyers, orders = excluded.orders, "
                    "sales = excluded.sales, conversion_rate = excluded.conversion_rate, "
                    "add_cart = excluded.add_cart, refund_amount = excluded.refund_amount, "
                    "visitors_cycle = excluded.visitors_cycle, pv_cycle = excluded.pv_cycle, "
                    "buyers_cycle = excluded.buyers_cycle, orders_cycle = excluded.orders_cycle, "
                    "sales_cycle = excluded.sales_cycle, conversion_cycle = excluded.conversion_cycle, "
                    "add_cart_cycle = excluded.add_cart_cycle, updated_at = excluded.updated_at",
                    (store["id"], it["item_id"], it["item_title"], it.get("image", ""), it["visitors"], it["pv"], it["buyers"], it["orders"], it["sales"], it["conversion_rate"], it.get("add_cart", 0), it.get("refund_amount", 0), it.get("visitors_cycle", 0), it.get("pv_cycle", 0), it.get("buyers_cycle", 0), it.get("orders_cycle", 0), it.get("sales_cycle", 0), it.get("conversion_cycle", 0), it.get("add_cart_cycle", 0), now),
                )
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": True, "rows": len(items)})
        except SycmError as exc:
            results.append({"store_id": store["id"], "store_name": store["name"], "ok": False, "error": str(exc)})
    return {"results": results, "total": len(results), "ok": sum(1 for r in results if r["ok"])}


@router.post("/sync-items-realtime")
def sync_items_realtime(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """同步今日实时商品排行到 store_item_realtime。"""
    result = sync_items_realtime_all(db)
    _log(db, user, "同步实时商品", "", f"成功 {result['ok']} / 共 {result['total']} 家")
    return result


@router.get("/current")
def get_current_store(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    row = db.execute(
        "SELECT s.* FROM stores s JOIN users u ON u.current_store_id = s.id WHERE u.id = ?",
        (user["id"],),
    ).fetchone()
    if row and not can_access_store(user, row["id"]):
        row = None
    return {"store": _payload(row, db) if row else None}


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
