"""系统公告：管理员发布，所有账号登录后可见。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import get_current_user, require_admin
from backend.app.core.db import get_db
from backend.app.core.logs import log_op

router = APIRouter()


class AnnouncementIn(BaseModel):
    title: str
    content: str = ""


def _payload(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "active": bool(row["active"]),
    }


@router.get("/active")
def active_announcements(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    """所有登录用户可见的当前有效公告（按时间倒序）。"""
    rows = db.execute(
        "SELECT * FROM announcements WHERE active = 1 ORDER BY id DESC LIMIT 5"
    ).fetchall()
    return {"items": [_payload(r) for r in rows]}


@router.get("")
def list_announcements(actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    rows = db.execute("SELECT * FROM announcements ORDER BY id DESC").fetchall()
    return {"items": [_payload(r) for r in rows]}


@router.post("")
def create_announcement(
    body: AnnouncementIn,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="公告标题不能为空")
    if len(title) > 100:
        raise HTTPException(status_code=400, detail="标题不能超过 100 个字符")
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        "INSERT INTO announcements (title, content, created_by, created_at, active) VALUES (?, ?, ?, ?, 1)",
        (title, body.content.strip(), actor["id"], now),
    )
    row = db.execute("SELECT * FROM announcements WHERE id = ?", (cur.lastrowid,)).fetchone()
    log_op(db, actor, "announcements", "create", title, "发布系统公告")
    return {"item": _payload(row)}


@router.put("/{announcement_id}")
def update_announcement(
    announcement_id: int,
    body: AnnouncementIn,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    row = db.execute("SELECT * FROM announcements WHERE id = ?", (announcement_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="公告不存在")
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="公告标题不能为空")
    db.execute(
        "UPDATE announcements SET title = ?, content = ? WHERE id = ?",
        (title, body.content.strip(), announcement_id),
    )
    row = db.execute("SELECT * FROM announcements WHERE id = ?", (announcement_id,)).fetchone()
    log_op(db, actor, "announcements", "update", title, "编辑系统公告")
    return {"item": _payload(row)}


@router.post("/{announcement_id}/toggle")
def toggle_announcement(
    announcement_id: int,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    row = db.execute("SELECT * FROM announcements WHERE id = ?", (announcement_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="公告不存在")
    new_active = 0 if row["active"] else 1
    db.execute("UPDATE announcements SET active = ? WHERE id = ?", (new_active, announcement_id))
    log_op(db, actor, "announcements", "toggle", row["title"], "启用" if new_active else "停用")
    return {"ok": True, "active": bool(new_active)}


@router.delete("/{announcement_id}")
def delete_announcement(
    announcement_id: int,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    row = db.execute("SELECT * FROM announcements WHERE id = ?", (announcement_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="公告不存在")
    db.execute("DELETE FROM announcements WHERE id = ?", (announcement_id,))
    log_op(db, actor, "announcements", "delete", row["title"], "删除系统公告")
    return {"ok": True}