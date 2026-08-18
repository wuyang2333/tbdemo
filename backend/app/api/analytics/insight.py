"""数据洞察：AI 解读 + 单品 AI 分析。"""

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

from .overview import analytics_alerts

router = APIRouter()

# ---------- AI 解读 ----------

def _pct_chg(cur: float, prev: float) -> float | None:
    return round((cur - prev) / prev * 100, 1) if prev else None


def _insight_sum(db, sf, sp, start: date_cls, end: date_cls) -> dict:
    """某时间段内销售汇总（全部店铺或单店）。"""
    rows = db.execute(
        "SELECT * FROM store_daily_data WHERE data_date >= ? AND data_date <= ?" + sf,
        [start.isoformat(), end.isoformat()] + sp,
    ).fetchall()
    s = _sum_rows(rows)
    if len(rows) == 1 and rows[0]["conversion_rate"]:
        s["conversion_rate"] = round(rows[0]["conversion_rate"], 2)
    return s


def _insight_promo(db, sf, sp, start: date_cls, end: date_cls) -> dict:
    """某时间段内推广汇总（万相台按天数据）。"""
    row = db.execute(
        "SELECT COALESCE(SUM(spend),0) AS spend, COALESCE(SUM(sales),0) AS sales "
        "FROM promo_daily_data WHERE data_date >= ? AND data_date <= ?" + sf,
        [start.isoformat(), end.isoformat()] + sp,
    ).fetchone()
    spend = round(row["spend"] or 0, 2)
    sales = round(row["sales"] or 0, 2)
    return {"spend": spend, "sales": sales, "roi": round(sales / spend, 2) if spend else 0.0}


def _insight_peak(db, sf, sp, start: date_cls, end: date_cls) -> list[dict]:
    """统计区间内销售额最高的 2 个时段。"""
    rows = db.execute(
        "SELECT hour, SUM(sales) AS sales FROM store_hourly_data "
        "WHERE data_date >= ? AND data_date <= ?" + sf + " GROUP BY hour ORDER BY sales DESC LIMIT 2",
        [start.isoformat(), end.isoformat()] + sp,
    ).fetchall()
    return [{"hour": r["hour"], "sales": round(r["sales"] or 0, 2)} for r in rows]


