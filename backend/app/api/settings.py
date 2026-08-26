"""设置中心：品牌（白标）配置等。"""

from __future__ import annotations

import json
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from backend.app.api.auth import get_current_user, require_admin
from backend.app.core.db import get_db
from backend.app.core import gift_remark, tencent_docs

router = APIRouter()
oauth_router = APIRouter()

DEFAULT_BRAND = {
    "name": "淘宝运营工作台",
    "shortName": "TB Ops",
    "logoText": "淘",
    "logoUrl": "",
    "tagline": "淘宝店铺运营中台",
    "eyebrow": "TAOBAO OPS",
    "primaryColor": "var(--ops-accent)",
    "primaryLight": "var(--ops-accent-light)",
    "gradient": "linear-gradient(135deg, var(--ops-accent) 0%, var(--ops-accent) 100%)",
}


def get_brand(db) -> dict:
    row = db.execute("SELECT value FROM meta WHERE key = 'brand'").fetchone()
    if not row or not row["value"]:
        return dict(DEFAULT_BRAND)
    try:
        data = json.loads(row["value"])
        merged = dict(DEFAULT_BRAND)
        if isinstance(data, dict):
            merged.update(data)
        return merged
    except (ValueError, TypeError):
        return dict(DEFAULT_BRAND)


class BrandIn(BaseModel):
    name: str = ""
    shortName: str = ""
    logoText: str = ""
    logoUrl: str = ""
    tagline: str = ""
    eyebrow: str = ""
    primaryColor: str = ""
    primaryLight: str = ""
    gradient: str = ""


class TencentDocsConfigIn(BaseModel):
    enabled: bool = False
    browser_fallback_enabled: bool = False
    browser_cdp_url: str = "http://127.0.0.1:9222"
    document_url: str = tencent_docs.DEFAULT_DOCUMENT_URL
    sheet_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    access_token: str = ""
    open_id: str = ""
    redirect_uri: str = ""


class GiftRemarkConfigIn(BaseModel):
    enabled: bool = False


@router.get("/brand")
def get_brand_config(user: dict = Depends(get_current_user), db=Depends(get_db)) -> dict:
    return {"brand": get_brand(db)}


@router.put("/brand")
def set_brand_config(body: BrandIn, actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    brand = get_brand(db)
    for field in ("name", "shortName", "logoText", "logoUrl", "tagline", "eyebrow", "primaryColor", "primaryLight", "gradient"):
        value = getattr(body, field, "")
        if value and value.strip():
            brand[field] = value.strip()
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('brand', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (json.dumps(brand, ensure_ascii=False),),
    )
    return {"brand": brand}


@router.get("/tencent-docs")
def get_tencent_docs_config(actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    return tencent_docs.public_config(db)


@router.put("/tencent-docs")
def set_tencent_docs_config(body: TencentDocsConfigIn, actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    current = tencent_docs.public_config(db)
    values = {
        "enabled": body.enabled,
        "browser_fallback_enabled": body.browser_fallback_enabled,
        "browser_cdp_url": body.browser_cdp_url.strip(),
        "document_url": body.document_url.strip(),
        "sheet_id": body.sheet_id.strip(),
        "client_id": body.client_id.strip(),
        "redirect_uri": body.redirect_uri.strip(),
    }
    if body.client_secret.strip():
        values["client_secret"] = body.client_secret.strip()
    elif not current["client_secret_configured"]:
        values["client_secret"] = ""
    if body.access_token.strip():
        values["access_token"] = body.access_token.strip()
        values["token_expires_at"] = ""
    if body.open_id.strip():
        values["open_id"] = body.open_id.strip()
    try:
        tencent_docs.update_config(db, values)
    except tencent_docs.TencentDocsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return tencent_docs.public_config(db)


@router.get("/tencent-docs/oauth-url")
def get_tencent_docs_oauth_url(actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    try:
        return {"url": tencent_docs.build_authorization_url(db)}
    except tencent_docs.TencentDocsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tencent-docs/test")
def test_tencent_docs(actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    try:
        return tencent_docs.test_connection(db)
    except tencent_docs.TencentDocsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/tencent-docs/disconnect")
def disconnect_tencent_docs(actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    tencent_docs.clear_authorization(db)
    return tencent_docs.public_config(db)


@router.get("/gift-qianniu-remark")
def get_gift_remark_config(actor: dict = Depends(require_admin), db=Depends(get_db)) -> dict:
    return gift_remark.public_config(db)


@router.put("/gift-qianniu-remark")
def set_gift_remark_config(
    body: GiftRemarkConfigIn,
    actor: dict = Depends(require_admin),
    db=Depends(get_db),
) -> dict:
    gift_remark.update_config(db, enabled=body.enabled)
    return gift_remark.public_config(db)


@oauth_router.get("/tencent-docs/oauth/callback", response_class=HTMLResponse)
def tencent_docs_oauth_callback(
    code: str = Query(""),
    state: str = Query(""),
    error: str = Query(""),
    error_description: str = Query(""),
    db=Depends(get_db),
) -> HTMLResponse:
    try:
        if error:
            raise tencent_docs.TencentDocsError(error_description or error)
        tencent_docs.exchange_authorization_code(db, code, state)
        return HTMLResponse("<meta charset='utf-8'><title>授权成功</title><h2>腾讯文档授权成功</h2><p>可以关闭此页面，返回系统设置并刷新状态。</p>")
    except tencent_docs.TencentDocsError as exc:
        return HTMLResponse(
            f"<meta charset='utf-8'><title>授权失败</title><h2>腾讯文档授权失败</h2><p>{escape(str(exc))}</p>",
            status_code=400,
        )
