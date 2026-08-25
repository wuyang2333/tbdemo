from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.api.auth import get_current_user, visible_store_ids
from backend.app.core import loops
from backend.app.core.db import get_db
from backend.app.core.sycm import has_profile

router = APIRouter()


ALLOWED_WIDGETS = {"actions", "kpis", "stores", "shortcuts", "system", "notice", "tasks", "changelog"}
DEFAULT_WIDGETS = ["actions", "kpis", "shortcuts", "system", "notice", "tasks", "changelog"]


class DashboardConfigIn(BaseModel):
    widgets: list[str]


class DashboardTodoSnoozeIn(BaseModel):
    minutes: int = Field(default=60, ge=5, le=1440)


def _ensure_todo_snoozes(db) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_todo_snoozes (
            user_id INTEGER NOT NULL,
            todo_key TEXT NOT NULL,
            snoozed_until TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, todo_key)
        )
        """
    )


def _module_allowed(user: dict, module_id: str) -> bool:
    if user["role"] in ("admin", "super_admin"):
        return True
    allowed = user.get("allowed_modules")
    return allowed is None or module_id in allowed


def _todo_store_rows(db, user: dict, store_id: int | None) -> list[dict]:
    visible = visible_store_ids(user)
    if store_id is not None:
        if visible is not None and store_id not in visible:
            raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
        row = db.execute("SELECT id, name, status FROM stores WHERE id = ?", (store_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="店铺不存在")
        return [dict(row)]
    rows = db.execute("SELECT id, name, status FROM stores ORDER BY id").fetchall()
    if visible is None:
        return [dict(row) for row in rows]
    return [dict(row) for row in rows if row["id"] in visible]


def _todo_item(
    *,
    key: str,
    module: str,
    category: str,
    severity: str,
    title: str,
    description: str,
    count: int,
    route: str = "",
    external_url: str = "",
    retry_task: str = "",
    store: dict | None = None,
    updated_at: str | None = None,
) -> dict:
    return {
        "key": key,
        "module": module,
        "category": category,
        "severity": severity,
        "title": title,
        "description": description,
        "count": count,
        "route": route,
        "external_url": external_url,
        "retryable": bool(retry_task),
        "retry_task": retry_task,
        "store_id": store["id"] if store else None,
        "store_name": store["name"] if store else "",
        "updated_at": updated_at,
    }


@router.get("/todos")
def dashboard_todos(
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """统一今日待办：直接聚合源业务状态，不复制任务完成状态。"""
    _ensure_todo_snoozes(db)
    stores = _todo_store_rows(db, user, store_id)
    items: list[dict] = []

    if _module_allowed(user, "gifts"):
        remark_meta = {
            "order_not_found": ("warning", "订单未查到", "每 3 分钟自动重试，也可核对订单号或旺旺号"),
            "awaiting_payment": ("warning", "订单待付款", "买家付款后系统会再次检查并插旗备注"),
            "remark_failed": ("critical", "千牛备注失败", "请检查千牛登录状态或前往礼品单重试"),
            "order_closed": ("critical", "订单已关闭", "已关闭订单不会插旗备注，请人工核对"),
        }
        for store in stores:
            rows = db.execute(
                """
                SELECT remark_status, COUNT(*) AS count,
                       MAX(COALESCE(remark_attempted_at, created_at)) AS updated_at
                FROM gifts
                WHERE store_id = ? AND remark_status IN ('order_not_found','awaiting_payment','remark_failed','order_closed')
                GROUP BY remark_status
                """,
                (store["id"],),
            ).fetchall()
            for row in rows:
                severity, label, description = remark_meta[row["remark_status"]]
                items.append(_todo_item(
                    key=f"gifts:remark:{row['remark_status']}:{store['id']}", module="gifts", category="礼品单",
                    severity=severity, title=f"{row['count']} 笔{label}", description=description,
                    count=row["count"], route=f"/gifts?remark_status={row['remark_status']}&store_id={store['id']}",
                    store=store, updated_at=row["updated_at"],
                ))
            sync_row = db.execute(
                """
                SELECT COUNT(*) AS count, MAX(COALESCE(tencent_synced_at, created_at)) AS updated_at
                FROM gifts WHERE store_id = ? AND TRIM(tencent_sync_error) != ''
                """,
                (store["id"],),
            ).fetchone()
            if sync_row["count"]:
                items.append(_todo_item(
                    key=f"gifts:tencent_sync:{store['id']}", module="gifts", category="礼品单",
                    severity="critical", title=f"{sync_row['count']} 笔礼品单同步失败",
                    description="腾讯文档未成功接收最新内容，请检查同步状态",
                    count=sync_row["count"], route=f"/gifts?sync_status=error&store_id={store['id']}", store=store,
                    updated_at=sync_row["updated_at"],
                ))

        if user["role"] in ("admin", "super_admin"):
            config_row = db.execute("SELECT value FROM meta WHERE key = 'tencent_docs_gifts_config'").fetchone()
            try:
                config = json.loads(config_row["value"] or "{}") if config_row else {}
            except (TypeError, ValueError):
                config = {}
            if config.get("last_error"):
                items.append(_todo_item(
                    key="gifts:tencent_global", module="gifts", category="礼品单", severity="critical",
                    title="腾讯文档同步异常", description=str(config["last_error"])[:160], count=1,
                    route="/settings", updated_at=config.get("last_sync_at"),
                ))

    if _module_allowed(user, "customers"):
        for store in stores:
            review_sources = [
                (
                    "alert", "critical", "待处理评价预警",
                    "SELECT COUNT(*) AS count, MAX(created_at) AS updated_at FROM review_alerts WHERE store_id = ? AND status = 'open'",
                    f"/customers?sentiment=negative&process_status=pending&store_id={store['id']}",
                ),
                (
                    "draft", "warning", "条评价回复待审核",
                    "SELECT COUNT(*) AS count, MAX(updated_at) AS updated_at FROM product_reviews WHERE store_id = ? AND reply_status = 'draft'",
                    f"/customers?reply_status=draft&store_id={store['id']}",
                ),
                (
                    "failed", "critical", "条评价回复发布失败",
                    "SELECT COUNT(*) AS count, MAX(updated_at) AS updated_at FROM product_reviews WHERE store_id = ? AND reply_status = 'failed'",
                    f"/customers?reply_status=failed&store_id={store['id']}",
                ),
            ]
            for source, severity, label, sql, route in review_sources:
                row = db.execute(sql, (store["id"],)).fetchone()
                if not row["count"]:
                    continue
                title = f"{row['count']} 个{label}" if source == "alert" else f"{row['count']} {label}"
                items.append(_todo_item(
                    key=f"customers:{source}:{store['id']}", module="customers", category="评价",
                    severity=severity, title=title,
                    description="进入评价管理查看原文、处理记录和回复状态",
                    count=row["count"], route=route, store=store, updated_at=row["updated_at"],
                ))

    if _module_allowed(user, "promotions"):
        from backend.app.api.promotions.data import promo_alerts

        for store in stores:
            result = promo_alerts(store_id=store["id"], user=user, db=db)
            if result["count"]:
                first = result["items"][0]["message"] if result["items"] else "存在推广经营异常"
                has_error = any(item["level"] == "error" for item in result["items"])
                items.append(_todo_item(
                    key=f"promotions:alerts:{store['id']}", module="promotions", category="推广",
                    severity="critical" if has_error else "warning",
                    title=f"{result['count']} 项推广预警", description=first,
                    count=result["count"], route=f"/promotions/plans?todo=alerts&store_id={store['id']}", store=store,
                ))

    if _module_allowed(user, "stores"):
        for store in stores:
            if store["status"] != "active":
                continue
            status_row = db.execute(
                "SELECT key, value FROM meta WHERE key IN (?, ?, ?)",
                (
                    f"store_{store['id']}_sycm_status",
                    f"store_{store['id']}_sycm_error",
                    f"store_{store['id']}_sycm_checked_at",
                ),
            ).fetchall()
            meta = {row["key"]: row["value"] for row in status_row}
            status = meta.get(f"store_{store['id']}_sycm_status") or "unknown"
            error = meta.get(f"store_{store['id']}_sycm_error") or ""
            checked_at = meta.get(f"store_{store['id']}_sycm_checked_at")
            if not has_profile(store["id"]):
                items.append(_todo_item(
                    key=f"stores:not_configured:{store['id']}", module="stores", category="店铺",
                    severity="critical", title="店铺尚未绑定登录态",
                    description="绑定生意参谋登录后才能自动同步经营数据",
                    count=1, route="/stores?login_status=error", store=store, updated_at=checked_at,
                ))
            elif status == "error" or error:
                items.append(_todo_item(
                    key=f"stores:login_error:{store['id']}", module="stores", category="店铺",
                    severity="critical", title="店铺登录状态异常",
                    description=(error or "登录验证失败，请重新验证")[:160],
                    count=1, route="/stores?login_status=error", store=store, updated_at=checked_at,
                ))

    if _module_allowed(user, "tasks"):
        task_labels = {"realtime_sync": "经营数据同步", "promo_daily": "推广数据补录", "inspect": "系统巡检"}
        retryable_tasks = {"realtime_sync", "promo_daily", "inspect"}
        for status in loops.get_all_status():
            name = status["name"]
            if name == "product_catalog_sync" or status["error_count"] <= 0:
                continue
            items.append(_todo_item(
                key=f"tasks:error:{name}", module="tasks", category="系统", severity="critical",
                title=f"{task_labels.get(name, name)}连续失败 {status['error_count']} 次",
                description=status.get("last_error") or "后台任务执行异常",
                count=status["error_count"], route=f"/tasks?task={name}&status=error",
                retry_task=name if name in retryable_tasks else "", updated_at=status.get("last_run"),
            ))

    if _module_allowed(user, "gifts"):
        for store in stores:
            row = db.execute(
                "SELECT pending_shipments, updated_at FROM store_operational_status WHERE store_id = ?",
                (store["id"],),
            ).fetchone()
            if row and row["pending_shipments"] > 0:
                items.append(_todo_item(
                    key=f"fulfillment:pending:{store['id']}", module="gifts", category="订单",
                    severity="warning", title=f"{row['pending_shipments']} 笔订单待发货",
                    description="前往千牛已卖出宝贝处理发货",
                    count=row["pending_shipments"],
                    external_url="https://trade.taobao.com/trade/itemlist/list_sold_items.htm",
                    store=store, updated_at=row["updated_at"],
                ))

    now = datetime.now().astimezone()
    snoozed_rows = db.execute(
        "SELECT todo_key, snoozed_until FROM dashboard_todo_snoozes WHERE user_id = ?",
        (user["id"],),
    ).fetchall()
    snoozed = {row["todo_key"]: row["snoozed_until"] for row in snoozed_rows}
    for item in items:
        until = snoozed.get(item["key"])
        try:
            is_snoozed = bool(until and datetime.fromisoformat(until) > now)
        except (TypeError, ValueError):
            is_snoozed = False
        item["snoozed"] = is_snoozed
        item["snoozed_until"] = until if is_snoozed else None

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    items.sort(key=lambda item: (item["snoozed"], severity_order.get(item["severity"], 9), -item["count"], item["key"]))
    return {
        "items": items,
        "summary": {
            "urgent": sum(1 for item in items if item["severity"] == "critical" and not item["snoozed"]),
            "pending": sum(1 for item in items if not item["snoozed"]),
            "snoozed": sum(1 for item in items if item["snoozed"]),
        },
    }


@router.post("/todos/{todo_key:path}/snooze")
def snooze_dashboard_todo(
    todo_key: str,
    body: DashboardTodoSnoozeIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    _ensure_todo_snoozes(db)
    now = datetime.now().astimezone()
    snoozed_until = now + timedelta(minutes=body.minutes)
    db.execute(
        """
        INSERT INTO dashboard_todo_snoozes (user_id, todo_key, snoozed_until, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, todo_key) DO UPDATE SET
            snoozed_until = excluded.snoozed_until, updated_at = excluded.updated_at
        """,
        (user["id"], todo_key, snoozed_until.isoformat(), now.isoformat()),
    )
    return {"ok": True, "todo_key": todo_key, "snoozed_until": snoozed_until.isoformat()}


@router.get("/config")
def get_dashboard_config(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """读取当前账号的自定义看板配置（未配置时返回默认）。"""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_configs (
            user_id INTEGER PRIMARY KEY,
            config TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    row = db.execute(
        "SELECT config FROM dashboard_configs WHERE user_id = ?", (user["id"],)
    ).fetchone()
    if not row:
        return {"widgets": DEFAULT_WIDGETS, "default": True}
    try:
        widgets = json.loads(row["config"])
    except (ValueError, TypeError):
        widgets = []
    return {"widgets": widgets, "default": False}


@router.put("/config")
def save_dashboard_config(
    body: DashboardConfigIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """保存当前账号的自定义看板配置（只允许白名单内的组件）。"""
    widgets = [w for w in body.widgets if w in ALLOWED_WIDGETS]
    seen: set[str] = set()
    deduped: list[str] = []
    for w in widgets:
        if w not in seen:
            seen.add(w)
            deduped.append(w)
    now = date.today().isoformat() + "T00:00:00"
    db.execute(
        """
        INSERT INTO dashboard_configs (user_id, config, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET config = excluded.config, updated_at = excluded.updated_at
        """,
        (user["id"], json.dumps(deduped), now),
    )
    return {"ok": True, "widgets": deduped}


@router.get("")
def overview(
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """总览：从真实数据表聚合核心指标（SaaS：按账号可见店铺隔离）。"""
    visible = visible_store_ids(user)
    empty = {
        "store_count": 0,
        "product_count": 0,
        "today_orders": 0,
        "today_sales": 0,
        "today_visitors": 0,
        "pending_shipments": 0,
        "operational_updated_at": None,
        "operational_stale": True,
        "data_date": None,
        "message": "暂无店铺权限，请联系管理员分配店铺",
    }
    if visible is not None and not visible:
        return empty

    if store_id is not None:
        if visible is not None and store_id not in visible:
            raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
        exists = db.execute("SELECT 1 FROM stores WHERE id = ?", (store_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="店铺不存在")
        sf = f" AND store_id = {int(store_id)}"
        store_count = 1
    elif visible is not None:
        sf = " AND store_id IN (" + ",".join(str(i) for i in visible) + ")"
        store_count = len(visible)
    else:
        sf = ""
        store_count = db.execute("SELECT COUNT(*) AS c FROM stores").fetchone()["c"]
    # 只统计店铺列表里真实存在的店铺，避免残留数据混入
    sf += " AND store_id IN (SELECT id FROM stores)"

    # 经营指标以 store_daily_data 为准（数据最实时），商品数单独取商品明细表的最新日
    latest = db.execute(
        "SELECT MAX(data_date) AS d FROM store_daily_data WHERE 1=1" + sf
    ).fetchone()["d"]
    if not latest:
        empty["store_count"] = store_count
        empty["message"] = "暂无经营数据，请先在店铺管理同步数据"
        return empty

    row = db.execute(
        """
        SELECT
            COALESCE(SUM(sales), 0) AS sales,
            COALESCE(SUM(orders), 0) AS orders,
            COALESCE(SUM(visitors), 0) AS visitors
        FROM store_daily_data
        WHERE data_date = ?
        """
        + sf,
        (latest,),
    ).fetchone()

    yesterday = (date.fromisoformat(latest) - timedelta(days=1)).isoformat()

    # 较昨日采用「同时段对比」：取今日分时数据里最后一个有数据的整点，
    # 今日与昨日都只累计到该小时，避免今日还没同步完就与昨日全天对比的不公平。
    hour_rows = db.execute(
        """
        SELECT data_date, hour,
               COALESCE(SUM(visitors), 0) AS visitors,
               COALESCE(SUM(sales), 0) AS sales,
               COALESCE(SUM(orders), 0) AS orders
        FROM store_hourly_data
        WHERE data_date IN (?, ?)
        """
        + sf
        + " GROUP BY data_date, hour",
        (latest, yesterday),
    ).fetchall()
    today_hours: dict[str, dict] = {}
    yesterday_hours: dict[str, dict] = {}
    for r in hour_rows:
        target = today_hours if r["data_date"] == latest else yesterday_hours
        target[r["hour"]] = {
            "visitors": r["visitors"],
            "sales": r["sales"],
            "orders": r["orders"],
        }

    # 推广花费分时（用于真实 ROI 的同时段对比）
    promo_rows = db.execute(
        """
        SELECT data_date, hour,
               COALESCE(SUM(spend), 0) AS spend
        FROM promo_realtime
        WHERE data_date IN (?, ?)
        """
        + sf
        + " GROUP BY data_date, hour",
        (latest, yesterday),
    ).fetchall()
    today_spend_hours: dict[str, float] = {}
    yesterday_spend_hours: dict[str, float] = {}
    for r in promo_rows:
        target_sp = today_spend_hours if r["data_date"] == latest else yesterday_spend_hours
        target_sp[r["hour"]] = target_sp.get(r["hour"], 0.0) + (r["spend"] or 0)

    active_hours = [
        h for h, v in today_hours.items() if v["visitors"] or v["sales"] or v["orders"]
    ]
    if active_hours:
        upto = max(active_hours)

        def _segment(hours_map: dict[str, dict]) -> dict:
            agg = {"visitors": 0, "sales": 0.0, "orders": 0}
            for h, v in hours_map.items():
                if h <= upto:
                    agg["visitors"] += v["visitors"]
                    agg["sales"] += v["sales"]
                    agg["orders"] += v["orders"]
            agg["sales"] = round(agg["sales"], 2)
            return agg

        today_row = _segment(today_hours)
        yrow = _segment(yesterday_hours)

        def _spend_segment(hours_map: dict[str, float]) -> float:
            return round(sum(v for h, v in hours_map.items() if h <= upto), 2)

        today_spend = _spend_segment(today_spend_hours)
        yesterday_spend = _spend_segment(yesterday_spend_hours)
        hour_until = upto
        compare_mode = "同时段"
    else:
        # 无分时数据时回退为全天对比
        today_row = row
        yrow = db.execute(
            """
            SELECT
                COALESCE(SUM(sales), 0) AS sales,
                COALESCE(SUM(orders), 0) AS orders,
                COALESCE(SUM(visitors), 0) AS visitors
            FROM store_daily_data
            WHERE data_date = ?
            """
            + sf,
            (yesterday,),
        ).fetchone()

        def _daily_spend(d: str) -> float:
            r = db.execute(
                "SELECT COALESCE(SUM(spend), 0) AS spend FROM promo_daily_data WHERE data_date = ?" + sf,
                (d,),
            ).fetchone()
            return round(r["spend"] or 0, 2)

        today_spend = _daily_spend(latest)
        yesterday_spend = _daily_spend(yesterday)
        hour_until = None
        compare_mode = "全天"

    # 真实 ROI = 总成交 / 推广花费（推广花费为 0 时不展示）
    today_real_roi = round(today_row["sales"] / today_spend, 2) if today_spend else None
    yesterday_real_roi = round(yrow["sales"] / yesterday_spend, 2) if yesterday_spend else None

    # 近 14 天趋势（缺日补 0，保证图表连续）
    start = date.fromisoformat(latest) - timedelta(days=13)
    trend_rows = db.execute(
        """
        SELECT data_date,
               COALESCE(SUM(sales), 0) AS sales,
               COALESCE(SUM(orders), 0) AS orders,
               COALESCE(SUM(visitors), 0) AS visitors
        FROM store_daily_data
        WHERE data_date >= ?
        """
        + sf
        + " GROUP BY data_date ORDER BY data_date ASC",
        (start.isoformat(),),
    ).fetchall()
    trend_map = {r["data_date"]: r for r in trend_rows}
    trend = []
    for i in range(14):
        d = start + timedelta(days=i)
        ds = d.isoformat()
        r = trend_map.get(ds)
        trend.append(
            {
                "date": d.strftime("%m-%d"),
                "sales": round(r["sales"], 2) if r else 0,
                "orders": r["orders"] if r else 0,
                "visitors": r["visitors"] if r else 0,
            }
        )

    operational = db.execute(
        """
        SELECT COALESCE(SUM(pending_shipments), 0) AS pending_shipments,
               COALESCE(SUM(product_count), 0) AS product_count,
               MIN(updated_at) AS updated_at,
               COUNT(*) AS status_count
        FROM store_operational_status
        WHERE 1=1
        """
        + sf
    ).fetchone()
    operational_updated_at = operational["updated_at"]
    try:
        operational_age = datetime.now() - datetime.fromisoformat(operational_updated_at)
    except (TypeError, ValueError):
        operational_age = timedelta.max
    operational_stale = (
        operational["status_count"] < store_count
        or operational_age > timedelta(minutes=10)
    )
    return {
        "store_count": store_count,
        "product_count": operational["product_count"],
        "today_orders": today_row["orders"],
        "today_sales": today_row["sales"],
        "today_visitors": today_row["visitors"],
        "yesterday_orders": yrow["orders"],
        "yesterday_sales": yrow["sales"],
        "yesterday_visitors": yrow["visitors"],
        "today_real_roi": today_real_roi,
        "yesterday_real_roi": yesterday_real_roi,
        "pending_shipments": operational["pending_shipments"],
        "data_date": latest,
        "hour_until": hour_until,
        "compare_mode": compare_mode,
        "operational_updated_at": operational_updated_at,
        "operational_stale": operational_stale,
        "trend": trend,
        "message": f"真实数据（较昨日为{compare_mode}对比，截至 {latest} {hour_until or '全天'}）",
    }

