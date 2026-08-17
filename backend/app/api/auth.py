"""注册 / 登录 / 登出 与登录态校验。"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from backend.app.core.db import get_db

router = APIRouter()

USERNAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]{2,19}$")

LOGIN_MAX_FAILED = 5          # 连续失败次数上限
LOGIN_LOCK_SECONDS = 600      # 锁定时长（秒）
TOKEN_TTL_SECONDS = 7 * 24 * 3600  # token 有效期（7 天）


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _write_login_log(db, user_id: int, username: str, action: str, ip: str, user_agent: str, detail: str = "") -> None:
    db.execute(
        "INSERT INTO login_logs (user_id, username, action, ip, user_agent, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, username, action, ip, user_agent[:200], detail, datetime.now(timezone.utc).isoformat()),
    )


def _log_fail(db, user_id: int, username: str, ip: str, user_agent: str, detail: str = "") -> None:
    """写失败日志并立即 commit（失败路径 get_db 不会自动 commit）。"""
    _write_login_log(db, user_id, username, "fail", ip, user_agent, detail)
    db.commit()


class RegisterIn(BaseModel):
    username: str
    password: str
    nickname: str = ""
    invite_code: str = ""


class LoginIn(BaseModel):
    username: str
    password: str


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()


def user_payload(row) -> dict:
    allowed_raw = row["allowed_modules"]
    allowed = None
    if allowed_raw is not None:
        try:
            parsed = json.loads(allowed_raw)
            allowed = parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            allowed = []
    store_raw = row["allowed_store_ids"]
    allowed_stores = None
    if store_raw is not None:
        try:
            parsed_stores = json.loads(store_raw)
            allowed_stores = parsed_stores if isinstance(parsed_stores, list) else []
        except (ValueError, TypeError):
            allowed_stores = []
    return {
        "id": row["id"],
        "username": row["username"],
        "nickname": row["nickname"] or row["username"],
        "role": row["role"],
        "status": row["status"],
        "allowed_modules": allowed,
        "avatar_url": row["avatar_url"],
        "allowed_store_ids": allowed_stores,
        "parent_id": row["parent_id"] if "parent_id" in row.keys() else None,
        "sub_account_quota": row["sub_account_quota"] if "sub_account_quota" in row.keys() else 2,
        "store_quota": row["store_quota"] if "store_quota" in row.keys() else 3,
    }


def _effective_payload(db, row) -> dict:
    """构建用户 payload；子账号（parent_id）继承主账号的可见店铺。"""
    payload = user_payload(row)
    pid = payload.get("parent_id")
    if pid:
        parent = db.execute("SELECT allowed_store_ids FROM users WHERE id = ?", (pid,)).fetchone()
        if parent and parent["allowed_store_ids"]:
            try:
                payload["allowed_store_ids"] = json.loads(parent["allowed_store_ids"])
            except (ValueError, TypeError):
                payload["allowed_store_ids"] = []
    return payload


def _issue_token(db, user_id: int) -> str:
    token = secrets.token_hex(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=TOKEN_TTL_SECONDS)
    db.execute(
        "INSERT INTO tokens (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, now.isoformat(), expires_at.isoformat()),
    )
    return token


def _consume_invite_code(db, code: str) -> None:
    """校验并消耗一个邀请码（不存在/失效/过期/用完均拒绝）。"""
    row = db.execute("SELECT * FROM invite_codes WHERE code = ?", (code,)).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="邀请码无效")
    if row["status"] != "active":
        raise HTTPException(status_code=400, detail="邀请码已失效")
    if row["expires_at"]:
        try:
            exp = datetime.fromisoformat(row["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                raise HTTPException(status_code=400, detail="邀请码已过期")
        except ValueError:
            raise HTTPException(status_code=400, detail="邀请码已过期")
    if row["used_count"] >= row["max_uses"]:
        raise HTTPException(status_code=400, detail="邀请码使用次数已用完")
    db.execute("UPDATE invite_codes SET used_count = used_count + 1 WHERE id = ?", (row["id"],))
    return True


@router.post("/register")
def register(body: RegisterIn, db=Depends(get_db)) -> dict:
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

    exists = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在，换个名字试试")

    count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    is_first = count == 0
    code = (body.invite_code or "").strip()
    # 首个用户：直接激活并成为超级管理员
    # 有邀请码：校验通过后直接激活（免审核）
    # 无邀请码：进入待审核，由管理员审核通过后登录
    role = "super_admin" if is_first else "member"
    if is_first or (code and _consume_invite_code(db, code)):
        status = "active"
    else:
        status = "pending"
    salt = secrets.token_bytes(16)
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        """
        INSERT INTO users (username, password_hash, salt, nickname, created_at, role, status, allowed_modules, allowed_store_ids)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (username, hash_password(body.password, salt), salt.hex(), nickname, now, role, status, "[]"),
    )
    user_id = cur.lastrowid
    if status == "active":
        token = _issue_token(db, user_id)
        return {
            "token": token,
            "user": {
                "id": user_id,
                "username": username,
                "nickname": nickname,
                "role": role,
                "status": status,
                "allowed_modules": None,
                "avatar_url": None,
                "allowed_store_ids": None,
            },
        }
    return {"ok": True, "pending": True, "message": "注册申请已提交，请等待管理员审核通过后登录"}

