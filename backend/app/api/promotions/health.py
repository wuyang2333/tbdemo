"""推广数据可信度与同步健康状态。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends

from backend.app.api.auth import get_current_user, visible_store_ids
from backend.app.core.db import get_db


router = APIRouter()

SYNC_STATE_PREFIX = "promo_sync_state:"

DATASETS = {
    "realtime": {
        "name": "推广实时数据",
        "source": "万相台实时场景报表",
        "source_code": "alimama_scene_realtime",
        "stale_after_minutes": 90,
        "task": "realtime",
        "retry_path": "/api/promotions/sync",
        "retry_params": {"mode": "realtime"},
    },
    "daily": {
        "name": "推广按天数据",
        "source": "万相台场景日报",
        "source_code": "alimama_scene_daily",
        "stale_after_minutes": 36 * 60,
        "task": "daily",
        "retry_path": "/api/promotions/sync",
        "retry_params": {"mode": "7d"},
    },
    "plans": {
        "name": "推广计划数据",
        "source": "万相台计划快照与计划报表",
        "source_code": "alimama_campaign_report",
        "stale_after_minutes": 90,
        "task": "plans_realtime",
        "retry_path": "/api/promotions/sync-plans",
        "retry_params": {"mode": "realtime"},
    },
    "items": {
        "name": "商品级推广数据",
        "source": "万相台商品报表或计划归因兜底",
        "source_code": "alimama_item_or_plan_attribution",
        "stale_after_minutes": 90,
        "task": "items_realtime",
        "retry_path": "/api/promotions/sync-items",
        "retry_params": {"mode": "realtime"},
    },
}


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone()


def _meta_json(db, key: str) -> dict:
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if not row or not row["value"]:
        return {}
    try:
        value = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _scoped_sync_state(state: dict, user: dict, store_id: int | None) -> dict:
    """过滤同步明细，避免把无权店铺的失败原因暴露给当前账号。"""
    visible = visible_store_ids(user)
    stores = state.get("stores") if isinstance(state.get("stores"), dict) else {}
    allowed: set[int] | None = visible
    if store_id is not None:
        allowed = {store_id} if allowed is None else ({store_id} & allowed)
    scoped_stores = {
        key: value
        for key, value in stores.items()
        if isinstance(value, dict) and (allowed is None or value.get("store_id") in allowed)
    }
    if not scoped_stores:
        if stores:
            return {}
        return {key: value for key, value in state.items() if key not in {"stores", "failures"}}
    failures = [
        {"store_id": item.get("store_id"), "store_name": item.get("store_name") or "", "error": item.get("error") or "同步失败"}
        for item in scoped_stores.values()
        if item.get("status") == "failed"
    ]
    successes = [item for item in scoped_stores.values() if item.get("status") == "success"]
    status = "success" if not failures else "partial" if successes else "failed"
    result = dict(state)
    result.update({"status": status, "total": len(scoped_stores), "ok": len(successes), "failed": len(failures), "failures": failures, "stores": scoped_stores})
    return result


def record_sync_result(db, task: str, result: dict, *, source: str) -> dict:
    """持久化同步尝试；部分失败不会覆盖成功店铺的最近成功时间。"""
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    total = int(result.get("total") or 0)
    ok = int(result.get("ok") or 0)
    status = "success" if total > 0 and ok == total else "partial" if ok > 0 else "failed"
    previous = _meta_json(db, SYNC_STATE_PREFIX + task)
    stores = previous.get("stores") if isinstance(previous.get("stores"), dict) else {}
    failures: list[dict] = []
    for raw in result.get("results") or []:
        item = dict(raw)
        store_key = str(item.get("store_id") or "unknown")
        prior = stores.get(store_key) if isinstance(stores.get(store_key), dict) else {}
        store_state = {
            "store_id": item.get("store_id"),
            "store_name": item.get("store_name") or prior.get("store_name") or "",
            "status": "success" if item.get("ok") else "failed",
            "last_attempt_at": now,
            "last_success_at": now if item.get("ok") else prior.get("last_success_at"),
            "rows": item.get("rows", item.get("plans")),
            "source": item.get("source") or source,
            "error": "" if item.get("ok") else str(item.get("error") or "同步失败")[:300],
            "retryable": not bool(item.get("ok")),
        }
        stores[store_key] = store_state
        if not item.get("ok"):
            failures.append({"store_id": item.get("store_id"), "store_name": item.get("store_name") or "", "error": store_state["error"]})
    state = {
        "task": task,
        "source": source,
        "status": status,
        "last_attempt_at": now,
        "last_success_at": now if status == "success" else previous.get("last_success_at"),
        "last_any_success_at": now if ok > 0 else previous.get("last_any_success_at"),
        "last_partial_success_at": now if status == "partial" else previous.get("last_partial_success_at"),
        "total": total,
        "ok": ok,
        "failed": max(0, total - ok),
        "failures": failures[:20],
        "retryable": status != "success",
        "stores": stores,
    }
    db.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SYNC_STATE_PREFIX + task, json.dumps(state, ensure_ascii=False)),
    )
    return state


def _scope(user: dict, store_id: int | None, column: str = "store_id") -> tuple[str, list]:
    visible = visible_store_ids(user)
    parts: list[str] = []
    params: list = []
    if visible is not None:
        if not visible:
            parts.append("1=0")
        else:
            parts.append(f"{column} IN ({','.join('?' for _ in visible)})")
            params.extend(sorted(visible))
    if store_id is not None:
        parts.append(f"{column} = ?")
        params.append(store_id)
    return (" WHERE " + " AND ".join(parts) if parts else ""), params


def _retry_url(config: dict, store_id: int | None) -> str:
    params = dict(config["retry_params"])
    if store_id is not None:
        params["store_id"] = store_id
    return f"{config['retry_path']}?{urlencode(params)}"


def _freshness(reference_at: str | None, stale_after_minutes: int, now: datetime) -> tuple[str, float | None]:
    reference = _parse_datetime(reference_at)
    if reference is None:
        return "missing", None
    age_minutes = max(0.0, (now - reference).total_seconds() / 60)
    return ("stale" if age_minutes > stale_after_minutes else "fresh"), round(age_minutes, 1)


def _business_data_at(dataset: str, row) -> str | None:
    """把平台业务日期/小时转换为业务数据截至时间，不使用数据库写入时间冒充。"""
    if not row:
        return None
    latest_date = row["latest_data_date"] if "latest_data_date" in row.keys() else None
    if not latest_date:
        return None
    try:
        if dataset == "realtime":
            hour = str(row["latest_hour"] or "00:00") if "latest_hour" in row.keys() else "00:00"
            return datetime.fromisoformat(f"{latest_date}T{hour[:5]}:00").astimezone().isoformat(timespec="seconds")
        return datetime.fromisoformat(f"{latest_date}T23:59:59").astimezone().isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def build_dataset_metadata(
    db,
    dataset: str,
    user: dict,
    store_id: int | None = None,
    *,
    expected_points: int | None = None,
    actual_points: int | None = None,
) -> dict:
    """返回单一数据集的统一来源、更新时间、完整性和同步状态。"""
    config = DATASETS[dataset]
    where, params = _scope(user, store_id)
    sources: list[str] = []
    latest_data_date: str | None = None
    if dataset == "realtime":
        row = db.execute(
            "SELECT MAX(created_at) AS storage_updated_at, COUNT(*) AS row_count FROM promo_realtime" + where,
            params,
        ).fetchone()
        business_row = db.execute(
            "SELECT data_date AS latest_data_date, hour AS latest_hour FROM promo_realtime" + where + " ORDER BY data_date DESC, hour DESC LIMIT 1",
            params,
        ).fetchone()
    elif dataset == "daily":
        row = db.execute(
            "SELECT MAX(created_at) AS storage_updated_at, MAX(data_date) AS latest_data_date, COUNT(*) AS row_count "
            "FROM promo_daily_data" + where,
            params,
        ).fetchone()
        business_row = row
    elif dataset == "plans":
        row = db.execute("SELECT MAX(updated_at) AS storage_updated_at, COUNT(*) AS row_count FROM promo_plans" + where, params).fetchone()
        business_row = None
    else:
        row = db.execute("SELECT MAX(updated_at) AS storage_updated_at, COUNT(*) AS row_count FROM promo_item_stats" + where, params).fetchone()
        business_row = None
        source_rows = db.execute("SELECT DISTINCT source FROM promo_item_stats" + where, params).fetchall()
        sources = sorted({str(item["source"] or "unknown") for item in source_rows})
    storage_updated_at = row["storage_updated_at"] if row else None
    if business_row and "latest_data_date" in business_row.keys():
        latest_data_date = business_row["latest_data_date"]
    row_count = int((row["row_count"] if row else 0) or 0)
    if actual_points is None:
        actual_points = row_count
    if expected_points is None:
        expected_points = actual_points
    completeness_rate = round(min(1.0, actual_points / expected_points) * 100, 1) if expected_points else (100.0 if actual_points else 0.0)
    completeness = "complete" if completeness_rate >= 99.9 else "partial" if actual_points else "missing"
    sync_state = _scoped_sync_state(_meta_json(db, SYNC_STATE_PREFIX + config["task"]), user, store_id)
    business_data_at = _business_data_at(dataset, business_row)
    last_sync_at = sync_state.get("last_attempt_at")
    freshness_basis = "business_data_at" if business_data_at else "last_sync_at"
    freshness_reference_at = business_data_at or last_sync_at
    now = datetime.now().astimezone()
    freshness, age_minutes = _freshness(freshness_reference_at, config["stale_after_minutes"], now)
    return {
        "dataset": dataset,
        "name": config["name"],
        "source": config["source"],
        "source_code": config["source_code"],
        "source_variants": sources,
        "business_data_at": business_data_at,
        "last_sync_at": last_sync_at,
        "storage_updated_at": storage_updated_at,
        # 兼容旧客户端；新界面必须使用 business_data_at / last_sync_at。
        "updated_at": last_sync_at,
        "latest_data_date": latest_data_date,
        "age_minutes": age_minutes,
        "freshness": freshness,
        "freshness_basis": freshness_basis,
        "stale_after_minutes": config["stale_after_minutes"],
        "row_count": row_count,
        "expected_points": expected_points,
        "actual_points": actual_points,
        "completeness": completeness,
        "completeness_rate": completeness_rate,
        "sync": {
            "status": sync_state.get("status") or "never",
            "ok": int(sync_state.get("ok") or 0),
            "total": int(sync_state.get("total") or 0),
            "last_attempt_at": sync_state.get("last_attempt_at"),
            "last_success_at": sync_state.get("last_success_at"),
            "last_any_success_at": sync_state.get("last_any_success_at"),
            "last_partial_success_at": sync_state.get("last_partial_success_at"),
            "failed": int(sync_state.get("failed") or 0),
            "failures": sync_state.get("failures") or [],
            "stores": list((sync_state.get("stores") or {}).values()),
        },
        "retryable": freshness != "fresh" or completeness != "complete" or sync_state.get("status") in {"partial", "failed"},
        "retry_method": "POST",
        "retry_url": _retry_url(config, store_id),
    }


def promotion_health_payload(db, user: dict, store_id: int | None = None) -> dict:
    where, params = _scope(user, store_id)
    stores_where, stores_params = _scope(user, store_id, "id")
    visible_stores = int(db.execute("SELECT COUNT(*) AS c FROM stores" + stores_where, stores_params).fetchone()["c"] or 0)
    active_plans = int(db.execute("SELECT COUNT(*) AS c FROM promo_plans" + where + (" AND" if where else " WHERE") + " status = '在投'", params).fetchone()["c"] or 0)
    stats_where, stats_params = _scope(user, store_id)
    realtime_stats = int(db.execute("SELECT COUNT(DISTINCT store_id || ':' || campaign_id) AS c FROM promo_plan_stats" + stats_where + (" AND" if stats_where else " WHERE") + " mode = 'realtime'", stats_params).fetchone()["c"] or 0)
    today = date.today()
    daily_start = (today - timedelta(days=7)).isoformat()
    daily_end = (today - timedelta(days=1)).isoformat()
    daily_points = int(db.execute("SELECT COUNT(DISTINCT store_id || ':' || data_date) AS c FROM promo_daily_data" + where + (" AND" if where else " WHERE") + " data_date >= ? AND data_date <= ?", [*params, daily_start, daily_end]).fetchone()["c"] or 0)
    realtime_points = int(db.execute("SELECT COUNT(DISTINCT store_id || ':' || hour) AS c FROM promo_realtime" + where + (" AND" if where else " WHERE") + " data_date = ?", [*params, today.isoformat()]).fetchone()["c"] or 0)
    elapsed_hours = datetime.now().astimezone().hour + 1
    datasets = [
        build_dataset_metadata(db, "realtime", user, store_id, expected_points=visible_stores * elapsed_hours, actual_points=realtime_points),
        build_dataset_metadata(db, "daily", user, store_id, expected_points=visible_stores * 7, actual_points=daily_points),
        build_dataset_metadata(db, "plans", user, store_id, expected_points=active_plans, actual_points=realtime_stats),
        build_dataset_metadata(db, "items", user, store_id),
    ]
    status = "unavailable" if all(item["freshness"] == "missing" for item in datasets) else "degraded" if any(item["freshness"] != "fresh" or item["completeness"] != "complete" or item["sync"]["status"] in {"partial", "failed"} for item in datasets) else "healthy"
    return {
        "status": status,
        "trustworthy": status == "healthy",
        "summary": {
            "datasets": len(datasets),
            "fresh": sum(1 for item in datasets if item["freshness"] == "fresh"),
            "stale": sum(1 for item in datasets if item["freshness"] == "stale"),
            "missing": sum(1 for item in datasets if item["freshness"] == "missing"),
            "partial": sum(1 for item in datasets if item["completeness"] == "partial" or item["sync"]["status"] == "partial"),
            "retryable": sum(1 for item in datasets if item["retryable"]),
        },
        "datasets": datasets,
        "business_data_at": max((item["business_data_at"] or "" for item in datasets), default="") or None,
        "last_sync_at": max((item["last_sync_at"] or "" for item in datasets), default="") or None,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


@router.get("/health")
def promotion_health(
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    return promotion_health_payload(db, user, store_id)
