"""站内通知 + 新功能/更新日志。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import get_current_user, require_admin
from backend.app.core.db import get_db

notifications_router = APIRouter()
changelog_router = APIRouter()


def notify(db, user_id: int, title: str, content: str = "", link: str = "", ntype: str = "info") -> None:
    """写入一条站内通知（供各模块在业务事件发生时调用）。"""
    db.execute(
        "INSERT INTO notifications (user_id, title, content, link, type, is_read, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
        (user_id, title, content, link, ntype, datetime.now(timezone.utc).isoformat()),
    )


@notifications_router.get("")
def my_notifications(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    rows = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 50", (user["id"],)
    ).fetchall()
    unread = db.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0", (user["id"],)
    ).fetchone()["c"]
    return {
        "items": [
            {
                "id": r["id"],
                "title": r["title"],
                "content": r["content"],
                "link": r["link"],
                "type": r["type"],
                "is_read": bool(r["is_read"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ],
        "unread_count": int(unread),
    }


class ReadIn(BaseModel):
    id: int | None = None


@notifications_router.post("/read")
def mark_read(body: ReadIn, user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    if body.id:
        db.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (body.id, user["id"]))
    else:
        db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user["id"],))
    return {"ok": True}


# ---------- 更新日志 ----------

@changelog_router.get("")
def list_changelog(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    rows = db.execute("SELECT * FROM changelog ORDER BY id DESC LIMIT 50").fetchall()
    return {"items": [dict(r) for r in rows]}


class ChangelogIn(BaseModel):
    version: str = ""
    title: str
    content: str = ""


@changelog_router.post("")
def create_changelog(body: ChangelogIn, actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    if len(title) > 100:
        raise HTTPException(status_code=400, detail="标题不能超过 100 字")
    if len(body.content) > 2000:
        raise HTTPException(status_code=400, detail="内容不能超过 2000 字")
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        "INSERT INTO changelog (version, title, content, created_at) VALUES (?, ?, ?, ?)",
        (body.version.strip()[:30], title, body.content.strip(), now),
    )
    row = db.execute("SELECT * FROM changelog WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"item": dict(row)}


@changelog_router.delete("/{entry_id}")
def delete_changelog(entry_id: int, actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    db.execute("DELETE FROM changelog WHERE id = ?", (entry_id,))
    return {"ok": True}
