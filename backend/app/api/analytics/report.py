"""数据洞察：经营日报、健康分、导出。"""

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

from .goal import _goal_value, analytics_linkage

router = APIRouter()

# ---------- 经营日报 ----------

def _report_day_summary(db, d: str, sf: str, sp: list) -> dict:
    rows = db.execute("SELECT * FROM store_daily_data WHERE data_date = ?" + sf, [d] + sp).fetchall()
    s = _sum_rows(rows)
    if len(rows) == 1 and rows[0]["conversion_rate"]:
        s["conversion_rate"] = round(rows[0]["conversion_rate"], 2)
    if rows:
        s["repeat_rate"] = round(rows[0]["repeat_rate"] or 0, 2)
        s["old_buyer_cnt"] = int(rows[0]["old_buyer_cnt"] or 0)
    s["avg_order_value"] = round(s["sales"] / s["orders"], 2) if s["orders"] else 0.0
    return s


def _report_top_items(db, d: str, sf: str, sp: list, realtime: bool, limit: int = 5) -> list[dict]:
    if realtime:
        rows = db.execute(
            "SELECT item_id, item_title, sales, orders, image FROM store_item_realtime WHERE 1=1"
            + sf + " ORDER BY sales DESC LIMIT " + str(limit),
            sp,
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT item_id, item_title, SUM(sales) AS sales, SUM(orders) AS orders, image FROM store_item_daily "
            "WHERE data_date = ?" + sf + " GROUP BY item_id ORDER BY sales DESC LIMIT " + str(limit),
            [d] + sp,
        ).fetchall()
    return [
        {
            "item_id": r["item_id"],
            "item_title": r["item_title"] or "",
            "image": r["image"] or "",
            "sales": round(r["sales"] or 0, 2),
            "orders": int(r["orders"] or 0),
        }
        for r in rows
    ]


def _report_scenes(db, d: str, sf: str, sp: list, realtime: bool) -> list[dict]:
    table = "promo_realtime" if realtime else "promo_daily_data"
    rows = db.execute(
        f"SELECT scene, scene_name, SUM(spend) AS spend, SUM(sales) AS sales FROM {table} "
        "WHERE data_date = ?" + sf + " GROUP BY scene ORDER BY spend DESC",
        [d] + sp,
    ).fetchall()
    return [
        {
            "scene": r["scene"],
            "scene_name": r["scene_name"] or r["scene"],
            "spend": round(r["spend"] or 0, 2),
            "sales": round(r["sales"] or 0, 2),
            "roi": round((r["sales"] or 0) / (r["spend"] or 0), 2) if r["spend"] else 0.0,
        }
        for r in rows
    ]


def _report_add_cart_refund(db, d: str, sf: str, sp: list, realtime: bool) -> dict:
    table = "store_item_realtime" if realtime else "store_item_daily"
    cond = ("WHERE 1=1" + sf) if realtime else ("WHERE data_date = ?" + sf)
    params = sp if realtime else [d] + sp
    r = db.execute(
        f"SELECT COALESCE(SUM(add_cart),0) AS ac, COALESCE(SUM(refund_amount),0) AS rf FROM {table} {cond}",
        params,
    ).fetchone()
    return {"add_cart": int(r["ac"] or 0), "refund_amount": round(r["rf"] or 0, 2)}


