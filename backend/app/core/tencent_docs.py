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

from backend.app.core.db import DB_PATH


META_KEY = "tencent_docs_gifts_config"
OAUTH_AUTHORIZE_URL = "https://docs.qq.com/oauth/v2/authorize"
OAUTH_TOKEN_URL = "https://docs.qq.com/oauth/v2/token"
API_ROOT = "https://docs.qq.com"
DEFAULT_DOCUMENT_URL = "https://docs.qq.com/sheet/DTG1YaFV2eUhMRGdF"
SYNC_COLUMNS = 13
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
        "client_id": "",
        "client_secret": "",
        "redirect_uri": "",
        "access_token": "",
        "refresh_token": "",
        "open_id": "",
        "token_expires_at": "",
        "oauth_state": "",
        "oauth_state_expires_at": "",
        "last_sync_at": "",
        "last_error": "",
        "last_result": {},
    }
    defaults.update(data)
    return defaults


def _store_config(db, config: dict) -> None:
    db.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (META_KEY, json.dumps(config, ensure_ascii=False)),
    )


def update_config(db, values: dict) -> dict:
    config = _load_config(db)
    for key, value in values.items():
        if key in config:
            config[key] = value
    if "document_url" in values:
        config["file_id"] = parse_file_id(str(config["document_url"]))
    _store_config(db, config)
    return config


def public_config(db) -> dict:
    config = _load_config(db)
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
        "authorized": bool(config["access_token"] and config["open_id"]),
        "token_expires_at": config["token_expires_at"],
        "last_sync_at": config["last_sync_at"],
        "last_error": config["last_error"],
        "last_result": config["last_result"],
        "poll_minutes": 1,
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


def clear_authorization(db) -> None:
    config = _load_config(db)
    for key in ("access_token", "refresh_token", "open_id", "token_expires_at", "oauth_state", "oauth_state_expires_at"):
        config[key] = ""
    config["enabled"] = False
    _store_config(db, config)


class TencentDocsClient:
    def __init__(self, db):
        self.db = db
        self.config = _load_config(db)
        self._ensure_token()

    def _ensure_token(self) -> None:
        expires_at = None
        try:
            expires_at = datetime.fromisoformat(str(self.config.get("token_expires_at") or ""))
        except (TypeError, ValueError):
            pass
        if self.config.get("access_token") and self.config.get("open_id"):
            if expires_at is None or expires_at > _now() + timedelta(minutes=5):
                return
        if not self.config.get("refresh_token"):
            raise TencentDocsError("腾讯文档 Access Token 已过期，请重新生成后保存")
        self._refresh_token()

    def _refresh_token(self) -> None:
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
            raise TencentDocsError(f"腾讯文档令牌刷新失败：{exc}") from exc
        _save_token_payload(self.config, payload)
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
            response = httpx.request(method, API_ROOT + path, headers=self._headers(), timeout=30.0, **kwargs)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TencentDocsError(f"腾讯文档接口调用失败：{exc}") from exc
        code = payload.get("code", payload.get("ret", 0))
        if code not in (0, None):
            raise TencentDocsError(str(payload.get("message") or payload.get("msg") or f"腾讯文档返回错误 {code}"))
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


def test_connection(db) -> dict:
    client = TencentDocsClient(db)
    sheets = client.get_sheets()
    if not sheets:
        raise TencentDocsError("腾讯在线表格中没有可用工作表")
    config = _load_config(db)
    selected = next((item for item in sheets if str(item.get("sheetId")) == str(config.get("sheet_id"))), sheets[0])
    config["sheet_id"] = str(selected.get("sheetId") or "")
    config["sheet_title"] = str(selected.get("title") or "")
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


def _layout_assignments(gifts: list[dict]) -> list[tuple[int, dict]]:
    assignments = []
    row_number = 2
    previous_date = None
    ordered = sorted(gifts, key=lambda gift: (_gift_date(gift) == "", _gift_date(gift), int(gift["id"])))
    for gift in ordered:
        gift_date = _gift_date(gift)
        if previous_date is not None and gift_date != previous_date:
            row_number += 3
        assignments.append((row_number, gift))
        row_number += 1
        previous_date = gift_date
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


