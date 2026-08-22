"""系统状态：后台循环运行情况 + SaaS 租户概览。"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.api.auth import get_current_user, require_admin, visible_store_ids
from backend.app.core import loops
from backend.app.core import maintenance
from backend.app.core.db import get_db
from backend.app.core.logs import log_op

router = APIRouter()


class MaintenanceIn(BaseModel):
    enabled: bool
    reason: str = ""
    duration_minutes: int = 0
    pause_tasks: list[str] = Field(default_factory=list)
    resume_strategy: str = "next_cycle"


@router.get("/maintenance")
def maintenance_status(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    return maintenance.get_maintenance(db)


@router.put("/maintenance")
def update_maintenance(body: MaintenanceIn, actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    if body.duration_minutes < 0 or body.duration_minutes > 7 * 24 * 60:
        raise HTTPException(status_code=400, detail="维护时长需在 0 到 7 天之间")
    if body.resume_strategy not in {"next_cycle", "run_once"}:
        raise HTTPException(status_code=400, detail="恢复策略无效")
    unknown = [name for name in body.pause_tasks if name not in maintenance.ALL_TASKS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知任务：{unknown[0]}")
    if body.enabled and not body.pause_tasks:
        raise HTTPException(status_code=400, detail="请至少选择一项暂停任务")
    was_enabled = maintenance.get_maintenance(db, auto_resume=False)["enabled"]
    state = maintenance.set_maintenance(
        db,
        enabled=body.enabled,
        actor=actor,
        reason=body.reason,
        duration_minutes=body.duration_minutes,
        pause_tasks=body.pause_tasks,
        resume_strategy=body.resume_strategy,
    )
    if body.enabled:
        action = "maintenance_update" if was_enabled else "maintenance_enable"
        log_op(
            db,
            actor,
            "system",
            action,
            target_name="后台任务维护模式",
            detail=f"原因：{state['reason']}；暂停任务：{', '.join(state['pause_tasks'])}；恢复策略：{state['resume_strategy']}",
        )
    return state


@router.get("/loops")
def loops_status(user: dict = Depends(get_current_user)) -> dict:
    """返回全部后台循环的运行状态（最后运行/成功时间、失败次数、错误信息）。"""
    state = maintenance.get_maintenance()
    items = [{**item, "paused": bool(state["enabled"] and item["name"] in state["pause_tasks"])} for item in loops.get_all_status()]
    return {"items": items, "maintenance": state}


@router.get("/loops/history")
def loops_history(
    name: str = "",
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    where = " WHERE 1=1"
    params: list = []
    if name:
        where += " AND r.name = ?"
        params.append(name)
    visible = visible_store_ids(user)
    if visible is not None:
        if visible:
            where += " AND (r.store_id IS NULL OR r.store_id IN (" + ",".join("?" for _ in visible) + "))"
            params.extend(visible)
        else:
            where += " AND r.store_id IS NULL"
    rows = db.execute(
        """
        SELECT r.*, s.name AS store_name
        FROM sync_runs r
        LEFT JOIN stores s ON s.id = r.store_id
        """
        + where
        + " ORDER BY r.id DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.post("/loops/{name}/retry")
def retry_loop(
    name: str,
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    supported = {"realtime_sync", "product_catalog_sync", "promo_daily", "inspect"}
    if name not in supported:
        raise HTTPException(status_code=400, detail="该任务暂不支持手动重试")
    visible = visible_store_ids(user)
    if store_id is not None and visible is not None and store_id not in visible:
        raise HTTPException(status_code=403, detail="没有访问该店铺的权限")
    if maintenance.is_task_paused(name, db):
        state = maintenance.get_maintenance(db)
        raise HTTPException(status_code=423, detail=f"任务处于维护模式，暂不可执行：{state.get('reason') or '系统维护'}")

    started = time.monotonic()
    loops.mark_running(name)
    try:
        if name == "product_catalog_sync":
            from backend.app.api.products import sync_catalog_all

            result = sync_catalog_all(db, store_id=store_id, user=user)
        elif name == "realtime_sync":
            from backend.app.api.stores import sync_all_stores, sync_store_row

            if store_id is not None:
                store = db.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone()
                if not store:
                    raise HTTPException(status_code=404, detail="店铺不存在")
                item = sync_store_row(db, store)
                result = {"results": [{"store_id": store_id, "store_name": store["name"], "ok": True, "item": item}], "total": 1, "ok": 1}
            else:
                result = sync_all_stores(db, user)
        elif name == "promo_daily":
            from backend.app.main import _run_promo_daily_once

            _run_promo_daily_once()
            result = {"total": 1, "ok": 1}
        else:
            from backend.app.api.stores import run_inspect_once

            count = run_inspect_once()
            result = {"updated": count, "total": count, "ok": count}

        if "total" in result and result.get("ok", 0) < result.get("total", 0):
            failed = [item.get("error", "同步失败") for item in result.get("results", []) if not item.get("ok")]
            raise RuntimeError("；".join(failed[:3]) or "部分店铺同步失败")
        duration = time.monotonic() - started
        loops.record_success(name, duration, trigger="manual", store_id=store_id)
        log_op(db, user, "system", "retry_sync", target_name=name, detail=f"手动重试成功，耗时 {duration:.1f}s")
        return {"ok": True, "result": result, "status": loops.get_status(name)}
    except HTTPException:
        loops.record_error(name, RuntimeError("手动重试失败"), time.monotonic() - started, trigger="manual", store_id=store_id)
        raise
    except Exception as exc:
        duration = time.monotonic() - started
        loops.record_error(name, exc, duration, trigger="manual", store_id=store_id)
        log_op(db, user, "system", "retry_sync", target_name=name, detail=f"手动重试失败：{exc}")
        raise HTTPException(status_code=502, detail=str(exc) or "同步重试失败") from exc


@router.get("/version")
def version_info(actor: dict = Depends(require_admin)) -> dict:
    """系统版本信息。"""
    return {
        "name": "淘宝运营工作台",
        "version": "0.1.0",
        "backend": "FastAPI + SQLite",
        "frontend": "React + Vite",
    }


@router.get("/cleanup-config")
def cleanup_config(actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    from backend.app.main import DATA_RETENTION_DAYS

    return {"retention_days": DATA_RETENTION_DAYS}


@router.post("/cleanup")
def run_cleanup(actor: dict = Depends(require_admin)) -> dict:
    """一键清理超过保留期的历史数据。"""
    from backend.app.main import _run_data_cleanup_once

    return _run_data_cleanup_once()


@router.get("/tenant-overview")
def tenant_overview(actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    """SaaS 租户概览：账号 / 店铺 / 绑定关系 / 最近登录。"""
    users = db.execute(
        "SELECT id, username, nickname, role, status, allowed_store_ids, parent_id, last_login_at, last_login_ip, expires_at, created_at FROM users ORDER BY id ASC"
    ).fetchall()
    stores = db.execute("SELECT id, name FROM stores ORDER BY id ASC").fetchall()
    store_name = {s["id"]: s["name"] for s in stores}

    total = len(users)
    super_admin = sum(1 for u in users if u["role"] == "super_admin")
    admin = sum(1 for u in users if u["role"] == "admin")
    member = sum(1 for u in users if u["role"] == "member")
    disabled = sum(1 for u in users if u["status"] == "disabled")

    bound_accounts = 0
    total_bindings = 0
    accounts = []
    for u in users:
        is_platform = u["role"] in ("admin", "super_admin")
        allowed = []
        if u["allowed_store_ids"]:
            try:
                allowed = json.loads(u["allowed_store_ids"])
            except (ValueError, TypeError):
                allowed = []
        if is_platform:
            bind_count = len(stores)
            names = [store_name.get(s["id"], s["name"]) for s in stores]
        else:
            bind_count = len(allowed)
            names = [store_name.get(i, f"店铺{i}") for i in allowed]
        if is_platform or bind_count > 0:
            bound_accounts += 1
        total_bindings += bind_count
        accounts.append(
            {
                "id": u["id"],
                "username": u["username"],
                "nickname": u["nickname"] or u["username"],
                "role": u["role"],
                "parent_id": u["parent_id"],
                "status": u["status"],
                "store_count": bind_count,
                "store_names": names,
                "last_login_at": u["last_login_at"],
                "last_login_ip": u["last_login_ip"],
                "expires_at": u["expires_at"],
                "created_at": u["created_at"],
            }
        )

    recent_logins = db.execute(
        "SELECT id, user_id, username, action, ip, created_at FROM login_logs ORDER BY id DESC LIMIT 10"
    ).fetchall()

    return {
        "summary": {
            "total_accounts": total,
            "super_admin": super_admin,
            "admin": admin,
            "member": member,
            "disabled": disabled,
            "total_stores": len(stores),
            "bound_accounts": bound_accounts,
            "unbound_accounts": max(total - bound_accounts, 0),
            "total_bindings": total_bindings,
        },
        "accounts": accounts,
        "recent_logins": [dict(r) for r in recent_logins],
    }


@router.get("/healthcheck")
def healthcheck(actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    """系统体检：数据库/磁盘/备份/同步健康/店铺登录态。"""
    from backend.app.core.db import DB_PATH
    from backend.app.core.sycm import has_profile

    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    disk = shutil.disk_usage("D:/")
    backup_dir = Path("D:/demo/backups")
    backups = sorted(backup_dir.glob("taobao_*.db"), key=lambda p: p.stat().st_mtime, reverse=True) if backup_dir.exists() else []
    stores = db.execute("SELECT * FROM stores ORDER BY id").fetchall()
    last_sync = db.execute("SELECT value FROM meta WHERE key = 'store_1_last_sync'").fetchone()
    loops_rows = db.execute("SELECT value FROM meta WHERE key = 'loops'").fetchone()
    return {
        "db_size_mb": round(db_size / 1024 / 1024, 1),
        "disk_free_gb": round(disk.free / 1024 ** 3, 1),
        "store_count": len(stores),
        "profile_ok": sum(1 for s in stores if has_profile(s["id"])),
        "last_sync": last_sync["value"] if last_sync else None,
        "backup_count": len(backups),
        "backup_latest": backups[0].name if backups else None,
        "store_status": [
            {"store_id": s["id"], "store_name": s["name"], "configured": has_profile(s["id"])}
            for s in stores
        ],
    }
