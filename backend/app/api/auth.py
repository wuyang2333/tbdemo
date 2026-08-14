"""注册 / 登录 / 登出 与登录态校验。"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from backend.app.core.db import get_db

router = APIRouter()

USERNAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]{2,19}$")


class RegisterIn(BaseModel):
    username: str
    password: str
    nickname: str = ""


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
    }


def _issue_token(db, user_id: int) -> str:
    token = secrets.token_hex(32)
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT INTO tokens (token, user_id, created_at) VALUES (?, ?, ?)",
        (token, user_id, now),
    )
    return token


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
    role = "super_admin" if count == 0 else "member"
    salt = secrets.token_bytes(16)
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        """
        INSERT INTO users (username, password_hash, salt, nickname, created_at, role, status, allowed_modules)
        VALUES (?, ?, ?, ?, ?, ?, 'active', NULL)
        """,
        (username, hash_password(body.password, salt), salt.hex(), nickname, now, role),
    )
    user_id = cur.lastrowid
    token = _issue_token(db, user_id)
    return {
        "token": token,
        "user": {
            "id": user_id,
            "username": username,
            "nickname": nickname,
            "role": role,
            "status": "active",
            "allowed_modules": None,
            "avatar_url": None,
            "allowed_store_ids": None,
        },
    }


@router.post("/login")
def login(body: LoginIn, db=Depends(get_db)) -> dict:
    username = body.username.strip()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="该账号已被禁用，请联系管理员")
    salt = bytes.fromhex(row["salt"])
    if hash_password(body.password, salt) != row["password_hash"]:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = _issue_token(db, row["id"])
    return {"token": token, "user": user_payload(row)}


def get_current_user(
    authorization: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    token = authorization[7:].strip()
    row = db.execute(
        """
        SELECT u.id, u.username, u.nickname, u.role, u.status, u.allowed_modules, u.avatar_url, u.allowed_store_ids
        FROM tokens t
        JOIN users u ON u.id = t.user_id
        WHERE t.token = ?
        """,
        (token,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    if row["status"] != "active":
        raise HTTPException(status_code=401, detail="账号已被禁用，请联系管理员")
    return user_payload(row)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


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
    authorization: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict:
    if authorization and authorization.startswith("Bearer "):
        db.execute("DELETE FROM tokens WHERE token = ?", (authorization[7:].strip(),))
    return {"ok": True}
