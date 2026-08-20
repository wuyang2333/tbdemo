"""生意参谋数据抓取：通过专用 Chrome 的登录态调用生意参谋接口。

- 今天（实时）：调用 portal/live/new/index/overview/v3.json?dateType=today
  （与生意参谋首页「数据概览」实时卡一致，返回 支付金额/访客/浏览量/支付买家数/支付订单数/转化率）
- 历史日期：调用 portal/coreIndex/new/overview/v3.json（数据概览按日）

Windows 上读取 Chrome 登录态采用 CDP（Chrome DevTools Protocol）方案：
- 首次使用会在专用 Chrome 窗口里登录一次，登录态自动保存（不导出 Cookie、不动日常浏览器）
- 每个店铺对应一份命名登录档案，同步时按店铺读取，互不干扰
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# 项目内内置的 sycm-cli（MIT 协议，见 backend/sycm_cli/LICENSE）
CLI_DIR = Path(__file__).resolve().parent.parent.parent / "sycm_cli"
CLI_SCRIPT = CLI_DIR / "sycm_cli.py"
PYTHON = sys.executable

# 后台自动同步可能发生在夜间，放开 CLI 的 1:00-6:00 禁跑限制
_ENV = dict(os.environ)
# 清掉继承的代理环境变量：WorkBuddy 会话会注入 HTTP_PROXY/HTTPS_PROXY（如 127.0.0.1:7892），
# 抓取国内生意参谋数据应直连，否则 curl 走无效代理报 (7) Could not connect
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    _ENV.pop(_k, None)
_ENV["SYCM_BYPASS_CURFEW"] = "1"
_ENV["PYTHONIOENCODING"] = "utf-8"
_ENV["PYTHONUTF8"] = "1"

LOGIN_WAIT_SECONDS = int(os.environ.get("SYCM_LOGIN_WAIT", "300"))
BIND_POLL_STEP = 5

_LIVE_PATH = "/portal/live/new/index/overview/v3.json"
_DAY_PATH = "/portal/coreIndex/new/overview/v3.json"
_HOME_REFERER = "https://sycm.taobao.com/portal/home.htm"


class SycmError(Exception):
    """带用户可读信息的抓取错误。"""


# ---------- 店铺登录档案 ----------

def profile_name(store_id: int) -> str:
    return f"store_{store_id}"


def profile_path(store_id: int) -> Path:
    root = Path(
        os.environ.get(
            "TAOBAO_CLI_PROFILE_DIR",
            str(Path.home() / ".taobao-cli" / "profiles"),
        )
    )
    return root / f"{profile_name(store_id)}.json"


PROFILE_MISSING_MSG = "生意参谋未登录（未配置登录档案）"


def has_profile(store_id: int) -> bool:
    """该店铺是否已保存生意参谋登录档案。"""
    return profile_path(store_id).exists()


# ---------- 调用内置 CLI ----------

def _run_cli(
    args: list[str],
    timeout: float = 120,
    input_data: str | None = None,
) -> tuple[str, str, int]:
    """运行内置 sycm-cli，返回 (stdout, stderr, exit_code)。"""
    if not CLI_SCRIPT.exists():
        raise SycmError("生意参谋组件缺失，请先更新程序")
    cmd = [str(PYTHON), str(CLI_SCRIPT), *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=input_data.encode("utf-8") if input_data else None,
            timeout=timeout,
            env=_ENV,
            cwd=str(CLI_DIR),
        )
    except FileNotFoundError as exc:
        raise SycmError(f"无法启动 Python：{exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SycmError("生意参谋请求超时，请稍后再试") from exc
    return proc.stdout or "", proc.stderr or "", proc.returncode or 0


def _friendly_error(text: str) -> str:
    """把 CLI 的报错翻译成给用户看的提示。"""
    if not text:
        return "生意参谋操作失败，请稍后再试"
    if "不存在" in text and ("profile" in text.lower() or "登录态" in text):
        return "该店铺还没有绑定生意参谋登录，请先点「打开浏览器登录」"
    if (
        "You must login" in text
        or "登录系统" in text
        or "未找到淘宝登录态" in text
        or "登录已过期" in text
        or "请重新登录" in text
    ):
        return "生意参谋登录已失效，请重新打开浏览器登录"
    if "验证码" in text or "滑块" in text or "风控" in text or "操作过于频繁" in text:
        return "生意参谋触发了安全验证，请稍后再试"
    if "超时" in text:
        return "等待登录超时，请确认已在 Chrome 窗口完成登录后重试"
    return text


def _ensure_profile(store: dict) -> None:
    if not has_profile(store["id"]):
        raise SycmError("该店铺还没有绑定生意参谋登录，请先点「打开浏览器登录」")


def _run_api_json(args: list[str], timeout: float = 120) -> dict:
    """运行 CLI 的 api 命令并解析返回 JSON。"""
    out, err, code = _run_cli(args, timeout=timeout)
    if code != 0:
        text = (err or out or "").strip().replace("\n", "；")
        raise SycmError(_friendly_error(text))
    try:
        return json.loads(out)
    except ValueError as exc:
        raise SycmError("生意参谋返回异常，请稍后再试") from exc


def _check_content(payload: dict) -> None:
    content = payload.get("content") or {}
    code = content.get("code")
    if payload.get("hasError") is True or code not in (None, 0, 200, "0", "200"):
        msg = content.get("message") or content.get("msg") or "未知错误"
        raise SycmError(_friendly_error(f"生意参谋返回失败：{msg}"))


def _to_num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _take(item: dict, field: str):
    """从 {字段: {value, cycleCrc}} 结构里取值。"""
    return (item.get(field) or {}).get("value")


def _norm_img(url: str) -> str:
    """规范化商品图片 URL：兼容协议相对地址，并修复重复协议（https:https:// 等）。"""
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("https:https://"):
        return "https://" + url[len("https:https://"):]
    if url.startswith("http:http://"):
        return "http://" + url[len("http:http://"):]
    return url