def _collect_insight(mode: str, store_id: int | None, user: dict, db) -> dict:
    """按模式汇总 AI 解读所需数据：销售额、推广、趋势、TOP商品、高峰时段、异常。"""
    today = date_cls.today()
    sf, sp = _store_filter(store_id, user)
    anomalies: list[str] = []
    if mode == "realtime":
        ts = today.isoformat()
        cur = _insight_sum(db, sf, sp, today, today)
        if not cur["sales"] and not cur["visitors"]:
            hrows = db.execute(
                "SELECT visitors, pv, sales, orders FROM store_hourly_data WHERE data_date = ?" + sf,
                [ts] + sp,
            ).fetchall()
            cur = _sum_rows(hrows)
        prev = _insight_sum(db, sf, sp, today - timedelta(days=1), today - timedelta(days=1))
        pr = db.execute(
            "SELECT COALESCE(SUM(spend),0) AS spend, COALESCE(SUM(sales),0) AS sales "
            "FROM promo_realtime WHERE data_date = ?" + sf,
            [ts] + sp,
        ).fetchone()
        promo = {"spend": round(pr["spend"] or 0, 2), "sales": round(pr["sales"] or 0, 2)}
        promo["roi"] = round(promo["sales"] / promo["spend"], 2) if promo["spend"] else 0.0
        promo_prev = _insight_promo(db, sf, sp, today - timedelta(days=1), today - timedelta(days=1))
        prods = db.execute(
            "SELECT item_title, sales FROM store_item_realtime WHERE 1=1" + sf + " ORDER BY sales DESC LIMIT 3",
            sp,
        ).fetchall()
        top_products = [{"item_title": r["item_title"], "sales": round(r["sales"] or 0, 2)} for r in prods]
        peak = _insight_peak(db, sf, sp, today, today)
        trend = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            s = _insight_sum(db, sf, sp, d, d)
            trend.append(f"{d.strftime('%m-%d')}:¥{s['sales']:.0f}")
        range_label = f"今日实时（{ts[5:]}）"
    else:
        if mode == "yesterday":
            end = today - timedelta(days=1)
            days = 1
        else:
            try:
                days = int(mode)
            except (TypeError, ValueError):
                days = 14
            if not (1 <= days <= 90):
                days = 14
            end = today
        start = end - timedelta(days=days - 1)
        cur = _insight_sum(db, sf, sp, start, end)
        prev = _insight_sum(db, sf, sp, start - timedelta(days=days), end - timedelta(days=days))
        promo = _insight_promo(db, sf, sp, start, end)
        promo_prev = _insight_promo(db, sf, sp, start - timedelta(days=days), end - timedelta(days=days))
        prods = db.execute(
            "SELECT item_title, SUM(sales) AS sales FROM store_item_daily "
            "WHERE data_date >= ? AND data_date <= ?" + sf + " GROUP BY item_id ORDER BY sales DESC LIMIT 3",
            [start.isoformat(), end.isoformat()] + sp,
        ).fetchall()
        top_products = [{"item_title": r["item_title"], "sales": round(r["sales"] or 0, 2)} for r in prods]
        peak = _insight_peak(db, sf, sp, start, end)
        n = min(days, 7)
        trend = []
        for i in range(n - 1, -1, -1):
            d = end - timedelta(days=i)
            s = _insight_sum(db, sf, sp, d, d)
            trend.append(f"{d.strftime('%m-%d')}:¥{s['sales']:.0f}")
        range_label = f"近 {days} 天（{start.strftime('%m-%d')}~{end.strftime('%m-%d')}）" if days > 1 else f"昨日（{end.strftime('%m-%d')}）"
        try:
            alerts = analytics_alerts(days=30, store_id=store_id, user=None, db=db)
            anomalies = [a["message"] for a in alerts["items"][:3]]
        except Exception:  # noqa: BLE001
            anomalies = []
    ad_share = round(min(promo["sales"] / cur["sales"] * 100, 100.0), 1) if cur["sales"] else 0.0
    if mode == "realtime":
        scene_rows = db.execute(
            "SELECT scene, scene_name, SUM(spend) AS spend, SUM(sales) AS sales FROM promo_realtime "
            "WHERE data_date = ?" + sf + " GROUP BY scene ORDER BY spend DESC",
            [ts] + sp,
        ).fetchall()
    else:
        scene_rows = db.execute(
            "SELECT scene, scene_name, SUM(spend) AS spend, SUM(sales) AS sales FROM promo_daily_data "
            "WHERE data_date >= ? AND data_date <= ?" + sf + " GROUP BY scene ORDER BY spend DESC",
            [start.isoformat(), end.isoformat()] + sp,
        ).fetchall()
    promo_scenes = []
    for r in scene_rows:
        spend = round(r["spend"] or 0, 2)
        sales = round(r["sales"] or 0, 2)
        promo_scenes.append(
            {
                "scene": r["scene"],
                "scene_name": r["scene_name"] or r["scene"],
                "spend": spend,
                "sales": sales,
                "roi": round(sales / spend, 2) if spend else 0.0,
            }
        )
    avg_order_value = round(cur["sales"] / cur["orders"], 2) if cur["orders"] else 0.0
    value_per_visitor = round(cur["sales"] / cur["visitors"], 2) if cur["visitors"] else 0.0
    return {
        "range_label": range_label,
        "cur": cur,
        "prev": prev,
        "avg_order_value": avg_order_value,
        "value_per_visitor": value_per_visitor,
        "promo_scenes": promo_scenes,
        "chg": {
            "sales": _pct_chg(cur["sales"], prev["sales"]),
            "orders": _pct_chg(cur["orders"], prev["orders"]),
            "visitors": _pct_chg(cur["visitors"], prev["visitors"]),
            "conversion": round(cur["conversion_rate"] - prev["conversion_rate"], 2) if prev["conversion_rate"] else None,
        },
        "promo": {**promo, "ad_share": ad_share},
        "promo_chg": {
            "spend": _pct_chg(promo["spend"], promo_prev["spend"]),
            "roi": round(promo["roi"] - promo_prev["roi"], 2) if promo_prev["spend"] else None,
        },
        "trend": trend,
        "top_products": top_products,
        "peak": peak,
        "anomalies": anomalies,
    }


