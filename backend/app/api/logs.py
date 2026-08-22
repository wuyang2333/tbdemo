"""统一操作日志查询（仅管理员）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.auth import get_current_user
from backend.app.core.db import get_db

router = APIRouter()


@router.get("")
def list_logs(
    module: str = "",
    limit: int = 100,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    limit = max(1, min(limit, 500))
    is_admin = user["role"] in ("admin", "super_admin")
    user_clause = "" if is_admin else " AND user_id = ?"
    user_params = [] if is_admin else [user["id"]]
    if module:
        rows = db.execute(
            "SELECT * FROM op_logs WHERE module = ?" + user_clause + " ORDER BY id DESC LIMIT ?",
            [module, *user_params, limit],
        ).fetchall()
    else:
        where = " WHERE user_id = ?" if not is_admin else ""
        rows = db.execute("SELECT * FROM op_logs" + where + " ORDER BY id DESC LIMIT ?", [*user_params, limit]).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "module": row["module"],
                "user_id": row["user_id"],
                "username": row["username"],
                "action": row["action"],
                "target_name": row["target_name"],
                "detail": row["detail"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    }
