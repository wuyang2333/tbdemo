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
        "roi_high": 2.0,
        "min_visitors": 50,
    },
    "plan": {"budget_over": 1.0, "budget_warn": 0.8, "roi_low": 1.0, "roi_drop_ratio": 0.6},
    "rules": [],
}


RULE_MODULES = {"product", "plan", "hour"}
RULE_OPERATORS = {"cycle_drop_pct", "cycle_up_pct", "lt", "gt"}


def _norm_rule(r) -> dict | None:
    """规范化一条自定义规则，非法则丢弃。"""
    if not isinstance(r, dict):
        return None
    if r.get("module") not in RULE_MODULES or r.get("operator") not in RULE_OPERATORS:
        return None
    try:
        threshold = float(r.get("threshold") or 0)
    except (TypeError, ValueError):
        return None
    return {
        "id": str(r.get("id") or ""),
        "module": r["module"],
        "field": str(r.get("field") or ""),
        "operator": r["operator"],
        "threshold": threshold,
        "enabled": bool(r.get("enabled", True)),
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
            if group == "rules":
                continue
            src = data.get(group) or {}
            for k in fields:
                if k in src and isinstance(src[k], (int, float)):
                    fields[k] = float(src[k])
        if isinstance(data.get("rules"), list):
            base["rules"] = [_norm_rule(r) for r in data["rules"]]
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
    rules: list | None = None


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
    if body.rules is not None:
        cur["rules"] = [r for r in (_norm_rule(x) for x in body.rules) if r]
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('alert_config', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (json.dumps(cur, ensure_ascii=False),),
    )
    return {"ok": True, **cur}



# ==================== 小时级异常推送（pushplus → 微信） ====================

HOURLY_FIELDS = {"sales", "visitors", "orders", "conversion_rate", "promo_spend", "promo_roi"}
HOURLY_LABELS = {
    "sales": "销售额",
    "visitors": "访客",
    "orders": "订单",
    "conversion_rate": "转化率",
    "promo_spend": "推广花费",
    "promo_roi": "推广ROI",
}


def _norm_hourly_rule(r) -> dict | None:
    if not isinstance(r, dict):
        return None
    if r.get("field") not in HOURLY_FIELDS or r.get("operator") not in RULE_OPERATORS:
        return None
    try:
        threshold = float(r.get("threshold") or 0)
    except (TypeError, ValueError):
        return None
    compare = "prev_hour" if r.get("compare") == "prev_hour" else "yesterday"
    return {
        "id": str(r.get("id") or ""),
        "field": r["field"],
        "operator": r["operator"],
        "threshold": threshold,
        "compare": compare,
        "enabled": bool(r.get("enabled", True)),
    }


def _hourly_push_config(db) -> dict:
    default = {"enabled": False, "token": "", "rules": []}
    row = db.execute("SELECT value FROM meta WHERE key = 'hourly_push_config'").fetchone()
    if row and row["value"]:
        try:
            data = json.loads(row["value"])
            default["enabled"] = bool(data.get("enabled", False))
            default["token"] = str(data.get("token") or "")
            if isinstance(data.get("rules"), list):
                default["rules"] = [r for r in (_norm_hourly_rule(x) for x in data["rules"]) if r]
        except (ValueError, TypeError):
            pass
    return default


class HourlyPushIn(BaseModel):
    enabled: bool = False
    token: str = ""
    rules: list | None = None


@router.get("/hourly-push-config")
def get_hourly_push_config(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    return _hourly_push_config(db)


@router.put("/hourly-push-config")
def set_hourly_push_config(
    body: HourlyPushIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = {
        "enabled": bool(body.enabled),
        "token": (body.token or "").strip(),
        "rules": [r for r in (_norm_hourly_rule(x) for x in (body.rules or [])) if r],
    }
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('hourly_push_config', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (json.dumps(cfg, ensure_ascii=False),),
    )
    return {"ok": True, **cfg}


def send_pushplus(token: str, title: str, content: str) -> None:
    """通过 pushplus 推送到个人微信。"""
    import urllib.request

    body = json.dumps({"token": token, "title": title, "content": content, "template": "txt"}).encode("utf-8")
    req = urllib.request.Request("https://www.pushplus.plus/send", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def _hpct(cur: float, prev: float):
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def check_hourly_rules(db, cfg: dict | None = None) -> list[str]:
    """检查上个小时的数据是否触发推送规则，返回触发消息列表（不推送）。"""
    from datetime import datetime, timedelta

    cfg = cfg or _hourly_push_config(db)
    rules = [r for r in cfg.get("rules") or [] if r.get("enabled")]
    if not rules:
        return []
    now = datetime.now()
    prev = now - timedelta(hours=1)
    date_str = prev.strftime("%Y-%m-%d")
    hour_str = prev.strftime("%H:00")
    yest_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    prev_hour_dt = prev - timedelta(hours=1)
    prev_hour_date = prev_hour_dt.strftime("%Y-%m-%d")
    prev_hour_str = prev_hour_dt.strftime("%H:00")

    cur_rows = db.execute(
        "SELECT * FROM store_hourly_data WHERE data_date = ? AND hour = ?", (date_str, hour_str)
    ).fetchall()
    yest_rows = db.execute(
        "SELECT * FROM store_hourly_data WHERE data_date = ? AND hour = ?", (yest_str, hour_str)
    ).fetchall()
    last_hour_rows = db.execute(
        "SELECT * FROM store_hourly_data WHERE data_date = ? AND hour = ?", (prev_hour_date, prev_hour_str)
    ).fetchall()

    def _agg(rows):
        visitors = sum(r["visitors"] or 0 for r in rows)
        sales = sum(r["sales"] or 0 for r in rows)
        orders = sum(r["orders"] or 0 for r in rows)
        return {
            "visitors": visitors,
            "sales": round(sales, 2),
            "orders": orders,
            "conversion_rate": round(orders / visitors * 100, 2) if visitors else 0.0,
        }

    cur = _agg(cur_rows)
    yest = _agg(yest_rows)
    last_hour = _agg(last_hour_rows)
    baseline = {"yesterday": yest, "prev_hour": last_hour}
    base_label = {"yesterday": "昨日同时段", "prev_hour": "上一小时"}
    pcur = db.execute(
        "SELECT * FROM promo_realtime WHERE data_date = ? AND hour = ?", (date_str, hour_str)
    ).fetchall()
    py = db.execute(
        "SELECT * FROM promo_realtime WHERE data_date = ? AND hour = ?", (yest_str, hour_str)
    ).fetchall()
    pl = db.execute(
        "SELECT * FROM promo_realtime WHERE data_date = ? AND hour = ?", (prev_hour_date, prev_hour_str)
    ).fetchall()
    p_spend = sum(r["spend"] or 0 for r in pcur)
    p_sales = sum(r["sales"] or 0 for r in pcur)
    p_spend_y = sum(r["spend"] or 0 for r in py)
    p_sales_y = sum(r["sales"] or 0 for r in py)
    p_spend_l = sum(r["spend"] or 0 for r in pl)
    p_sales_l = sum(r["sales"] or 0 for r in pl)
    p_roi = round(p_sales / p_spend, 2) if p_spend else 0.0
    p_roi_y = round(p_sales_y / p_spend_y, 2) if p_spend_y else 0.0
    p_roi_l = round(p_sales_l / p_spend_l, 2) if p_spend_l else 0.0

    item = {
        "sales": cur["sales"],
        "visitors": cur["visitors"],
        "orders": cur["orders"],
        "conversion_rate": cur["conversion_rate"],
        "promo_spend": round(p_spend, 2),
        "promo_roi": p_roi,
    }
    base_map = {
        "yesterday": {"sales": yest["sales"], "visitors": yest["visitors"], "orders": yest["orders"], "conversion_rate": yest["conversion_rate"], "promo_roi": p_roi_y},
        "prev_hour": {"sales": last_hour["sales"], "visitors": last_hour["visitors"], "orders": last_hour["orders"], "conversion_rate": last_hour["conversion_rate"], "promo_roi": p_roi_l},
    }
    messages = []
    for r in rules:
        field = r["field"]
        op = r["operator"]
        threshold = abs(r["threshold"])
        compare = r.get("compare", "yesterday")
        base = base_map.get(compare, base_map["yesterday"])
        bl = base_label.get(compare, "昨日同时段")
        label = HOURLY_LABELS.get(field, field)
        if op == "cycle_drop_pct":
            v = _hpct(item.get(field) or 0, base.get(field) or 0)
            if v is not None and v <= -threshold:
                messages.append(f"{hour_str} {label}较{bl}跌 {abs(v):.0f}%（阈值 {threshold}%）")
        elif op == "cycle_up_pct":
            v = _hpct(item.get(field) or 0, base.get(field) or 0)
            if v is not None and v >= threshold:
                messages.append(f"{hour_str} {label}较{bl}涨 {v:.0f}%（阈值 {threshold}%）")
        elif op == "lt":
            v = item.get(field)
            if v is not None and v < threshold:
                val = f"{v:.2f}" if field == "conversion_rate" else f"{v:,.0f}"
                messages.append(f"{hour_str} {label} {val} 低于阈值 {threshold}")
        elif op == "gt":
            v = item.get(field)
            if v is not None and v > threshold:
                val = f"{v:.2f}" if field == "conversion_rate" else f"{v:,.0f}"
                messages.append(f"{hour_str} {label} {val} 超过阈值 {threshold}")
    return messages


@router.post("/hourly-push/test")
def hourly_push_test(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """测试 pushplus 推送。"""
    cfg = _hourly_push_config(db)
    if not cfg.get("token"):
        raise HTTPException(status_code=400, detail="还没有配置 pushplus token")
    try:
        send_pushplus(cfg["token"], "店铺小时异常提醒 - 测试", "这是一条测试消息，收到说明配置成功。")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"推送失败：{exc}") from exc
    return {"ok": True}


@router.post("/hourly-push/check")
def hourly_push_check(
    push: int = 0,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """手动检查上个小时的数据（push=1 时同时推送到微信）。"""
    cfg = _hourly_push_config(db)
    messages = check_hourly_rules(db, cfg)
    pushed = False
    if messages and push and cfg.get("enabled") and cfg.get("token"):
        try:
            send_pushplus(cfg["token"], "店铺小时异常提醒", "\n".join(messages))
            pushed = True
        except Exception:  # noqa: BLE001
            pass
    return {"messages": messages, "pushed": pushed}