def sync_gifts(db, client: TencentDocsClient | None = None) -> dict:
    with _SYNC_LOCK:
        return _sync_gifts_locked(db, client)


def _sync_gifts_locked(db, client: TencentDocsClient | None = None) -> dict:
    config = _load_config(db)
    if not config["enabled"]:
        return {"ok": True, "skipped": True, "reason": "腾讯文档同步未启用", "pushed": 0, "pulled": 0, "errors": []}
    if not config["file_id"]:
        raise TencentDocsError("尚未配置腾讯在线表格链接")
    client = client or TencentDocsClient(db)
    sheets = client.get_sheets()
    if not sheets:
        raise TencentDocsError("腾讯在线表格中没有可用工作表")
    sheet = next((item for item in sheets if str(item.get("sheetId")) == str(config.get("sheet_id"))), sheets[0])
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
    cloud_by_id: dict[int, tuple[int, list[str]]] = {}
    occupied = set()
    for row_number, values in table_rows.items():
        if any(value.strip() for value in values):
            occupied.add(row_number)
        try:
            gift_id = int(values[0].strip())
        except (TypeError, ValueError):
            continue
        if gift_id > 0:
            cloud_by_id[gift_id] = (row_number, values)

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
        raise TencentDocsError("腾讯在线表格没有足够的空白行")
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
        if gift_id in local_by_id and row_number not in desired_rows
    )

    requests = [
        {
            "updateRangeRequest": {
                "sheetId": sheet_id,
                "gridData": {"startRow": 0, "startColumn": 0, "rows": [_row_payload(HEADERS)]},
            }
        }
    ]
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
    existing_without_images = [(row_number, gift) for row_number, gift in existing_same if not gift.get("image")]
    existing_with_images = [(row_number, gift) for row_number, gift in existing_same if gift.get("image")]
    for group in _groups(existing_same):
        requests.append(
            {
                "updateRangeRequest": {
                    "sheetId": sheet_id,
                    "gridData": {
                        "startRow": group[0][0] - 1,
                        "startColumn": 0,
                        "rows": [_row_payload(_gift_values(gift, include_cloud_fields=False)[:4]) for _, gift in group],
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
                        "rows": [_row_payload(_gift_values(gift, include_cloud_fields=False)[4:8]) for _, gift in group],
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
                        "rows": [_row_payload(_gift_values(gift, include_cloud_fields=False)[5:8]) for _, gift in group],
                    },
                }
            }
        )
    for group in _groups(existing_same):
        requests.append(
            {
                "updateRangeRequest": {
                    "sheetId": sheet_id,
                    "gridData": {
                        "startRow": group[0][0] - 1,
                        "startColumn": 10,
                        "rows": [_row_payload(_gift_values(gift, include_cloud_fields=False)[10:]) for _, gift in group],
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
    for row_number, gift in assignments:
        previous_marker = str(gift.get("tencent_image_synced") or "")
        current_image = str(gift.get("image") or "")
        current_marker = _image_marker(current_image, row_number) if current_image else ""
        old_match = cloud_by_id.get(int(gift["id"]))
        if previous_marker and previous_marker != current_marker:
            stale_row, stale_column = _marker_cell(previous_marker, old_match[0] if old_match else row_number)
            stale_image_cells[stale_column].append(stale_row)
    if any(stale_image_cells.values()):
        legacy_file_id = client.convert_file_id()
        for column, row_numbers in stale_image_cells.items():
            column_name = chr(ord("A") + column - 1)
            for row_number in sorted(set(row_numbers)):
                client.clear_range(legacy_file_id, f"{sheet_id}!{column_name}{row_number}:{column_name}{row_number}")

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
    result = {"ok": not errors, "skipped": False, "pushed": len(new), "updated": len(existing), "pulled": pulled, "errors": errors}
    config.update(
        {
            "sheet_id": sheet_id,
            "sheet_title": str(sheet.get("title") or ""),
            "last_sync_at": synced_at,
            "last_error": "；".join(errors[:3]),
            "last_result": result,
        }
    )
    _store_config(db, config)
    return result
