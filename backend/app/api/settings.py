"""设置中心：品牌（白标）配置等。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.app.api.auth import get_current_user, require_admin
from backend.app.core.db import get_db

router = APIRouter()

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