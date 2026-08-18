"""系统状态：后台循环运行情况 + SaaS 租户概览。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends

from backend.app.api.auth import get_current_user, require_admin
from backend.app.core import loops
from backend.app.core.db import get_db

router = APIRouter()


@router.get("/loops")
def loops_status(user: dict = Depends(get_current_user)) -> dict:
    """返回全部后台循环的运行状态（最后运行/成功时间、失败次数、错误信息）。"""
    return {"items": loops.get_all_status()}


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