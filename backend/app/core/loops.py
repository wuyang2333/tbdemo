"""后台循环运行状态记录与日志。

让 main.py 里 4 个"静默循环"变得可观测：
- 每次运行更新内存状态表（最后运行/成功时间、连续失败次数、错误信息、耗时）
- 失败必写 ERROR 日志到 logs/loops.log；成功不落盘（避免每分钟刷屏，状态表仍完整记录）
- 连续失败达到 3 的倍数时，尝试通过 pushplus 推送告警（未配置 token 则静默跳过）
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from backend.app.core.db import connect_db

# logs/ 目录位于项目根（backend/app/core/loops.py 向上 3 级 = D:/demo/logs）
LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_logger = logging.getLogger("workbench.loops")
if not _logger.handlers:
    _handler = logging.FileHandler(LOG_DIR / "loops.log", encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False

_lock = threading.Lock()
_loops: dict[str, dict] = {}
_last_alert_at: dict[str, float] = {}  # 同一循环 10 分钟内最多告警一次，防告警风暴


def _init(name: str) -> dict:
    with _lock:
        st = _loops.get(name)
        if st is None:
            st = {
                "name": name,
                "last_run": None,
                "last_success": None,
                "last_error": None,
                "error_count": 0,
                "run_count": 0,
                "success_count": 0,
                "last_duration": 0.0,
                "running": False,
                "last_started": None,
            }
            _loops[name] = st
        return st


def register(name: str) -> None:
    """预置循环状态条目（服务启动时调用，保证查询端点总能列出全部循环）。"""
    _init(name)


def mark_running(name: str) -> None:
    """标记循环正在执行（用于长时间同步的可见性）。"""
    st = _init(name)
    with _lock:
        st["running"] = True
        st["last_started"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def record_success(name: str, duration: float) -> dict:
    st = _init(name)
    with _lock:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st["last_run"] = now
        st["last_success"] = now
        st["last_error"] = None
        st["error_count"] = 0
        st["run_count"] += 1
        st["success_count"] += 1
        st["last_duration"] = round(duration, 1)
        st["running"] = False
    _logger.debug("%s 成功（%.1fs）", name, duration)
    return st


def record_error(name: str, exc: BaseException, duration: float) -> dict:
    st = _init(name)
    with _lock:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st["last_run"] = now
        st["last_error"] = (str(exc) or exc.__class__.__name__)[:300]
        st["error_count"] += 1
        st["run_count"] += 1
        st["last_duration"] = round(duration, 1)
        st["running"] = False
        count = st["error_count"]
        err = st["last_error"]
    _logger.error("%s 失败（连续 %d 次，%.1fs）：%s", name, count, duration, err)
    if count % 3 == 0:
        _try_alert(name, err, count)
    return st


def log_event(name: str, msg: str) -> None:
    """记录一次真实动作（如推送成功），INFO 落盘。"""
    _logger.info("[%s] %s", name, msg)


def get_status(name: str) -> dict:
    return dict(_init(name))


def get_all_status() -> list[dict]:
    with _lock:
        return [dict(st) for st in _loops.values()]


def _try_alert(name: str, error: str, count: int) -> None:
    token = _read_pushplus_token()
    if not token:
        return
    with _lock:
        last = _last_alert_at.get(name, 0.0)
        if time.time() - last < 600:
            return
        _last_alert_at[name] = time.time()
    try:
        from backend.app.api.alerts import send_pushplus

        send_pushplus(
            token,
            "淘宝运营工作台-后台循环异常",
            f"循环 {name} 连续失败 {count} 次\n最近错误：{error}",
        )
        _logger.info("[%s] 已推送告警（连续失败 %d 次）", name, count)
    except Exception:
        _logger.exception("[%s] 告警推送失败", name)


def _read_pushplus_token() -> str:
    """从 meta 表 hourly_push_config 读取 pushplus token（未配置返回空串）。"""
    conn = None
    try:
        conn = connect_db()
        row = conn.execute("SELECT value FROM meta WHERE key = 'hourly_push_config'").fetchone()
        if row and row["value"]:
            return str(json.loads(row["value"]).get("token") or "")
        return ""
    except Exception:
        return ""
    finally:
        if conn is not None:
            conn.close()
