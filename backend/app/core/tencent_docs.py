"""腾讯文档在线表格与礼品单双向同步。"""

from __future__ import annotations

import json
import mimetypes
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

import httpx

try:
    import websocket
except ImportError:
    websocket = None

from backend.app.core.db import DB_PATH


META_KEY = "tencent_docs_gifts_config"
OAUTH_AUTHORIZE_URL = "https://docs.qq.com/oauth/v2/authorize"
OAUTH_TOKEN_URL = "https://docs.qq.com/oauth/v2/token"
API_ROOT = "https://docs.qq.com"
DEFAULT_DOCUMENT_URL = "https://docs.qq.com/sheet/DTG1YaFV2eUhMRGdF"
SYNC_COLUMNS = 13
POLL_MINUTES = 15
AUTO_ROW_BUFFER = 50
SHEET_METADATA_TTL_HOURS = 24
QUOTA_BACKOFF_HOURS = 4
MANUAL_TOKEN_VALID_DAYS = 30
QUOTA_EXHAUSTED_MESSAGE = "腾讯文档官方 API 额度已用尽，请等待额度恢复后再同步"
AUTH_REQUIRED_MESSAGE = "腾讯文档授权已失效，请重新填写 Access Token，或完成 OAuth 自动授权"
_SYNC_LOCK = threading.Lock()
HEADERS = [
    "系统礼品单ID",
    "日期",
    "下单时间",
    "店铺",
    "关键词",
    "规格",
    "金额",
    "佣金",
    "旺旺号",
    "订单号",
    "评论状态",
    "结款状态",
    "负责人",
]
REVIEW_LABELS = {"none": "未评论", "reviewed": "已评论"}
SETTLE_LABELS = {"unsettled": "未结款", "settled": "已结款"}


class TencentDocsError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_text() -> str:
    return _now().isoformat()


def parse_file_id(document_url: str) -> str:
    value = document_url.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc.lower() not in {"docs.qq.com", "www.docs.qq.com"} or len(parts) < 2 or parts[0] != "sheet":
        raise TencentDocsError("请输入有效的腾讯在线表格链接")
    return parts[1]


def _load_config(db) -> dict:
    row = db.execute("SELECT value FROM meta WHERE key = ?", (META_KEY,)).fetchone()
    data = {}
    if row and row["value"]:
        try:
            loaded = json.loads(row["value"])
            if isinstance(loaded, dict):
                data = loaded
        except (TypeError, ValueError):
            data = {}
    defaults = {
        "enabled": False,
        "document_url": DEFAULT_DOCUMENT_URL,
        "file_id": parse_file_id(DEFAULT_DOCUMENT_URL),
        "sheet_id": "",
        "sheet_title": "",
        "sheet_row_count": 0,
        "sheet_row_total": 0,
        "sheet_metadata_refreshed_at": "",
        "client_id": "",
        "client_secret": "",
        "redirect_uri": "",
        "access_token": "",
        "refresh_token": "",
        "open_id": "",
        "token_expires_at": "",
        "token_source": "",
        "auth_required": False,
        "auth_failure_at": "",
        "auth_error_detail": "",
        "oauth_state": "",
        "oauth_state_expires_at": "",
        "last_sync_at": "",
        "last_error": "",
        "last_result": {},
        "quota_backoff_until": "",
        "browser_fallback_enabled": False,
        "browser_cdp_url": "http://127.0.0.1:9222",
    }
    defaults.update(data)
    return defaults


def _store_config(db, config: dict) -> None:
    db.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (META_KEY, json.dumps(config, ensure_ascii=False)),
    )


def _is_quota_exhausted(error: BaseException | str) -> bool:
    text = str(error).lower()
    return "requests use up" in text or "官方 api 额度已用尽" in text


def _is_auth_error(error: BaseException | str) -> bool:
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "authentication internal error",
            "access token",
            "access_token",
            "invalid token",
            "token invalid",
            "token expired",
            "token has expired",
            "unauthorized",
            "未授权",
            "鉴权",
            "令牌过期",
            "令牌已失效",
            "授权已失效",
        )
    )


def _friendly_error_message(error: BaseException | str) -> str:
    if _is_quota_exhausted(error):
        return QUOTA_EXHAUSTED_MESSAGE
    if _is_auth_error(error):
        return AUTH_REQUIRED_MESSAGE
    return str(error)


def _mark_auth_required(db, config: dict, detail: BaseException | str) -> str:
    config["auth_required"] = True
    config["auth_failure_at"] = _now_text()
    config["auth_error_detail"] = str(detail)[:500]
    config["last_error"] = AUTH_REQUIRED_MESSAGE
    _store_config(db, config)
    db.commit()
    return AUTH_REQUIRED_MESSAGE


def update_config(db, values: dict) -> dict:
    config = _load_config(db)
    previous_file_id = str(config.get("file_id") or "")
    previous_sheet_id = str(config.get("sheet_id") or "")
    for key, value in values.items():
        if key in config:
            if key == "browser_cdp_url":
                value = str(value or "").strip().rstrip("/") or "http://127.0.0.1:9222"
                parsed = urlparse(value)
                if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                    raise TencentDocsError("Chrome 调试地址必须是本机 localhost、127.0.0.1 或 ::1")
            if key == "browser_fallback_enabled":
                value = bool(value)
            config[key] = value
    if str(values.get("access_token") or "").strip():
        config["refresh_token"] = ""
        config["token_source"] = "manual"
        config["token_expires_at"] = (_now() + timedelta(days=MANUAL_TOKEN_VALID_DAYS)).isoformat()
        config["auth_required"] = False
        config["auth_failure_at"] = ""
        config["auth_error_detail"] = ""
        config["last_error"] = ""
    if "document_url" in values:
        config["file_id"] = parse_file_id(str(config["document_url"]))
    if str(config.get("file_id") or "") != previous_file_id or str(config.get("sheet_id") or "") != previous_sheet_id:
        config["sheet_title"] = ""
        config["sheet_row_count"] = 0
        config["sheet_row_total"] = 0
        config["sheet_metadata_refreshed_at"] = ""
    _store_config(db, config)
    return config


