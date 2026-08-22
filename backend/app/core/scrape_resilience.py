"""抓取重试与登录失效熔断。"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeVar


T = TypeVar("T")

RETRY_DELAYS: tuple[float, ...] = (10.0, 30.0, 120.0)

_LOGIN_MARKERS = (
    "you must login",
    "登录已失效",
    "登录已过期",
    "登录态无效",
    "未找到淘宝登录态",
    "未找到阿里妈妈登录态",
    "请重新登录",
    "重新绑定",
    "token expired",
    "token已过期",
    "session expired",
    "会话已过期",
    "会话过期",
)
_TRANSIENT_MARKERS = (
    "请求超时",
    "请求失败",
    "返回异常",
    "稍后再试",
    "安全验证",
    "验证码",
    "滑块",
    "风控",
    "操作过于频繁",
    "could not connect",
    "connection reset",
    "connection refused",
    "timed out",
    "系统繁忙",
    "服务异常",
    "网络异常",
    "curl: (7)",
    "curl: (28)",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
)

_circuit_lock = threading.Lock()
_login_circuits: dict[tuple[str, int], tuple[tuple[int, int] | None, str]] = {}


def is_login_error(error: BaseException | str) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in _LOGIN_MARKERS)


def is_transient_error(error: BaseException | str) -> bool:
    text = str(error).lower()
    return not is_login_error(error) and any(marker in text for marker in _TRANSIENT_MARKERS)


def retry_with_backoff(
    operation: Callable[[], T],
    *,
    should_retry: Callable[[BaseException], bool] = is_transient_error,
    delays: Sequence[float] = RETRY_DELAYS,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """瞬时失败按 10 秒、30 秒、2 分钟退避，并添加少量随机抖动。"""
    for delay in (*delays, None):
        try:
            return operation()
        except Exception as exc:
            if delay is None or not should_retry(exc):
                raise
            jitter = random.uniform(0, min(float(delay) * 0.2, 5.0))
            sleep(float(delay) + jitter)
    raise RuntimeError("unreachable")


def _profile_fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def ensure_login_available(
    source: str,
    store_id: int,
    profile: Path,
    error_type: type[Exception],
) -> None:
    """档案未变化时快速拒绝已确认登录失效的数据源。"""
    key = (source, store_id)
    fingerprint = _profile_fingerprint(profile)
    with _circuit_lock:
        state = _login_circuits.get(key)
        if state is None:
            return
        blocked_fingerprint, message = state
        if fingerprint != blocked_fingerprint:
            _login_circuits.pop(key, None)
            return
    raise error_type(f"{message}；已暂停自动抓取，请重新登录后再试")


def trip_login_circuit(source: str, store_id: int, profile: Path, message: str) -> None:
    with _circuit_lock:
        _login_circuits[(source, store_id)] = (_profile_fingerprint(profile), message)


def clear_login_circuit(source: str, store_id: int) -> None:
    with _circuit_lock:
        _login_circuits.pop((source, store_id), None)


def reset_login_circuits() -> None:
    """仅供测试清理进程内状态。"""
    with _circuit_lock:
        _login_circuits.clear()
