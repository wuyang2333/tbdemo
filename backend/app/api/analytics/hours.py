"""数据洞察：时段分析 + 预警配置。"""

from __future__ import annotations

import io as _io
import json as _json
from datetime import date as date_cls
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel

from backend.app.api.auth import get_current_user, visible_store_ids
from backend.app.api.model_configs import get_default_config
from backend.app.core.ai_client import AIError, chat_completion
from backend.app.core.db import get_db
from backend.app.core.sycm import has_profile

from ._common import (
    AlertsConfigIn,
    _alerts_config,
    _buckets,
    _date_range,
    _derive,
    _store_filter,
    _sum_rows,
    _to_date,
)

from .insight import _parse_insight_sections

router = APIRouter()

# ---------- 客群分析（新老客/复购） ----------

HOUR_SEGMENTS = [
    ("凌晨", range(0, 6)),
    ("上午", range(6, 12)),
    ("下午", range(12, 18)),
    ("晚间", range(18, 22)),
    ("深夜", range(22, 24)),
]


def _hours_agg(db, sf, sp, start: date_cls, end: date_cls) -> dict[str, dict]:
    """某日期区间内按小时聚合店铺分时数据。"""
    rows = db.execute(
        "SELECT hour, visitors, pv, sales, orders, buyers FROM store_hourly_data "
        "WHERE data_date >= ? AND data_date <= ?" + sf,
        [start.isoformat(), end.isoformat()] + sp,
    ).fetchall()
    hour_map: dict[str, dict] = {}
    for r in rows:
        item = hour_map.setdefault(
            r["hour"],
            {"hour": r["hour"], "visitors": 0, "pv": 0, "sales": 0.0, "orders": 0, "buyers": 0},
        )
        item["visitors"] += r["visitors"] or 0
        item["pv"] += r["pv"] or 0
        item["sales"] += r["sales"] or 0
        item["orders"] += r["orders"] or 0
        item["buyers"] += r["buyers"] or 0
    return hour_map