def _report_alerts(db, d: str, sf: str, sp: list, realtime: bool) -> list[dict]:
    """日报预警：销售额骤降商品（最多3）+ 推广ROI偏低计划（最多2）。"""
    alerts: list[dict] = []
    if realtime:
        rows = db.execute(
            "SELECT item_title, sales_cycle FROM store_item_realtime "
            "WHERE sales_cycle IS NOT NULL AND sales_cycle < -30 AND sales > 0" + sf + " ORDER BY sales_cycle ASC LIMIT 3",
            sp,
        ).fetchall()
        for r in rows:
            alerts.append({"level": "error", "type": "商品骤降", "message": f"{r['item_title']} 销售额环比 {r['sales_cycle']:.0f}%"})
    else:
        cur_rows = db.execute(
            "SELECT item_id, item_title, sales FROM store_item_daily WHERE data_date = ?" + sf,
            [d] + sp,
        ).fetchall()
        prev_rows = db.execute(
            "SELECT item_id, sales FROM store_item_daily WHERE data_date = ?" + sf,
            [(date_cls.fromisoformat(d) - timedelta(days=1)).isoformat()] + sp,
        ).fetchall()
        prev_map = {r["item_id"]: r["sales"] or 0 for r in prev_rows}
        drops = []
        for r in cur_rows:
            pv = prev_map.get(r["item_id"])
            if pv:
                cyc = (r["sales"] - pv) / pv * 100 if pv else 0
                if cyc < -30:
                    drops.append((cyc, r["item_title"]))
        for cyc, title in sorted(drops)[:3]:
            alerts.append({"level": "error", "type": "商品骤降", "message": f"{title} 销售额环比 {cyc:.0f}%"})
    mode = "realtime" if realtime else "yesterday"
    plan_sf = sf.replace("store_id", "s.store_id") if "store_id" in sf else sf
    plan_rows = db.execute(
        "SELECT p.plan_name, s.roi, s.spend FROM promo_plan_stats s "
        "JOIN promo_plans p ON p.store_id = s.store_id AND p.campaign_id = s.campaign_id "
        "WHERE s.mode = ? AND s.roi > 0 AND s.roi < 1 AND s.spend > 0"
        + plan_sf + " ORDER BY s.roi ASC LIMIT 2",
        [mode] + sp,
    ).fetchall()
    for r in plan_rows:
        alerts.append({"level": "warn", "type": "ROI偏低", "message": f"「{r['plan_name']}」推广ROI {r['roi']:.2f}"})
    return alerts