@router.post("/login")
def login(body: LoginIn, request: Request, db=Depends(get_db)) -> dict:
    username = body.username.strip()
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        _log_fail(db, 0, username, ip, ua, "用户不存在")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 失败锁定检查
    if row["locked_until"]:
        try:
            locked = datetime.fromisoformat(row["locked_until"])
            if locked.tzinfo is None:
                locked = locked.replace(tzinfo=timezone.utc)
            if locked > datetime.now(timezone.utc):
                mins = int((locked - datetime.now(timezone.utc)).total_seconds() // 60) + 1
                _log_fail(db, row["id"], username, ip, ua, "账号锁定中")
                raise HTTPException(status_code=423, detail=f"登录失败次数过多，账号已锁定，请 {mins} 分钟后再试")
        except ValueError:
            pass

    if row["status"] == "pending":
        _log_fail(db, row["id"], username, ip, ua, "账号待审核")
        raise HTTPException(status_code=403, detail="账号待管理员审核，请稍后再试")
    if row["status"] != "active":
        _log_fail(db, row["id"], username, ip, ua, "账号已禁用")
        raise HTTPException(status_code=403, detail="该账号已被禁用，请联系管理员")

    # 有效期检查
    if row["expires_at"]:
        try:
            exp = datetime.fromisoformat(row["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                _log_fail(db, row["id"], username, ip, ua, "账号已到期")
                raise HTTPException(status_code=403, detail="账号已到期，请联系管理员续期")
        except ValueError:
            pass

    salt = bytes.fromhex(row["salt"])
    if hash_password(body.password, salt) != row["password_hash"]:
        failed = (row["failed_count"] or 0) + 1
        lock_until = None
        if failed >= LOGIN_MAX_FAILED:
            lock_until = (datetime.now(timezone.utc) + timedelta(seconds=LOGIN_LOCK_SECONDS)).isoformat()
        db.execute("UPDATE users SET failed_count = ?, locked_until = ? WHERE id = ?", (failed, lock_until, row["id"]))
        _log_fail(db, row["id"], username, ip, ua, f"密码错误（第 {failed} 次）")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "UPDATE users SET failed_count = 0, locked_until = NULL, last_login_at = ?, last_login_ip = ? WHERE id = ?",
        (now, ip, row["id"]),
    )
    token = _issue_token(db, row["id"])
    _write_login_log(db, row["id"], username, "login", ip, ua)
    return {"token": token, "user": _effective_payload(db, row)}


def get_current_user(
    authorization: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    token = authorization[7:].strip()
    row = db.execute(
        """
        SELECT u.id, u.username, u.nickname, u.role, u.status, u.allowed_modules, u.avatar_url, u.allowed_store_ids, u.expires_at, u.parent_id, u.sub_account_quota, u.store_quota, t.expires_at AS token_expires_at
        FROM tokens t
        JOIN users u ON u.id = t.user_id
        WHERE t.token = ?
        """,
        (token,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    if row["token_expires_at"]:
        try:
            exp = datetime.fromisoformat(row["token_expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                db.execute("DELETE FROM tokens WHERE token = ?", (token,))
                raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
        except ValueError:
            pass
    if row["expires_at"]:
        try:
            exp = datetime.fromisoformat(row["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                raise HTTPException(status_code=401, detail="账号已到期，请联系管理员")
        except ValueError:
            pass
    if row["status"] != "active":
        raise HTTPException(status_code=401, detail="账号已被禁用，请联系管理员")
    return _effective_payload(db, row)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def visible_store_ids(user: dict) -> set[int] | None:
    """返回该用户可见的店铺 id 集合；None 表示全部可见（超管/管理员）。

    SaaS 多租户隔离核心：普通账号只能看绑定的店铺，未绑定 = 无任何店铺数据。
    """
    if user["role"] in ("admin", "super_admin"):
        return None
    allowed = user.get("allowed_store_ids")
    if not allowed:
        return set()
    return set(allowed)


def require_super_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    return user


def require_module(module_id: str):
    def checker(user: dict = Depends(get_current_user)) -> dict:
        if module_id == "dashboard":
            return user
        if user["role"] in ("admin", "super_admin"):
            return user
        allowed = user["allowed_modules"]
        if allowed is None or module_id in allowed:
            return user
        raise HTTPException(status_code=403, detail=f"没有访问「{module_id}」模块的权限")

    return checker


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {"user": user}


@router.post("/logout")
def logout(
    request: Request,
    authorization: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict:
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        row = db.execute("SELECT user_id FROM tokens WHERE token = ?", (token,)).fetchone()
        if row:
            _write_login_log(db, row["user_id"], "", "logout", _client_ip(request), request.headers.get("user-agent", ""))
        db.execute("DELETE FROM tokens WHERE token = ?", (token,))
    return {"ok": True}


class VerifyPasswordIn(BaseModel):
    password: str


@router.post("/verify-password")
def verify_password(
    body: VerifyPasswordIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """高风险操作二次确认：验证当前登录用户密码。"""
    row = db.execute("SELECT password_hash, salt FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="账号不存在")
    if hash_password(body.password, bytes.fromhex(row["salt"])) != row["password_hash"]:
        raise HTTPException(status_code=401, detail="密码错误，请重试")
    return {"ok": True}
