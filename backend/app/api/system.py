"""系统状态：后台循环运行情况 + SaaS 租户概览。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from backend.app.api.auth import get_current_user, require_admin
from backend.app.core import loops
from backend.app.core.db import get_db

router = APIRouter()


@router.get("/loops")
def loops_status(user: dict = Depends(get_current_user)) -> dict:
    """返回全部后台循环的运行状态（最后运行/成功时间、失败次数、错误信息）。"""
    return {"items": loops.get_all_status()}


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