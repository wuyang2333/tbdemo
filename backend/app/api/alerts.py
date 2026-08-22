"""统一预警配置：时段分析 / 商品分析 / 推广计划 三套阈值，存 meta 表，账号级共享。

默认值在 DEFAULT_ALERT_CONFIG，用户可通过 /api/alerts/config 修改并持久化。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
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

HOURLY_SCOPES = {
    "report": "经营日报",
    "hours": "时段分析",
    "products": "商品分析",
    "promotions": "推广计划",
}
HOURLY_SCOPE_FIELDS = {
    "report": {
        "sales", "visitors", "pv", "buyers", "orders", "conversion_rate", "avg_order_value",
        "promo_spend", "promo_sales", "promo_roi", "add_cart", "refund_amount", "goal_progress",
    },
    "hours": {
        "sales", "visitors", "pv", "buyers", "orders", "conversion_rate",
        "promo_spend", "promo_sales", "promo_roi",
    },
    "products": {
        "sales", "visitors", "pv", "buyers", "orders", "conversion_rate", "add_cart", "refund_amount",
        "promo_spend", "promo_sales", "promo_roi", "promo_net_roi", "real_roi", "promo_share",
    },
    "promotions": {
        "spend", "sales", "roi", "retained_roi", "clicks", "impressions", "ctr", "cvr", "ecpc",
        "budget_usage", "orders", "refund_amt", "retained_sales", "alipay_dir", "alipay_indir",
    },
}
HOURLY_VALUE_ONLY_FIELDS = {
    "report": {"add_cart", "refund_amount", "goal_progress"},
    "hours": set(),
    "products": {"refund_amount", "promo_spend", "promo_sales", "promo_roi", "promo_net_roi", "real_roi", "promo_share"},
    "promotions": {
        "retained_roi", "impressions", "ctr", "cvr", "ecpc", "budget_usage", "orders",
        "refund_amt", "retained_sales", "alipay_dir", "alipay_indir",
    },
}
HOURLY_FIELDS = set().union(*HOURLY_SCOPE_FIELDS.values())
HOURLY_CHANNELS = {"pushplus", "webhook", "both"}
HOURLY_LABELS = {
    "sales": "销售额",
    "visitors": "访客",
    "orders": "订单",
    "conversion_rate": "转化率",
    "promo_spend": "推广花费",
    "promo_roi": "推广ROI",
    "promo_sales": "推广成交额",
    "promo_net_roi": "推广净ROI",
    "real_roi": "真实ROI",
    "promo_share": "推广成交占比",
    "pv": "浏览量",
    "buyers": "买家数",
    "avg_order_value": "客单价",
    "add_cart": "加购数",
    "refund_amount": "退款金额",
    "goal_progress": "月目标完成率",
    "spend": "花费",
    "roi": "ROI",
    "retained_roi": "净投产比",
    "clicks": "点击",
    "impressions": "展现量",
    "ctr": "点击率",
    "cvr": "转化率",
    "ecpc": "点击成本",
    "budget_usage": "预算消耗率",
    "refund_amt": "退款金额",
    "retained_sales": "留存成交额",
    "alipay_dir": "直接成交额",
    "alipay_indir": "间接成交额",
}
SCENE_LABELS = {"wholesite": "货品全站推广", "keyword": "关键词推广", "crowd": "人群推广", "content": "内容营销"}
HOURLY_SCENES = {"", "wholesite", "keyword", "crowd", "content"}


def _norm_hourly_rule(r, scope: str = "hours") -> dict | None:
    if not isinstance(r, dict):
        return None
    if scope not in HOURLY_SCOPES:
        return None
    if r.get("field") not in HOURLY_SCOPE_FIELDS[scope] or r.get("operator") not in RULE_OPERATORS:
        return None
    if r.get("field") in HOURLY_VALUE_ONLY_FIELDS[scope] and r.get("operator") in {"cycle_drop_pct", "cycle_up_pct"}:
        return None
    try:
        threshold = float(r.get("threshold") or 0)
    except (TypeError, ValueError):
        return None
    compare = "prev_hour" if r.get("compare") == "prev_hour" else "yesterday"
    scene = str(r.get("scene") or "")
    if scene not in HOURLY_SCENES:
        scene = ""
    return {
        "id": str(r.get("id") or ""),
        "field": r["field"],
        "operator": r["operator"],
        "threshold": threshold,
        "compare": compare,
        "scene": scene,
        "enabled": bool(r.get("enabled", True)),
    }


def _hourly_page_config(raw: object, scope: str) -> dict:
    data = raw if isinstance(raw, dict) else {}
    rules = data.get("rules") if isinstance(data.get("rules"), list) else []
    return {
        "enabled": bool(data.get("enabled", False)),
        "rules": [rule for rule in (_norm_hourly_rule(item, scope) for item in rules) if rule],
    }


def _hourly_push_config(db) -> dict:
    default = {
        "token": "",
        "webhook": "",
        "channel": "pushplus",
        "pages": {scope: _hourly_page_config({}, scope) for scope in HOURLY_SCOPES},
    }
    row = db.execute("SELECT value FROM meta WHERE key = 'hourly_push_config'").fetchone()
    if row and row["value"]:
        try:
            data = json.loads(row["value"])
            default["token"] = str(data.get("token") or "")
            default["webhook"] = str(data.get("webhook") or "")
            if str(data.get("channel") or "") in HOURLY_CHANNELS:
                default["channel"] = str(data["channel"])
            if isinstance(data.get("pages"), dict):
                default["pages"] = {
                    scope: _hourly_page_config(data["pages"].get(scope), scope)
                    for scope in HOURLY_SCOPES
                }
            else:
                default["pages"]["hours"] = _hourly_page_config(
                    {"enabled": data.get("enabled", False), "rules": data.get("rules") or []},
                    "hours",
                )
        except (ValueError, TypeError):
            pass
    default["enabled"] = any(page["enabled"] for page in default["pages"].values())
    default["rules"] = default["pages"]["hours"]["rules"]
    default["enabled_page_count"] = sum(1 for page in default["pages"].values() if page["enabled"])
    return default


def _hourly_scope_response(cfg: dict, scope: str) -> dict:
    page = cfg["pages"][scope]
    channel = cfg["channel"]
    return {
        "scope": scope,
        "scope_label": HOURLY_SCOPES[scope],
        "enabled": page["enabled"],
        "rules": page["rules"],
        "channel": channel,
        "channel_ready": hourly_channel_ready(cfg),
    }


def hourly_channel_ready(cfg: dict) -> bool:
    channel = cfg.get("channel", "pushplus")
    if channel == "pushplus":
        return bool(cfg.get("token"))
    if channel == "webhook":
        return bool(cfg.get("webhook"))
    return bool(cfg.get("token") and cfg.get("webhook"))


class HourlyPushIn(BaseModel):
    enabled: bool | None = None
    token: str | None = None
    webhook: str | None = None
    channel: str | None = None
    rules: list | None = None


@router.get("/hourly-push-config")
def get_hourly_push_config(
    scope: str = Query(""),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = _hourly_push_config(db)
    if scope:
        if scope not in HOURLY_SCOPES:
            raise HTTPException(status_code=400, detail="未知的页面推送范围")
        return _hourly_scope_response(cfg, scope)
    return cfg


@router.put("/hourly-push-config")
def set_hourly_push_config(
    body: HourlyPushIn,
    scope: str = Query(""),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    existing = _hourly_push_config(db)
    if scope and scope not in HOURLY_SCOPES:
        raise HTTPException(status_code=400, detail="未知的页面推送范围")
    channel = existing["channel"]
    if body.channel is not None:
        if body.channel not in HOURLY_CHANNELS:
            raise HTTPException(status_code=400, detail="推送渠道只能是 pushplus、webhook 或 both")
        channel = body.channel
    webhook = existing["webhook"] if body.webhook is None else (body.webhook or "").strip()
    cfg = {
        "token": existing["token"] if body.token is None else (body.token or "").strip(),
        "webhook": webhook,
        "channel": channel,
        "pages": existing["pages"],
    }
    target_scope = scope or "hours"
    if body.enabled is not None:
        cfg["pages"][target_scope]["enabled"] = bool(body.enabled)
    if body.rules is not None:
        cfg["pages"][target_scope]["rules"] = [
            rule for rule in (_norm_hourly_rule(item, target_scope) for item in body.rules) if rule
        ]
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('hourly_push_config', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (json.dumps(cfg, ensure_ascii=False),),
    )
    saved = _hourly_push_config(db)
    return {"ok": True, **(_hourly_scope_response(saved, scope) if scope else saved)}


def send_pushplus(token: str, title: str, content: str) -> None:
    """通过 pushplus 推送到个人微信。"""
    import urllib.request

    body = json.dumps({"token": token, "title": title, "content": content, "template": "txt"}).encode("utf-8")
    req = urllib.request.Request("https://www.pushplus.plus/send", data=body, headers={"Content-Type": "application/json"})
    # 显式禁用代理：WorkBuddy 会话会注入 HTTP_PROXY/HTTPS_PROXY（如 127.0.0.1:7892），
    # 让 urllib 走无效代理导致连不上 pushplus
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=15) as resp:
        resp.read()


def send_webhook(webhook: str, text: str) -> None:
    """推送文本到群机器人（钉钉/企业微信通用格式），显式禁用代理。"""
    import urllib.request

    body = json.dumps({"msgtype": "text", "text": {"content": text}}).encode("utf-8")
    req = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=15) as resp:
        resp.read()


def send_hourly_push(cfg: dict, title: str, content: str) -> list[str]:
    """按渠道发送小时异常提醒：pushplus / webhook / 两者同时。返回实际发送的渠道。"""
    sent: list[str] = []
    channel = cfg.get("channel", "pushplus")
    if channel in ("pushplus", "both") and cfg.get("token"):
        send_pushplus(cfg["token"], title, content)
        sent.append("pushplus")
    if channel in ("webhook", "both") and cfg.get("webhook"):
        send_webhook(cfg["webhook"], content)
        sent.append("webhook")
    return sent


def _hpct(cur: float, prev: float):
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def _check_operating_rules(db, rules: list[dict], scope: str) -> list[str]:
    """检查经营日报或时段分析的小时聚合规则。"""
    from datetime import datetime, timedelta

    if not rules:
        return []
    now = datetime.now()
    prev = now - timedelta(hours=1)
    date_str = prev.strftime("%Y-%m-%d")
    hour_str = prev.strftime("%H:00")
    yest_str = (prev - timedelta(days=1)).strftime("%Y-%m-%d")
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
        pv = sum(r["pv"] or 0 for r in rows)
        sales = sum(r["sales"] or 0 for r in rows)
        orders = sum(r["orders"] or 0 for r in rows)
        buyers = sum(r["buyers"] or 0 for r in rows)
        return {
            "visitors": visitors,
            "pv": pv,
            "sales": round(sales, 2),
            "orders": orders,
            "buyers": buyers,
            "conversion_rate": round(buyers / visitors * 100, 2) if visitors else 0.0,
            "avg_order_value": round(sales / buyers, 2) if buyers else 0.0,
        }

    cur = _agg(cur_rows)
    yest = _agg(yest_rows)
    last_hour = _agg(last_hour_rows)
    baseline = {"yesterday": yest, "prev_hour": last_hour}
    base_label = {"yesterday": "昨日同时段", "prev_hour": "上一小时"}
    scenes_needed = {r.get("scene") or "" for r in rules}
    promo: dict[str, dict] = {}
    for sc in scenes_needed:
        cond = "" if not sc else " AND scene = ?"
        params = () if not sc else (sc,)
        pc = db.execute("SELECT * FROM promo_realtime WHERE data_date = ? AND hour = ?" + cond, (date_str, hour_str) + params).fetchall()
        pcy = db.execute("SELECT * FROM promo_realtime WHERE data_date = ? AND hour = ?" + cond, (yest_str, hour_str) + params).fetchall()
        pcl = db.execute("SELECT * FROM promo_realtime WHERE data_date = ? AND hour = ?" + cond, (prev_hour_date, prev_hour_str) + params).fetchall()
        spend = sum(r["spend"] or 0 for r in pc)
        sales = sum(r["sales"] or 0 for r in pc)
        spend_y = sum(r["spend"] or 0 for r in pcy)
        sales_y = sum(r["sales"] or 0 for r in pcy)
        spend_l = sum(r["spend"] or 0 for r in pcl)
        sales_l = sum(r["sales"] or 0 for r in pcl)
        promo[sc] = {
            "spend": round(spend, 2),
            "sales": round(sales, 2),
            "spend_y": round(spend_y, 2),
            "sales_y": round(sales_y, 2),
            "spend_l": round(spend_l, 2),
            "sales_l": round(sales_l, 2),
            "roi": round(sales / spend, 2) if spend else 0.0,
            "roi_y": round(sales_y / spend_y, 2) if spend_y else 0.0,
            "roi_l": round(sales_l / spend_l, 2) if spend_l else 0.0,
        }

    def _fmt_val(field: str, v) -> str:
        if v is None:
            return "—"
        if field in ("sales", "promo_spend", "promo_sales", "avg_order_value", "refund_amount"):
            return f"¥{v:,.0f}"
        if field in ("visitors", "pv", "buyers", "orders", "add_cart"):
            return f"{v:,.0f}"
        if field in {"conversion_rate", "goal_progress"}:
            return f"{v:.1f}%"
        if field == "promo_roi":
            return f"{v:.1f}"
        return str(v)

    triggered: list[str] = []
    for r in rules:
        field = r["field"]
        op = r["operator"]
        threshold = abs(r["threshold"])
        compare = r.get("compare", "yesterday")
        sc = r.get("scene") or ""
        pr = promo.get(sc, promo.get("", {}))
        item = {
            "sales": cur["sales"],
            "visitors": cur["visitors"],
            "pv": cur["pv"],
            "buyers": cur["buyers"],
            "orders": cur["orders"],
            "conversion_rate": cur["conversion_rate"],
            "avg_order_value": cur["avg_order_value"],
            "promo_spend": pr.get("spend", 0),
            "promo_sales": pr.get("sales", 0),
            "promo_roi": pr.get("roi", 0),
        }
        base_map = {
            "yesterday": {
                **yest,
                "promo_spend": pr.get("spend_y", 0),
                "promo_sales": pr.get("sales_y", 0),
                "promo_roi": pr.get("roi_y", 0),
            },
            "prev_hour": {
                **last_hour,
                "promo_spend": pr.get("spend_l", 0),
                "promo_sales": pr.get("sales_l", 0),
                "promo_roi": pr.get("roi_l", 0),
            },
        }
        if scope == "report" and field in HOURLY_VALUE_ONLY_FIELDS["report"]:
            realtime = db.execute(
                "SELECT COALESCE(SUM(add_cart), 0) AS add_cart, COALESCE(SUM(refund_amount), 0) AS refund_amount FROM store_item_realtime"
            ).fetchone()
            item["add_cart"] = int(realtime["add_cart"] or 0)
            item["refund_amount"] = round(realtime["refund_amount"] or 0, 2)
            goal_row = db.execute("SELECT value FROM meta WHERE key = 'analytics_sales_goal'").fetchone()
            try:
                goal_data = json.loads(goal_row["value"]) if goal_row and goal_row["value"] else {}
            except (TypeError, ValueError):
                goal_data = {}
            goal = float(goal_data.get("goal") or 0)
            month = datetime.now().strftime("%Y-%m")
            month_row = db.execute(
                "SELECT COALESCE(SUM(sales), 0) AS sales FROM store_daily_data WHERE data_date LIKE ?",
                (month + "%",),
            ).fetchone()
            item["goal_progress"] = round((month_row["sales"] or 0) / goal * 100, 2) if goal else 0.0
        base = base_map.get(compare, base_map["yesterday"])
        bl = base_label.get(compare, "昨日同时段")
        label = HOURLY_LABELS.get(field, field)
        scene_part = f"{SCENE_LABELS.get(sc, sc)} " if sc else ""
        cur_val = _fmt_val(field, item.get(field))
        if op == "cycle_drop_pct":
            v = _hpct(item.get(field) or 0, base.get(field) or 0)
            if v is not None and v <= -threshold:
                triggered.append(f"❌ {scene_part}{label} 较{bl}下跌 {abs(v):.1f}%\n   （阈值 {threshold}%｜当前 {cur_val}）")
        elif op == "cycle_up_pct":
            v = _hpct(item.get(field) or 0, base.get(field) or 0)
            if v is not None and v >= threshold:
                triggered.append(f"📈 {scene_part}{label} 较{bl}上涨 {v:.1f}%\n   （阈值 {threshold}%｜当前 {cur_val}）")
        elif op == "lt":
            v = item.get(field)
            if v is not None and v < threshold:
                val = _fmt_val(field, v)
                triggered.append(f"⚠️ {scene_part}{label} {val} 低于阈值 {threshold}\n   （当前 {val}）")
        elif op == "gt":
            v = item.get(field)
            if v is not None and v > threshold:
                val = _fmt_val(field, v)
                triggered.append(f"⚠️ {scene_part}{label} {val} 超过阈值 {threshold}\n   （当前 {val}）")
    if not triggered:
        return []
    messages = [f"📊【{HOURLY_SCOPES[scope]}】{now.strftime('%m-%d')} {hour_str} 小时预警"]
    for m in triggered:
        messages.append(m)
        messages.append("")
    messages.pop()
    return messages


def _row_rule_message(rule: dict, item: dict, cycles: dict, name: str) -> str | None:
    field = rule["field"]
    operator = rule["operator"]
    threshold = abs(float(rule["threshold"]))
    current = item.get(field)
    label = HOURLY_LABELS.get(field, field)
    display = _format_push_value(field, current)
    if operator == "cycle_drop_pct":
        cycle = cycles.get(field)
        if cycle is not None and cycle <= -threshold:
            return f"❌ {name} · {label}下降 {abs(cycle):.1f}%\n   （阈值 {threshold}%｜当前 {display}）"
    elif operator == "cycle_up_pct":
        cycle = cycles.get(field)
        if cycle is not None and cycle >= threshold:
            return f"📈 {name} · {label}上涨 {cycle:.1f}%\n   （阈值 {threshold}%｜当前 {display}）"
    elif operator == "lt" and current is not None and current < threshold:
        return f"⚠️ {name} · {label} {display} 低于阈值 {threshold}"
    elif operator == "gt" and current is not None and current > threshold:
        return f"⚠️ {name} · {label} {display} 超过阈值 {threshold}"
    return None


def _format_push_value(field: str, value) -> str:
    if value is None:
        return "—"
    if field in {"sales", "spend", "avg_order_value", "refund_amount", "promo_spend", "promo_sales", "refund_amt", "retained_sales", "alipay_dir", "alipay_indir", "ecpc"}:
        return f"¥{float(value):,.0f}"
    if field in {"visitors", "pv", "buyers", "orders", "clicks", "impressions", "add_cart"}:
        return f"{float(value):,.0f}"
    if field in {"conversion_rate", "ctr", "cvr", "budget_usage", "promo_share", "goal_progress"}:
        return f"{float(value):.2f}%"
    return f"{float(value):.2f}"


def _check_product_rules(db, rules: list[dict]) -> list[str]:
    if not rules:
        return []
    rows = db.execute(
        """
        SELECT store_id, item_id, item_title, sales, visitors, pv, buyers, orders, conversion_rate,
               add_cart, refund_amount, sales_cycle, visitors_cycle, pv_cycle, buyers_cycle,
               orders_cycle, conversion_cycle, add_cart_cycle
        FROM store_item_realtime
        ORDER BY sales DESC
        """
    ).fetchall()
    promo_rows = db.execute(
        "SELECT store_id, item_id, spend, sales, roi FROM promo_item_stats WHERE mode = 'realtime'"
    ).fetchall()
    promo_map = {(row["store_id"], row["item_id"]): dict(row) for row in promo_rows}
    net_rows = db.execute(
        """
        SELECT pi.store_id, pi.item_id, COALESCE(SUM(ps.spend), 0) AS spend,
               COALESCE(SUM(ps.retained_sales), 0) AS retained_sales
        FROM promo_plan_items pi
        JOIN promo_plan_stats ps
          ON ps.store_id = pi.store_id AND ps.campaign_id = pi.campaign_id AND ps.mode = 'realtime'
        GROUP BY pi.store_id, pi.item_id
        """
    ).fetchall()
    net_map = {
        (row["store_id"], row["item_id"]): round((row["retained_sales"] or 0) / row["spend"], 2)
        for row in net_rows
        if row["spend"]
    }
    triggered: list[str] = []
    for row in rows:
        item = dict(row)
        promo = promo_map.get((item["store_id"], item["item_id"]), {})
        item["promo_spend"] = round(promo.get("spend") or 0, 2)
        item["promo_sales"] = round(promo.get("sales") or 0, 2)
        item["promo_roi"] = round(promo.get("roi") or 0, 2)
        item["promo_net_roi"] = net_map.get((item["store_id"], item["item_id"]), 0.0)
        item["real_roi"] = round(item["sales"] / item["promo_spend"], 2) if item["promo_spend"] else None
        item["promo_share"] = round(item["promo_sales"] / item["sales"] * 100, 2) if item["sales"] else 0.0
        cycles = {
            "sales": item.get("sales_cycle"),
            "visitors": item.get("visitors_cycle"),
            "pv": item.get("pv_cycle"),
            "buyers": item.get("buyers_cycle"),
            "orders": item.get("orders_cycle"),
            "conversion_rate": item.get("conversion_cycle"),
            "add_cart": item.get("add_cart_cycle"),
        }
        name = f"商品「{item.get('item_title') or item.get('item_id')}」"
        for rule in rules:
            message = _row_rule_message(rule, item, cycles, name)
            if message:
                triggered.append(message)
                if len(triggered) >= 20:
                    break
        if len(triggered) >= 20:
            break
    return ["📦【商品分析】商品实时预警", *triggered] if triggered else []


def _check_promotion_rules(db, rules: list[dict]) -> list[str]:
    if not rules:
        return []
    rows = db.execute(
        """
        SELECT p.plan_name, p.day_budget, s.campaign_id, s.spend, s.sales, s.roi, s.retained_roi,
               s.clicks, s.prev_spend, s.prev_sales, s.prev_roi, s.prev_clicks,
               s.alipay_dir, s.alipay_indir, s.retained_sales, s.refund_amt, s.extra_json
        FROM promo_plan_stats s
        JOIN promo_plans p ON p.store_id = s.store_id AND p.campaign_id = s.campaign_id
        WHERE s.mode = 'realtime'
        ORDER BY s.spend DESC
        """
    ).fetchall()
    triggered: list[str] = []
    for row in rows:
        item = dict(row)
        try:
            extra = json.loads(item.get("extra_json") or "{}")
        except (TypeError, ValueError):
            extra = {}
        item["impressions"] = int(extra.get("adPv") or 0)
        item["ctr"] = float(extra.get("ctr") or 0)
        item["cvr"] = float(extra.get("cvr") or 0)
        if 0 < item["ctr"] <= 1:
            item["ctr"] = round(item["ctr"] * 100, 2)
        if 0 < item["cvr"] <= 1:
            item["cvr"] = round(item["cvr"] * 100, 2)
        item["ecpc"] = round(float(extra.get("ecpc") or 0), 2)
        item["orders"] = int(extra.get("alipayInshopNum") or 0)
        item["budget_usage"] = round((item.get("spend") or 0) / item["day_budget"] * 100, 2) if item.get("day_budget") else 0.0
        cycles = {
            "spend": _hpct(item.get("spend") or 0, item.get("prev_spend") or 0),
            "sales": _hpct(item.get("sales") or 0, item.get("prev_sales") or 0),
            "roi": _hpct(item.get("roi") or 0, item.get("prev_roi") or 0),
            "clicks": _hpct(item.get("clicks") or 0, item.get("prev_clicks") or 0),
            "retained_roi": None,
        }
        name = f"计划「{item.get('plan_name') or item.get('campaign_id')}」"
        for rule in rules:
            message = _row_rule_message(rule, item, cycles, name)
            if message:
                triggered.append(message)
                if len(triggered) >= 20:
                    break
        if len(triggered) >= 20:
            break
    return ["📣【推广计划】计划实时预警", *triggered] if triggered else []


def check_hourly_rules(db, cfg: dict | None = None, scope: str = "") -> list[str]:
    """按页面独立检查小时规则；未指定页面时检查所有已启用页面。"""
    config = cfg or _hourly_push_config(db)
    scopes = [scope] if scope else [name for name, page in config["pages"].items() if page["enabled"]]
    messages: list[str] = []
    for name in scopes:
        if name not in HOURLY_SCOPES:
            continue
        rules = [rule for rule in config["pages"][name]["rules"] if rule.get("enabled")]
        if name in {"report", "hours"}:
            scoped_messages = _check_operating_rules(db, rules, name)
        elif name == "products":
            scoped_messages = _check_product_rules(db, rules)
        else:
            scoped_messages = _check_promotion_rules(db, rules)
        if scoped_messages:
            if messages:
                messages.append("")
            messages.extend(scoped_messages)
    return messages


@router.post("/hourly-push/test")
def hourly_push_test(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """测试小时异常推送（按配置的渠道）。"""
    cfg = _hourly_push_config(db)
    channel = cfg.get("channel", "pushplus")
    missing = []
    if channel in ("pushplus", "both") and not cfg.get("token"):
        missing.append("pushplus token")
    if channel in ("webhook", "both") and not cfg.get("webhook"):
        missing.append("webhook 地址")
    if missing:
        raise HTTPException(status_code=400, detail="推送渠道未配置完整：" + "、".join(missing))
    try:
        sent = send_hourly_push(cfg, "店铺小时异常提醒 - 测试", "这是一条测试消息，收到说明配置成功。")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"推送失败：{exc}") from exc
    return {"ok": True, "channels": sent}


@router.post("/hourly-push/check")
def hourly_push_check(
    push: int = 0,
    scope: str = Query(""),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """手动检查上个小时的数据（push=1 时按配置渠道推送）。"""
    if scope and scope not in HOURLY_SCOPES:
        raise HTTPException(status_code=400, detail="未知的页面推送范围")
    cfg = _hourly_push_config(db)
    messages = check_hourly_rules(db, cfg, scope=scope)
    channels: list[str] = []
    enabled = cfg["pages"][scope]["enabled"] if scope else cfg.get("enabled")
    if messages and push and enabled:
        try:
            title = f"{HOURLY_SCOPES[scope]}小时异常提醒" if scope else "店铺小时异常提醒"
            channels = send_hourly_push(cfg, title, "\n".join(messages))
        except Exception:  # noqa: BLE001
            pass
    return {"messages": messages, "pushed": bool(channels), "channels": channels}
