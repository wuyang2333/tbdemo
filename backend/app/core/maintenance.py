"""后台任务维护模式的持久化状态与自动恢复。"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

from backend.app.core.db import connect_db

META_KEY = "task_maintenance"
ALL_TASKS = (
    "inspect",
    "realtime_sync",
    "product_catalog_sync",
    "report_push",
    "hourly_push",
    "promo_daily",
    "backup",
    "data_cleanup",
    "log_rotate",
)
DEFAULT_PAUSE_TASKS = (
    "inspect",
    "realtime_sync",
    "product_catalog_sync",
    "report_push",
    "hourly_push",
    "promo_daily",
    "data_cleanup",
)

_lock = threading.RLock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _default_state() -> dict:
    return {
        "enabled": False,
        "reason": "",
        "started_at": None,
        "ends_at": None,
        "created_by": "",
        "pause_tasks": list(DEFAULT_PAUSE_TASKS),
        "resume_strategy": "next_cycle",
        "pending_resume": [],
        "resumed_at": None,
    }


def _normalize(raw: object) -> dict:
    state = _default_state()
    if isinstance(raw, dict):
        state.update(raw)
    state["enabled"] = bool(state.get("enabled"))
    state["reason"] = str(state.get("reason") or "")[:200]
    state["created_by"] = str(state.get("created_by") or "")[:80]
    state["pause_tasks"] = [name for name in state.get("pause_tasks") or [] if name in ALL_TASKS]
    state["pending_resume"] = [name for name in state.get("pending_resume") or [] if name in ALL_TASKS]
    if state.get("resume_strategy") not in {"next_cycle", "run_once"}:
        state["resume_strategy"] = "next_cycle"
    return state


def _read(conn) -> dict:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (META_KEY,)).fetchone()
    if not row or not row["value"]:
        return _default_state()
    try:
        return _normalize(json.loads(row["value"]))
    except (TypeError, ValueError):
        return _default_state()


def _write(conn, state: dict) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (META_KEY, json.dumps(_normalize(state), ensure_ascii=False)),
    )


def _expired(state: dict) -> bool:
    if not state["enabled"] or not state.get("ends_at"):
        return False
    try:
        ends_at = datetime.fromisoformat(state["ends_at"])
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        return ends_at <= _now()
    except (TypeError, ValueError):
        return False


def _resume(conn, state: dict, user_id: int, username: str, action: str) -> dict:
    paused = list(state.get("pause_tasks") or [])
    state["enabled"] = False
    state["resumed_at"] = _now().isoformat()
    state["pending_resume"] = paused if state.get("resume_strategy") == "run_once" else []
    _write(conn, state)
    conn.execute(
        """
        INSERT INTO op_logs (module, user_id, username, action, target_name, detail, created_at)
        VALUES ('system', ?, ?, ?, '后台任务维护模式', ?, ?)
        """,
        (
            user_id,
            username,
            action,
            f"维护已恢复；原因：{state.get('reason') or '未填写'}；恢复策略：{state.get('resume_strategy')}",
            _now().isoformat(),
        ),
    )
    return state


def get_maintenance(conn=None, auto_resume: bool = True) -> dict:
    """读取维护状态；到期时原子地自动恢复。"""
    owns_connection = conn is None
    db = conn or connect_db()
    try:
        with _lock:
            state = _read(db)
            if auto_resume and _expired(state):
                state = _resume(db, state, 0, "系统", "maintenance_auto_resume")
                db.commit()
            return dict(state)
    finally:
        if owns_connection:
            db.close()


def is_task_paused(task_name: str, conn=None) -> bool:
    state = get_maintenance(conn, auto_resume=True)
    return bool(state["enabled"] and task_name in state["pause_tasks"])


def set_maintenance(
    conn,
    *,
    enabled: bool,
    actor: dict,
    reason: str = "",
    duration_minutes: int = 0,
    pause_tasks: list[str] | None = None,
    resume_strategy: str = "next_cycle",
) -> dict:
    with _lock:
        current = _read(conn)
        now = _now()
        if enabled:
            valid_tasks = list(dict.fromkeys(name for name in (pause_tasks or []) if name in ALL_TASKS))
            state = {
                **current,
                "enabled": True,
                "reason": (reason or "系统维护")[:200],
                "started_at": current.get("started_at") if current.get("enabled") else now.isoformat(),
                "ends_at": (now + timedelta(minutes=duration_minutes)).isoformat() if duration_minutes > 0 else None,
                "created_by": actor.get("nickname") or actor.get("username") or "管理员",
                "pause_tasks": valid_tasks,
                "resume_strategy": resume_strategy,
                "pending_resume": [],
                "resumed_at": None,
            }
            _write(conn, state)
            return state
        if not current["enabled"]:
            return current
        return _resume(
            conn,
            current,
            int(actor.get("id") or 0),
            actor.get("username") or "管理员",
            "maintenance_resume",
        )


def claim_pending_resume_tasks() -> list[str]:
    """一次性领取恢复后需要补跑的任务，避免 watcher 重复执行。"""
    conn = connect_db()
    try:
        with _lock:
            state = _read(conn)
            tasks = list(state.get("pending_resume") or [])
            if tasks:
                state["pending_resume"] = []
                _write(conn, state)
                conn.commit()
            return tasks
    finally:
        conn.close()
