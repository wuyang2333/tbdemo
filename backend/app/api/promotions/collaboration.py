"""推广执行协同中心：只记录本地协作状态，不会调用万相台。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.api.auth import get_current_user, visible_store_ids
from backend.app.core.db import get_db
from backend.app.core.logs import log_op


router = APIRouter()

EXECUTION_STATUSES = ("executing", "observing", "pending_verification", "needs_rollback", "completed")
APPROVAL_STATUSES = ("not_required", "pending", "approved", "rejected")
ACTION_EXECUTION_STATUS = {
    "planned": "executing",
    "observing": "observing",
    "success": "completed",
    "partial": "completed",
    "failed": "needs_rollback",
    "insufficient": "completed",
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_promo_collaboration_tables(db) -> None:
    """创建并补齐协同中心本地表；可安全地在应用启动时重复调用。"""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_collaboration_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            action_record_id INTEGER,
            decision_record_id INTEGER,
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            owner_id INTEGER,
            owner_name TEXT NOT NULL DEFAULT '',
            planned_at TEXT,
            approval_status TEXT NOT NULL DEFAULT 'not_required',
            execution_status TEXT NOT NULL DEFAULT 'executing',
            rollback_reason TEXT NOT NULL DEFAULT '',
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_collaboration_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            remind_at TEXT,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_promo_collab_tasks_store ON promo_collaboration_tasks(store_id, updated_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_promo_collab_reminders_task ON promo_collaboration_reminders(task_id, created_at DESC)")

    columns = {row[1] for row in db.execute("PRAGMA table_info(promo_collaboration_tasks)").fetchall()}
    for name, definition in (
        ("action_record_id", "INTEGER"),
        ("decision_record_id", "INTEGER"),
        ("owner_id", "INTEGER"),
        ("owner_name", "TEXT NOT NULL DEFAULT ''"),
        ("planned_at", "TEXT"),
        ("approval_status", "TEXT NOT NULL DEFAULT 'not_required'"),
        ("execution_status", "TEXT NOT NULL DEFAULT 'executing'"),
        ("rollback_reason", "TEXT NOT NULL DEFAULT ''"),
        ("updated_at", "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in columns:
            db.execute(f"ALTER TABLE promo_collaboration_tasks ADD COLUMN {name} {definition}")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_collab_tasks_action ON promo_collaboration_tasks(action_record_id) WHERE action_record_id IS NOT NULL")


migrate_promo_collaboration = ensure_promo_collaboration_tables


def _scope_clause(user: dict, column: str = "t.store_id") -> tuple[str, list[int]]:
    visible = visible_store_ids(user)
    if visible is None:
        return "", []
    if not visible:
        return " AND 1=0", []
    values = sorted(visible)
    return f" AND {column} IN ({','.join('?' for _ in values)})", values


def _task_row(db, task_id: int, user: dict):
    scope, params = _scope_clause(user)
    return db.execute(
        "SELECT t.*, p.plan_name, p.campaign_id, p.scene_name, s.name AS store_name "
        "FROM promo_collaboration_tasks t "
        "LEFT JOIN promo_plans p ON p.id = t.plan_id "
        "LEFT JOIN stores s ON s.id = t.store_id WHERE t.id = ?" + scope,
        [task_id, *params],
    ).fetchone()


def _serialize_task(db, row) -> dict:
    item = dict(row)
    item["reminder_count"] = db.execute(
        "SELECT COUNT(*) AS count FROM promo_collaboration_reminders WHERE task_id = ?", (item["id"],)
    ).fetchone()["count"]
    return item


def _visible_plan(db, plan_id: int, user: dict):
    scope, params = _scope_clause(user, "store_id")
    return db.execute("SELECT * FROM promo_plans WHERE id = ?" + scope, [plan_id, *params]).fetchone()


class CollaborationTaskIn(BaseModel):
    plan_id: int
    action_record_id: int | None = None
    decision_record_id: int | None = None
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    owner_id: int | None = None
    owner_name: str = Field(default="", max_length=80)
    planned_at: str | None = None
    approval_status: str = "not_required"
    execution_status: str = "executing"


class CollaborationTaskUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    owner_id: int | None = None
    owner_name: str | None = Field(default=None, max_length=80)
    planned_at: str | None = None
    approval_status: str | None = None
    execution_status: str | None = None
    rollback_reason: str | None = Field(default=None, max_length=1000)


class ReminderIn(BaseModel):
    message: str = Field(default="", max_length=1000)
    remind_at: str | None = None


class RollbackSuggestionIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


def _validate_statuses(approval_status: str | None, execution_status: str | None) -> None:
    if approval_status is not None and approval_status not in APPROVAL_STATUSES:
        raise HTTPException(status_code=422, detail="无效的审批状态")
    if execution_status is not None and execution_status not in EXECUTION_STATUSES:
        raise HTTPException(status_code=422, detail="无效的执行状态")


def create_collaboration_task_for_action(
    db,
    user: dict,
    plan: dict,
    action_record_id: int,
    *,
    decision_record_id: int | None = None,
    title: str,
    description: str = "",
) -> int:
    """为推广动作建立本地协同任务，重复调用保持幂等。"""
    ensure_promo_collaboration_tables(db)
    now = _now()
    db.execute(
        "INSERT OR IGNORE INTO promo_collaboration_tasks "
        "(store_id, plan_id, action_record_id, decision_record_id, title, description, owner_id, owner_name, planned_at, approval_status, execution_status, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_required', 'executing', ?, ?, ?)",
        (
            plan["store_id"], plan["id"], action_record_id, decision_record_id, title, description,
            user["id"], user["username"], now, user["id"], now, now,
        ),
    )
    row = db.execute("SELECT id FROM promo_collaboration_tasks WHERE action_record_id = ?", (action_record_id,)).fetchone()
    return int(row["id"])


@router.get("/collaboration/tasks")
def list_collaboration_tasks(
    store_id: int | None = None,
    execution_status: str | None = Query(default=None),
    approval_status: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """返回当前账号可见店铺的协同任务。"""
    ensure_promo_collaboration_tables(db)
    _validate_statuses(approval_status, execution_status)
    scope, params = _scope_clause(user)
    where, query_params = ["WHERE 1=1" + scope], list(params)
    if store_id is not None:
        where.append("AND t.store_id = ?")
        query_params.append(store_id)
    if execution_status:
        where.append("AND t.execution_status = ?")
        query_params.append(execution_status)
    if approval_status:
        where.append("AND t.approval_status = ?")
        query_params.append(approval_status)
    rows = db.execute(
        "SELECT t.*, p.plan_name, p.campaign_id, p.scene_name, s.name AS store_name "
        "FROM promo_collaboration_tasks t LEFT JOIN promo_plans p ON p.id = t.plan_id "
        "LEFT JOIN stores s ON s.id = t.store_id " + " ".join(where) + " ORDER BY t.updated_at DESC, t.id DESC",
        query_params,
    ).fetchall()
    return {"items": [_serialize_task(db, row) for row in rows], "total": len(rows)}


@router.get("/collaboration/summary")
def collaboration_summary(
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """按执行与审批状态汇总当前账号可见协同任务。"""
    ensure_promo_collaboration_tables(db)
    scope, params = _scope_clause(user)
    store_clause = " AND t.store_id = ?" if store_id is not None else ""
    if store_id is not None:
        params.append(store_id)
    row = db.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN execution_status = 'executing' THEN 1 ELSE 0 END) AS executing, "
        "SUM(CASE WHEN execution_status = 'observing' THEN 1 ELSE 0 END) AS observing, "
        "SUM(CASE WHEN execution_status = 'pending_verification' THEN 1 ELSE 0 END) AS pending_verification, "
        "SUM(CASE WHEN execution_status = 'needs_rollback' THEN 1 ELSE 0 END) AS needs_rollback, "
        "SUM(CASE WHEN execution_status = 'completed' THEN 1 ELSE 0 END) AS completed, "
        "SUM(CASE WHEN approval_status = 'pending' THEN 1 ELSE 0 END) AS approval_pending "
        "FROM promo_collaboration_tasks t WHERE 1=1" + scope + store_clause,
        params,
    ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


@router.post("/collaboration/tasks", status_code=201)
def create_collaboration_task(
    body: CollaborationTaskIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """创建本地执行任务；不触发任何万相台写操作。"""
    ensure_promo_collaboration_tables(db)
    _validate_statuses(body.approval_status, body.execution_status)
    plan = _visible_plan(db, body.plan_id, user)
    if not plan:
        raise HTTPException(status_code=404, detail="推广计划不存在或无权访问")
    if body.action_record_id:
        action = db.execute(
            "SELECT id, status FROM promo_action_records WHERE id = ? AND plan_id = ? AND store_id = ?",
            (body.action_record_id, plan["id"], plan["store_id"]),
        ).fetchone()
        if not action:
            raise HTTPException(status_code=404, detail="关联动作不存在或与计划不匹配")
        execution_status = ACTION_EXECUTION_STATUS.get(action["status"], "executing")
    else:
        execution_status = body.execution_status
    now = _now()
    cursor = db.execute(
        "INSERT INTO promo_collaboration_tasks (store_id, plan_id, action_record_id, decision_record_id, title, description, owner_id, owner_name, planned_at, approval_status, execution_status, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (plan["store_id"], body.plan_id, body.action_record_id, body.decision_record_id, body.title, body.description, body.owner_id, body.owner_name, body.planned_at,
         body.approval_status, execution_status, user["id"], now, now),
    )
    log_op(db, user, "promotions", "collaboration_create", body.title, f"计划#{body.plan_id}")
    return _serialize_task(db, _task_row(db, cursor.lastrowid, user))


@router.patch("/collaboration/tasks/{task_id}")
def update_collaboration_task(
    task_id: int,
    body: CollaborationTaskUpdateIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    ensure_promo_collaboration_tables(db)
    _validate_statuses(body.approval_status, body.execution_status)
    task = _task_row(db, task_id, user)
    if not task:
        raise HTTPException(status_code=404, detail="协同任务不存在或无权访问")
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=422, detail="请提供至少一个要更新的字段")
    if task["action_record_id"] is not None and "execution_status" in fields:
        raise HTTPException(status_code=409, detail="关联动作的执行状态由动作执行和验证结果自动同步")
    fields["updated_at"] = _now()
    db.execute(
        "UPDATE promo_collaboration_tasks SET " + ", ".join(f"{name} = ?" for name in fields) + " WHERE id = ?",
        [*fields.values(), task_id],
    )
    log_op(db, user, "promotions", "collaboration_update", str(task_id), ",".join(fields.keys()))
    return _serialize_task(db, _task_row(db, task_id, user))


@router.post("/collaboration/tasks/{task_id}/reminders", status_code=201)
def create_collaboration_reminder(
    task_id: int,
    body: ReminderIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    ensure_promo_collaboration_tables(db)
    task = _task_row(db, task_id, user)
    if not task:
        raise HTTPException(status_code=404, detail="协同任务不存在或无权访问")
    if task["action_record_id"] is not None:
        action = db.execute(
            "SELECT status FROM promo_action_records WHERE id = ?",
            (task["action_record_id"],),
        ).fetchone()
        if not action or action["status"] != "failed":
            raise HTTPException(status_code=409, detail="关联动作需完成验证且判定失败后才能登记回退建议")
    now = _now()
    cursor = db.execute(
        "INSERT INTO promo_collaboration_reminders (task_id, message, remind_at, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
        (task_id, body.message, body.remind_at, user["id"], now),
    )
    log_op(db, user, "promotions", "collaboration_reminder", str(task_id), body.message)
    return {"id": cursor.lastrowid, "task_id": task_id, "message": body.message, "remind_at": body.remind_at, "created_at": now, "queued": True}


@router.post("/collaboration/tasks/{task_id}/rollback-suggestion")
def suggest_collaboration_rollback(
    task_id: int,
    body: RollbackSuggestionIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """登记需回退建议，不会实际修改万相台计划。"""
    ensure_promo_collaboration_tables(db)
    if not _task_row(db, task_id, user):
        raise HTTPException(status_code=404, detail="协同任务不存在或无权访问")
    db.execute(
        "UPDATE promo_collaboration_tasks SET execution_status = 'needs_rollback', rollback_reason = ?, updated_at = ? WHERE id = ?",
        (body.reason, _now(), task_id),
    )
    log_op(db, user, "promotions", "collaboration_rollback_suggestion", str(task_id), body.reason)
    return {"task": _serialize_task(db, _task_row(db, task_id, user)), "applied_to_platform": False}