def _data_lines(d: dict) -> list[str]:
    """把采集到的经营数据整理成给模型看的数据行（解读与追问共用）。"""
    cur = d["cur"]
    chg = d["chg"]
    promo = d["promo"]
    pchg = d["promo_chg"]
    fmt_pct = lambda x: f"{x:+.1f}%" if x is not None else "—"
    fmt_pp = lambda x: f"{x:+.2f} 个百分点" if x is not None else "—"
    lines = [
        f"数据范围：{d['range_label']}",
        (
            f"销售额 {cur['sales']:.0f} 元（环比 {fmt_pct(chg['sales'])}），订单 {cur['orders']}（环比 {fmt_pct(chg['orders'])}），"
            f"访客 {cur['visitors']}（环比 {fmt_pct(chg['visitors'])}），转化率 {cur['conversion_rate']}%（较上期 {fmt_pp(chg['conversion'])}）"
        ),
        (
            f"推广花费 {promo['spend']:.0f} 元（环比 {fmt_pct(pchg['spend'])}），推广成交 {promo['sales']:.0f} 元，"
            f"推广ROI {promo['roi']}（较上期 {fmt_pp(pchg['roi'])}），广告成交占比 {promo['ad_share']}%"
        ),
    ]
    if d.get("avg_order_value") is not None:
        lines.append(f"客单价 {d['avg_order_value']:.2f} 元，单访客价值 {d['value_per_visitor']:.2f} 元")
    if d.get("promo_scenes"):
        lines.append("推广分场景：" + "、".join(f"{s['scene_name']}花费{s['spend']:.0f}元成交{s['sales']:.0f}元ROI{s['roi']}" for s in d["promo_scenes"]))
    if d["trend"]:
        lines.append("逐日销售额：" + "、".join(d["trend"]))
    if d["top_products"]:
        lines.append("TOP商品：" + "；".join(f"{p['item_title'][:24]} ¥{p['sales']:.0f}" for p in d["top_products"]))
    if d["peak"]:
        lines.append("高峰时段：" + "、".join(f"{p['hour']}（¥{p['sales']:.0f}）" for p in d["peak"]))
    if d["anomalies"]:
        lines.append("异常提醒：" + "；".join(d["anomalies"]))
    if any(x.endswith(":¥0") for x in d["trend"]):
        lines.append("注：部分日期销售额为0可能是数据未同步，解读时以有数据的日期为准，不要解读为经营异常。")
    return lines


def _build_insight_prompt(d: dict) -> str:
    prompt = (
        "你是淘宝店铺的运营数据分析师。请根据下面数据输出详细经营解读，严格按格式，每部分独占一段，条目用“- ”开头：\n"
        "【整体表现】2-3句话概括本期经营（含销售额、订单、访客、转化率、推广ROI关键数字，并说明同比/环比趋势）\n"
        "【亮点】\n- 销售/流量/转化/推广方面的亮点（3-4条，确实没有就写“本期暂无突出亮点”）\n"
        "【推广表现】\n- 分场景说明投放效果，点出ROI高/低的场景与原因（2-3条）\n"
        "【风险】\n- 数据异常、低效投放、转化下滑等（3条，没有就写“暂无明显风险”）\n"
        "【建议】\n- 具体可执行的运营/投放建议（4-5条，明确到动作或时段）\n"
        "简体中文务实，金额≥1万用X.X万简化；只依据给定数据，不要编造。\n\n"
        + "\n".join(_data_lines(d))
    )
    return prompt


def _parse_insight_sections(reply: str) -> dict:
    """解析【...】标记输出为结构化 sections（支持 5 段时段解读与通用 4 段）。"""
    import re as _re
    sections = {"overall": "", "highlights": [], "conversion": [], "promo": [], "risks": [], "suggestions": []}
    key_map = {
        "整体表现": "overall",
        "销售时段规律": "highlights",
        "亮点": "highlights",
        "流量与转化": "conversion",
        "流量转化": "conversion",
        "转化分析": "conversion",
        "流量分析": "conversion",
        "推广表现": "promo",
        "推广分析": "promo",
        "付费推广": "promo",
        "风险提醒": "risks",
        "风险": "risks",
        "投放建议": "suggestions",
        "建议": "suggestions",
    }
    found = False
    for m in _re.finditer(r"【([^】]+)】\s*(.*?)(?=【[^】]+】|$)", reply, _re.S):
        title = m.group(1).strip()
        key = key_map.get(title)
        if key is None:
            for _k, _v in key_map.items():
                if _k in title or title in _k:
                    key = _v
                    break
        if key is None:
            continue
        found = True
        body = m.group(2).strip()
        if key == "overall":
            sections[key] = _re.sub(r"\s+", " ", body).strip()
        else:
            items = []
            for line in body.splitlines():
                line = line.strip()
                if not line:
                    continue
                line = _re.sub(r"^[-•*]\s*", "", line)
                line = _re.sub(r"^\d+[.、)]\s*", "", line)
                if line:
                    items.append(line)
            if not items and body:
                items = [_re.sub(r"^[-•*]\s*", "", body)]
            sections[key] = items[:4]
    if not found:
        sections["overall"] = _re.sub(r"\s+", " ", reply).strip()
    return sections


