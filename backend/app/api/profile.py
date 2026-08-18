"""个人中心：修改花名、密码、头像。"""

from __future__ import annotations

import base64
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import get_current_user, hash_password
from backend.app.core.db import DB_PATH, get_db

router = APIRouter()

AVATAR_DIR = DB_PATH.parent / "avatars"
AVATAR_PATTERN = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,(.+)$", re.DOTALL)
MAX_AVATAR_BYTES = 2 * 1024 * 1024


class NicknameIn(BaseModel):
    nickname: str


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


class AvatarIn(BaseModel):
    data: str


@router.get("/sessions")
def my_sessions(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    """当前账号的登录会话列表（含 IP / 设备信息）。"""
    rows = db.execute(
        "SELECT token, created_at, expires_at, ip, user_agent FROM tokens WHERE user_id = ? ORDER BY created_at DESC",
        (user["id"],),
    ).fetchall()
    return {
        "items": [
            {
                "token": r["token"],
                "created_at": r["created_at"],
                "expires_at": r["expires_at"],
                "ip": r["ip"] or "",
                "user_agent": r["user_agent"] or "",
            }
            for r in rows
        ]
    }


@router.post("/sessions/revoke-others")
def revoke_other_sessions(
    current_token: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """下线除当前设备外的所有会话。"""
    token = current_token.strip()
    if token:
        db.execute("DELETE FROM tokens WHERE user_id = ? AND token != ?", (user["id"], token))
    else:
        db.execute("DELETE FROM tokens WHERE user_id = ?", (user["id"],))
    return {"ok": True}


@router.post("/sessions/{token}/revoke")
def revoke_my_session(
    token: str,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """下线当前账号的指定会话（其他设备立即退出）。"""
    db.execute("DELETE FROM tokens WHERE user_id = ? AND token = ?", (user["id"], token))
    return {"ok": True}


@router.post("/nickname")
def update_nickname(
    body: NicknameIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    nickname = body.nickname.strip()
    if not nickname:
        raise HTTPException(status_code=400, detail="花名不能为空")
    if len(nickname) > 20:
        raise HTTPException(status_code=400, detail="花名不能超过 20 个字符")
    db.execute("UPDATE users SET nickname = ? WHERE id = ?", (nickname, user["id"]))
    return {"ok": True}


@router.post("/password")
def update_password(
    body: PasswordIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    row = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    salt = bytes.fromhex(row["salt"])
    if hash_password(body.old_password, salt) != row["password_hash"]:
        raise HTTPException(status_code=400, detail="原密码不正确")
    if not (6 <= len(body.new_password) <= 64):
        raise HTTPException(status_code=400, detail="新密码长度需为 6-64 个字符")
    new_salt = secrets.token_bytes(16)
    db.execute(
        "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
        (hash_password(body.new_password, new_salt), new_salt.hex(), user["id"]),
    )
    return {"ok": True}


@router.post("/avatar")
def update_avatar(
    body: AvatarIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    match = AVATAR_PATTERN.match(body.data.strip())
    if not match:
        raise HTTPException(status_code=400, detail="仅支持 PNG / JPG / WebP / GIF 图片")
    ext = "jpg" if match.group(1) == "jpeg" else match.group(1)
    try:
        raw = base64.b64decode(match.group(2))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="图片数据解析失败")
    if len(raw) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="头像图片不能超过 2MB")
    if not raw:
        raise HTTPException(status_code=400, detail="图片内容为空")

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    for old in AVATAR_DIR.glob(f"{user['id']}.*"):
        old.unlink()
    target = AVATAR_DIR / f"{user['id']}.{ext}"
    target.write_bytes(raw)

    avatar_url = f"/api/avatars/{user['id']}.{ext}"
    db.execute("UPDATE users SET avatar_url = ? WHERE id = ?", (avatar_url, user["id"]))
    return {"avatar_url": avatar_url}
