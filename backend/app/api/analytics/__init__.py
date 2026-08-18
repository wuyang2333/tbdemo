"""数据洞察 API 包：分模块路由聚合。"""

from fastapi import APIRouter

from .overview import router as _overview_router
from .goal import router as _goal_router
from .report import router as _report_router
from .insight import router as _insight_router
from .hours import router as _hours_router
from .products import router as _products_router
from .glossary import router as _glossary_router

# main.py 日报推送循环与 promotions 需要用到这些符号
from .report import _report_push_config, _report_text_lines, daily_report, send_report_webhook
from .insight import _parse_insight_sections

router = APIRouter()
router.include_router(_overview_router)
router.include_router(_goal_router)
router.include_router(_report_router)
router.include_router(_insight_router)
router.include_router(_hours_router)
router.include_router(_products_router)
router.include_router(_glossary_router)
