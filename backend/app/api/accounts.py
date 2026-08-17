"""账号管理：超级管理员 / 管理员对注册账号的角色、状态、密码、模块可见范围管理。"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import (
    USERNAME_PATTERN,
    hash_password,
    require_admin,
    require_super_admin,
    user_payload,
)
from backend.app.core.db import get_db
from backend.app.core.logs import log_op
from backend.app.core.modules import MODULES

router = APIRouter()

ROLES = ("member", "admin", "super_admin")


class RoleIn(BaseModel):
    role: str


class StatusIn(BaseModel):
    status: str


class PasswordIn(BaseModel):
    password: str


class ModulesIn(BaseModel):
    modules: list[str]


class CreateIn(BaseModel):
    username: str
    password: str
    nickname: str = ""
    role: str = "member"


class StoreAccessIn(BaseModel):
    store_ids: list[int] | None = None


def _get_user_or_404(db, user_id: int):
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="账号不存在")
    return row


def _super_admin_count(db) -> int:
    return db.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'super_admin'").fetchone()["c"]


def _ensure_can_manage(actor: dict, target) -> None:
    """权限判定：超级管理员可管理任何人（除自己），普通管理员只能管理普通账号。"""
    if actor["id"] == target["id"]:
        raise HTTPException(status_code=400, detail="不能操作自己的账号")
    if actor["role"] == "super_admin":
        return
    if actor["role"] == "admin" and target["role"] == "member":
        return
    raise HTTPException(status_code=403, detail="没有权限操作该账号")


@router.post("")
def create_user(
    body: CreateIn,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    username = body.username.strip()
    nickname = body.nickname.strip()
    if not USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(status_code=400, detail="用户名需以字母开头，仅限英文字母和数字（3-20 位）")
    if not (6 <= len(body.password) <= 64):
        raise HTTPException(status_code=400, detail="密码长度需为 6-64 个字符")
    if not nickname:
        raise HTTPException(status_code=400, detail="花名不能为空")
    if len(nickname) > 20:
        raise HTTPException(status_code=400, detail="花名不能超过 20 个字符")
    if body.role not in ("member", "admin"):
        raise HTTPException(status_code=400, detail="角色只能是普通账号或管理员")
    if actor["role"] == "admin" and body.role != "member":
        raise HTTPException(status_code=403, detail="管理员只能创建普通账号")

    exists = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在，换个名字试试")

    salt = secrets.token_bytes(16)
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        """
        INSERT INTO users (username, password_hash, salt, nickname, created_at, role, status, allowed_modules, avatar_url)
        VALUES (?, ?, ?, ?, ?, ?, 'active', NULL, NULL)
        """,
        (username, hash_password(body.password, salt), salt.hex(), nickname, now, body.role),
    )
    row = db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    item = user_payload(row)
    item["created_at"] = row["created_at"]
    return {"item": item}


@router.get("")
def list_users(actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    rows = db.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
    items = []
    for row in rows:
        item = user_payload(row)
        item["created_at"] = row["created_at"]
        items.append(item)
    return {"items": items}


@router.post("/{user_id}/role")
def set_role(
    user_id: int,
    body: RoleIn,
    actor: dict = Depends(require_super_admin),
    db=Depends(get_db),
) -> dict:
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail="角色只能是 member、admin 或 super_admin")
    target = _get_user_or_404(db, user_id)
    if actor["id"] == target["id"] and body.role != "super_admin":
        raise HTTPException(status_code=400, detail="不能取消自己的超级管理员权限")
    if target["role"] == "super_admin" and body.role != "super_admin" and _super_admin_count(db) <= 1:
        raise HTTPException(status_code=400, detail="系统至少需要保留一名超级管理员")
    db.execute("UPDATE users SET role = ? WHERE id = ?", (body.role, user_id))
    return {"ok": True}


@router.post("/{user_id}/status")
def set_status(
    user_id: int,
    body: StatusIn,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    if body.status not in ("active", "disabled"):
        raise HTTPException(status_code=400, detail="状态只能是 active 或 disabled")
    target = _get_user_or_404(db, user_id)
    _ensure_can_manage(actor, target)
    if body.status == "disabled" and target["role"] == "super_admin" and _super_admin_count(db) <= 1:
        raise HTTPException(status_code=400, detail="系统至少需要保留一名启用的超级管理员")
    db.execute("UPDATE users SET status = ? WHERE id = ?", (body.status, user_id))
    if body.status == "disabled":
        db.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))
    return {"ok": True}


@router.post("/{user_id}/password")
def set_password(
    user_id: int,
    body: PasswordIn,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    if not (6 <= len(body.password) <= 64):
        raise HTTPException(status_code=400, detail="密码长度需为 6-64 个字符")
    target = _get_user_or_404(db, user_id)
    _ensure_can_manage(actor, target)
    salt = secrets.token_bytes(16)
    db.execute(
        "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
        (hash_password(body.password, salt), salt.hex(), user_id),
    )
    db.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))
    return {"ok": True}


@router.post("/{user_id}/modules")
def set_modules(
    user_id: int,
    body: ModulesIn,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    target = _get_user_or_404(db, user_id)
    _ensure_can_manage(actor, target)
    if target["role"] != "member":
        raise HTTPException(status_code=400, detail="管理员和超级管理员默认拥有全部模块权限，无需设置")
    grantable = {m["id"] for m in MODULES if m["id"] not in ("accounts", "profile", "logs", "settings")}
    unknown = set(body.modules) - grantable
    if unknown:
        raise HTTPException(status_code=400, detail=f"包含不可授予的模块：{', '.join(sorted(unknown))}")
    if "accounts" in body.modules:
        raise HTTPException(status_code=400, detail="账号管理模块仅管理员可见")
    db.execute(
        "UPDATE users SET allowed_modules = ? WHERE id = ?",
        (json.dumps(body.modules, ensure_ascii=False), user_id),
    )
    return {"ok": True}


@router.post("/{user_id}/stores")
def set_store_access(
    user_id: int,
    body: StoreAccessIn,
    actor: dict = Depends(require_super_admin),
    db=Depends(get_db),
) -> dict:
    target = _get_user_or_404(db, user_id)
    if target["role"] != "member":
        raise HTTPException(status_code=400, detail="管理员和超级管理员默认拥有全部店铺权限")
    if body.store_ids is not None:
        for store_id in body.store_ids:
            store = db.execute("SELECT id FROM stores WHERE id = ?", (store_id,)).fetchone()
            if not store:
                raise HTTPException(status_code=400, detail=f"店铺不存在：{store_id}")
    db.execute(
        "UPDATE users SET allowed_store_ids = ? WHERE id = ?",
        (json.dumps(body.store_ids, ensure_ascii=False) if body.store_ids is not None else None, user_id),
    )
    log_op(db, actor, "accounts", "perm", target["username"], "设置店铺权限")
    return {"ok": True}


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    actor: dict = Depends(require_super_admin),
    db=Depends(get_db),
) -> dict:
    target = _get_user_or_404(db, user_id)
    if actor["id"] == target["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    if target["role"] == "super_admin" and _super_admin_count(db) <= 1:
        raise HTTPException(status_code=400, detail="系统至少需要保留一名超级管理员")
    db.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return {"ok": True}