def public_config(db) -> dict:
    config = _load_config(db)
    token_source = str(config.get("token_source") or "")
    if not token_source:
        token_source = "oauth" if config.get("refresh_token") else "manual" if config.get("access_token") else ""
    auth_required = bool(config.get("auth_required"))
    return {
        "enabled": bool(config["enabled"]),
        "document_url": config["document_url"],
        "file_id": config["file_id"],
        "sheet_id": config["sheet_id"],
        "sheet_title": config["sheet_title"],
        "client_id": config["client_id"],
        "client_secret_configured": bool(config["client_secret"]),
        "access_token_configured": bool(config["access_token"]),
        "redirect_uri": config["redirect_uri"],
        "authorized": bool(config["access_token"] and config["open_id"] and not auth_required),
        "token_expires_at": config["token_expires_at"],
        "token_source": token_source,
        "auto_refresh_enabled": bool(config["client_secret"] and config["refresh_token"]),
        "auth_required": auth_required,
        "auth_failure_at": config.get("auth_failure_at", ""),
        "last_sync_at": config["last_sync_at"],
        "last_error": config["last_error"],
        "last_result": config["last_result"],
        "quota_backoff_until": config["quota_backoff_until"],
        "browser_fallback_enabled": bool(config["browser_fallback_enabled"]),
        "browser_cdp_url": config["browser_cdp_url"],
        "poll_minutes": POLL_MINUTES,
    }


def build_authorization_url(db) -> str:
    config = _load_config(db)
    if not config["client_id"] or not config["client_secret"]:
        raise TencentDocsError("请先填写 Client ID 和 Client Secret")
    redirect_uri = str(config["redirect_uri"] or "").strip()
    if not redirect_uri.lower().startswith("https://"):
        raise TencentDocsError("腾讯文档 OAuth 回调地址必须使用 HTTPS")
    state = secrets.token_urlsafe(32)
    config["oauth_state"] = state
    config["oauth_state_expires_at"] = (_now() + timedelta(minutes=15)).isoformat()
    _store_config(db, config)
    return OAUTH_AUTHORIZE_URL + "?" + urlencode(
        {
            "client_id": config["client_id"],
            "redirect_uri": redirect_uri,
            "new_login": "1",
            "response_type": "code",
            "scope": "all",
            "state": state,
        }
    )