@router.get("/report")
def daily_report(
    date: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """经营日报：支持查看历史日期（date=YYYY-MM-DD），含完整指标/TOP商品/推广分场景/上周同期/预警。"""
    real_today = date_cls.today()
    # 经营日报默认分析昨天（前一天数据完整后再看），date 参数可指定任意日期
    if date:
        try:
            today = date_cls.fromisoformat(date)
        except ValueError:
            today = real_today - timedelta(days=1)
    else:
        today = real_today - timedelta(days=1)
    yesterday = today - timedelta(days=1)
    last_week = today - timedelta(days=7)
    ts, ys, ws = today.isoformat(), yesterday.isoformat(), last_week.isoformat()
    is_realtime = ts == real_today.isoformat()
    sf, sp = _store_filter(store_id, user)

    td = _report_day_summary(db, ts, sf, sp)
    yd = _report_day_summary(db, ys, sf, sp)
    wd = _report_day_summary(db, ws, sf, sp)

    if is_realtime:
        pr = db.execute(
            "SELECT COALESCE(SUM(spend),0) AS spend, COALESCE(SUM(sales),0) AS sales FROM promo_realtime WHERE data_date = ?" + sf,
            [ts] + sp,
        ).fetchone()
    else:
        pr = db.execute(
            "SELECT COALESCE(SUM(spend),0) AS spend, COALESCE(SUM(sales),0) AS sales FROM promo_daily_data WHERE data_date = ?" + sf,
            [ts] + sp,
        ).fetchone()
    py = db.execute(
        "SELECT COALESCE(SUM(spend),0) AS spend, COALESCE(SUM(sales),0) AS sales FROM promo_daily_data WHERE data_date = ?" + sf,
        [ys] + sp,
    ).fetchone()

    goal, _ = _goal_value(db)
    month = today.strftime("%Y-%m")
    month_rows = db.execute("SELECT sales FROM store_daily_data WHERE data_date LIKE ?" + sf, [month + "%"] + sp).fetchall()
    month_sales = round(sum(r["sales"] or 0 for r in month_rows), 2)

    ac = _report_add_cart_refund(db, ts, sf, sp, is_realtime)

    return {
        "date": ts,
        "is_today": is_realtime,
        "today": td,
        "yesterday": yd,
        "last_week": wd,
        "promo_today": {"spend": round(pr["spend"] or 0, 2), "sales": round(pr["sales"] or 0, 2), "roi": round((pr["sales"] or 0) / (pr["spend"] or 0), 2) if pr["spend"] else 0.0},
        "promo_yesterday": {"spend": round(py["spend"] or 0, 2), "sales": round(py["sales"] or 0, 2), "roi": round((py["sales"] or 0) / (py["spend"] or 0), 2) if py["spend"] else 0.0},
        "promo_today_scenes": _report_scenes(db, ts, sf, sp, is_realtime),
        "promo_yesterday_scenes": _report_scenes(db, ys, sf, sp, False),
        "top_today": _report_top_items(db, ts, sf, sp, is_realtime),
        "top_yesterday": _report_top_items(db, ys, sf, sp, False),
        "add_cart": ac["add_cart"],
        "refund_amount": ac["refund_amount"],
        "report_alerts": _report_alerts(db, ts, sf, sp, is_realtime),
        "goal": goal,
        "month_sales": month_sales,
        "month": month,
    }


def _report_text_lines(r: dict) -> list[str]:
    t = r["today"]
    pt = r["promo_today"]
    lines = [f"【经营日报 {r['date']}】"]
    lines.append(
        f"访客 {t['visitors']}｜销售额 ¥{t['sales']:,.0f}｜订单 {t['orders']}｜转化率 {t['conversion_rate']}%"
        f"｜客单价 ¥{t['avg_order_value']:,.0f}"
    )
    if r.get("add_cart"):
        lines.append(f"加购 {r['add_cart']}")
    lines.append(f"推广：花费 ¥{pt['spend']:,.0f}，成交 ¥{pt['sales']:,.0f}，ROI {pt['roi']:.2f}")
    if r["promo_today_scenes"]:
        sc = "；".join(f"{x['scene_name']}花¥{x['spend']:,.0f}/ROI{x['roi']:.2f}" for x in r["promo_today_scenes"])
        lines.append("分场景：" + sc)
    if r["top_today"]:
        top = "、".join(f"{x['item_title'][:14]}¥{x['sales']:,.0f}" for x in r["top_today"][:3])
        lines.append("TOP商品：" + top)
    return lines


@router.get("/report/text")
def report_text(
    date: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """经营日报纯文本（供复制/推送）。"""
    report = daily_report(date=date, store_id=store_id, user=user, db=db)
    return {"text": "\n".join(_report_text_lines(report)), "date": report["date"]}


@router.post("/report/ai")
def report_ai(
    date: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """AI 生成今日经营总结（可复制发群）。"""
    from backend.app.api.model_configs import get_default_config
    from backend.app.core.ai_client import AIError, chat_completion

    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    report = daily_report(date=date, store_id=store_id, user=user, db=db)
    context = "\n".join(_report_text_lines(report))
    prompt = (
        "你是淘宝店铺的运营分析师。根据下面这份经营日报（默认是昨日数据），写一段120字以内的日报总结，口语化、适合直接发到工作群。"
        "包含：整体表现一句话、今天最值得注意的亮点或问题、一句明天建议。不要编造数据。\n\n" + context
    )
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": prompt}], timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"reply": reply, "date": report["date"], "report": report}


def _report_push_config(db) -> dict:
    default = {"enabled": False, "webhook": "", "hour": 9, "minute": 0}
    row = db.execute("SELECT value FROM meta WHERE key = 'daily_report_push'").fetchone()
    if row and row["value"]:
        try:
            data = _json.loads(row["value"])
            for k in default:
                if k in data and isinstance(data[k], (int, float, str, bool)):
                    default[k] = data[k]
        except (ValueError, TypeError):
            pass
    return default


class ReportPushIn(BaseModel):
    enabled: bool = False
    webhook: str = ""
    hour: int = 21
    minute: int = 0


@router.get("/report/push-config")
def get_push_config(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    return _report_push_config(db)


@router.put("/report/push-config")
def set_push_config(
    body: ReportPushIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = {
        "enabled": bool(body.enabled),
        "webhook": (body.webhook or "").strip(),
        "hour": max(0, min(23, int(body.hour))),
        "minute": max(0, min(59, int(body.minute))),
    }
    db.execute(
        "INSERT INTO meta (key, value) VALUES ('daily_report_push', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_json.dumps(cfg, ensure_ascii=False),),
    )
    return {"ok": True, **cfg}


def send_report_webhook(webhook: str, text: str) -> None:
    """推送日报文本到群机器人（钉钉/企业微信 通用格式）。"""
    import urllib.request

    body = _json.dumps({"msgtype": "text", "text": {"content": text}}).encode("utf-8")
    req = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"})
    # 显式禁用代理：WorkBuddy 会话注入的 HTTP_PROXY/HTTPS_PROXY 会劫持 urllib 导致连不上
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=15) as resp:
        resp.read()


@router.post("/report/push")
def push_report_now(
    date: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """手动触发一次日报推送（测试）。"""
    cfg = _report_push_config(db)
    if not cfg["webhook"]:
        raise HTTPException(status_code=400, detail="还没有配置推送 webhook，请先到「推送设置」填写")
    report = daily_report(date=date, store_id=store_id, user=user, db=db)
    text = "\n".join(_report_text_lines(report))
    try:
        send_report_webhook(cfg["webhook"], text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"推送失败：{exc}") from exc
    return {"ok": True}


def _build_analysis_context(r: dict) -> str:
    t, y = r["today"], r["yesterday"]
    pt, py = r["promo_today"], r["promo_yesterday"]
    real_roi = t["sales"] / pt["spend"] if pt["spend"] else 0.0
    prev_real_roi = y["sales"] / py["spend"] if py["spend"] else 0.0
    lines = [
        f"日期：{r['date']}",
        f"访客 {t['visitors']}（前日 {y['visitors']}）｜销售额 ¥{t['sales']:,.0f}（前日 ¥{y['sales']:,.0f}）｜订单 {t['orders']}｜转化率 {t['conversion_rate']}%｜客单价 ¥{t['avg_order_value']:,.0f}｜真实ROI {real_roi:.2f}（前日 {prev_real_roi:.2f}）",
    ]
    if r.get("add_cart"):
        lines.append(f"加购 {r['add_cart']} 次")
    lines.append(f"推广：花费 ¥{pt['spend']:,.0f}，成交 ¥{pt['sales']:,.0f}，推广ROI {pt['roi']:.2f}，真实ROI {real_roi:.2f}")
    for x in r["promo_today_scenes"]:
        lines.append(f"场景 {x['scene_name']}：花费 ¥{x['spend']:,.0f}，成交 ¥{x['sales']:,.0f}，ROI {x['roi']:.2f}")
    if r["top_today"]:
        lines.append("TOP商品：" + "；".join(f"{x['item_title'][:14]} ¥{x['sales']:,.0f}" for x in r["top_today"][:3]))
    if r["report_alerts"]:
        lines.append("异常：" + "；".join(a["message"] for a in r["report_alerts"]))
    return "\n".join(lines)


_ANALYSIS_KEYS = ["经营分析", "推广分析", "异常分析", "总结", "今日行动建议"]


def _parse_analysis_sections(reply: str) -> dict:
    import re as _re

    sections = {k: "" for k in _ANALYSIS_KEYS}
    matches = list(_re.finditer(r"【(.+?)】", reply))
    for i, m in enumerate(matches):
        key = m.group(1)
        if key in sections:
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(reply)
            sections[key] = reply[start:end].strip()
    return sections


@router.post("/report/analysis")
def report_analysis(
    date: str = "",
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """AI 详细经营分析：经营分析/推广分析/异常分析/总结/今日行动建议。"""
    from backend.app.api.model_configs import get_default_config
    from backend.app.core.ai_client import AIError, chat_completion

    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    report = daily_report(date=date, store_id=store_id, user=user, db=db)
    context = _build_analysis_context(report)
    prompt = (
        "你是淘宝店铺的资深运营专家。基于下面这份昨日真实经营数据，输出一份详细的经营分析报告。"
        "严格按格式，每部分独占一段，条目用“- ”开头，务实用数据说话、可执行，不要编造：\n"
        "【经营分析】2-4句话：整体经营状况（销售额、访客、转化、客单价、真实ROI 及环比），指出趋势和问题\n"
        "【推广分析】2-4句话：付费推广表现（总花费/成交/ROI/真实ROI、各场景优劣、哪些场景在浪费钱、推广ROI与真实ROI的差异）\n"
        "【异常分析】逐条列出数据里的异常（商品骤降、ROI偏低计划、转化异常等），说明可能影响\n"
        "【总结】2-3句话：今天整体状况一句话总结\n"
        "【今日行动建议】3-5条具体可执行的建议（调预算、停投/加投场景、优化哪些商品、补货/定价等），落到具体场景或商品\n\n"
        + context
    )
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": prompt}], timeout=180.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"sections": _parse_analysis_sections(reply), "reply": reply, "date": report["date"]}


@router.get("/export")
def export_analytics(
    days: int = 14,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> StreamingResponse:
    if not (1 <= days <= 90):
        days = 14
    start, today = _date_range(days)
    linkage = analytics_linkage(days=days, user=user, db=db)
    wb = Workbook()
    ws = wb.active
    ws.title = "经营数据"
    ws.append(["日期", "总销售额", "总访客", "总订单", "推广花费", "推广成交", "推广ROI", "广告成交占比", "整体ROI", "自然销售额"])
    for item in linkage["items"]:
        ws.append(
            [
                item["date"],
                item["total_sales"],
                item["total_visitors"],
                item["total_orders"],
                item["promo_spend"],
                item["promo_sales"],
                item["promo_roi"],
                f"{item['ad_share']}%",
                item["overall_roi"],
                item["natural_sales"],
            ]
        )
    widths = [12, 12, 10, 10, 12, 12, 10, 14, 10, 12]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + idx)].width = width
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"经营数据_{today.strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


# ---------- 健康分 ----------

@router.get("/health")
def analytics_health(
    days: int = 14,
    store_id: int | None = None,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    if not (1 <= days <= 90):
        days = 14
    start, today = _date_range(days)
    sf, sp = _store_filter(store_id, user)
    rows = db.execute(
        "SELECT * FROM store_daily_data WHERE data_date >= ? AND data_date <= ?" + sf + " ORDER BY data_date",
        [start.isoformat(), today.isoformat()] + sp,
    ).fetchall()
    if not rows:
        return {"score": 0, "items": [], "days": days}

    def agg(rs):
        s = _sum_rows(rs)
        if len(rs) == 1 and rs[0]["conversion_rate"]:
            s["conversion_rate"] = round(rs[0]["conversion_rate"], 2)
        return s

    today_s = agg([r for r in rows if r["data_date"] == today.isoformat()])
    prev_rows = [r for r in rows if r["data_date"] != today.isoformat()]
    base = agg(prev_rows) if prev_rows else None

    items = []
    # 1) 销售额趋势
    if base and base["sales"]:
        chg = (today_s["sales"] - base["sales"]) / base["sales"] * 100
    else:
        chg = 0.0
    score = min(max(50 + chg * 2, 0), 100)
    items.append({"key": "sales", "name": "销售额", "score": round(score), "detail": f"今日 ¥{today_s['sales']:.2f}" + (f"，较前日均值 {chg:+.1f}%" if base and base["sales"] else "，暂无对比基准")})

    # 2) 转化率
    if base and base["conversion_rate"]:
        chg = today_s["conversion_rate"] - base["conversion_rate"]
    else:
        chg = 0.0
    score = min(max(60 + chg * 5, 0), 100)
    items.append({"key": "conv", "name": "转化率", "score": round(score), "detail": f"今日 {today_s['conversion_rate']:.2f}%" + (f"，较前日均值 {chg:+.2f} 个百分点" if base else "")})

    # 3) 访客
    if base and base["visitors"]:
        chg = (today_s["visitors"] - base["visitors"]) / base["visitors"] * 100
    else:
        chg = 0.0
    score = min(max(50 + chg, 0), 100)
    items.append({"key": "uv", "name": "访客", "score": round(score), "detail": f"今日 {today_s['visitors']}" + (f"，较前日均值 {chg:+.1f}%" if base and base["visitors"] else "")})

    # 4) 推广 ROI（区间平均）
    promo_rows = db.execute(
        "SELECT * FROM promo_daily_data WHERE data_date >= ? AND data_date <= ?" + sf,
        [start.isoformat(), today.isoformat()] + sp,
    ).fetchall()
    pspend = sum(r["spend"] or 0 for r in promo_rows)
    psales = sum(r["sales"] or 0 for r in promo_rows)
    roi = psales / pspend if pspend else 0.0
    score = min(max(roi / 2.0 * 100, 0), 100) if pspend else 0
    items.append({"key": "roi", "name": "推广 ROI", "score": round(score), "detail": f"区间 ROI {roi:.2f}" + ("（目标 2.0）" if pspend else "，暂无推广数据")})

    total = sum(i["score"] for i in items) / len(items)
    return {"score": round(total), "items": items, "days": days}
