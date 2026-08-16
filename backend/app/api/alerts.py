"""统一预警配置：时段分析 / 商品分析 / 推广计划 三套阈值，存 meta 表，账号级共享。

默认值在 DEFAULT_ALERT_CONFIG，用户可通过 /api/alerts/config 修改并持久化。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.app.api.auth import get_current_user
from backend.app.core.db import get_db

router = APIRouter()

DEFAULT_ALERT_CONFIG = {
    "hour": {"roi_high": 2.0, "roi_low": 1.0, "drop_pct": 50.0, "surge_pct": 100.0},
    "product": {
        "sales_drop_pct": 50.0,
        "visitors_drop_pct": 50.0,
        "conversion_low": 0.5,
        "promo_roi_low": 1.0,
        "min_visitors": 50,
    },
    "plan": {"budget_over": 1.0, "budget_warn": 0.8, "roi_drop_ratio": 0.6},
}


def get_alert_config(db) -> dict:
    """读取统一预警配置（默认值 + 用户覆盖）。"""
    base = json.loads(json.dumps(DEFAULT_ALERT_CONFIG))
    row = db.execute("SELECT value FROM meta WHERE key = 'alert_config'").fetchone()
    if not row or not row["value"]:
        return base
    try:
        data = json.loads(row["value"])
        for group, fields in base.items():
            src = data.get(group) or {}
            for k in fields:
                if k in src and isinstance(src[k], (int, float)):
                    fields[k] = float(src[k])
    except (ValueError, TypeError):
        pass
    return base


def _clamp(value, lo, hi):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(v, hi))


class AlertConfigIn(BaseModel):
    hour: dict | None = None
    product: dict | None = None
    plan: dict | None = None


@router.get("/config")
def get_config(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    return get_alert_config(db)


@router.put("/config")
def set_config(
    body: AlertConfigIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cur = get_alert_config(db)
    if body.hour is not None:
        for k, v in body.hour.items():
            if k in cur["hour"]:
                cur["hour"][k] = _clamp(v, 0.1, 999)
    if body.product is not None:
        for k, v in body.product.items():
            if k in cur["product"]:
                cur["product"][k] = _clamp(v, 0.01, 999)
    if body.plan is not None:
        for k, v in body.plan.items():
            if k in cur["plan"]:
                cur["plan"][k] = _clamp(v, 0.01, 10)
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('alert_config', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (json.dumps(cur, ensure_ascii=False),),
    )
    return {"ok": True, **cur}