def exchange_authorization_code(db, code: str, state: str) -> dict:
    config = _load_config(db)
    if not code or not state or not secrets.compare_digest(state, str(config["oauth_state"] or "")):
        raise TencentDocsError("授权状态校验失败，请重新发起授权")
    try:
        expires_at = datetime.fromisoformat(str(config["oauth_state_expires_at"]))
    except (TypeError, ValueError):
        raise TencentDocsError("授权请求已失效，请重新发起授权") from None
    if expires_at <= _now():
        raise TencentDocsError("授权请求已过期，请重新发起授权")
    try:
        response = httpx.get(
            OAUTH_TOKEN_URL,
            params={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "redirect_uri": config["redirect_uri"],
                "grant_type": "authorization_code",
                "code": code,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TencentDocsError(f"腾讯文档授权换取令牌失败：{exc}") from exc
    _save_token_payload(config, payload)
    config["oauth_state"] = ""
    config["oauth_state_expires_at"] = ""
    config["last_error"] = ""
    _store_config(db, config)
    return public_config(db)


def _save_token_payload(config: dict, payload: dict) -> None:
    access_token = str(payload.get("access_token") or "")
    open_id = str(payload.get("user_id") or payload.get("open_id") or config.get("open_id") or "")
    if not access_token or not open_id:
        raise TencentDocsError(str(payload.get("error_description") or payload.get("message") or "腾讯文档未返回有效令牌"))
    config["access_token"] = access_token
    config["open_id"] = open_id
    if payload.get("refresh_token"):
        config["refresh_token"] = str(payload["refresh_token"])
    expires_in = max(int(payload.get("expires_in") or 259200), 300)
    config["token_expires_at"] = (_now() + timedelta(seconds=expires_in)).isoformat()
    config["token_source"] = "oauth"
    config["auth_required"] = False
    config["auth_failure_at"] = ""
    config["auth_error_detail"] = ""
    config["last_error"] = ""


def clear_authorization(db) -> None:
    config = _load_config(db)
    for key in (
        "access_token",
        "refresh_token",
        "open_id",
        "token_expires_at",
        "token_source",
        "auth_failure_at",
        "auth_error_detail",
        "oauth_state",
        "oauth_state_expires_at",
    ):
        config[key] = ""
    config["auth_required"] = False
    config["last_error"] = ""
    config["enabled"] = False
    _store_config(db, config)


class TencentDocsClient:
    def __init__(self, db):
        self.db = db
        self.config = _load_config(db)
        self._ensure_token()

    def _ensure_token(self) -> None:
        if self.config.get("auth_required"):
            raise TencentDocsError(AUTH_REQUIRED_MESSAGE)
        expires_at = None
        try:
            expires_at = datetime.fromisoformat(str(self.config.get("token_expires_at") or ""))
        except (TypeError, ValueError):
            pass
        if self.config.get("access_token") and self.config.get("open_id"):
            if expires_at is None or expires_at > _now() + timedelta(minutes=5):
                return
        if not self.config.get("refresh_token"):
            message = _mark_auth_required(self.db, self.config, "Access Token 已到期且没有 Refresh Token")
            raise TencentDocsError(message)
        self._refresh_token()

    def _refresh_token(self) -> None:
        response = None
        try:
            response = httpx.get(
                OAUTH_TOKEN_URL,
                params={
                    "client_id": self.config["client_id"],
                    "client_secret": self.config["client_secret"],
                    "grant_type": "refresh_token",
                    "refresh_token": self.config["refresh_token"],
                },
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            message = str(exc)
            if response is not None:
                try:
                    error_payload = response.json()
                    message = str(error_payload.get("message") or error_payload.get("msg") or error_payload.get("error_description") or message)
                except ValueError:
                    pass
            status_code = getattr(response, "status_code", 0) if response is not None else 0
            if status_code in {400, 401, 403} or _is_auth_error(message):
                friendly = _mark_auth_required(self.db, self.config, message)
                raise TencentDocsError(friendly) from exc
            raise TencentDocsError(f"腾讯文档令牌暂时无法刷新，请稍后自动重试：{message}") from exc
        try:
            _save_token_payload(self.config, payload)
        except (TencentDocsError, TypeError, ValueError) as exc:
            friendly = _mark_auth_required(self.db, self.config, exc)
            raise TencentDocsError(friendly) from exc
        _store_config(self.db, self.config)
        self.db.commit()

    def _headers(self) -> dict[str, str]:
        return {
            "Access-Token": self.config["access_token"],
            "Client-Id": self.config["client_id"],
            "Open-Id": self.config["open_id"],
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            return self._request_once(method, path, **kwargs)
        except TencentDocsError as exc:
            if not _is_auth_error(exc):
                raise
            if self.config.get("refresh_token") and self.config.get("client_secret"):
                self._refresh_token()
                try:
                    return self._request_once(method, path, **kwargs)
                except TencentDocsError as retry_error:
                    if _is_auth_error(retry_error):
                        message = _mark_auth_required(self.db, self.config, retry_error)
                        raise TencentDocsError(message) from retry_error
                    raise
            message = _mark_auth_required(self.db, self.config, exc)
            raise TencentDocsError(message) from exc

    def _request_once(self, method: str, path: str, **kwargs) -> dict:
        response = None
        try:
            response = httpx.request(method, API_ROOT + path, headers=self._headers(), timeout=30.0, **kwargs)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            message = str(exc)
            if response is not None:
                try:
                    error_payload = response.json()
                    message = str(error_payload.get("message") or error_payload.get("msg") or message)
                except ValueError:
                    pass
            if _is_quota_exhausted(message):
                raise TencentDocsError(QUOTA_EXHAUSTED_MESSAGE) from exc
            raise TencentDocsError(f"腾讯文档接口调用失败：{message}") from exc
        code = payload.get("code", payload.get("ret", 0))
        if code not in (0, None):
            message = str(payload.get("message") or payload.get("msg") or f"腾讯文档返回错误 {code}")
            raise TencentDocsError(_friendly_error_message(message))
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    def get_sheets(self) -> list[dict]:
        data = self._request("GET", f"/openapi/spreadsheet/v3/files/{quote(self.config['file_id'], safe='')}")
        properties = data.get("properties") or []
        return [item for item in properties if isinstance(item, dict)]

    def get_range(self, sheet_id: str, range_a1: str) -> dict:
        return self._request(
            "GET",
            f"/openapi/spreadsheet/v3/files/{quote(self.config['file_id'], safe='')}/{quote(sheet_id, safe='')}/{quote(range_a1, safe=':')}",
        ).get("gridData", {})

    def batch_update(self, requests: list[dict]) -> None:
        for index in range(0, len(requests), 5):
            self._request(
                "POST",
                f"/openapi/spreadsheet/v3/files/{quote(self.config['file_id'], safe='')}/batchUpdate",
                json={"requests": requests[index:index + 5]},
            )

    def ensure_row_capacity(self, sheet_id: str, current_total: int, required_total: int) -> int:
        """Add rows through the official spreadsheet batch-update API."""
        current_total = max(int(current_total or 0), 0)
        required_total = max(int(required_total or 0), current_total)
        if required_total <= current_total:
            return current_total
        self.batch_update(
            [{
                "insertDimensionRequest": {
                    "range": {
                        "sheetId": str(sheet_id),
                        "dimension": "ROWS",
                        "startIndex": current_total,
                        "endIndex": required_total,
                    },
                }
            }]
        )
        return required_total

    def convert_file_id(self) -> str:
        data = self._request(
            "GET",
            "/openapi/drive/v2/util/converter",
            params={"type": 2, "value": self.config["file_id"]},
        )
        file_id = str(data.get("fileID") or "")
        if not file_id:
            raise TencentDocsError("腾讯文档未返回可用于插入图片的文件 ID")
        return file_id

    def upload_image(self, image_path: Path) -> str:
        mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        with image_path.open("rb") as image_file:
            data = self._request(
                "POST",
                "/openapi/resources/v2/images",
                files={"image": (image_path.name, image_file, mime_type)},
            )
        image_id = str(data.get("imageID") or "")
        if not image_id:
            raise TencentDocsError("腾讯文档上传图片后未返回 imageID")
        return image_id

    def insert_cell_images(self, file_id: str, sheet_id: str, images: list[dict]) -> None:
        if not images:
            return
        self._request(
            "POST",
            f"/openapi/sheetbook/v2/{quote(file_id, safe='$')}:batchUpdate",
            json={"bookID": file_id, "insertImages": {"sheetID": sheet_id, "images": images}},
        )

    def clear_range(self, file_id: str, range_a1: str) -> None:
        self._request(
            "POST",
            f"/openapi/sheetbook/v2/{quote(file_id, safe='$')}/values/{quote(range_a1, safe='!:')}:clear",
        )


def _parse_a1_range(range_a1: str) -> tuple[int, int, int, int]:
    import re

    value = range_a1.split("!", 1)[-1].replace("$", "").strip().upper()
    match = re.fullmatch(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?", value)
    if not match:
        raise TencentDocsError(f"腾讯文档范围格式不支持：{range_a1}")

    def column_index(column: str) -> int:
        result = 0
        for char in column:
            result = result * 26 + ord(char) - ord("A") + 1
        return result - 1

    start_column = column_index(match.group(1))
    start_row = int(match.group(2)) - 1
    end_column = column_index(match.group(3) or match.group(1))
    end_row = int(match.group(4) or match.group(2)) - 1
    if min(start_row, end_row, start_column, end_column) < 0:
        raise TencentDocsError(f"腾讯文档范围必须从第 1 行、第 A 列开始：{range_a1}")
    return start_row, end_row, start_column, end_column


class TencentDocsBrowserClient:
    """通过已登录 Chrome 的本地 CDP 页面复用腾讯文档内部表格模型。"""

    transport = "browser"

    def __init__(self, db):
        self.db = db
        self.config = _load_config(db)
        self.file_id = str(self.config.get("file_id") or "")
        self.cdp_url = str(self.config.get("browser_cdp_url") or "http://127.0.0.1:9222").rstrip("/")
        self.timeout = 15.0
        self._socket = None
        self._message_id = 0
        self._lock = threading.Lock()

    def _connect(self) -> None:
        if websocket is None:
            raise TencentDocsError("浏览器备用通道缺少 websocket-client 依赖")
        try:
            response = httpx.get(f"{self.cdp_url}/json/list", timeout=5.0, trust_env=False)
            response.raise_for_status()
            pages = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TencentDocsError(f"无法连接 Chrome 调试端口 {self.cdp_url}：{exc}") from exc
        target = next(
            (
                page
                for page in pages
                if page.get("type") == "page"
                and self.file_id
                and f"/sheet/{self.file_id}" in str(page.get("url") or "")
            ),
            None,
        )
        if target is None:
            raise TencentDocsError(f"Chrome 中没有打开目标腾讯文档，请先打开文档（文件 ID：{self.file_id}）")
        ws_url = str(target.get("webSocketDebuggerUrl") or "")
        if not ws_url:
            raise TencentDocsError("Chrome 调试页未返回 WebSocket 地址")
        try:
            self._socket = websocket.create_connection(ws_url, timeout=self.timeout, origin="http://127.0.0.1")
        except Exception as exc:
            try:
                self._socket = websocket.create_connection(ws_url, timeout=self.timeout, suppress_origin=True)
            except Exception as retry_exc:
                raise TencentDocsError(f"无法连接 Chrome 调试页：{retry_exc}") from exc

    def _call(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            if self._socket is None:
                self._connect()
            self._message_id += 1
            message_id = self._message_id
            try:
                self._socket.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
                while True:
                    raw = self._socket.recv()
                    message = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                    if message.get("id") == message_id:
                        if "error" in message:
                            raise TencentDocsError(f"Chrome CDP 调用失败：{message['error']}")
                        return message.get("result") or {}
            except TencentDocsError:
                raise
            except Exception as exc:
                self.close()
                raise TencentDocsError(f"Chrome 调试连接中断：{exc}") from exc

    def close(self) -> None:
        socket = self._socket
        self._socket = None
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass

    def _evaluate(self, expression: str):
        result = self._call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
        )
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            exception = details.get("exception") or {}
            message = exception.get("description") or exception.get("value") or details.get("text") or "未知页面异常"
            raise TencentDocsError(f"腾讯文档浏览器接口执行失败：{message}")
        value = (result.get("result") or {}).get("value")
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return value
        return value

    def _page_context(self) -> dict:
        return self._evaluate(
            """(() => {
                const workbook = window.SpreadsheetApp?.workbook;
                const sheet = workbook?.activeSheet;
                if (!workbook || !sheet) throw new Error("当前页面不是可编辑的腾讯文档表格");
                return JSON.stringify({
                    sheetId: String(workbook.activeSheetId || ""),
                    title: String(sheet.getSheetName?.() || ""),
                    rowCount: Number(sheet.getRowCount?.() || 0),
                    colCount: Number(sheet.getColCount?.() || 0),
                });
            })()"""
        )

    def _assert_sheet(self, sheet_id: str, context: dict | None = None) -> dict:
        context = context or self._page_context()
        expected = str(sheet_id or self.config.get("sheet_id") or "")
        if expected and context.get("sheetId") != expected:
            raise TencentDocsError(
                f"Chrome 当前打开的是工作表 {context.get('sheetId') or '未知'}，不是配置的工作表 {expected}；请切换到目标子表"
            )
        return context

    def get_sheets(self) -> list[dict]:
        context = self._page_context()
        self._assert_sheet(str(self.config.get("sheet_id") or context.get("sheetId") or ""), context)
        row_count = max(int(context.get("rowCount") or 0), 2)
        return [{"sheetId": context["sheetId"], "title": context["title"], "rowCount": row_count, "rowTotal": row_count}]

    def get_range(self, sheet_id: str, range_a1: str) -> dict:
        start_row, end_row, start_column, end_column = _parse_a1_range(range_a1)
        self._assert_sheet(sheet_id)
        payload = json.dumps(
            {
                "sheetId": str(sheet_id),
                "startRow": start_row,
                "endRow": end_row,
                "startColumn": start_column,
                "endColumn": end_column,
            },
            ensure_ascii=False,
        )
        result = self._evaluate(
            f"""(() => {{
                const input = JSON.parse({json.dumps(payload)});
                const sheet = window.SpreadsheetApp.workbook.activeSheet;
                const rows = [];
                for (let row = input.startRow; row <= input.endRow; row++) {{
                    const values = [];
                    for (let col = input.startColumn; col <= input.endColumn; col++) {{
                        const cell = sheet.getCellDataAtPosition(row, col);
                        const value = cell?.value;
                        values.push({{cellValue: {{text: value == null ? "" : String(value)}}}});
                    }}
                    rows.push({{values}});
                }}
                return JSON.stringify({{startRow: input.startRow, rows}});
            }})()"""
        )
        return result if isinstance(result, dict) else {"startRow": start_row, "rows": []}

    def batch_update(self, requests: list[dict]) -> None:
        operations = []
        for request in requests:
            update = request.get("updateRangeRequest") if isinstance(request, dict) else None
            if not isinstance(update, dict):
                raise TencentDocsError("浏览器备用通道暂不支持该批量更新类型")
            grid = update.get("gridData") or {}
            rows = grid.get("rows") or []
            operations.append(
                {
                    "sheetId": str(update.get("sheetId") or self.config.get("sheet_id") or ""),
                    "startRow": int(grid.get("startRow") or 0),
                    "startColumn": int(grid.get("startColumn") or 0),
                    "rows": [
                        [
                            str(((cell.get("cellValue") or {}).get("text")) or "")
                            for cell in (row.get("values") or [])
                        ]
                        for row in rows
                    ],
                }
            )
        payload = json.dumps(operations, ensure_ascii=False)
        self._evaluate(
            f"""(async () => {{
                const operations = JSON.parse({json.dumps(payload)});
                const api = window.SpreadsheetApp.behaviorApi?.cellApi;
                if (!api?.setRangeValue) throw new Error("腾讯文档内部写入接口不可用");
                for (const operation of operations) {{
                    const rangeValues = [];
                    operation.rows.forEach((row, rowOffset) => row.forEach((value, colOffset) => rangeValues.push({{
                        rowIndex: operation.startRow + rowOffset,
                        colIndex: operation.startColumn + colOffset,
                        userEnterValue: value,
                    }})));
                    if (rangeValues.length) await api.setRangeValue({{sheetId: operation.sheetId, rangeValues}});
                }}
                return JSON.stringify({{updated: operations.length}});
            }})()"""
        )

    def ensure_row_capacity(self, sheet_id: str, current_total: int, required_total: int) -> int:
        raise TencentDocsError("腾讯文档浏览器备用通道暂不支持自动新增行，请先手动新增后重试")

    def convert_file_id(self) -> str:
        raise TencentDocsError("浏览器备用通道暂不支持图片上传，请先用官方 API 完成图片同步")

    def upload_image(self, image_path: Path) -> str:
        raise TencentDocsError("浏览器备用通道暂不支持图片上传，请先用官方 API 完成图片同步")

    def insert_cell_images(self, file_id: str, sheet_id: str, images: list[dict]) -> None:
        raise TencentDocsError("浏览器备用通道暂不支持图片插入，请先用官方 API 完成图片同步")

    def clear_range(self, file_id: str, range_a1: str) -> None:
        sheet_id, _, a1 = range_a1.partition("!")
        start_row, end_row, start_column, end_column = _parse_a1_range(a1 or range_a1)
        self._assert_sheet(sheet_id)
        self._evaluate(
            f"""(async () => {{
                const ranges = window.SpreadsheetApp.view?.getSelectionRanges?.() || [];
                const GridRange = ranges[0]?.constructor;
                if (!GridRange) throw new Error("腾讯文档范围对象不可用");
                const range = new GridRange({json.dumps(sheet_id)}, {start_row}, {end_row}, {start_column}, {end_column});
                await window.SpreadsheetApp.behaviorApi.cellApi.clearContent({{gridRanges: [range]}});
                return JSON.stringify({{cleared: true}});
            }})()"""
        )


def test_connection(db) -> dict:
    config = _load_config(db)
    try:
        client = TencentDocsClient(db)
        result = _test_connection_with_client(db, client)
        result["transport"] = "openapi"
        return result
    except TencentDocsError as primary_error:
        if not config.get("browser_fallback_enabled"):
            raise
        browser_client = None
        try:
            browser_client = TencentDocsBrowserClient(db)
            result = _test_connection_with_client(db, browser_client)
            result["transport"] = "browser"
            result["fallback_used"] = True
            result["primary_error"] = str(primary_error)
            return result
        except TencentDocsError as browser_error:
            raise TencentDocsError(f"官方 API 失败：{primary_error}；浏览器备用通道失败：{browser_error}") from browser_error
        finally:
            if browser_client is not None:
                close = getattr(browser_client, "close", None)
                if callable(close):
                    close()


def _test_connection_with_client(db, client) -> dict:
    sheets = client.get_sheets()
    if not sheets:
        raise TencentDocsError("腾讯在线表格中没有可用工作表")
    config = _load_config(db)
    selected = next((item for item in sheets if str(item.get("sheetId")) == str(config.get("sheet_id"))), sheets[0])
    config["sheet_id"] = str(selected.get("sheetId") or "")
    config["sheet_title"] = str(selected.get("title") or "")
    config["sheet_row_count"] = int(selected.get("rowCount") or 0)
    config["sheet_row_total"] = int(selected.get("rowTotal") or 200)
    config["sheet_metadata_refreshed_at"] = _now_text()
    config["last_error"] = ""
    _store_config(db, config)
    return {"ok": True, "sheet_id": config["sheet_id"], "sheet_title": config["sheet_title"], "sheets": sheets}


def _cell_text(cell: dict | None) -> str:
    if not isinstance(cell, dict):
        return ""
    value = cell.get("cellValue") or {}
    if not isinstance(value, dict):
        return ""
    if value.get("text") is not None:
        return str(value["text"])
    if value.get("number") is not None:
        number = value["number"]
        return str(int(number)) if isinstance(number, float) and number.is_integer() else str(number)
    link = value.get("link")
    if isinstance(link, dict):
        return str(link.get("text") or link.get("url") or "")
    return ""


def _read_table(client: TencentDocsClient, sheet: dict, minimum_rows: int) -> tuple[dict[int, list[str]], int]:
    used_rows = int(sheet.get("rowCount") or 0)
    row_total = max(int(sheet.get("rowTotal") or 200), 2)
    read_to = min(row_total, max(200, used_rows + 50, minimum_rows + 20))
    rows: dict[int, list[str]] = {}
    for start in range(1, read_to + 1, 1000):
        end = min(read_to, start + 999)
        grid = client.get_range(str(sheet["sheetId"]), f"A{start}:M{end}")
        start_row = int(grid.get("startRow", start - 1))
        for offset, row in enumerate(grid.get("rows") or []):
            values = [_cell_text(cell) for cell in (row.get("values") or [])[:SYNC_COLUMNS]]
            values.extend([""] * (SYNC_COLUMNS - len(values)))
            rows[start_row + offset + 1] = values
    return rows, row_total


def _gift_date(gift: dict) -> str:
    order_time = str(gift.get("order_time") or gift.get("created_at") or "")
    return order_time[:10] if len(order_time) >= 10 else ""


def _gift_values(gift: dict, *, include_cloud_fields: bool) -> list[str]:
    order_time = str(gift.get("order_time") or gift.get("created_at") or "")
    date_value = _gift_date(gift)
    time_source = order_time.split("T", 1)[-1] if "T" in order_time else order_time.split(" ", 1)[-1]
    time_value = time_source[:5] if len(time_source) >= 5 else ""
    values = [
        str(gift["id"]),
        date_value,
        time_value,
        str(gift.get("store_name") or ""),
        "" if gift.get("image") else str(gift.get("keyword") or ""),
        str(gift.get("spec") or ""),
        str(gift.get("price") or 0),
        str(gift.get("commission") or 0),
        str(gift.get("wangwang") or "") if include_cloud_fields else "",
        str(gift.get("order_no") or "") if include_cloud_fields else "",
        REVIEW_LABELS.get(str(gift.get("review_status")), str(gift.get("review_status") or "")),
        SETTLE_LABELS.get(str(gift.get("settle_status")), str(gift.get("settle_status") or "")),
        str(gift.get("owner_nickname") or ""),
    ]
    return values


def _row_payload(values: list[str]) -> dict:
    return {"values": [{"cellValue": {"text": str(value)}} for value in values]}


def _local_image_path(image: str) -> Path | None:
    if not image.startswith("/api/images/"):
        return None
    name = Path(image.rsplit("/", 1)[-1]).name
    path = DB_PATH.parent / "images" / name
    return path if path.is_file() else None


def _image_marker(image: str, row_number: int) -> str:
    return f"{image}#cell-r{row_number}-c5"


def _marker_cell(marker: str, fallback_row: int) -> tuple[int, int]:
    if "#cell-r" in marker:
        cell = marker.rsplit("#cell-r", 1)[-1]
        row_text, separator, column_text = cell.partition("-c")
        if separator and row_text.isdigit() and column_text.isdigit():
            return int(row_text), int(column_text)
    column = 5 if marker.endswith("#cell-col5") else 4
    return max(1, fallback_row - 1), column


def _groups(assignments: list[tuple[int, dict]]) -> list[list[tuple[int, dict]]]:
    grouped: list[list[tuple[int, dict]]] = []
    for item in sorted(assignments, key=lambda entry: entry[0]):
        if not grouped or item[0] != grouped[-1][-1][0] + 1:
            grouped.append([item])
        else:
            grouped[-1].append(item)
    return grouped


def _parse_config_time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


def _cached_sheet(config: dict) -> dict | None:
    refreshed_at = _parse_config_time(config.get("sheet_metadata_refreshed_at"))
    if (
        not config.get("sheet_id")
        or int(config.get("sheet_row_total") or 0) <= 0
        or refreshed_at is None
        or refreshed_at <= _now() - timedelta(hours=SHEET_METADATA_TTL_HOURS)
    ):
        return None
    return {
        "sheetId": str(config["sheet_id"]),
        "title": str(config.get("sheet_title") or ""),
        "rowCount": int(config.get("sheet_row_count") or 0),
        "rowTotal": int(config.get("sheet_row_total") or 200),
    }


def _quota_backoff_result(config: dict) -> dict | None:
    if config.get("browser_fallback_enabled"):
        return None
    backoff_until = _parse_config_time(config.get("quota_backoff_until"))
    if backoff_until is None or backoff_until <= _now():
        return None
    return {
        "ok": False,
        "skipped": True,
        "reason": f"腾讯文档官方 API 额度已用尽，将在 {backoff_until.astimezone().strftime('%H:%M')} 后自动重试",
        "pushed": 0,
        "pulled": 0,
        "errors": [],
    }


def _values_differ(cloud_values: list[str], start: int, desired_values: list[str]) -> bool:
    return cloud_values[start:start + len(desired_values)] != desired_values


def _cloud_rows_by_id(table_rows: dict[int, list[str]]) -> dict[int, tuple[int, list[str]]]:
    """Build the cloud gift index from the rows we actually read."""
    cloud_by_id: dict[int, tuple[int, list[str]]] = {}
    for row_number, values in table_rows.items():
        try:
            gift_id = int(str(values[0] or "").strip())
        except (TypeError, ValueError, IndexError):
            continue
        if gift_id > 0:
            cloud_by_id[gift_id] = (row_number, values)
    return cloud_by_id


def _layout_assignments(gifts: list[dict]) -> list[tuple[int, dict]]:
    assignments = []
    row_number = 2
    previous_date = None
    previous_owner = None
    # 腾讯文档先按日期分组，再按负责人分组，负责人组内按时间和 ID 排列。
    # 未填写负责人的礼品单放在当天最后。
    ordered = sorted(
        gifts,
        key=lambda gift: (
            _gift_date(gift) == "",
            _gift_date(gift),
            not str(gift.get("owner_nickname") or "").strip(),
            str(gift.get("owner_nickname") or "").strip().casefold(),
            not str(gift.get("order_time") or gift.get("created_at") or "").strip(),
            str(gift.get("order_time") or gift.get("created_at") or ""),
            int(gift["id"]),
        ),
    )
    for gift in ordered:
        owner_name = str(gift.get("owner_nickname") or "").strip()
        gift_date = _gift_date(gift)
        if previous_date is not None and gift_date != previous_date:
            row_number += 3
        elif previous_owner is not None and owner_name != previous_owner:
            row_number += 1
        assignments.append((row_number, gift))
        row_number += 1
        previous_date = gift_date
        previous_owner = owner_name
    return assignments


def _update_cloud_fields(db, gift: dict, cloud_values: list[str]) -> list[str]:
    errors = []
    wangwang = cloud_values[8].strip()
    order_no = cloud_values[9].strip()
    previous_wangwang = str(gift.get("wangwang") or "")
    previous_order_no = str(gift.get("order_no") or "")
    wangwang_changed = False
    if len(wangwang) > 100:
        errors.append(f"礼品单 {gift['id']} 的旺旺号超过 100 个字符")
    else:
        db.execute("UPDATE gifts SET wangwang = ? WHERE id = ?", (wangwang, gift["id"]))
        wangwang_changed = wangwang != previous_wangwang
    if order_no and (not order_no.isdigit() or len(order_no) > 40):
        errors.append(f"礼品单 {gift['id']} 的订单号格式不正确")
    else:
        duplicate = db.execute("SELECT id FROM gifts WHERE order_no = ? AND id != ?", (order_no, gift["id"])).fetchone() if order_no else None
        if duplicate:
            errors.append(f"订单号 {order_no} 已被礼品单 {duplicate['id']} 使用")
        elif order_no != previous_order_no:
            db.execute(
                """
                UPDATE gifts
                SET order_no = ?, remark_status = 'unremarked', remark_auto_pending = ?,
                    remark_attempts = 0, remark_attempted_at = NULL, remarked_at = NULL,
                    remark_error = '', remark_next_retry_at = NULL
                WHERE id = ?
                """,
                (order_no, 1 if order_no or wangwang else 0, gift["id"]),
            )
        elif wangwang_changed and not previous_order_no:
            db.execute(
                """
                UPDATE gifts
                SET remark_status = 'unremarked', remark_auto_pending = ?,
                    remark_attempts = 0, remark_attempted_at = NULL, remarked_at = NULL,
                    remark_error = '', remark_next_retry_at = NULL
                WHERE id = ?
                """,
                (1 if wangwang else 0, gift["id"]),
            )
    return errors


def sync_gifts(db, client: TencentDocsClient | None = None, *, force: bool = False) -> dict:
    with _SYNC_LOCK:
        config = _load_config(db)
        if not force:
            if config.get("auth_required") and not config.get("browser_fallback_enabled"):
                return {
                    "ok": False,
                    "skipped": True,
                    "requires_authorization": True,
                    "reason": AUTH_REQUIRED_MESSAGE,
                    "pushed": 0,
                    "pulled": 0,
                    "errors": [],
                }
            backoff_result = _quota_backoff_result(config)
            if backoff_result is not None:
                return backoff_result
        try:
            if client is not None:
                return _sync_gifts_locked(db, client)
            try:
                return _sync_gifts_locked(db, None)
            except TencentDocsError as primary_error:
                if not config.get("browser_fallback_enabled"):
                    raise
                browser_client = None
                try:
                    browser_client = TencentDocsBrowserClient(db)
                    result = _sync_gifts_locked(db, browser_client)
                    result["transport"] = "browser"
                    result["fallback_used"] = True
                    result["primary_error"] = str(primary_error)
                    config = _load_config(db)
                    config["last_result"] = result
                    config["last_error"] = "；".join(result.get("errors") or [])
                    _store_config(db, config)
                    return result
                except TencentDocsError as browser_error:
                    raise TencentDocsError(f"官方 API 失败：{primary_error}；浏览器备用通道失败：{browser_error}") from browser_error
                finally:
                    if browser_client is not None:
                        close = getattr(browser_client, "close", None)
                        if callable(close):
                            close()
        except TencentDocsError as exc:
            if _is_quota_exhausted(exc):
                config = _load_config(db)
                config["quota_backoff_until"] = (_now() + timedelta(hours=QUOTA_BACKOFF_HOURS)).isoformat()
                config["last_error"] = QUOTA_EXHAUSTED_MESSAGE
                _store_config(db, config)
                db.commit()
                raise TencentDocsError(QUOTA_EXHAUSTED_MESSAGE) from exc
            raise


def _sync_gifts_locked(db, client: TencentDocsClient | None = None) -> dict:
    config = _load_config(db)
    if not config["enabled"]:
        return {"ok": True, "skipped": True, "reason": "腾讯文档同步未启用", "pushed": 0, "pulled": 0, "errors": []}
    if not config["file_id"]:
        raise TencentDocsError("尚未配置腾讯在线表格链接")
    client = client or TencentDocsClient(db)
    sheet = _cached_sheet(config)
    sheet_metadata_refreshed = False
    if sheet is None:
        sheets = client.get_sheets()
        if not sheets:
            raise TencentDocsError("腾讯在线表格中没有可用工作表")
        sheet = next((item for item in sheets if str(item.get("sheetId")) == str(config.get("sheet_id"))), sheets[0])
        sheet_metadata_refreshed = True
    sheet_id = str(sheet.get("sheetId") or "")
    if not sheet_id:
        raise TencentDocsError("腾讯文档未返回工作表 ID")
    local_rows = [dict(row) for row in db.execute(
        """SELECT g.*, COALESCE(s.name, '') AS linked_store_name
        FROM gifts g LEFT JOIN stores s ON s.id = g.store_id ORDER BY g.id"""
    ).fetchall()]
    for gift in local_rows:
        gift["store_name"] = (gift.get("linked_store_name") if gift["store_id"] else gift.get("store_name")) or "未关联店铺"
    table_rows, row_total = _read_table(client, sheet, len(local_rows))
    cloud_by_id = _cloud_rows_by_id(table_rows)

    errors = []
    pulled = 0
    local_by_id = {int(gift["id"]): gift for gift in local_rows}
    for gift_id, (_, values) in cloud_by_id.items():
        gift = local_by_id.get(gift_id)
        if not gift:
            continue
        before = (str(gift.get("wangwang") or ""), str(gift.get("order_no") or ""))
        row_errors = _update_cloud_fields(db, gift, values)
        errors.extend(row_errors)
        refreshed = db.execute("SELECT wangwang, order_no FROM gifts WHERE id = ?", (gift_id,)).fetchone()
        if refreshed and before != (refreshed["wangwang"], refreshed["order_no"]):
            pulled += 1

    db.commit()

    local_rows = [dict(row) for row in db.execute(
        """SELECT g.*, COALESCE(s.name, '') AS linked_store_name
        FROM gifts g LEFT JOIN stores s ON s.id = g.store_id ORDER BY g.id"""
    ).fetchall()]
    for gift in local_rows:
        gift["store_name"] = (gift.get("linked_store_name") if gift["store_id"] else gift.get("store_name")) or "未关联店铺"

    assignments = _layout_assignments(local_rows)
    if assignments and assignments[-1][0] > row_total:
        # rowTotal is cached for up to 24 hours. The operator can add rows in
        # Tencent Docs during that window, so refresh metadata before failing.
        get_sheets = getattr(client, "get_sheets", None)
        sheets = get_sheets() if callable(get_sheets) else []
        refreshed_sheet = next(
            (item for item in sheets if str(item.get("sheetId")) == sheet_id),
            None,
        )
        refreshed_total = int((refreshed_sheet or {}).get("rowTotal") or 0)
        if refreshed_total > row_total:
            sheet = refreshed_sheet or sheet
            row_total = max(refreshed_total, 2)
            table_rows, row_total = _read_table(client, sheet, len(local_rows))
            cloud_by_id = _cloud_rows_by_id(table_rows)

            config = _load_config(db)
            config.update(
                {
                    "sheet_id": sheet_id,
                    "sheet_title": str(sheet.get("title") or ""),
                    "sheet_row_count": int(sheet.get("rowCount") or 0),
                    "sheet_row_total": row_total,
                    "sheet_metadata_refreshed_at": _now_text(),
                }
            )
            _store_config(db, config)
            db.commit()

        if assignments and assignments[-1][0] > row_total:
            required_total = assignments[-1][0] + AUTO_ROW_BUFFER
            ensure_capacity = getattr(client, "ensure_row_capacity", None)
            if not callable(ensure_capacity):
                raise TencentDocsError(
                    f"腾讯在线表格可用行数不足：需要第 {assignments[-1][0]} 行，"
                    f"当前只有 {row_total} 行；请在文档中新增行后重试"
                )
            try:
                row_total = int(ensure_capacity(sheet_id, row_total, required_total) or required_total)
            except TencentDocsError:
                raise
            sheet = dict(sheet)
            sheet["rowTotal"] = row_total
            table_rows, row_total = _read_table(client, sheet, len(local_rows))
            cloud_by_id = _cloud_rows_by_id(table_rows)
            config = _load_config(db)
            config.update(
                {
                    "sheet_row_total": row_total,
                    "sheet_metadata_refreshed_at": _now_text(),
                }
            )
            _store_config(db, config)
            db.commit()

        if assignments and assignments[-1][0] > row_total:
            raise TencentDocsError(
                f"腾讯在线表格可用行数不足：需要第 {assignments[-1][0]} 行，"
                f"当前只有 {row_total} 行；请在文档中新增行后重试"
            )
    existing = [(row_number, gift) for row_number, gift in assignments if int(gift["id"]) in cloud_by_id]
    new = [(row_number, gift) for row_number, gift in assignments if int(gift["id"]) not in cloud_by_id]
    existing_same = [
        (row_number, gift)
        for row_number, gift in existing
        if cloud_by_id[int(gift["id"])][0] == row_number
    ]
    existing_moved = [
        (row_number, gift)
        for row_number, gift in existing
        if cloud_by_id[int(gift["id"])][0] != row_number
    ]
    desired_rows = {row_number for row_number, _ in assignments}
    rows_to_clear = sorted(
        row_number
        for gift_id, (row_number, _) in cloud_by_id.items()
        if gift_id not in local_by_id or row_number not in desired_rows
    )

    desired_by_id = {
        int(gift["id"]): _gift_values(gift, include_cloud_fields=False)
        for gift in local_rows
    }
    requests = []
    if table_rows.get(1, [""] * SYNC_COLUMNS)[:SYNC_COLUMNS] != HEADERS:
        requests.append({
            "updateRangeRequest": {
                "sheetId": sheet_id,
                "gridData": {"startRow": 0, "startColumn": 0, "rows": [_row_payload(HEADERS)]},
            }
        })
    for group in _groups([(row_number, {}) for row_number in rows_to_clear]):
        requests.append(
            {
                "updateRangeRequest": {
                    "sheetId": sheet_id,
                    "gridData": {
                        "startRow": group[0][0] - 1,
                        "startColumn": 0,
                        "rows": [_row_payload([""] * SYNC_COLUMNS) for _ in group],
                    },
                }
            }
        )
    identity_changes = [
        (row_number, gift)
        for row_number, gift in existing_same
        if _values_differ(cloud_by_id[int(gift["id"])][1], 0, desired_by_id[int(gift["id"])][:4])
    ]
    existing_without_images = [
        (row_number, gift)
        for row_number, gift in existing_same
        if not gift.get("image")
        and _values_differ(cloud_by_id[int(gift["id"])][1], 4, desired_by_id[int(gift["id"])][4:8])
    ]
    existing_with_images = [
        (row_number, gift)
        for row_number, gift in existing_same
        if gift.get("image")
        and _values_differ(cloud_by_id[int(gift["id"])][1], 5, desired_by_id[int(gift["id"])][5:8])
    ]
    status_changes = [
        (row_number, gift)
        for row_number, gift in existing_same
        if _values_differ(cloud_by_id[int(gift["id"])][1], 10, desired_by_id[int(gift["id"])][10:])
    ]
    for group in _groups(identity_changes):
        requests.append(
            {
                "updateRangeRequest": {
                    "sheetId": sheet_id,
                    "gridData": {
                        "startRow": group[0][0] - 1,
                        "startColumn": 0,
                        "rows": [_row_payload(desired_by_id[int(gift["id"])][:4]) for _, gift in group],
                    },
                }
            }
        )
    for group in _groups(existing_without_images):
        requests.append(
            {
                "updateRangeRequest": {
                    "sheetId": sheet_id,
                    "gridData": {
                        "startRow": group[0][0] - 1,
                        "startColumn": 4,
                        "rows": [_row_payload(desired_by_id[int(gift["id"])][4:8]) for _, gift in group],
                    },
                }
            }
        )
    for group in _groups(existing_with_images):
        requests.append(
            {
                "updateRangeRequest": {
                    "sheetId": sheet_id,
                    "gridData": {
                        "startRow": group[0][0] - 1,
                        "startColumn": 5,
                        "rows": [_row_payload(desired_by_id[int(gift["id"])][5:8]) for _, gift in group],
                    },
                }
            }
        )
    for group in _groups(status_changes):
        requests.append(
            {
                "updateRangeRequest": {
                    "sheetId": sheet_id,
                    "gridData": {
                        "startRow": group[0][0] - 1,
                        "startColumn": 10,
                        "rows": [_row_payload(desired_by_id[int(gift["id"])][10:]) for _, gift in group],
                    },
                }
            }
        )
    for group in _groups([*existing_moved, *new]):
        requests.append(
            {
                "updateRangeRequest": {
                    "sheetId": sheet_id,
                    "gridData": {
                        "startRow": group[0][0] - 1,
                        "startColumn": 0,
                        "rows": [_row_payload(_gift_values(gift, include_cloud_fields=True)) for _, gift in group],
                    },
                }
            }
        )
    legacy_file_id = ""
    stale_image_cells: dict[int, list[int]] = {4: [], 5: []}
    missing_moved_images = []
    for row_number, gift in assignments:
        previous_marker = str(gift.get("tencent_image_synced") or "")
        current_image = str(gift.get("image") or "")
        current_marker = _image_marker(current_image, row_number) if current_image else ""
        old_match = cloud_by_id.get(int(gift["id"]))
        if (
            current_image
            and old_match
            and old_match[0] != row_number
            and _local_image_path(current_image) is None
        ):
            missing_moved_images.append(int(gift["id"]))
        if previous_marker and previous_marker != current_marker:
            stale_row, stale_column = _marker_cell(previous_marker, old_match[0] if old_match else row_number)
            stale_image_cells[stale_column].append(stale_row)
    if missing_moved_images:
        gift_ids = "、".join(str(gift_id) for gift_id in missing_moved_images[:10])
        suffix = "等" if len(missing_moved_images) > 10 else ""
        raise TencentDocsError(
            f"礼品单 {gift_ids}{suffix} 的本地图片缺失；为避免清除腾讯文档中的原图片，"
            "本次重新排版已停止。请重新上传图片后再同步"
        )
    if any(stale_image_cells.values()):
        legacy_file_id = client.convert_file_id()
        for column, row_numbers in stale_image_cells.items():
            column_name = chr(ord("A") + column - 1)
            for row_number in sorted(set(row_numbers)):
                client.clear_range(legacy_file_id, f"{sheet_id}!{column_name}{row_number}:{column_name}{row_number}")

    if requests:
        client.batch_update(requests)
    image_uploads: dict[str, str] = {}
    image_rows = []
    image_gifts: list[tuple[int, dict]] = []
    for row_number, gift in assignments:
        image = str(gift.get("image") or "")
        image_marker = _image_marker(image, row_number)
        if not image or image_marker == str(gift.get("tencent_image_synced") or ""):
            continue
        image_path = _local_image_path(image)
        if image_path is None:
            errors.append(f"礼品单 {gift['id']} 的关键词图片文件不存在")
            continue
        try:
            image_id = image_uploads.get(image)
            if image_id is None:
                image_id = client.upload_image(image_path)
                image_uploads[image] = image_id
            image_rows.append(
                {
                    "type": 1,
                    "imageID": image_id,
                    "width": 100,
                    "height": 100,
                    "row": row_number,
                    "col": 5,
                    "offsetX": None,
                    "offsetY": None,
                    "clipInfo": None,
                }
            )
            image_gifts.append((row_number, gift))
        except TencentDocsError as exc:
            errors.append(f"礼品单 {gift['id']} 图片上传失败：{exc}")
    if image_rows:
        try:
            legacy_file_id = legacy_file_id or client.convert_file_id()
            for index in range(0, len(image_rows), 500):
                client.insert_cell_images(legacy_file_id, sheet_id, image_rows[index:index + 500])
            for row_number, gift in image_gifts:
                db.execute(
                    "UPDATE gifts SET tencent_image_synced = ? WHERE id = ?",
                    (_image_marker(str(gift["image"]), row_number), gift["id"]),
                )
        except TencentDocsError as exc:
            errors.append(f"腾讯文档插入关键词图片失败：{exc}")
    removed_image_ids = [
        gift["id"]
        for _, gift in assignments
        if not gift.get("image") and gift.get("tencent_image_synced")
    ]
    for gift_id in removed_image_ids:
        db.execute("UPDATE gifts SET tencent_image_synced = '' WHERE id = ?", (gift_id,))
    synced_at = _now_text()
    for row_number, gift in assignments:
        row_errors = [error for error in errors if f"礼品单 {gift['id']} " in error or (gift.get("order_no") and str(gift["order_no"]) in error)]
        db.execute(
            "UPDATE gifts SET tencent_row = ?, tencent_synced_at = ?, tencent_sync_error = ? WHERE id = ?",
            (row_number, synced_at, "；".join(row_errors), gift["id"]),
        )
    config = _load_config(db)
    result = {
        "ok": not errors,
        "skipped": False,
        "pushed": len(new),
        "updated": len(existing),
        "pulled": pulled,
        "errors": errors,
        "transport": getattr(client, "transport", "openapi"),
    }
    config.update(
        {
            "sheet_id": sheet_id,
            "sheet_title": str(sheet.get("title") or ""),
            "sheet_row_count": int(sheet.get("rowCount") or 0),
            "sheet_row_total": row_total,
            "sheet_metadata_refreshed_at": _now_text() if sheet_metadata_refreshed else config.get("sheet_metadata_refreshed_at"),
            "last_sync_at": synced_at,
            "last_error": "；".join(errors[:3]),
            "last_result": result,
            "quota_backoff_until": "",
        }
    )
    _store_config(db, config)
    return result
