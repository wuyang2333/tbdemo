# -*- coding: utf-8 -*-
"""数据口径说明：系统内每个指标的数据来源、时间口径、存储表与刷新频率。"""
from fastapi import APIRouter

router = APIRouter()

GLOSSARY = [
    {
        "group": "生意参谋 · 今日实时 KPI（今日总览）",
        "items": [
            {
                "metric": "访客数 / 浏览量 / 支付金额 / 支付买家 / 支付件数 / 支付订单 / 支付转化率",
                "source": "首页-数据概括 实时接口 /portal/live/new/index/overview/v3.json",
                "granularity": "实时 T+0（今日累计到当前时刻）",
                "table": "store_daily_data（今日行）",
                "refresh": "每 3 分钟自动同步 + 「同步店铺数据」按钮",
                "note": "环比为「今日累计 vs 昨日同时段」，由接口 cycleCrc 或分时表对齐计算。",
            }
        ],
    },
    {
        "group": "生意参谋 · 分时数据（时段分析 / 总览环比）",
        "items": [
            {
                "metric": "24 小时 访客/浏览/支付金额/订单/买家/转化率",
                "source": "首页实时趋势 /portal/live/new/index/trend/v3.json?dateType=today",
                "granularity": "今日 + 昨日，按小时累计序列转每小时增量",
                "table": "store_hourly_data",
                "refresh": "每 3 分钟自动同步",
                "note": "小时值是「本小时累计 - 上一小时累计」计算出的增量。",
            }
        ],
    },
    {
        "group": "生意参谋 · 店铺日数据（历史 / 昨日）",
        "items": [
            {
                "metric": "访客 / 浏览量 / 销售额 / 订单 / 转化率 / 复购率 / 老客数 / 复购销售额",
                "source": "数据概览日档 /portal/coreIndex/new/overview/v3.json?dateType=day",
                "granularity": "T+1 日档（生意参谋日档通常到昨日或前日）",
                "table": "store_daily_data",
                "refresh": "「同步店铺数据」按钮 + 「补拉历史数据」",
                "note": "日档有 1-2 天确认延迟；当天实时数据不在此表。",
            }
        ],
    },
    {
        "group": "生意参谋 · 商品排行（商品分析）",
        "items": [
            {
                "metric": "商品 销售额/订单/买家/访客/转化率/加购/退款/排名 等 40+ 指标",
                "source": "商品-商品排行 实时 /cc/item/live/view/top.json?dateType=today",
                "granularity": "实时 T+0（今日累计）",
                "table": "store_item_realtime",
                "refresh": "每 3 分钟自动同步",
                "note": "商品分析默认「实时」档；环比涨跌幅 = 当前值 vs 昨日同时段（涨红跌绿）。",
            },
            {
                "metric": "商品 销售额/订单/买家/访客/转化率/加购/退款 等",
                "source": "商品-商品排行 日档 /cc/item/view/top.json?dateType=day",
                "granularity": "T+1 日档（昨日及更早）",
                "table": "store_item_daily",
                "refresh": "「同步店铺数据」+「补拉历史数据」",
                "note": "用于商品分析的「昨日」及自定义日期范围。",
            },
        ],
    },
    {
        "group": "生意参谋 · 流量来源（今日总览-流量结构）",
        "items": [
            {
                "metric": "流量来源 Top10（来源名 + 访客 UV）",
                "source": "流量-流量看板-流量来源排行 /flow/overview/live/shopFlowSourceTop/v4.json",
                "granularity": "实时 T+0（今日累计）",
                "table": "flow_source_top",
                "refresh": "每 3 分钟自动同步 + 「同步店铺数据」按钮",
                "note": "仅实时档；搜索 UV = 来源名含「搜索」的合计。",
            }
        ],
    },
    {
        "group": "生意参谋 · 今日退款（首页-数据概括-完结时间）",
        "items": [
            {
                "metric": "退款金额（完结时间）/ 退款率 / 订单退款率",
                "source": "首页-数据概括 实时接口 /portal/live/new/index/overview/v3.json",
                "granularity": "实时 T+0（今日累计，按退款完结时间）",
                "table": "refund_today",
                "refresh": "每 3 分钟自动同步 + 「同步店铺数据」按钮",
                "note": "金额取 rfdSucAmt；退款率取接口官方 payAmtRfdRate，不是 退款/销售额 直接除。",
            }
        ],
    },
    {
        "group": "万相台 · 推广实时（推广数据-实时）",
        "items": [
            {
                "metric": "各场景 花费/成交/点击/展现/ROI",
                "source": "万相台报表 /report/query.json?bizCode=关键词/人群/全站/内容",
                "granularity": "实时 T+0（今日累计）",
                "table": "promo_realtime",
                "refresh": "每 3 分钟自动同步",
                "note": "实时档花费口径 = 全站推广 + 人群 + 关键词（内容推广暂不计入）。",
            }
        ],
    },
    {
        "group": "万相台 · 推广日数据（推广数据-昨日/近7天）",
        "items": [
            {
                "metric": "各场景 花费/成交/点击/展现/ROI/转化",
                "source": "万相台日报报表 /report/query.json（日档）",
                "granularity": "T+1 日档（昨日及更早）",
                "table": "promo_daily_data",
                "refresh": "「同步店铺数据」/ 推广数据页同步",
                "note": "用于「昨日」「近七天」及自定义时间范围。",
            }
        ],
    },
    {
        "group": "万相台 · 推广计划（推广计划）",
        "items": [
            {
                "metric": "计划名 / 场景 / 状态 / 日预算 / 出价 / 计划花费 / 成交 / ROI",
                "source": "万相台计划 /campaign/horizontal/findPage.json + 计划报表",
                "granularity": "计划快照 + 日报/实时",
                "table": "promo_plans / promo_plan_items / promo_plan_stats / promo_plan_daily",
                "refresh": "「同步计划」/「同步计划数据」",
                "note": "计划状态与本地备注分开存储，本地标记不影响线上计划。",
            }
        ],
    },
    {
        "group": "万相台 · 商品级推广（商品分析联动 / 推广计划商品）",
        "items": [
            {
                "metric": "商品级 花费/成交/ROI/点击/订单",
                "source": "万相台 report-item / report-realtime（按宝贝维度）",
                "granularity": "实时或日档（跟随所选日期档）",
                "table": "promo_item_stats",
                "refresh": "「同步店铺数据」/ 推广商品同步",
                "note": "用于商品分析里「广告占比 / 真实ROI」与推广计划的商品表现。",
            }
        ],
    },
    {
        "group": "通用说明",
        "items": [
            {
                "metric": "口径 / 时间 / 更新",
                "source": "—",
                "granularity": "—",
                "table": "—",
                "refresh": "—",
                "note": "T+0 = 今日实时（累计到当前）；T+1 = 次日才有完整日数据。生意参谋/万相台日档通常比实时档晚 1-2 天确认。",
            }
        ],
    },
]


@router.get("/glossary")
def get_glossary() -> dict:
    """返回数据口径说明（静态）。"""
    return {"groups": GLOSSARY, "updated_at": "2026-08-19"}
