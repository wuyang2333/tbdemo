"""账号管理：超级管理员 / 管理员对注册账号的角色、状态、密码、模块可见范围管理。"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.notifications import notify

from backend.app.api.auth import (
    USERNAME_PATTERN,
    _effective_payload,
    get_current_user,
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

MAX_STORES_PER_TENANT = 3   # 免费套餐：每个主账号最多绑定 3 家店铺
MAX_SUB_ACCOUNTS = 20       # 每个主账号最多 20 个子账号


def require_tenant_owner(user: dict = Depends(get_current_user)) -> dict:
    """主账号权限：管理员/超管，或普通账号（非子账号）的主账号。"""
    if user["role"] in ("admin", "super_admin"):
        return user
    if user["role"] == "member" and not user.get("parent_id"):
        return user
    raise HTTPException(status_code=403, detail="需要主账号权限")


def _check_store_quota(db, target_row, new_ids: list[int] | None) -> None:
    """校验主账号绑定店铺数不超过该账号的店铺配额；超管/管理员/子账号不受限。"""
    if target_row["role"] in ("admin", "super_admin"):
        return
    if target_row["parent_id"]:
        return
    quota = target_row["store_quota"] if "store_quota" in target_row.keys() else 3
    if new_ids is not None and len(new_ids) > quota:
        raise HTTPException(
            status_code=400,
            detail=f"该账号最多绑定 {quota} 家店铺，如需更多请联系平台调整配额",
        )


def _validate_store_ids(db, store_ids: list[int]) -> None:
    """校验店铺 id 都存在（管理员/超管分配店铺用）。"""
    ids = list(dict.fromkeys(store_ids))
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(f"SELECT id FROM stores WHERE id IN ({placeholders})", tuple(ids)).fetchall()
    valid = {r["id"] for r in rows}
    bad = [sid for sid in ids if sid not in valid]
    if bad:
        raise HTTPException(status_code=400, detail=f"店铺不存在或无法分配：{bad}")


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


def _invite_payload(row) -> dict:
    return {
        "id": row["id"],
        "code": row["code"],
        "note": row["note"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "max_uses": row["max_uses"],
        "used_count": row["used_count"],
        "status": row["status"],
    }



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
        INSERT INTO users (username, password_hash, salt, nickname, created_at, role, status, allowed_modules, avatar_url, allowed_store_ids)
        VALUES (?, ?, ?, ?, ?, ?, 'active', NULL, NULL, ?)
        """,
        (username, hash_password(body.password, salt), salt.hex(), nickname, now, body.role, "[]"),
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
        item["last_login_at"] = row["last_login_at"]
        item["last_login_ip"] = row["last_login_ip"]
        item["expires_at"] = row["expires_at"]
        item["failed_count"] = row["failed_count"]
        item["locked_until"] = row["locked_until"]
        item["parent_id"] = row["parent_id"]
        item["sub_account_quota"] = row["sub_account_quota"] if "sub_account_quota" in row.keys() else 2
        item["store_quota"] = row["store_quota"] if "store_quota" in row.keys() else 3
        items.append(item)
    return {"items": items}


class InviteIn(BaseModel):
    note: str = ""
    max_uses: int = 1
    expires_at: str = ""