# ---------- 实时（今天） ----------

def _run_live_overview(store: dict, timeout: float = 120) -> dict:
    _ensure_profile(store)
    return _run_api_json(
        [
            "--store",
            profile_name(store["id"]),
            "api",
            _LIVE_PATH,
            "-p",
            "dateType=today",
            "--referer",
            _HOME_REFERER,
        ],
        timeout=timeout,
    )


def _parse_live_overview(payload: dict) -> dict:
    _check_content(payload)
    data = (payload.get("content") or {}).get("data") or {}
    today = (data.get("data") or {}).get("today") or {}
    return {
        "visitors": int(_to_num(_take(today, "uv"))),
        "pv": int(_to_num(_take(today, "pv"))),
        "sales": round(_to_num(_take(today, "payAmt")), 2),
        "orders": int(_to_num(_take(today, "payOrdCnt") or _take(today, "payByrCnt"))),
        "buyers": int(_to_num(_take(today, "payByrCnt"))),
        "conversion_rate": round(_to_num(_take(today, "payRate")) * 100, 2),
        "repeat_rate": round(_to_num(_take(today, "reVisitAmtRatio")) * 100, 1),
        "update_time": (data.get("data") or {}).get("updateTime") or (data.get("updateTime") or ""),
    }


# ---------- 历史日期（数据概览按日） ----------

def _run_day_overview(store: dict, target_date: str, timeout: float = 120) -> dict:
    _ensure_profile(store)
    return _run_api_json(
        [
            "--store",
            profile_name(store["id"]),
            "api",
            _DAY_PATH,
            "-p",
            f"dateType=day",
            "-p",
            f"dateRange={target_date}|{target_date}",
            "-p",
            "needCycleCrc=true",
            "--referer",
            _HOME_REFERER,
        ],
        timeout=timeout,
    )


