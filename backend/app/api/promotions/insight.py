"""推广管理：AI 解读与计划 AI 分析。"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import get_current_user, visible_store_ids
from backend.app.core.alimama import (
    AlimamaError,
    check_access,
    fetch_item_promo_plan_based,
    fetch_item_report,
    fetch_plan_realtime,
    fetch_plan_reports,
    fetch_plan_snapshots,
    fetch_promo_item_fallback,
    fetch_realtime,
    fetch_scene_daily,
    fetch_scene_hourly,
)
from backend.app.core.db import get_db
from backend.app.core.logs import log_op
from backend.app.core.sycm import PROFILE_MISSING_MSG, has_profile

from ._common import (
    MODES,
    PlanNoteIn,
    _now,
    _log,
    _scope_filter,
    _bound_stores,
    _all_stores,
    sync_promo_daily_all,
    _mode,
    _finalize,
    _store_daily_rows,
    _store_realtime_rows,
    _last_sync,
    sync_promo_realtime_all,
    sync_promo_items_realtime_all,
    _promo_insight_data,
    _build_promo_prompt,
    _lookup_item_image,
    _refresh_plan_items,
    PlanStatusIn,
    PlanChatIn,
    PlanChatBody,
    _ensure_plan_daily,
    _collect_plan_data,
    _build_plan_prompt,
)

router = APIRouter()

@router.post("/insight")
def promo_ai_insight(
    mode: str = "realtime",
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """AI 推广解读：基于计划/场景数据给出投放优化建议。"""
    from backend.app.api.analytics import _parse_insight_sections
    from backend.app.api.model_configs import get_default_config
    from backend.app.core.ai_client import AIError, chat_completion

    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    data = _promo_insight_data(mode, db, user)
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": _build_promo_prompt(data)}], timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "sections": _parse_insight_sections(reply),
        "reply": reply,
        "mode": data["mode"],
        "summary": {
            "total_spend": data["total_spend"],
            "total_sales": data["total_sales"],
            "total_roi": data["total_roi"],
            "active_count": data["active_count"],
            "high_count": data["high_count"],
            "mid_count": data["mid_count"],
            "low_count": data["low_count"],
        },
    }

@router.post("/plans/{plan_id}/insight")
def plan_ai_insight(
    plan_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """单个推广计划的 AI 分析。"""
    from backend.app.api.analytics import _parse_insight_sections
    from backend.app.api.model_configs import get_default_config
    from backend.app.core.ai_client import AIError, chat_completion

    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    scope_frag, scope_params = _scope_filter(None, user)
    row = db.execute(
        "SELECT * FROM promo_plans WHERE id = ?" + scope_frag,
        [plan_id] + scope_params,
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="推广计划不存在")
    store = db.execute("SELECT * FROM stores WHERE id = ?", (row["store_id"],)).fetchone()
    if not store:
        raise HTTPException(status_code=400, detail="店铺不存在")
    data = _collect_plan_data(db, dict(store), dict(row), user)
    try:
        reply = chat_completion(cfg, [{"role": "user", "content": _build_plan_prompt(data)}], timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "sections": _parse_insight_sections(reply),
        "reply": reply,
        "plan": {"id": row["id"], "plan_name": row["plan_name"], "campaign_id": row["campaign_id"], "scene_name": row["scene_name"]},
        "date": date_cls.today().isoformat(),
    }

@router.post("/plans/{plan_id}/insight/chat")
def plan_ai_insight_chat(
    plan_id: int,
    body: PlanChatBody,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """围绕单个计划的 AI 追问。"""
    from backend.app.api.model_configs import get_default_config
    from backend.app.core.ai_client import AIError, chat_completion

    cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    scope_frag, scope_params = _scope_filter(None, user)
    row = db.execute(
        "SELECT * FROM promo_plans WHERE id = ?" + scope_frag,
        [plan_id] + scope_params,
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="推广计划不存在")
    store = db.execute("SELECT * FROM stores WHERE id = ?", (row["store_id"],)).fetchone()
    if not store:
        raise HTTPException(status_code=400, detail="店铺不存在")
    data = _collect_plan_data(db, dict(store), dict(row), user)
    context = (
        "你是淘宝万相台推广运营专家。以下是这个推广计划的数据上下文：\n"
        + "计划：%s（ID %s）\n" % (row["plan_name"], row["campaign_id"])
        + "\n".join(data["lines"])
        + "\n用户会围绕这个计划追问，请结合数据回答，简洁务实，不要编造；数据里没有的信息要如实说明。"
    )
    msgs = [{"role": "system", "content": context}]
    for m in body.messages:
        msgs.append({"role": m.role, "content": m.content})
    try:
        reply = chat_completion(cfg, msgs, timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"reply": reply}
