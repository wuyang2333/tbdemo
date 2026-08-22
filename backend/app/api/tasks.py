from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Response

from backend.app.api.auth import get_current_user, visible_store_ids
from backend.app.core import loops
from backend.app.core import maintenance
from backend.app.core.db import get_db

router = APIRouter()


@router.get("")
def list_tasks(
    response: Response,
    limit: int = Query(200, ge=1, le=500),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """系统任务中心：当前调度状态、今日统计与最近执行记录。"""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    visible = visible_store_ids(user)
    scope_sql = ""
    scope_params: list[int] = []
    if visible is not None:
        if visible:
            placeholders = ",".join("?" for _ in visible)
            scope_sql = f" AND (r.store_id IS NULL OR r.store_id IN ({placeholders}))"
            scope_params.extend(visible)
        else:
            scope_sql = " AND r.store_id IS NULL"

    history_rows = db.execute(
        """
        SELECT r.*, s.name AS store_name
        FROM sync_runs r
        LEFT JOIN stores s ON s.id = r.store_id
        WHERE 1=1
        """
        + scope_sql
        + " ORDER BY r.id DESC LIMIT ?",
        [*scope_params, limit],
    ).fetchall()

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    summary_row = db.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN r.status = 'success' THEN 1 ELSE 0 END) AS success,
            SUM(CASE WHEN r.status = 'error' THEN 1 ELSE 0 END) AS error
        FROM sync_runs r
        WHERE r.finished_at >= ? AND r.finished_at < ?
        """
        + scope_sql,
        [
            today_start.strftime("%Y-%m-%d %H:%M:%S"),
            tomorrow_start.strftime("%Y-%m-%d %H:%M:%S"),
            *scope_params,
        ],
    ).fetchone()

    maintenance_state = maintenance.get_maintenance(db)
    statuses = [
        {**item, "paused": bool(maintenance_state["enabled"] and item["name"] in maintenance_state["pause_tasks"])}
        for item in loops.get_all_status()
    ]
    today_total = int(summary_row["total"] or 0)
    today_success = int(summary_row["success"] or 0)
    return {
        "tasks": statuses,
        "maintenance": maintenance_state,
        "history": [dict(row) for row in history_rows],
        "summary": {
            "running": sum(1 for item in statuses if item["running"]),
            "abnormal": sum(1 for item in statuses if item["error_count"] > 0),
            "today_total": today_total,
            "today_success": today_success,
            "today_error": int(summary_row["error"] or 0),
            "success_rate": round(today_success / today_total * 100, 1) if today_total else 0,
        },
    }