def _parse_day_overview(payload: dict) -> dict:
    _check_content(payload)
    data = (payload.get("content") or {}).get("data") or {}
    self_ = data.get("self") or {}
    return {
        "visitors": int(_to_num(_take(self_, "uv"))),
        "pv": int(_to_num(_take(self_, "pv"))),
        "sales": round(_to_num(_take(self_, "payAmt")), 2),
        "orders": int(_to_num(_take(self_, "payOrdCnt") or _take(self_, "payByrCnt"))),
        "buyers": int(_to_num(_take(self_, "payByrCnt"))),
        "conversion_rate": round(_to_num(_take(self_, "payRate")) * 100, 2),
        "repeat_rate": round(_to_num(_take(self_, "reVisitAmtRatio")) * 100, 1),
        "old_buyer_cnt": int(_to_num(_take(self_, "payOldByrCnt"))),
        "repeat_sales": round(_to_num(_take(self_, "rePurchasePayAmount") or _take(self_, "olderPayAmt")), 2),
    }


# ---------- 对外接口 ----------

def check_sycm_login(store: dict) -> dict:
    """验证该店铺的生意参谋登录是否有效（调一次今天的实时接口）。"""
    payload = _run_live_overview(store)
    _parse_live_overview(payload)
    return {"ok": True, "store_id": store["id"], "store_name": store["name"]}


def fetch_store_daily(store: dict, target_date: str | None = None) -> dict:
    """抓取单个店铺指定日期的指标：今天走实时接口，历史日期走数据概览。"""
    target = target_date or date.today().isoformat()
    if target == date.today().isoformat():
        payload = _run_live_overview(store)
        metrics = _parse_live_overview(payload)
    else:
        payload = _run_day_overview(store, target)
        metrics = _parse_day_overview(payload)
    metrics["date"] = target
    return metrics


def _verify_profile(store: dict, name: str) -> dict:
    """用刚保存的档案调今天的实时接口验证登录。

    新登录态首次请求偶发风控：耐心重试几次（隔几秒再试），
    与手动点「测试」的等待效果一致；仍失败则交给前端手动「测试/保存」。
    """
    last_error = ""
    for attempt in range(5):
        try:
            payload = _run_live_overview(store, timeout=120)
            metrics = _parse_live_overview(payload)
            return {
                "ok": True,
                "profile": name,
                "metrics": metrics,
            }
        except SycmError as exc:
            last_error = str(exc)
            time.sleep(3 + attempt * 4)  # 3,7,11,15,19 → 最多约 55 秒重试窗口
    raise SycmError(last_error or "登录成功但实时数据验证失败，请点击「测试」确认后保存")


def bind_login(store: dict, wait_seconds: int | None = None) -> dict:
    """打开专用 Chrome 并等待用户登录该店铺，登录成功后保存档案并验证。"""
    name = profile_name(store["id"])
    total_wait = wait_seconds or LOGIN_WAIT_SECONDS
    _run_cli(["export-profile", name], timeout=total_wait + 30)
    return _verify_profile(store, name)


def bind_login_from_browser(store: dict) -> dict:
    """不弹窗：直接从当前 Chrome/Edge 读取已登录的生意参谋登录态并保存为档案。"""
    name = profile_name(store["id"])
    out, err, code = _run_cli(["export-default", name], timeout=120)
    if code != 0:
        text = (err or out or "").strip().replace("\n", "；")
        raise SycmError(_friendly_error(text))
    return _verify_profile(store, name)


def bind_login_from_cookies(store: dict, cookies_text: str) -> dict:
    """不弹窗：粘贴当前浏览器里复制的登录态 cookie，保存并验证。"""
    name = profile_name(store["id"])
    out, err, code = _run_cli(
        ["import-cookies", name],
        timeout=60,
        input_data=cookies_text,
    )
    if code != 0:
        text = (err or out or "").strip().replace("\n", "；")
        raise SycmError(_friendly_error(text))
    return _verify_profile(store, name)