@router.post("/invite-codes")
def create_invite_code(
    body: InviteIn,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    if not (1 <= body.max_uses <= 100):
        raise HTTPException(status_code=400, detail="使用次数需为 1-100")
    expires_at = None
    if body.expires_at and body.expires_at.strip():
        try:
            dt = datetime.fromisoformat(body.expires_at.strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt <= datetime.now(timezone.utc):
                raise HTTPException(status_code=400, detail="过期时间需晚于当前时间")
            expires_at = dt.isoformat()
        except ValueError:
            raise HTTPException(status_code=400, detail="过期时间格式不正确")
    code = secrets.token_hex(4).upper()
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        """
        INSERT INTO invite_codes (code, note, created_by, created_at, expires_at, max_uses, used_count, status)
        VALUES (?, ?, ?, ?, ?, ?, 0, 'active')
        """,
        (code, body.note.strip(), actor["id"], now, expires_at, body.max_uses),
    )
    row = db.execute("SELECT * FROM invite_codes WHERE id = ?", (cur.lastrowid,)).fetchone()
    log_op(db, actor, "accounts", "生成邀请码", code, f"备注：{body.note.strip() or '无'}，可用 {body.max_uses} 次")
    return {"item": _invite_payload(row)}


@router.get("/invite-codes")
def list_invite_codes(actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    rows = db.execute("SELECT * FROM invite_codes ORDER BY id DESC").fetchall()
    return {"items": [_invite_payload(r) for r in rows]}


@router.post("/invite-codes/{code_id}/disable")
def disable_invite_code(
    code_id: int,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    row = db.execute("SELECT * FROM invite_codes WHERE id = ?", (code_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    db.execute("UPDATE invite_codes SET status = 'disabled' WHERE id = ?", (code_id,))
    log_op(db, actor, "accounts", "作废邀请码", row["code"], "")
    return {"ok": True}


@router.delete("/invite-codes/{code_id}")
def delete_invite_code(
    code_id: int,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    row = db.execute("SELECT * FROM invite_codes WHERE id = ?", (code_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    db.execute("DELETE FROM invite_codes WHERE id = ?", (code_id,))
    log_op(db, actor, "accounts", "删除邀请码", row["code"], "")
    return {"ok": True}


@router.get("/pending")
def list_pending(actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    rows = db.execute("SELECT * FROM users WHERE status = 'pending' ORDER BY created_at ASC").fetchall()
    items = []
    for row in rows:
        item = user_payload(row)
        item["created_at"] = row["created_at"]
        item["last_login_at"] = row["last_login_at"]
        item["last_login_ip"] = row["last_login_ip"]
        item["expires_at"] = row["expires_at"]
        item["failed_count"] = row["failed_count"]
        item["locked_until"] = row["locked_until"]
        item["parent_id"] = row["parent_id"]
        item["sub_account_quota"] = row["sub_account_quota"] if "sub_account_quota" in row.keys() else 2
        item["store_quota"] = row["store_quota"] if "store_quota" in row.keys() else 3
        items.append(item)
    return {"items": items}


@router.post("/{user_id}/approve")
def approve_user(
    user_id: int,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    row = _get_user_or_404(db, user_id)
    if row["status"] != "pending":
        raise HTTPException(status_code=400, detail="该账号不是待审核状态")
    db.execute("UPDATE users SET status = 'active' WHERE id = ?", (user_id,))
    notify(db, user_id, "注册审核通过", "你的账号已通过审核，现在可以登录了", "/login")
    log_op(db, actor, "accounts", "审核通过", row["username"], f"账号 {row['username']} 审核通过")
    return {"ok": True, "username": row["username"]}


@router.post("/{user_id}/reject")
def reject_user(
    user_id: int,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    row = _get_user_or_404(db, user_id)
    if row["status"] != "pending":
        raise HTTPException(status_code=400, detail="该账号不是待审核状态")
    notify(db, user_id, "注册申请被拒绝", "你的注册申请未通过审核，如有疑问请联系管理员", "/login")
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    log_op(db, actor, "accounts", "拒绝注册", row["username"], f"账号 {row['username']} 注册被拒绝并删除")
    return {"ok": True, "username": row["username"]}


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
    notify(db, user_id, "账号权限已变更", "管理员已调整你的账号角色权限", "/profile")
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
        notify(db, user_id, "账号已被禁用", "你的账号已被禁用，暂时无法登录，如有疑问请联系管理员")
    else:
        notify(db, user_id, "账号已启用", "你的账号已恢复，可以正常登录")
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
    notify(db, user_id, "密码已被重置", "管理员已重置你的登录密码，请使用新密码登录")
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
    _check_store_quota(db, target, body.store_ids)
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


class ExpiryIn(BaseModel):
    expires_at: str = ""


@router.post("/{user_id}/expiry")
def set_expiry(
    user_id: int,
    body: ExpiryIn,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    """设置账号有效期（留空 = 清除有效期，永久有效）。"""
    target = _get_user_or_404(db, user_id)
    _ensure_can_manage(actor, target)
    expires_at = None
    if body.expires_at and body.expires_at.strip():
        try:
            dt = datetime.fromisoformat(body.expires_at.strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt <= datetime.now(timezone.utc):
                raise HTTPException(status_code=400, detail="有效期需晚于当前时间")
            expires_at = dt.isoformat()
        except ValueError:
            raise HTTPException(status_code=400, detail="有效期格式不正确")
    db.execute("UPDATE users SET expires_at = ? WHERE id = ?", (expires_at, user_id))
    log_op(db, actor, "accounts", "设置有效期", target["username"], f"有效期至 {expires_at or '永久'}")
    return {"ok": True}


@router.get("/{user_id}/sessions")
def list_sessions(
    user_id: int,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    """查看账号的登录会话（有效 token）。"""
    _get_user_or_404(db, user_id)
    rows = db.execute(
        "SELECT token, created_at, expires_at FROM tokens WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    return {"items": [{"token": r["token"], "created_at": r["created_at"], "expires_at": r["expires_at"]} for r in rows]}


@router.post("/{user_id}/sessions/{token}/revoke")
def revoke_session(
    user_id: int,
    token: str,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    """强制下线指定会话。"""
    target = _get_user_or_404(db, user_id)
    db.execute("DELETE FROM tokens WHERE user_id = ? AND token = ?", (user_id, token))
    log_op(db, actor, "accounts", "强制下线", target["username"], "下线一个登录会话")
    return {"ok": True}


class CopyIn(BaseModel):
    source_user_id: int


@router.post("/{user_id}/copy-permissions")
def copy_permissions(
    user_id: int,
    body: CopyIn,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    """把源账号的模块+店铺权限复制给目标账号。"""
    target = _get_user_or_404(db, user_id)
    source = _get_user_or_404(db, body.source_user_id)
    if target["id"] == source["id"]:
        raise HTTPException(status_code=400, detail="不能把权限复制给自己")
    _ensure_can_manage(actor, target)
    db.execute(
        "UPDATE users SET allowed_modules = ?, allowed_store_ids = ? WHERE id = ?",
        (source["allowed_modules"], source["allowed_store_ids"], user_id),
    )
    log_op(db, actor, "accounts", "复制权限", target["username"], f"从 {source['username']} 复制模块与店铺权限")
    return {"ok": True}


@router.get("/{user_id}/logs")
def user_logs(
    user_id: int,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    """单个账号的操作日志。"""
    target = _get_user_or_404(db, user_id)
    rows = db.execute(
        "SELECT module, action, target_name, detail, created_at FROM op_logs WHERE user_id = ? ORDER BY id DESC LIMIT 100",
        (user_id,),
    ).fetchall()
    return {"items": [dict(r) for r in rows], "username": target["username"]}


@router.get("/login-logs")
def login_logs(
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
    limit: int = 100,
) -> dict:
    """全体登录日志（登录成功/失败/登出）。"""
    limit = max(1, min(limit, 500))
    rows = db.execute("SELECT * FROM login_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"items": [dict(r) for r in rows]}


class SubAccountIn(BaseModel):
    username: str
    password: str
    nickname: str = ""
    allowed_modules: list[str] | None = None
    allowed_store_ids: list[int] | None = None


class SubStoresIn(BaseModel):
    store_ids: list[int] = []


def _sub_payload(row, db) -> dict:
    item = _effective_payload(db, row)
    item["created_at"] = row["created_at"]
    item["last_login_at"] = row["last_login_at"]
    item["last_login_ip"] = row["last_login_ip"]
    store_ids = item.get("allowed_store_ids") or []
    names: list[str] = []
    if store_ids:
        placeholders = ",".join("?" * len(store_ids))
        rows = db.execute(f"SELECT id, name FROM stores WHERE id IN ({placeholders})", tuple(store_ids)).fetchall()
        name_map = {r["id"]: r["name"] for r in rows}
        names = [name_map.get(sid, f"店铺#{sid}") for sid in store_ids]
    item["store_names"] = names
    return item


@router.get("/my/sub-accounts")
def list_sub_accounts(actor: dict = Depends(require_tenant_owner), db=Depends(get_db)) -> dict:
    """主账号查看自己的子账号列表。"""
    rows = db.execute(
        "SELECT * FROM users WHERE parent_id = ? ORDER BY id ASC", (actor["id"],)
    ).fetchall()
    return {"items": [_sub_payload(r, db) for r in rows]}


@router.post("/my/sub-accounts")
def create_sub_account(
    body: SubAccountIn,
    actor: dict = Depends(require_tenant_owner),
    db=Depends(get_db),
) -> dict:
    """主账号创建子账号：子账号继承主账号绑定的店铺数据。"""
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
    if actor["role"] not in ("admin", "super_admin"):
        count = db.execute("SELECT COUNT(*) AS c FROM users WHERE parent_id = ?", (actor["id"],)).fetchone()["c"]
        quota = actor.get("sub_account_quota") or 2
        if count >= quota:
            raise HTTPException(status_code=400, detail=f"子账号配额已用完（上限 {quota} 个），如需更多请联系平台调整配额")
    exists = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在，换个名字试试")
    salt = secrets.token_bytes(16)
    now = datetime.now(timezone.utc).isoformat()
    modules_json = json.dumps(body.allowed_modules or [], ensure_ascii=False) if body.allowed_modules is not None else None
    if actor["role"] in ("admin", "super_admin"):
        store_ids = body.allowed_store_ids or []
        _validate_store_ids(db, store_ids)
        store_json = json.dumps(store_ids)
    else:
        store_json = "[]"
    cur = db.execute(
        """
        INSERT INTO users (username, password_hash, salt, nickname, created_at, role, status, allowed_modules, allowed_store_ids, parent_id)
        VALUES (?, ?, ?, ?, ?, 'member', 'active', ?, ?, ?)
        """,
        (username, hash_password(body.password, salt), salt.hex(), nickname, now, modules_json, store_json, actor["id"]),
    )
    row = db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    log_op(db, actor, "accounts", "create_sub", username, "创建子账号")
    return {"item": _sub_payload(row, db)}


@router.post("/my/sub-accounts/{sub_id}/stores")
def set_sub_stores(
    sub_id: int,
    body: SubStoresIn,
    actor: dict = Depends(require_tenant_owner),
    db=Depends(get_db),
) -> dict:
    """分配子账号可见店铺（管理员/超管的子账号支持手动分配）。"""
    if actor["role"] not in ("admin", "super_admin"):
        raise HTTPException(status_code=400, detail="普通主账号的子账号自动跟随你的店铺，无需单独分配")
    row = db.execute(
        "SELECT * FROM users WHERE id = ? AND parent_id = ?", (sub_id, actor["id"])
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="子账号不存在")
    store_ids = list(dict.fromkeys(body.store_ids or []))
    _validate_store_ids(db, store_ids)
    db.execute(
        "UPDATE users SET allowed_store_ids = ? WHERE id = ?",
        (json.dumps(store_ids), sub_id),
    )
    log_op(db, actor, "accounts", "sub_stores", row["username"], f"分配子账号可见店铺 {len(store_ids)} 家")
    return {"ok": True, "store_ids": store_ids}


@router.post("/my/sub-accounts/{sub_id}/password")
def reset_sub_password(
    sub_id: int,
    body: PasswordIn,
    actor: dict = Depends(require_tenant_owner),
    db=Depends(get_db),
) -> dict:
    row = db.execute(
        "SELECT * FROM users WHERE id = ? AND parent_id = ?", (sub_id, actor["id"])
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="子账号不存在")
    if not (6 <= len(body.password) <= 64):
        raise HTTPException(status_code=400, detail="密码长度需为 6-64 个字符")
    salt = secrets.token_bytes(16)
    db.execute(
        "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
        (hash_password(body.password, salt), salt.hex(), sub_id),
    )
    db.execute("DELETE FROM tokens WHERE user_id = ?", (sub_id,))
    log_op(db, actor, "accounts", "sub_password", row["username"], "重置子账号密码")
    return {"ok": True}


@router.delete("/my/sub-accounts/{sub_id}")
def delete_sub_account(
    sub_id: int,
    actor: dict = Depends(require_tenant_owner),
    db=Depends(get_db),
) -> dict:
    row = db.execute(
        "SELECT * FROM users WHERE id = ? AND parent_id = ?", (sub_id, actor["id"])
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="子账号不存在")
    db.execute("DELETE FROM tokens WHERE user_id = ?", (sub_id,))
    db.execute("DELETE FROM users WHERE id = ?", (sub_id,))
    log_op(db, actor, "accounts", "delete_sub", row["username"], "删除子账号")
    return {"ok": True}


class QuotaIn(BaseModel):
    sub_account_quota: int | None = None
    store_quota: int | None = None


@router.post("/{user_id}/quota")
def set_quota(
    user_id: int,
    body: QuotaIn,
    actor: dict = Depends(require_super_admin),
    db=Depends(get_db),
) -> dict:
    """超管设置某账号的子账号配额与店铺配额。"""
    target = _get_user_or_404(db, user_id)
    if target["role"] in ("admin", "super_admin"):
        raise HTTPException(status_code=400, detail="管理员/超管无需配额限制")
    new_sub = body.sub_account_quota if body.sub_account_quota is not None else (target["sub_account_quota"] if "sub_account_quota" in target.keys() else 2)
    new_store = body.store_quota if body.store_quota is not None else (target["store_quota"] if "store_quota" in target.keys() else 3)
    if not (0 <= new_sub <= 100) or not (0 <= new_store <= 100):
        raise HTTPException(status_code=400, detail="配额需在 0-100 之间")
    db.execute(
        "UPDATE users SET sub_account_quota = ?, store_quota = ? WHERE id = ?",
        (new_sub, new_store, user_id),
    )
    log_op(db, actor, "accounts", "quota", target["username"], f"子账号配额 {new_sub}，店铺配额 {new_store}")
    return {"ok": True, "sub_account_quota": new_sub, "store_quota": new_store}