def _insight_metrics(d: dict) -> list[dict]:
    chg = d["chg"]
    promo = d["promo"]
    pchg = d["promo_chg"]
    return [
        {"label": "销售额", "value": f"¥{d['cur']['sales']:,.0f}", "change": chg["sales"], "unit": "%"},
        {"label": "订单", "value": f"{d['cur']['orders']}", "change": chg["orders"], "unit": "%"},
        {"label": "访客", "value": f"{d['cur']['visitors']}", "change": chg["visitors"], "unit": "%"},
        {"label": "转化率", "value": f"{d['cur']['conversion_rate']}%", "change": chg["conversion"], "unit": "pp"},
        {"label": "推广花费", "value": f"¥{promo['spend']:,.0f}", "change": pchg["spend"], "unit": "%"},
        {"label": "推广ROI", "value": f"{promo['roi']}", "change": pchg["roi"], "unit": "val"},
    ]


@router.post("/insight")
def ai_insight(
    mode: str = "14",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    data = _collect_insight(mode, store_id, user, db)
    prompt = _build_insight_prompt(data)
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": prompt}], timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "sections": _parse_insight_sections(reply),
        "reply": reply,
        "metrics": _insight_metrics(data),
        "range": data["range_label"],
        "date": date_cls.today().isoformat(),
    }

class InsightMsgIn(BaseModel):
    role: str
    content: str


class InsightChatIn(BaseModel):
    mode: str = "14"
    store_id: int | None = None
    messages: list[InsightMsgIn] = []