def fetch_hourly(store: dict, timeout: float = 120) -> list[dict]:
    """拉取生意参谋今日/昨日分时数据（累计序列，转每小时增量）。"""
    payload = _run_api_json(
        [
            "--store",
            profile_name(store["id"]),
            "api",
            "/portal/live/new/index/trend/v3.json",
            "-p",
            "dateType=today",
            "--referer",
            _HOME_REFERER,
        ],
        timeout=timeout,
    )
    content = payload.get("content") or {}
    data = (content.get("data") or {}).get("data") or {}
    today = date.today()
    out: list[dict] = []
    for label, offset in (("today", 0), ("yesterday", 1)):
        block = data.get(label) or {}
        if not block:
            continue
        ds = (today - timedelta(days=offset)).isoformat()
        uv = block.get("uv") or []
        pv = block.get("pv") or []
        pay = block.get("payAmt") or []
        byr = block.get("payByrCnt") or []
        ord_ = block.get("payOrdCnt") or []
        prev = {"uv": 0, "pv": 0, "pay": 0.0, "byr": 0, "ord": 0}
        for h in range(24):
            cur = {
                "uv": int(_to_num(uv[h])) if h < len(uv) else 0,
                "pv": int(_to_num(pv[h])) if h < len(pv) else 0,
                "pay": _to_num(pay[h]) if h < len(pay) else 0.0,
                "byr": int(_to_num(byr[h])) if h < len(byr) else 0,
                "ord": int(_to_num(ord_[h])) if h < len(ord_) else 0,
            }
            duv = max(cur["uv"] - prev["uv"], 0)
            out.append(
                {
                    "date": ds,
                    "hour": f"{h:02d}:00",
                    "visitors": duv,
                    "pv": max(cur["pv"] - prev["pv"], 0),
                    "sales": round(max(cur["pay"] - prev["pay"], 0), 2),
                    "orders": max(cur["ord"] - prev["ord"], 0),
                    "buyers": max(cur["byr"] - prev["byr"], 0),
                    "conversion_rate": round(max(cur["byr"] - prev["byr"], 0) / duv * 100, 2) if duv else 0.0,
                }
            )
            prev = cur
    return out
def fetch_item_sales(store: dict, target_date: str, timeout: float = 120) -> list[dict]:
    """拉取指定日期商品排行（生意参谋 商品-商品排行，全量商品 + 40+ 指标，自动翻页）。"""
    out: list[dict] = []
    page = 1
    while True:
        # 实测（2026-08-20）：商品排行 top.json 对「最近一个完整日」必须带
        # compareType=cycle，否则 recordCount=0 返回空；对更早的日期带不带都行。
        # 之前注释声称带 compareType 会导致昨日单日查询为空，属于误判（当时
        # 可能撞上了风控或日期未出数），实际带上的效果才是对的，统一带上。
        payload = _run_api_json(
            [
                "--store",
                profile_name(store["id"]),
                "api",
                "/cc/item/view/top.json",
                "-p",
                f"dateRange={target_date}|{target_date}",
                "-p",
                "dateType=day",
                "-p",
                f"page={page}",
                "-p",
                "pageSize=10",
                "-p",
                "order=desc",
                "-p",
                "orderBy=payAmt",
                "-p",
                "device=0",
                "-p",
                "compareType=cycle",
            ],
            timeout=timeout,
        )
        data = payload.get("data") or {}
        rows = data.get("data") or []
        if not isinstance(rows, list) or not rows:
            break
        for r in rows:
            if not isinstance(r, dict):
                continue
            item = r.get("item") or {}
            title = str(item.get("title") or "")
            if not title:
                continue
            out.append(
                {
                    "item_id": str(
                        (r.get("mainProductId") or {}).get("value")
                        if isinstance(r.get("mainProductId"), dict)
                        else r.get("mainProductId") or item.get("itemId") or ""
                    ),
                    "item_title": title,
                    "image": _norm_img(str(item.get("pictUrl") or "")),
                    "sales": round(_to_num(_take(r, "payAmt")), 2),
                    "orders": int(_to_num(_take(r, "payItmCnt"))),
                    "buyers": int(_to_num(_take(r, "payByrCnt"))),
                    "visitors": int(_to_num(_take(r, "itmUv"))),
                    "pv": int(_to_num(_take(r, "itmPv"))),
                    "conversion_rate": round(_to_num(_take(r, "payRate")) * 100, 2),
                    "add_cart": int(_to_num(_take(r, "itemCartCnt"))),
                    "refund_amount": round(_to_num(_take(r, "sucRefundAmt")), 2),
                    "pay_pct": round(_to_num(_take(r, "payPct")), 2),
                    "item_clt_byr_cnt": int(_to_num(_take(r, "itemCltByrCnt"))),
                    "uv_avg_value": round(_to_num(_take(r, "uvAvgValue")), 2),
                    "stay_time_avg": round(_to_num(_take(r, "stayTimeAvg")), 2),
                    "itm_bounce_rate": round(_to_num(_take(r, "itmBounceRate")) * 100, 2),
                    "se_guide_uv": int(_to_num(_take(r, "seGuideUv"))),
                    "se_guide_pay_byr_cnt": int(_to_num(_take(r, "seGuidePayByrCnt"))),
                    "se_guide_pay_rate": round(_to_num(_take(r, "seGuidePayRate")) * 100, 2),                }

            )
        total = data.get("recordCount") or 0
        if len(out) >= total or len(rows) < 10:
            break
        page += 1
    return out
