"""万相台推广数据抓取：复用店铺的淘宝登录档案（taobao.com 通用登录态）调用万相台 one.alimama.com 接口。

依赖项目内内置的 alimama-cli（MIT 协议，见 backend/alimama_cli/LICENSE）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from backend.app.core.scrape_guard import exclusive_scrape
from backend.app.core.scrape_resilience import (
    ensure_login_available,
    is_login_error,
    retry_with_backoff,
    trip_login_circuit,
)
from backend.app.core.sycm import has_profile, profile_path

CLI_DIR = Path(__file__).resolve().parent.parent.parent / "alimama_cli"
CLI_SCRIPT = CLI_DIR / "alimama_cli.py"
PYTHON = sys.executable

_ENV = dict(os.environ)
# 清掉继承的代理环境变量：WorkBuddy 会话会注入 HTTP_PROXY/HTTPS_PROXY（如 127.0.0.1:7892），
# 抓取万相台数据应直连，否则 curl 走无效代理报 (7) Could not connect
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    _ENV.pop(_k, None)
_ENV["ALIMAMA_BYPASS_CURFEW"] = "1"
_ENV["SYCM_BYPASS_CURFEW"] = "1"
_ENV["PYTHONIOENCODING"] = "utf-8"
_ENV["PYTHONUTF8"] = "1"

SCENES = [
    ("wholesite", "onebpSite", "货品全站推广"),
    ("keyword", "onebpSearch", "关键词推广"),
    ("crowd", "onebpDisplay", "人群推广"),
    ("content", "onebpShortVideo", "内容营销"),
]

SCENE_NAMES = {key: name for key, _, name in SCENES}


class AlimamaError(Exception):
    """带用户可读信息的万相台抓取错误。"""


def _friendly(text: str) -> str:
    if not text:
        return "万相台操作失败，请稍后再试"
    if (
        "登录态无效" in text
        or "未找到阿里妈妈登录态" in text
        or "请重新登录" in text
        or "重新绑定" in text
    ):
        return "万相台登录已失效，请重新点「打开浏览器登录」绑定店铺"
    if "验证码" in text or "滑块" in text or "风控" in text or "操作过于频繁" in text:
        return "万相台触发了安全验证，请稍后再试"
    return text


def _run_cli(store: dict, args: list[str], timeout: float = 120) -> tuple[str, str, int]:
    if not has_profile(store["id"]):
        raise AlimamaError("该店铺还没有绑定生意参谋/万相台登录，请先点「打开浏览器登录」")
    if not CLI_SCRIPT.exists():
        raise AlimamaError("万相台组件缺失，请先更新程序")
    env = dict(_ENV)
    env["ALIMAMA_COOKIE_FILE"] = str(profile_path(store["id"]))
    cmd = [str(PYTHON), str(CLI_SCRIPT), *args]
    try:
        with exclusive_scrape():
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
                cwd=str(CLI_DIR),
            )
    except FileNotFoundError as exc:
        raise AlimamaError(f"无法启动 Python：{exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AlimamaError("万相台请求超时，请稍后再试") from exc
    return proc.stdout or "", proc.stderr or "", proc.returncode or 0


def _run_json_once(store: dict, args: list[str], timeout: float = 120) -> dict:
    out, err, code = _run_cli(store, args, timeout=timeout)
    if code != 0:
        text = (err or out or "").strip().replace("\n", "；")
        raise AlimamaError(_friendly(text))
    try:
        return json.loads(out)
    except ValueError as exc:
        raise AlimamaError("万相台返回异常，请稍后再试") from exc


def _run_json(store: dict, args: list[str], timeout: float = 120) -> dict:
    store_id = int(store["id"])
    profile = profile_path(store_id)
    ensure_login_available("alimama", store_id, profile, AlimamaError)
    try:
        return retry_with_backoff(lambda: _run_json_once(store, args, timeout))
    except AlimamaError as exc:
        if is_login_error(exc):
            trip_login_circuit("alimama", store_id, profile, str(exc))
        raise


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def check_access(store: dict) -> dict:
    """验证该店铺登录态能否访问万相台。"""
    out, err, code = _run_cli(store, ["doctor"], timeout=60)
    if code != 0:
        raise AlimamaError(_friendly((err or out or "").strip()))
    return {"ok": True, "store_id": store["id"], "store_name": store["name"]}


_SCENE_DAILY_FIELDS = [
    "adPv", "charge", "click", "ctr", "alipayInshopAmt", "alipayInshopNum",
    "cvr", "roi", "cartInshopNum",
]


def fetch_scene_daily(store: dict, start: str, end: str) -> list[dict]:
    """拉取各推广场景按天的数据（展现/点击/花费/成交/ROI 等），逐场景调用接口。"""
    body = {
        "bizCode": "universalBP",
        "fromRealTime": False,
        "source": "baseReport",
        "from": "pcBaseReport",
        "byPage": True,
        "totalTag": True,
        "needCountAccelerate": True,
        "rptType": "account",
        "queryDomains": ["date"],
        "queryFieldIn": _SCENE_DAILY_FIELDS,
        "startTime": start,
        "endTime": end,
        "splitType": "day",
        "effectEqual": 15,
        "havingList": [],
        "pageSize": 100,
        "pageNo": 1,
        "unifyType": "zhai",
    }
    body_json = json.dumps(body, ensure_ascii=False)
    out: list[dict] = []
    for key, biz, name in SCENES:
        payload = _run_json(
            store,
            ["api", f"/report/query.json?bizCode={biz}", "--body", body_json],
        )
        for row in (payload.get("data") or {}).get("list") or []:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "scene": key,
                    "scene_name": name,
                    "date": row.get("thedate") or row.get("startTime") or "",
                    "impressions": int(_num(row.get("adPv"))),
                    "clicks": int(_num(row.get("click"))),
                    "ctr": round(_num(row.get("ctr")) * 100, 2),
                    "spend": round(_num(row.get("charge")), 2),
                    "sales": round(_num(row.get("alipayInshopAmt")), 2),
                    "roi": round(_num(row.get("roi")), 2),
                    "orders": int(_num(row.get("alipayInshopNum"))),
                    "add_cart": int(_num(row.get("cartInshopNum") or row.get("colCartNum"))),
                    "conversion_rate": round(_num(row.get("cvr")) * 100, 2),
                }
            )
    return out


def _campaign_page(payload: dict) -> tuple[list[dict], int | None]:
    data = payload.get("data") or {}
    if not isinstance(data, dict) or "list" not in data or not isinstance(data.get("list"), list):
        raise AlimamaError("万相台计划列表格式异常，本次未更新计划状态")
    rows = data["list"]
    raw_count = data.get("count")
    try:
        count = int(raw_count) if raw_count is not None else None
    except (TypeError, ValueError):
        count = None
    return rows, count


def _fetch_campaign_pages(store: dict, key: str, page_size: int = 100) -> list[dict]:
    """完整读取一个推广场景；只有所有分页均成功时才返回。"""
    rows: list[dict] = []
    page = 1
    total: int | None = None
    while page <= 100:
        payload = _run_json(
            store,
            [f"promo-{key}", "--limit", str(page_size), "--page", str(page), "--raw"],
        )
        batch, count = _campaign_page(payload)
        if total is None:
            total = count
        rows.extend(batch)
        if not batch or (total is not None and len(rows) >= total) or len(batch) < page_size:
            break
        page += 1
    else:
        raise AlimamaError("万相台计划数量异常，本次未更新计划状态")
    if total is not None and len(rows) < total:
        raise AlimamaError(f"万相台计划列表未读取完整（{len(rows)}/{total}），本次未更新计划状态")
    return rows


def _fetch_content_campaign_pages(store: dict, page_size: int = 100) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    total: int | None = None
    for _ in range(100):
        body = json.dumps(
            {
                "bizCode": "onebpShortVideo",
                "adgroupRequired": True,
                "offset": offset,
                "pageSize": page_size,
                "statusList": ["start", "pause"],
            },
            ensure_ascii=False,
        )
        payload = _run_json(
            store,
            ["api", "/campaign/horizontal/findPage.json?bizCode=onebpShortVideo", "--body", body],
        )
        batch, count = _campaign_page(payload)
        if total is None:
            total = count
        rows.extend(batch)
        if not batch or (total is not None and len(rows) >= total) or len(batch) < page_size:
            break
        offset += page_size
    else:
        raise AlimamaError("万相台内容营销计划数量异常，本次未更新计划状态")
    if total is not None and len(rows) < total:
        raise AlimamaError(f"万相台内容营销计划未读取完整（{len(rows)}/{total}），本次未更新计划状态")
    return rows


def fetch_plan_snapshots(store: dict) -> list[dict]:
    """完整拉取各推广场景的当前计划快照。任一分页失败时整体失败，避免误判计划失效。"""
    plans: list[dict] = []
    for key in ("crowd", "keyword", "wholesite"):
        payload = {"data": {"list": _fetch_campaign_pages(store, key)}}
        plans.extend(_parse_campaigns(payload, key, SCENE_NAMES.get(key, key)))
    content_payload = {"data": {"list": _fetch_content_campaign_pages(store)}}
    plans.extend(_parse_campaigns(content_payload, "content", "内容营销"))
    return plans


def _parse_campaigns(payload: dict, key: str, name: str) -> list[dict]:
    out: list[dict] = []
    for c in (payload.get("data") or {}).get("list") or []:
        if not isinstance(c, dict):
            continue
        out.append(
            {
                "scene": key,
                "scene_name": name,
                "campaign_id": str(c.get("campaignId") or ""),
                "plan_name": c.get("campaignName") or "",
                "day_budget": round(_num(c.get("dayBudget")), 2),
                # 万相台预算接口要求同时提交预算类型。当前接口返回字段名为
                # dmcType：normal 表示日预算，unlimited 表示不限预算。
                "budget_type": str(c.get("dmcType") or "").strip().lower(),
                "bid_type": c.get("bidType") or c.get("constraintType") or "",
                "bid_value": round(_num(c.get("constraintValue")), 2),
                "status": "在投" if c.get("onlineStatus") == 1 else "暂停",
                "gmt_create": c.get("gmtCreate") or "",
            }
        )
    return out


def fetch_plan_reports(store: dict, start: str, end: str) -> list[dict]:
    """拉取计划维度报表（各计划的花费/成交/ROI/点击）。"""
    payload = _run_json(
        store, ["report-campaign", "--date", start, "--end-date", end, "--limit", "100", "--raw"]
    )
    out: list[dict] = []
    for r in (payload.get("data") or {}).get("list") or []:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "campaign_id": str(r.get("campaignId") or ""),
                "plan_name": r.get("promotionName") or "",
                "spend": round(_num(r.get("charge")), 2),
                "sales": round(_num(r.get("alipayInshopAmt")), 2),
                "roi": round(_num(r.get("roi")), 2),
                "clicks": int(_num(r.get("click"))),
            }
        )
    return out
REALTIME_SCENES = SCENES


def fetch_realtime(store: dict, target_date: str | None = None) -> list[dict]:
    """拉取指定日期各推广场景的实时数据（按小时，分场景）。

    万相台默认实时报表只覆盖短视频/关键词；货品全站等场景需按 bizCode 单独查。
    ``target_date`` 默认今天；补历史时传入昨天，可把昨日实时小时留存下来。
    """
    target_date = target_date or date.today().isoformat()
    fields = ["adPv", "charge", "click", "ctr", "alipayInshopAmt", "alipayInshopNum", "cvr", "roi"]
    body = {
        "bizCode": "universalBP",
        "fromRealTime": True,
        "source": "baseReport",
        "from": "pcBaseReport",
        "byPage": True,
        "totalTag": True,
        "needCountAccelerate": True,
        "rptType": "real_time",
        "queryDomains": ["date"],
        "queryFieldIn": fields,
        "startTime": target_date,
        "endTime": target_date,
        "splitType": "hour",
        "effectEqual": 15,
        "havingList": [],
        "pageSize": 100,
        "pageNo": 1,
        "orderField": "charge",
        "orderBy": "desc",
        "unifyType": "zhai",
        "offset": 0,
    }
    body_json = json.dumps(body, ensure_ascii=False)
    # 按 (场景, 小时) 先聚合再返回：部分场景（如关键词）实时接口会把多行时间戳都标成 00:00，
    # 不聚合直接入库会被唯一键去重、丢掉总额。
    agg: dict[tuple[str, str], dict] = {}
    for key, biz, name in REALTIME_SCENES:
        payload = _run_json(
            store,
            ["api", f"/report/query.json?bizCode={biz}", "--body", body_json],
        )
        rows = (payload.get("data") or {}).get("list") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            thedate = row.get("thedate") or ""
            hour = thedate[-5:] if len(thedate) >= 5 else thedate
            k = (key, hour)
            item = agg.setdefault(
                k,
                {
                    "scene": key,
                    "scene_name": name,
                    "hour": hour,
                    "impressions": 0,
                    "clicks": 0,
                    "spend": 0.0,
                    "sales": 0.0,
                    "orders": 0,
                },
            )
            item["impressions"] += int(_num(row.get("adPv")))
            item["clicks"] += int(_num(row.get("click")))
            item["spend"] += _num(row.get("charge"))
            item["sales"] += _num(row.get("alipayInshopAmt"))
            item["orders"] += int(_num(row.get("alipayInshopNum")))
    out: list[dict] = []
    for item in agg.values():
        imp = item["impressions"]
        clicks = item["clicks"]
        spend = item["spend"]
        sales = item["sales"]
        item["ctr"] = round(clicks / imp * 100, 2) if imp else 0.0
        item["roi"] = round(sales / spend, 2) if spend else 0.0
        item["conversion_rate"] = 0.0
        item["spend"] = round(spend, 2)
        item["sales"] = round(sales, 2)
        out.append(item)
    return out
def fetch_plan_realtime(store: dict, target_date: str | None = None, through_hour: int | None = None) -> list[dict]:
    """拉取计划维度数据；可按历史日期截至指定小时汇总，用于同一时段环比。"""
    today = date.today().isoformat()
    target_date = target_date or today
    # report-realtime 接口也支持历史日期，能返回留存 ROI。
    is_realtime = True
    fields = ["campaignId", "roi", "retainedRoi", "charge", "adPv", "click", "ctr", "cvr", "ecpc", "ecpm",
              "alipayInshopAmt", "alipayInshopNum", "alipayDirAmt", "alipayDirNum", "alipayIndirAmt", "alipayIndirNum",
              "cartInshopNum", "cartDirNum", "cartIndirNum",
              "refundDirAmt", "refundDirNum", "refundIndirAmt", "refundIndirNum",
              "retainedAlipayInshopAmt", "retainedAlipayInshopNum"]
    merged: dict[str, dict] = {}
    # 历史计划小时明细统一走 universalBP；按场景地址查询会漏掉货品全站。
    requests = [("all", "universalBP", "全量")] if through_hour is not None else SCENES
    for _key, biz, _name in requests:
        page = 1
        while True:
            body = {
                "mx_bizCode": "universalBP" if through_hour is not None else "onebpSite",
                "bizCode": "universalBP" if through_hour is not None else "onebpSite",
                "tab": "campaign",
                "startTime": target_date,
                "endTime": target_date,
                "byPage": True,
                "pageSize": 100,
                "pageNo": page,
                "offset": (page - 1) * 100,
                "computeType": "sum",
                "effectEqual": "15",
                "fromRealTime": is_realtime,
                "queryDomains": ["campaign", "date"] if through_hour is not None else ["campaign"],
                "queryFieldIn": fields,
                "sourceList": ["scene", "campaign_list"],
                "splitType": "hour" if through_hour is not None else "sum",
                "unifyType": "last_click_by_effect_time",
            }
            body_json = json.dumps(body, ensure_ascii=False)
            payload = _run_json(
                store,
                ["api", f"/report/query.json?bizCode={biz}", "--body", body_json],
            )
            rows = (payload.get("data") or {}).get("list") or []
            got = 0
            for r in rows:
                if not isinstance(r, dict):
                    continue
                cid = str(r.get("campaignId") or "")
                if not cid:
                    continue
                if through_hour is not None:
                    stamp = str(r.get("thedate") or r.get("date") or r.get("hour") or "")
                    time_text = stamp.replace("T", " ").split()[-1] if stamp else ""
                    hour_text = time_text[:2] if len(time_text) >= 2 and time_text[:2].isdigit() else ""
                    if not hour_text or int(hour_text) > through_hour:
                        continue
                got += 1
                item = merged.setdefault(cid, {"campaign_id": cid})
                for _f in fields:
                    if _f == "campaignId":
                        continue
                    _v = _num(r.get(_f))
                    if _f in ("roi", "retainedRoi", "ctr", "cvr", "ecpc", "ecpm"):
                        item[_f] = max(item.get(_f, 0.0), _v)
                    else:
                        item[_f] = item.get(_f, 0.0) + _v
            if len(rows) < 100 or not rows:
                break
            page += 1
    out: list[dict] = []
    for item in merged.values():
        item["spend"] = round(item.get("charge") or 0, 2)
        item["sales"] = round(item.get("alipayInshopAmt") or 0, 2)
        item["alipay_dir"] = round(item.get("alipayDirAmt") or 0, 2)
        item["alipay_indir"] = round(item.get("alipayIndirAmt") or 0, 2)
        item["retained_sales"] = round(item.get("retainedAlipayInshopAmt") or 0, 2)
        item["refund_amt"] = round((item.get("refundDirAmt") or 0) + (item.get("refundIndirAmt") or 0), 2)
        item["roi"] = round(item["sales"] / item["spend"], 2) if item["spend"] else 0.0
        item["retained_roi"] = (
            round(item["retained_sales"] / item["spend"], 2)
            if item["spend"] and item["retained_sales"]
            else round(item.get("retainedRoi") or 0, 2)
        )
        item["clicks"] = int(item.get("click") or 0)
        out.append(item)
    return out


def fetch_item_report(store: dict, start: str, end: str, realtime: bool = False) -> list[dict]:
    """万相台商品报表（方案A）：按商品维度的推广花费/成交/ROI/点击。

    实时走 report-realtime（--dim promotion），历史走 report-item；两者都支持任意日期区间。
    """
    cmd = "report-realtime" if realtime else "report-item"
    all_rows: list[dict] = []
    offset = 0
    for _ in range(200):
        payload = _run_json(
            store,
            [cmd, "--date", start, "--end-date", end, "--dim", "promotion", "--limit", "100", "--offset", str(offset), "--raw"],
            timeout=180,
        )
        d = payload.get("data") or {}
        rows = d.get("list") or []
        count = int(_num(d.get("count")))
        for r in rows:
            if not isinstance(r, dict):
                continue
            item_id = str(r.get("promotionId") or "").strip()
            if not item_id:
                continue
            all_rows.append(
                {
                    "item_id": item_id,
                    "item_title": r.get("promotionName") or "",
                    "spend": round(_num(r.get("charge")), 2),
                    "sales": round(_num(r.get("alipayInshopAmt")), 2),
                    "roi": round(_num(r.get("roi")), 2),
                    "clicks": int(_num(r.get("click"))),
                    "orders": int(_num(r.get("alipayInshopNum"))),
                    "impressions": int(_num(r.get("adPv"))),
                }
            )
        offset += len(rows)
        if not rows or offset >= count:
            break
    return all_rows


def _campaign_item(row: dict) -> tuple[str | None, str | None]:
    """从计划行里取出 (宝贝ID, 商品标题)，对应 CLI 的 _promo_item。"""
    for ag_field in ("adgroupList", "lastAdgroup"):
        ag = row.get(ag_field)
        if isinstance(ag, dict):
            ag = [ag]
        if isinstance(ag, list) and ag:
            mat = (ag[0] or {}).get("material") or {}
            mid = mat.get("materialId")
            if mid:
                return str(mid), (mat.get("title") or mat.get("itemTitle") or "")
    return None, None


def _campaign_items(row: dict) -> list[tuple[str, str]]:
    """一个计划下的所有商品 (item_id, title)：每个 adgroup = 一个商品。"""
    out: list[tuple[str, str]] = []
    for ag in (row.get("adgroupList") or []):
        ag = ag or {}
        mat = ag.get("material") or {}
        mid = mat.get("materialId")
        if not mid:
            continue
        title = mat.get("title") or mat.get("itemTitle") or ""
        out.append((str(mid), title))
    if not out:
        ag = row.get("lastAdgroup")
        if isinstance(ag, dict):
            ag = [ag]
        if isinstance(ag, list) and ag:
            mat = (ag[0] or {}).get("material") or {}
            mid = mat.get("materialId")
            if mid:
                out.append((str(mid), mat.get("title") or mat.get("itemTitle") or ""))
    return out


def _promo_item_map(store: dict) -> dict[str, list[dict]]:
    """宝贝↔计划映射：campaign_id -> [{item_id, item_title}]（方案B）。

    关键词推广的计划级接口经常返回 ``material=null``，因此不能依赖
    ``promo-keyword`` 的计划行来取商品。CLI 的 ``promo-units`` 改走
    ``/adgroup/horizontal/findPage`` 单元接口，该接口会稳定返回
    ``material.materialId``。
    """
    mapping: dict[str, list[dict]] = {}
    for scene in ("wholesite", "keyword", "crowd"):
        try:
            payload = _run_json(
                store,
                ["promo-units", "--biz", scene, "--status", "start", "pause", "end", "--raw"],
                timeout=180,
            )
            units = payload.get("units") or []
            for unit in units:
                if not isinstance(unit, dict):
                    continue
                cid = str(unit.get("campaignId") or "").strip()
                item_id = str(unit.get("itemId") or "").strip()
                if not cid or not item_id:
                    continue
                bucket = mapping.setdefault(cid, [])
                if not any(item.get("item_id") == item_id for item in bucket):
                    bucket.append({"item_id": item_id, "item_title": unit.get("title") or ""})
        except AlimamaError:
            # 保持兼容：旧接口仍可为全站/人群推广提供兜底映射。
            cmd = f"promo-{scene}"
            offset = 0
            for _ in range(200):
                payload = _run_json(store, [cmd, "--limit", "100", "--page", str(offset // 100 + 1), "--raw"], timeout=180)
                d = payload.get("data") or {}
                rows = d.get("list") or []
                count = int(_num(d.get("count")))
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    cid = str(row.get("campaignId") or "").strip()
                    if not cid:
                        continue
                    for item_id, item_title in _campaign_items(row):
                        bucket = mapping.setdefault(cid, [])
                        if not any(item.get("item_id") == item_id for item in bucket):
                            bucket.append({"item_id": item_id, "item_title": item_title or ""})
                offset += len(rows)
                if not rows or offset >= count:
                    break
    return mapping


def fetch_promo_item_fallback(store: dict, start: str, end: str, realtime: bool = False) -> list[dict]:
    """方案B兜底：宝贝↔计划映射 + 计划花费归因（单商品计划全额，多商品计划均摊）。"""
    stats = fetch_plan_realtime(store) if realtime else fetch_plan_reports(store, start, end)
    mapping = _promo_item_map(store)
    agg: dict[str, dict] = {}
    for st in stats:
        cid = st.get("campaign_id") or ""
        items = mapping.get(cid) or []
        if not items:
            continue
        n = len(items)
        for it in items:
            row = agg.setdefault(
                it["item_id"],
                {"item_id": it["item_id"], "item_title": it.get("item_title") or "", "spend": 0.0, "sales": 0.0, "roi": 0.0, "clicks": 0, "orders": 0, "impressions": 0},
            )
            row["spend"] += _num(st.get("spend")) / n
            row["sales"] += _num(st.get("sales")) / n
            row["clicks"] += int(_num(st.get("clicks"))) / n
    out: list[dict] = []
    for row in agg.values():
        row["spend"] = round(row["spend"], 2)
        row["sales"] = round(row["sales"], 2)
        row["clicks"] = int(row["clicks"])
        row["roi"] = round(row["sales"] / row["spend"], 2) if row["spend"] else 0.0
        out.append(row)
    return out


def fetch_item_promo_plan_based(store: dict, start: str, end: str, realtime: bool = True) -> list[dict]:
    """推广计划 → 商品 的推广数据（全站推广 + 关键词 + 人群，不含内容营销）。

    每个计划绑定若干商品，计划花费按商品均摊；同一商品跨多个计划时累加。
    """
    mapping = _promo_item_map(store)
    stats = fetch_plan_realtime(store) if realtime else fetch_plan_reports(store, start, end)
    agg: dict[str, dict] = {}
    for st in stats:
        cid = st.get("campaign_id") or ""
        items = mapping.get(cid) or []
        if not items:
            continue
        n = len(items)
        for it in items:
            key = it["item_id"]
            row = agg.setdefault(
                key,
                {"item_id": key, "item_title": it["item_title"] or "", "spend": 0.0, "sales": 0.0, "roi": 0.0, "clicks": 0, "orders": 0, "impressions": 0},
            )
            row["spend"] += _num(st.get("spend")) / n
            row["sales"] += _num(st.get("sales")) / n
            row["clicks"] += int(_num(st.get("clicks"))) / n
    out: list[dict] = []
    for row in agg.values():
        row["spend"] = round(row["spend"], 2)
        row["sales"] = round(row["sales"], 2)
        row["clicks"] = int(row["clicks"])
        row["roi"] = round(row["sales"] / row["spend"], 2) if row["spend"] else 0.0
        out.append(row)
    return out


_SCENE_HOURLY_FIELDS = ["adPv", "charge", "click", "alipayInshopAmt", "alipayInshopNum"]


def fetch_scene_hourly(store: dict, target_date: str, timeout: float = 180) -> list[dict]:
    """拉取某天各推广场景的 24 小时分时数据（splitType=hour，支持历史日期）。"""
    body = {
        "bizCode": "universalBP",
        "fromRealTime": False,
        "source": "baseReport",
        "from": "pcBaseReport",
        "byPage": True,
        "totalTag": True,
        "needCountAccelerate": True,
        "rptType": "account",
        "queryDomains": ["date"],
        "queryFieldIn": _SCENE_HOURLY_FIELDS,
        "startTime": target_date,
        "endTime": target_date,
        "splitType": "hour",
        "effectEqual": 15,
        "havingList": [],
        "pageSize": 50,
        "pageNo": 1,
        "orderField": "charge",
        "orderBy": "desc",
        "unifyType": "zhai",
        "offset": 0,
    }
    body_json = json.dumps(body, ensure_ascii=False)
    out: list[dict] = []
    for key, biz, name in SCENES:
        payload = _run_json(store, ["api", f"/report/query.json?bizCode={biz}", "--body", body_json], timeout=timeout)
        for row in (payload.get("data") or {}).get("list") or []:
            if not isinstance(row, dict):
                continue
            thedate = str(row.get("thedate") or "")
            hour = thedate[-5:] if len(thedate) >= 5 else ""
            if not hour:
                continue
            out.append(
                {
                    "date": target_date,
                    "hour": hour,
                    "scene": key,
                    "scene_name": name,
                    "impressions": int(_num(row.get("adPv"))),
                    "clicks": int(_num(row.get("click"))),
                    "spend": round(_num(row.get("charge")), 2),
                    "sales": round(_num(row.get("alipayInshopAmt")), 2),
                    "orders": int(_num(row.get("alipayInshopNum"))),
                }
            )
    return out
