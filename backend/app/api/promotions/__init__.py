"""推广管理 API 包：分模块路由聚合。"""

from fastapi import APIRouter

from .data import router as _data_router
from .data import sync_items, sync_plans
from .insight import router as _insight_router
from ._common import (
    sync_promo_daily_all,
    sync_promo_items_realtime_all,
    sync_promo_realtime_all,
)

router = APIRouter()
# 直接挂载子路由：data.py 含空路径 "" 的路由，include_router 会因「prefix 与 path 不能同时为空」报错
router.routes.extend(_data_router.routes)
router.routes.extend(_insight_router.routes)