@router.post("/insight/chat")
def ai_insight_chat(
    body: InsightChatIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    data = _collect_insight(body.mode, body.store_id, user, db)
    context = (
        "你是淘宝店铺的运营数据分析师。以下是当前数据上下文：\n"
        + "\n".join(_data_lines(data))
        + "\n用户会围绕这份数据追问，请结合数据回答，简洁务实，不要编造；数据里没有的信息要如实说明。"
    )
    msgs: list[dict] = [{"role": "system", "content": context}]
    for m in body.messages[-12:]:
        if m.role in ("user", "assistant") and (m.content or "").strip():
            msgs.append({"role": m.role, "content": m.content})
    try:
        reply = chat_completion(cfg, msgs, timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"reply": reply}


def _sum_product_rows(rows) -> dict:
    """商品每日明细汇总（销售额/订单/买家/访客/浏览/转化/加购/退款/收藏/客单价/UV价值等）。"""
    sales = 0.0
    orders = 0
    buyers = 0
    visitors = 0
    pv = 0
    add_cart = 0
    refund = 0.0
    clt = 0
    se_uv = 0
    se_pay = 0
    pp_w = 0.0
    uv_w = 0.0
    stay_w = 0.0
    bounce_w = 0.0
    se_rate_w = 0.0
    for r in rows:
        s = r["sales"] or 0
        sales += s
        orders += r["orders"] or 0
        buyers += r["buyers"] or 0
        visitors += r["visitors"] or 0
        pv += r["pv"] or 0
        add_cart += r["add_cart"] or 0
        refund += r["refund_amount"] or 0
        clt += r["item_clt_byr_cnt"] or 0
        se_uv += r["se_guide_uv"] or 0
        se_pay += r["se_guide_pay_byr_cnt"] or 0
        pp_w += (r["pay_pct"] or 0) * s
        uv_w += (r["uv_avg_value"] or 0) * s
        stay_w += (r["stay_time_avg"] or 0) * s
        bounce_w += (r["itm_bounce_rate"] or 0) * s
        se_rate_w += (r["se_guide_pay_rate"] or 0) * s
    return {
        "sales": round(sales, 2),
        "orders": orders,
        "buyers": buyers,
        "visitors": visitors,
        "pv": pv,
        "conversion_rate": round(buyers / visitors * 100, 2) if visitors else 0.0,
        "add_cart": add_cart,
        "refund_amount": round(refund, 2),
        "pay_pct": round(pp_w / sales, 2) if sales else 0.0,
        "item_clt_byr_cnt": clt,
        "uv_avg_value": round(uv_w / sales, 2) if sales else 0.0,
        "stay_time_avg": round(stay_w / sales, 1) if sales else 0.0,
        "itm_bounce_rate": round(bounce_w / sales, 2) if sales else 0.0,
        "se_guide_uv": se_uv,
        "se_guide_pay_byr_cnt": se_pay,
        "se_guide_pay_rate": round(se_rate_w / sales, 2) if sales else 0.0,
    }


def _lifecycle_of(item: dict) -> str:
    """商品生命周期：无销量 / 观察期 / 成长期 / 成熟期 / 衰退期（基于销售额与环比增速）。"""
    sales = item.get("sales") or 0
    cyc = item.get("sales_cycle")
    if sales <= 0:
        return "无销量"
    if cyc is None:
        return "观察期"
    if cyc > 30:
        return "成长期"
    if cyc < -30:
        return "衰退期"
    return "成熟期"


def _product_rank_realtime(item_id: str, store_id: int | None, user: dict, db) -> tuple[int, float, float]:
    """商品在店铺实时榜中的排名、销售占比与全店实时销售额。"""
    sf, sp = _store_filter(store_id, user)
    rows = db.execute("SELECT item_id, sales FROM store_item_realtime WHERE 1=1" + sf, sp).fetchall()
    items = sorted(rows, key=lambda r: r["sales"] or 0, reverse=True)
    store_total = sum(r["sales"] or 0 for r in items)
    rank = None
    sales = 0.0
    for i, r in enumerate(items):
        if r["item_id"] == item_id:
            rank = i + 1
            sales = r["sales"] or 0
            break
    share = round(sales / store_total * 100, 1) if store_total else 0.0
    return (rank or len(items) + 1), share, round(store_total, 2)


def _product_rank_days(item_id: str, store_id: int | None, days: int, user: dict, db) -> tuple[int, float, float]:
    """商品在店铺区间销售榜中的排名、占比与全店区间销售额。"""
    sf, sp = _store_filter(store_id, user)
    today = date_cls.today()
    start = today - timedelta(days=days - 1)
    rows = db.execute(
        "SELECT item_id, SUM(sales) AS sales FROM store_item_daily "
        "WHERE data_date >= ? AND data_date <= ?" + sf + " GROUP BY item_id",
        [start.isoformat(), today.isoformat()] + sp,
    ).fetchall()
    items = sorted(rows, key=lambda r: r["sales"] or 0, reverse=True)
    store_total = sum(r["sales"] or 0 for r in items)
    rank = None
    sales = 0.0
    for i, r in enumerate(items):
        if r["item_id"] == item_id:
            rank = i + 1
            sales = r["sales"] or 0
            break
    share = round(sales / store_total * 100, 1) if store_total else 0.0
    return (rank or len(items) + 1), share, round(store_total, 2)


def _product_trend_daily(item_id: str, store_id: int | None, days: int, user: dict, db) -> list[str]:
    """商品近 N 天逐日销售额（最多 7 个点）。"""
    sf, sp = _store_filter(store_id, user)
    today = date_cls.today()
    start = today - timedelta(days=days - 1)
    rows = db.execute(
        "SELECT data_date, sales FROM store_item_daily WHERE item_id = ? AND data_date >= ?" + sf + " ORDER BY data_date",
        [item_id, start.isoformat()] + sp,
    ).fetchall()
    return [f"{r['data_date'][5:]}:¥{r['sales'] or 0:.0f}" for r in rows[-7:]]


def _collect_product_data(item_id: str, store_id: int | None, mode: str, user: dict, db, start: str = "", end: str = "") -> dict:
    """按模式汇总单个商品的诊断数据。"""
    from .products import _product_rank_range, _range_promo_mode
    today = date_cls.today()
    ts = today.isoformat()
    sf, sp = _store_filter(store_id, user)
    rt = db.execute("SELECT * FROM store_item_realtime WHERE item_id = ?" + sf, [item_id] + sp).fetchone()
    title = (rt["item_title"] or "") if rt else ""
    image = (rt["image"] or "") if rt else ""

    if mode == "realtime":
        if rt:
            cur = {
                "sales": round(rt["sales"] or 0, 2),
                "orders": rt["orders"] or 0,
                "buyers": rt["buyers"] or 0,
                "visitors": rt["visitors"] or 0,
                "pv": rt["pv"] or 0,
                "conversion_rate": round(rt["conversion_rate"] or 0, 2),
                "add_cart": rt["add_cart"] or 0,
                "refund_amount": round(rt["refund_amount"] or 0, 2),
                "pay_pct": round(rt["pay_pct"] or 0, 2),
                "item_clt_byr_cnt": rt["item_clt_byr_cnt"] or 0,
                "uv_avg_value": round(rt["uv_avg_value"] or 0, 2),
                "stay_time_avg": round(rt["stay_time_avg"] or 0, 1),
                "itm_bounce_rate": round(rt["itm_bounce_rate"] or 0, 2),
                "se_guide_uv": rt["se_guide_uv"] or 0,
                "se_guide_pay_byr_cnt": rt["se_guide_pay_byr_cnt"] or 0,
                "se_guide_pay_rate": round(rt["se_guide_pay_rate"] or 0, 2),
            }
            chg = {
                "sales": round(rt["sales_cycle"] or 0, 1) if rt["sales_cycle"] is not None else None,
                "orders": round(rt["orders_cycle"] or 0, 1) if rt["orders_cycle"] is not None else None,
                "visitors": round(rt["visitors_cycle"] or 0, 1) if rt["visitors_cycle"] is not None else None,
                "conversion": round(rt["conversion_cycle"] or 0, 2) if rt["conversion_cycle"] is not None else None,
                "add_cart": round(rt["add_cart_cycle"] or 0, 1) if rt["add_cart_cycle"] is not None else None,
            }
        else:
            cur = {"sales": 0.0, "orders": 0, "buyers": 0, "visitors": 0, "pv": 0, "conversion_rate": 0.0, "add_cart": 0, "refund_amount": 0.0, "pay_pct": 0.0, "item_clt_byr_cnt": 0, "uv_avg_value": 0.0, "stay_time_avg": 0.0, "itm_bounce_rate": 0.0, "se_guide_uv": 0, "se_guide_pay_byr_cnt": 0, "se_guide_pay_rate": 0.0}
            chg = {"sales": None, "orders": None, "visitors": None, "conversion": None, "add_cart": None}
        rank, share, store_total = _product_rank_realtime(item_id, store_id, user, db)
        range_label = f"今日实时（{ts[5:]}）"
        trend = _product_trend_daily(item_id, store_id, 7, user, db)
    else:
        if start and end:
            try:
                s = date_cls.fromisoformat(start)
                e = date_cls.fromisoformat(end)
            except ValueError:
                s = e = None
            if not (s and e and s <= e):
                s, e = _date_range(int(mode) if str(mode).isdigit() else 14)
        else:
            try:
                days = int(mode)
            except (TypeError, ValueError):
                days = 14
            if not (1 <= days <= 90):
                days = 14
            e = today
            s = today - timedelta(days=days - 1)
        prev_end = s - timedelta(days=1)
        prev_start = prev_end - timedelta(days=(e - s).days)
        rows = db.execute(
            "SELECT * FROM store_item_daily WHERE item_id = ? AND data_date >= ? AND data_date <= ?" + sf + " ORDER BY data_date",
            [item_id, s.isoformat(), e.isoformat()] + sp,
        ).fetchall()
        prev_rows = db.execute(
            "SELECT * FROM store_item_daily WHERE item_id = ? AND data_date >= ? AND data_date <= ?" + sf,
            [item_id, prev_start.isoformat(), prev_end.isoformat()] + sp,
        ).fetchall()
        cur = _sum_product_rows(rows)
        prev = _sum_product_rows(prev_rows)
        if rows and not title:
            title = rows[-1]["item_title"] or ""
        prev_active_days = sum(1 for r in prev_rows if (r["sales"] or 0) > 0)
        if prev_active_days < 2:
            chg = {"sales": None, "orders": None, "visitors": None, "conversion": None, "add_cart": None}
        else:
            chg = {
                "sales": _pct_chg(cur["sales"], prev["sales"]),
                "orders": _pct_chg(cur["orders"], prev["orders"]),
                "visitors": _pct_chg(cur["visitors"], prev["visitors"]),
                "conversion": round(cur["conversion_rate"] - prev["conversion_rate"], 2) if prev["visitors"] else None,
                "add_cart": _pct_chg(cur["add_cart"], prev["add_cart"]),
            }
        if start and end:
            rank, share, store_total = _product_rank_range(item_id, store_id, s, e, db)
            range_label = f"{s.strftime('%m-%d')} ~ {e.strftime('%m-%d')}"
        else:
            rank, share, store_total = _product_rank_days(item_id, store_id, days, user, db)
            range_label = f"近 {days} 天（{s.strftime('%m-%d')}~{e.strftime('%m-%d')}）"
        trend = [f"{r['data_date'][5:]}:¥{r['sales'] or 0:.0f}" for r in rows[-7:]]

    if mode == "realtime":
        promo_mode = "realtime"
    elif mode == "yesterday":
        promo_mode = "yesterday"
    else:
        promo_mode = _range_promo_mode(s, e)
    prow = db.execute(
        "SELECT * FROM promo_item_stats WHERE item_id = ? AND mode = ?" + sf,
        [item_id, promo_mode] + sp,
    ).fetchone()
    promo = (
        {
            "spend": round(prow["spend"] or 0, 2),
            "sales": round(prow["sales"] or 0, 2),
            "roi": round(prow["roi"] or 0, 2),
            "clicks": int(prow["clicks"] or 0),
        }
        if prow
        else None
    )
    return {
        "item_id": item_id,
        "title": title or item_id,
        "image": image,
        "range_label": range_label,
        "cur": cur,
        "chg": chg,
        "trend": trend,
        "rank": rank,
        "share": share,
        "store_total_sales": store_total,
        "promo": promo,
    }


def _product_data_lines(d: dict) -> list[str]:
    """单品诊断数据行（解读与追问共用）。"""
    cur = d["cur"]
    chg = d["chg"]
    fmt_pct = lambda x: f"{x:+.1f}%" if x is not None else "—"
    fmt_pp = lambda x: f"{x:+.2f} 个百分点" if x is not None else "—"
    lines = [
        f"商品：{d['title']}（ID {d['item_id']}）",
        f"数据范围：{d['range_label']}",
        (
            f"销售额 {cur['sales']:.0f} 元（环比 {fmt_pct(chg['sales'])}），订单 {cur['orders']}（环比 {fmt_pct(chg['orders'])}），"
            f"访客 {cur['visitors']}（环比 {fmt_pct(chg['visitors'])}），转化率 {cur['conversion_rate']}%（较上期 {fmt_pp(chg['conversion'])}），"
            f"加购 {cur['add_cart']}（环比 {fmt_pct(chg['add_cart'])}），退款 {cur['refund_amount']:.0f} 元"
        ),
        (
            f"转化漏斗：访客 {cur['visitors']} → 收藏 {cur['item_clt_byr_cnt']}（收藏率 "
            f"{round(cur['item_clt_byr_cnt'] / (cur['visitors'] or 1) * 100, 1)}%）→ 加购 {cur['add_cart']}（加购率 "
            f"{round(cur['add_cart'] / (cur['visitors'] or 1) * 100, 1)}%）→ 支付买家 {cur['buyers']}（支付转化率 "
            f"{round(cur['buyers'] / (cur['visitors'] or 1) * 100, 1)}%）"
        ),
        f"店铺内排名第 {d['rank']} 名，占全店销售额 {d['share']}%（全店同期销售额 {d['store_total_sales']:.0f} 元）",
    ]
    if any(
        (
            cur.get("pay_pct") or 0,
            cur.get("uv_avg_value") or 0,
            cur.get("item_clt_byr_cnt") or 0,
            cur.get("stay_time_avg") or 0,
            cur.get("itm_bounce_rate") or 0,
        )
    ):
        lines.append(
            f"质量：客单价 {cur['pay_pct']:.0f} 元，UV价值 {cur['uv_avg_value']:.2f}，收藏买家 {cur['item_clt_byr_cnt']} 人，"
            f"平均停留 {cur['stay_time_avg']:.0f} 秒，跳失率 {cur['itm_bounce_rate']:.1f}%"
        )
    if cur.get("se_guide_uv"):
        lines.append(
            f"流量结构：搜索引导访客 {cur['se_guide_uv']}（占访客 {round(cur['se_guide_uv'] / (cur['visitors'] or 1) * 100, 1)}%），"
            f"搜索引导支付 {cur['se_guide_pay_byr_cnt']} 人，搜索引导转化率 {cur['se_guide_pay_rate']}%"
        )
    if d.get("promo"):
        promo = d["promo"]
        share = round(min(promo["sales"] / (d["cur"]["sales"] or 1) * 100, 100.0), 1)
        lines.append(f"推广：花费 {promo['spend']:.0f} 元，广告成交 {promo['sales']:.0f} 元，推广ROI {promo['roi']}，广告成交占该商品销售额 {share}%")
    if d["trend"]:
        lines.append("逐日销售额：" + "、".join(d["trend"]))
    return lines


def _build_product_prompt(d: dict) -> str:
    prompt = (
        "你是淘宝店铺的运营数据分析师。请针对下面这个单品输出诊断，要求严格按以下格式：\n"
        "【整体表现】一句话概括该商品本期表现并给出关键数字（销售额、订单、转化率、排名）。\n"
        "【亮点】\n- 亮点1\n- 亮点2\n- 亮点3\n- 亮点4\n- 亮点5（共5条，尽量覆盖不同维度：流量、转化、推广、排名、商品质量等；确有哪个维度没有亮点可少写，但不要编造）\n"
        "【流量与转化】分析流量结构与转化漏斗（访客→收藏→加购→支付买家，每步给出数量与转化率），"
        "指出流量来源是否单一、漏斗在哪一步流失最严重、UV价值/跳失率说明什么问题。\n"
        "【推广表现】分析推广效率（花费/广告成交/ROI/广告成交占比），判断推广是否值得、哪个环节低效。\n"
        "【风险】\n- 风险1\n- 风险2\n- 风险3\n- 风险4（最多4条，尽量覆盖不同角度：推广/转化/退款售后/体量等；没有就写“暂无明显风险”）\n"
        "【建议】\n- 建议1\n- 建议2\n- 建议3\n- 建议4\n- 建议5（共5条，尽量分别从：标题主图、流量获取、转化提升、推广优化、售后维护等方向给，每条具体可执行）\n"
        "简体中文、语气务实，不客套；金额≥1万用“X.X万”简化；只依据给定数据，不要编造。\n\n"
        + "\n".join(_product_data_lines(d))
    )
    return prompt


def _product_metrics(d: dict) -> list[dict]:
    cur = d["cur"]
    chg = d["chg"]
    metrics = [
        {"label": "销售额", "value": f"¥{cur['sales']:,.0f}", "change": chg["sales"], "unit": "%"},
        {"label": "订单", "value": f"{cur['orders']}", "change": chg["orders"], "unit": "%"},
        {"label": "转化率", "value": f"{cur['conversion_rate']}%", "change": chg["conversion"], "unit": "pp"},
        {"label": "加购", "value": f"{cur['add_cart']}", "change": chg["add_cart"], "unit": "%"},
        {"label": "退款", "value": f"¥{cur['refund_amount']:,.0f}", "change": None, "unit": "val"},
    ]
    if d.get("promo"):
        promo = d["promo"]
        share = round(min(promo["sales"] / (cur["sales"] or 1) * 100, 100.0), 1)
        metrics.extend(
            [
                {"label": "推广花费", "value": f"¥{promo['spend']:,.0f}", "change": None, "unit": "val"},
                {"label": "推广ROI", "value": f"{promo['roi']}", "change": None, "unit": "val"},
                {"label": "广告占比", "value": f"{share}%", "change": None, "unit": "val"},
            ]
        )
    metrics.extend(
        [
            {"label": "客单价", "value": f"¥{cur['pay_pct']:,.0f}", "change": None, "unit": "val"},
            {"label": "收藏买家", "value": f"{cur['item_clt_byr_cnt']}", "change": None, "unit": "val"},
            {"label": "UV价值", "value": f"{cur['uv_avg_value']:.2f}", "change": None, "unit": "val"},
            {"label": "停留时长", "value": f"{cur['stay_time_avg']:.0f}秒", "change": None, "unit": "val"},
            {"label": "跳失率", "value": f"{cur['itm_bounce_rate']:.1f}%", "change": None, "unit": "val"},
        ]
    )
    metrics.append({"label": "店铺排名", "value": f"第{d['rank']}名", "change": None, "unit": "val"})
    return metrics


class ProductMsgIn(BaseModel):
    role: str
    content: str


class ProductChatIn(BaseModel):
    mode: str = "realtime"
    store_id: int | None = None
    messages: list[ProductMsgIn] = []


@router.post("/products/{item_id}/insight")
def product_ai_insight(
    item_id: str,
    mode: str = "realtime",
    store_id: int | None = None,
    start: str = "",
    end: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    data = _collect_product_data(item_id, store_id, mode, user, db, start=start, end=end)
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": _build_product_prompt(data)}], timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "sections": _parse_insight_sections(reply),
        "reply": reply,
        "metrics": _product_metrics(data),
        "range": data["range_label"],
        "product": {"item_id": data["item_id"], "item_title": data["title"], "image": data["image"]},
        "date": date_cls.today().isoformat(),
    }


@router.post("/products/{item_id}/insight/chat")
def product_ai_insight_chat(
    item_id: str,
    body: ProductChatIn,
    start: str = "",
    end: str = "",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    data = _collect_product_data(item_id, body.store_id, body.mode, user, db, start=start, end=end)
    context = (
        "你是淘宝店铺的运营数据分析师。以下是该商品的数据上下文：\n"
        + "\n".join(_product_data_lines(data))
        + "\n用户会围绕这个商品追问，请结合数据回答，简洁务实，不要编造；数据里没有的信息要如实说明。"
    )
    msgs: list[dict] = [{"role": "system", "content": context}]
    for m in body.messages[-12:]:
        if m.role in ("user", "assistant") and (m.content or "").strip():
            msgs.append({"role": m.role, "content": m.content})
    try:
        reply = chat_completion(cfg, msgs, timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"reply": reply}
