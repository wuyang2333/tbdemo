"""统一操作日志：所有模块的审计记录共用一个表。"""

from __future__ import annotations

from datetime import datetime, timezone


def log_op(db, user: dict, module: str, action: str, target_name: str = "", detail: str = "") -> None:
    db.execute(
        """
        INSERT INTO op_logs (module, user_id, username, action, target_name, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            module,
            user["id"],
            user["username"],
            action,
            target_name,
            detail,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