def fetch_shop_flow_source(store: dict, target_date: str | None = None, timeout: float = 120) -> list[dict]:
    """流量来源排行 Top（生意参谋 流量看板-流量来源排行）。返回 [{rank, source, uv, desc}]。"""
    target = target_date or date.today().isoformat()
    payload = _run_api_json(
        [
            "--store", profile_name(store["id"]),
            "api", "/flow/overview/live/shopFlowSourceTop/v4.json",
            "-p", f"dateRange={target}|{target}",
            "-p", "dateType=today" if target == date.today().isoformat() else "day",
            "-p", "pageSize=50", "-p", "page=1", "-p", "order=desc", "-p", "orderBy=uv",
            "-p", "device=2", "-p", "flowBizType=all", "-p", "pageType=all", "-p", "indexCode=uv",
        ],
        timeout=timeout,
    )
    rows = (payload.get("data") or {}).get("data") or []
    out: list[dict] = []
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "rank": i,
                "source": str(_take(r, "pageName") or ""),
                "uv": int(_to_num(_take(r, "uv"))),
                "desc": str(_take(r, "pageDesc") or ""),
            }
        )
    return out


def fetch_shop_refund(store: dict, timeout: float = 120) -> dict:
    """拉取今日实时退款（生意参谋 首页-数据概括 退款金额-完结时间）。返回 dict。"""
    payload = _run_live_overview(store, timeout=timeout)
    _check_content(payload)
    data = (payload.get("content") or {}).get("data") or {}
    today_d = (data.get("data") or {}).get("today") or {}
    yest_d = (data.get("data") or {}).get("yestday") or {}

    def _val(item: dict, field: str) -> float:
        return _to_num(_take(item, field))

    cycle_raw = (today_d.get("rfdSucAmt") or {}).get("cycleCrc")
    cycle = round(float(cycle_raw) * 100, 1) if cycle_raw is not None else None
    return {
        "amount": round(_val(today_d, "rfdSucAmt"), 2),
        "pay_amt": round(_val(today_d, "payAmt"), 2),
        "rate": round(_val(today_d, "payAmtRfdRate") * 100, 2),
        "ord_rate": round(_val(today_d, "ordRfdRate") * 100, 2),
        "cycle": cycle,
        "yest_amount": round(_val(yest_d, "rfdSucAmt"), 2),
        "yest_pay_amt": round(_val(yest_d, "payAmt"), 2),
        "yest_rate": round(_val(yest_d, "payAmtRfdRate") * 100, 2),
        "update_time": (data.get("data") or {}).get("updateTime") or (data.get("updateTime") or ""),
    }