def _promo_hours_agg(db, sf, sp, start: date_cls, end: date_cls) -> dict[str, dict]:
    """某日期区间内按小时聚合万相台推广花费/成交。"""
    rows = db.execute(
        "SELECT hour, SUM(spend) AS spend, SUM(sales) AS sales FROM promo_realtime "
        "WHERE data_date >= ? AND data_date <= ?" + sf + " GROUP BY hour",
        [start.isoformat(), end.isoformat()] + sp,
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        out[r["hour"]] = {"spend": round(r["spend"] or 0, 2), "sales": round(r["sales"] or 0, 2)}
    return out


def _resolve_hours_range(date: str, start: str, end: str) -> tuple[date_cls, date_cls]:
    today = date_cls.today()
    if start and end:
        try:
            s = date_cls.fromisoformat(start)
            e = date_cls.fromisoformat(end)
        except ValueError:
            s = e = None
        if not (s and e and s <= e):
            s = e = today
    elif date:
        d = _to_date(date) or today
        s = e = d
    else:
        s = e = today
    return s, e


def _hours_dataset(db, sf, sp, s: date_cls, e: date_cls) -> dict:
    """聚合某日期区间的时段数据：24h指标 + 推广分时 + 环比 + 分段占比 + 按场景。"""
    today = date_cls.today()
    hour_map = _hours_agg(db, sf, sp, s, e)
    promo_map = _promo_hours_agg(db, sf, sp, s, e)
    prev_end = s - timedelta(days=1)
    prev_start = prev_end - timedelta(days=(e - s).days)
    prev_hour_map = _hours_agg(db, sf, sp, prev_start, prev_end)
    prev_promo_map = _promo_hours_agg(db, sf, sp, prev_start, prev_end)

    scene_rows = db.execute(
        "SELECT scene, scene_name, hour, SUM(spend) AS spend, SUM(sales) AS sales FROM promo_realtime "
        "WHERE data_date >= ? AND data_date <= ?" + sf + " GROUP BY scene, hour",
        [s.isoformat(), e.isoformat()] + sp,
    ).fetchall()
    promo_by_scene: dict[str, dict] = {}
    for r in scene_rows:
        sc = promo_by_scene.setdefault(r["scene"], {"scene": r["scene"], "scene_name": r["scene_name"] or r["scene"], "items": {}})
        sc["items"][r["hour"]] = {"spend": round(r["spend"] or 0, 2), "sales": round(r["sales"] or 0, 2)}
    for sc in promo_by_scene.values():
        for h in range(24):
            it = sc["items"].setdefault(f"{h:02d}:00", {"spend": 0.0, "sales": 0.0})
            it["roi"] = round(it["sales"] / it["spend"], 2) if it["spend"] else 0.0

    items: list[dict] = []
    for h in range(24):
        key = f"{h:02d}:00"
        row = hour_map.get(key)
        if row:
            row["conversion_rate"] = round(row["buyers"] / row["visitors"] * 100, 2) if row["visitors"] else 0.0
            row["sales"] = round(row["sales"], 2)
        else:
            row = {"hour": key, "visitors": 0, "pv": 0, "sales": 0.0, "orders": 0, "buyers": 0, "conversion_rate": 0.0}
        p = promo_map.get(key)
        row["promo_spend"] = p["spend"] if p else 0.0
        row["promo_sales"] = p["sales"] if p else 0.0
        row["promo_roi"] = round(p["sales"] / p["spend"], 2) if p and p["spend"] else 0.0
        prev = prev_hour_map.get(key)
        row["visitors_cycle"] = round((row["visitors"] - prev["visitors"]) / prev["visitors"] * 100, 1) if prev and prev["visitors"] else None
        row["sales_cycle"] = round((row["sales"] - prev["sales"]) / prev["sales"] * 100, 1) if prev and prev["sales"] else None
        row["orders_cycle"] = round((row["orders"] - prev["orders"]) / prev["orders"] * 100, 1) if prev and prev["orders"] else None
        row["conversion_cycle"] = round(row["conversion_rate"] - (round(prev["buyers"] / prev["visitors"] * 100, 2) if prev and prev["visitors"] else 0.0), 2) if prev and prev["visitors"] else None
        items.append(row)

    total_visitors = sum(i["visitors"] for i in items)
    total_sales = sum(i["sales"] for i in items)
    summary = {
        "visitors": total_visitors,
        "pv": sum(i["pv"] for i in items),
        "sales": round(total_sales, 2),
        "orders": sum(i["orders"] for i in items),
        "promo_spend": round(sum(i["promo_spend"] for i in items), 2),
        "promo_sales": round(sum(i["promo_sales"] for i in items), 2),
    }
    summary["promo_roi"] = round(summary["promo_sales"] / summary["promo_spend"], 2) if summary["promo_spend"] else 0.0

    def _prev_point(h: int) -> dict:
        key = f"{h:02d}:00"
        pm = prev_hour_map.get(key)
        if not pm:
            return {"hour": key, "visitors": 0, "sales": 0.0, "orders": 0, "conversion_rate": 0.0}
        return {
            "hour": key,
            "visitors": pm["visitors"],
            "sales": pm["sales"],
            "orders": pm["orders"],
            "conversion_rate": round(pm["buyers"] / pm["visitors"] * 100, 2) if pm["visitors"] else 0.0,
        }

    prev_items = [_prev_point(h) for h in range(24)]
    prev_promo_items = [
        {"hour": f"{h:02d}:00", "spend": (prev_promo_map.get(f"{h:02d}:00") or {}).get("spend", 0), "sales": (prev_promo_map.get(f"{h:02d}:00") or {}).get("sales", 0)}
        for h in range(24)
    ]

    segments: list[dict] = []
    for name, hrs in HOUR_SEGMENTS:
        seg = {"name": name, "hours": f"{hrs.start:02d}:00-{hrs.stop - 1:02d}:00", "visitors": 0, "sales": 0.0, "orders": 0, "promo_spend": 0.0, "promo_sales": 0.0}
        for h in hrs:
            it = items[h]
            seg["visitors"] += it["visitors"]
            seg["sales"] += it["sales"]
            seg["orders"] += it["orders"]
            seg["promo_spend"] += it["promo_spend"]
            seg["promo_sales"] += it["promo_sales"]
        seg["sales"] = round(seg["sales"], 2)
        seg["promo_spend"] = round(seg["promo_spend"], 2)
        seg["promo_sales"] = round(seg["promo_sales"], 2)
        seg["promo_roi"] = round(seg["promo_sales"] / seg["promo_spend"], 2) if seg["promo_spend"] else 0.0
        seg["sales_pct"] = round(seg["sales"] / total_sales * 100, 1) if total_sales else 0.0
        seg["visitors_pct"] = round(seg["visitors"] / total_visitors * 100, 1) if total_visitors else 0.0
        segments.append(seg)

    peak = max(items, key=lambda x: x["sales"]) if items else {"hour": "", "sales": 0}
    recommended_hours = [it["hour"] for it in items if it["promo_spend"] > 0 and it["promo_roi"] >= 2]

    if s == e == today:
        label = "今日"
    elif s == e == today - timedelta(days=1):
        label = "昨日"
    else:
        label = f"{s.strftime('%m-%d')} ~ {e.strftime('%m-%d')}"

    return {
        "date": s.isoformat(),
        "start": s.isoformat(),
        "end": e.isoformat(),
        "label": label,
        "items": items,
        "prev_items": prev_items,
        "prev_promo_items": prev_promo_items,
        "summary": summary,
        "segments": segments,
        "promo_by_scene": promo_by_scene,
        "recommended_hours": recommended_hours,
        "peak_hour": peak["hour"],
        "peak_sales": peak["sales"],
    }


@router.get("/hours")
def analytics_hours(
    date: str = "",
    start: str = "",
    end: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """时段分析：支持单日或日期区间，叠加推广分时、环比与时段分组。"""
    s, e = _resolve_hours_range(date, start, end)
    sf, sp = _store_filter(store_id, user)
    return _hours_dataset(db, sf, sp, s, e)


def _build_hours_prompt(d: dict) -> str:
    summary = d["summary"]
    conv_rate = round(summary["orders"] / max(summary["visitors"], 1) * 100, 2)
    lines = [
        f"数据范围：{d['label']}",
        f"访客 {summary['visitors']}，销售额 {summary['sales']:.0f} 元，订单 {summary['orders']}，转化率 {conv_rate}%，推广花费 {summary['promo_spend']:.0f} 元，推广成交 {summary['promo_sales']:.0f} 元，推广ROI {summary['promo_roi']}",
        "逐小时(访客/销售额/订单/转化率%/推广花费/ROI)：" + "、".join(
            f"{it['hour']}:{it['visitors']}/{it['sales']:.0f}/{it['orders']}/{it['conversion_rate']}/{it['promo_spend']:.0f}/{it['promo_roi']}"
            for it in d["items"]
        ),
    ]
    conv_peak = sorted([it for it in d["items"] if it["visitors"] > 0], key=lambda x: x["conversion_rate"], reverse=True)[:3]
    if conv_peak:
        lines.append("转化率最高时段：" + "、".join(f"{it['hour']}（{it['conversion_rate']}%）" for it in conv_peak))
    anomalies = []
    for it in d["items"]:
        for name, val in (("访客", it["visitors_cycle"]), ("销售额", it["sales_cycle"])):
            if val is not None and abs(val) >= 30:
                anomalies.append(f"{it['hour']}{name}{val:+.0f}%")
    if anomalies:
        lines.append("较上一周期涨跌≥30%的时段：" + "、".join(anomalies[:8]))
    for sc in d.get("promo_by_scene", {}).values():
        active = []
        for h in range(24):
            it = sc["items"].get(f"{h:02d}:00") or {"spend": 0.0, "sales": 0.0, "roi": 0.0}
            if it["spend"] > 0:
                active.append((f"{h:02d}:00", it))
        if not active:
            continue
        total_spend = sum(it["spend"] for _, it in active)
        total_sales = sum(it["sales"] for _, it in active)
        roi = round(total_sales / total_spend, 2) if total_spend else 0
        top = sorted(active, key=lambda x: x[1]["roi"], reverse=True)[:3]
        bottom = sorted(active, key=lambda x: x[1]["roi"])[:2]
        lines.append(
            f"场景{sc['scene_name']}：总花费{total_spend:.0f}元，ROI{roi}；ROI最高时段 "
            + "、".join(f"{h}({it['roi']})" for h, it in top)
            + "；ROI最低时段 "
            + "、".join(f"{h}({it['roi']})" for h, it in bottom)
        )
    if d["recommended_hours"]:
        lines.append("推广ROI≥2 的时段：" + "、".join(d["recommended_hours"]))
    prompt = (
        "你是淘宝店铺的运营数据分析师。根据以下分时数据输出详细时段经营解读，严格按格式，每部分独占一段，条目用“- ”开头：\n"
        "【整体表现】2-3句话概括本期（含销售额、访客、转化率、推广ROI关键数字）\n"
        "【销售时段规律】\n- 销售高峰/次高峰/低谷时段及特征（3-4条）\n"
        "【流量与转化】\n- 访客高峰、转化率特征（2-3条）\n"
        "【投放建议】\n- 按场景按时段的具体建议，明确“几点到几点投/停投”（4-5条）\n"
        "【风险提醒】\n- 低ROI时段、异常波动等（2-3条）\n"
        "简体中文务实，金额≥1万用X.X万简化；只依据给定数据，不要编造。\n\n"
        + "\n".join(lines)
    )
    return prompt


@router.post("/hours/insight")
def hours_ai_insight(
    start: str = "",
    end: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    s, e = _resolve_hours_range("", start, end)
    sf, sp = _store_filter(store_id, user)
    d = _hours_dataset(db, sf, sp, s, e)
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": _build_hours_prompt(d)}], timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "sections": _parse_insight_sections(reply),
        "reply": reply,
        "range": d["label"],
        "recommended_hours": d["recommended_hours"],
        "summary": d["summary"],
    }


@router.get("/alerts/config")
def get_alerts_config(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    return _alerts_config(db)


@router.put("/alerts/config")
def set_alerts_config(
    body: AlertsConfigIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = {
        "baseline_days": max(2, min(int(body.baseline_days), 30)),
        "sales_down": float(body.sales_down),
        "sales_up": float(body.sales_up),
        "orders_down": float(body.orders_down),
        "visitors_down": float(body.visitors_down),
        "conversion_down": float(body.conversion_down),
    }
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('analytics_alerts_config', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_json.dumps(cfg, ensure_ascii=False),),
    )
    return {"ok": True, **cfg}
