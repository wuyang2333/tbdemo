"""统一操作日志查询（仅管理员）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.auth import require_admin
from backend.app.core.db import get_db

router = APIRouter()


@router.get("")
def list_logs(
    module: str = "",
    limit: int = 100,
    admin: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    limit = max(1, min(limit, 500))
    if module:
        rows = db.execute(
            "SELECT * FROM op_logs WHERE module = ? ORDER BY id DESC LIMIT ?",
            (module, limit),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM op_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
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