def fetch_item_realtime(store: dict, index: str = "payAmt", timeout: float = 120) -> list[dict]:
    """拉取今日商品排行实时数据（商品-商品排行-实时档，全量商品，自动翻页）。"""
    today = date.today().isoformat()
    fields = ["payAmt", "payItmCnt", "payRate", "itmUv", "itmPv", "payByrCnt", "itemCartCnt", "sucRefundAmt", "payPct", "itemCltByrCnt", "uvAvgValue", "stayTimeAvg", "itmBounceRate", "seGuideUv", "seGuidePayByrCnt", "seGuidePayRate"]
    out: list[dict] = []
    page = 1
    while True:
        payload = _run_api_json(
            [
                "--store",
                profile_name(store["id"]),
                "api",
                "/cc/item/live/view/top.json",
                "-p",
                "dateType=today",
                "-p",
                f"dateRange={today}|{today}",
                "-p",
                "indexCode=" + ",".join(fields),
                "-p",
                f"page={page}",
                "-p",
                "pageSize=20",
                "-p",
                "order=desc",
                "-p",
                "orderBy=payAmt",
                "-p",
                "device=0",
            ],
            timeout=timeout,
        )
        data = payload.get("data") or {}
        inner = data.get("data") or {}
        rows = inner.get("data") or []
        if not isinstance(rows, list) or not rows:
            break

        def _id(x) -> str:
            return str(x.get("value") or "") if isinstance(x, dict) else str(x or "")

        def _cycle(field: str) -> float:
            v = r.get(field)
            if not isinstance(v, dict):
                return 0.0
            return round(_to_num(v.get("cycleCrc")) * 100, 2)

        for r in rows:
            if not isinstance(r, dict):
                continue
            item = r.get("item") or {}
            title = str(item.get("title") or "")
            if not title:
                continue
            pic = str(item.get("pictUrl") or "")
            out.append(
                {
                    "item_id": _id(r.get("mainProductId")) or _id(r.get("itemId")) or _id(item.get("itemId")),
                    "item_title": title,
                    "image": _norm_img(pic),
                    "visitors": int(_to_num(_take(r, "itmUv"))),
                    "pv": int(_to_num(_take(r, "itmPv"))),
                    "buyers": int(_to_num(_take(r, "payByrCnt"))),
                    "orders": int(_to_num(_take(r, "payItmCnt"))),
                    "sales": round(_to_num(_take(r, "payAmt")), 2),
                    "conversion_rate": round(_to_num(_take(r, "payRate")) * 100, 2),
                    "add_cart": int(_to_num(_take(r, "itemCartCnt"))),
                    "refund_amount": round(_to_num(_take(r, "sucRefundAmt")), 2),
                    "pay_pct": round(_to_num(_take(r, "payPct")), 2),
                    "item_clt_byr_cnt": int(_to_num(_take(r, "itemCltByrCnt"))),
                    "uv_avg_value": round(_to_num(_take(r, "uvAvgValue")), 2),
                    "stay_time_avg": round(_to_num(_take(r, "stayTimeAvg")), 2),
                    "itm_bounce_rate": round(_to_num(_take(r, "itmBounceRate")) * 100, 2),
                    "se_guide_uv": int(_to_num(_take(r, "seGuideUv"))),
                    "se_guide_pay_byr_cnt": int(_to_num(_take(r, "seGuidePayByrCnt"))),
                    "se_guide_pay_rate": round(_to_num(_take(r, "seGuidePayRate")) * 100, 2),
                    "visitors_cycle": _cycle("itmUv"),
                    "pv_cycle": _cycle("itmPv"),
                    "buyers_cycle": _cycle("payByrCnt"),
                    "orders_cycle": _cycle("payItmCnt"),
                    "sales_cycle": _cycle("payAmt"),
                    "conversion_cycle": _cycle("payRate"),
                    "add_cart_cycle": _cycle("itemCartCnt"),
                }
            )
        total = inner.get("recordCount") or 0
        if len(out) >= total or len(rows) < 20:
            break
        page += 1
    return out
