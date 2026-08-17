"""AI 助手：基于已配置的模型提供对话能力，并带上工作台实时数据快照。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import get_current_user, visible_store_ids
from backend.app.api.model_configs import _get_config_by_id, get_default_config
from backend.app.core.ai_client import AIError, chat_completion
from backend.app.core.db import get_db
from backend.app.core.logs import log_op

router = APIRouter()

MAX_HISTORY = 10


class ChatMessageIn(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    messages: list[ChatMessageIn]
    model_id: int | None = None


def _workbench_snapshot(db, user: dict) -> str:
    """把工作台当前状态压缩成一段文字，注入系统提示词（SaaS：按账号可见店铺隔离）。"""
    visible = visible_store_ids(user)
    if visible is not None and not visible:
        return "当前账号未绑定任何店铺，暂无可查看的数据。"
    if visible is not None:
        ids = ",".join(str(i) for i in visible)
        sf = f" AND id IN ({ids})"
        gift_sf = f" AND store_id IN ({ids})"
    else:
        sf = ""
        gift_sf = ""
    store_count = db.execute("SELECT COUNT(*) AS c FROM stores WHERE 1=1" + sf).fetchone()["c"]
    active_stores = db.execute("SELECT COUNT(*) AS c FROM stores WHERE status = 'active'" + sf).fetchone()["c"]
    gift_total = db.execute("SELECT COUNT(*) AS c FROM gifts WHERE 1=1" + gift_sf).fetchone()["c"]
    gift_pending = db.execute("SELECT COUNT(*) AS c FROM gifts WHERE status = 'pending'" + gift_sf).fetchone()["c"]
    gift_shipped = db.execute("SELECT COUNT(*) AS c FROM gifts WHERE status = 'shipped'" + gift_sf).fetchone()["c"]
    gift_delivered = db.execute("SELECT COUNT(*) AS c FROM gifts WHERE status = 'delivered'" + gift_sf).fetchone()["c"]
    gift_refunded = db.execute("SELECT COUNT(*) AS c FROM gifts WHERE status = 'refunded'" + gift_sf).fetchone()["c"]
    top_stores = db.execute(
        "SELECT name, category FROM stores WHERE 1=1" + sf + " ORDER BY id ASC LIMIT 5"
    ).fetchall()
    store_names = "、".join(f"{row['name']}（{row['category']}）" for row in top_stores) or "（暂无店铺）"
    return (
        f"店铺共 {store_count} 家，其中正常营业 {active_stores} 家；"
        f"礼品单共 {gift_total} 单：待发货 {gift_pending}、已发货 {gift_shipped}、已完成 {gift_delivered}、已退款 {gift_refunded}。"
        f"店铺列表（前 5 家）：{store_names}。"
    )


@router.post("/chat")
def chat(
    body: ChatIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = _get_config_by_id(db, body.model_id) if body.model_id is not None else None
    if not cfg:
        cfg = get_default_config(db)
    if not cfg or not cfg["api_key"]:
        raise HTTPException(status_code=400, detail="还没有配置 AI 模型，请先到「模型配置」页面添加模型并填写 API Key")
    history = [
        {"role": m.role, "content": m.content}
        for m in body.messages[-MAX_HISTORY:]
        if m.role in ("user", "assistant") and m.content.strip()
    ]
    if not history:
        raise HTTPException(status_code=400, detail="请输入内容后再发送")

    system_prompt = (
        "你是「淘宝运营工作台」的 AI 运营助手，帮助运营人员分析店铺与礼品单数据、撰写文案、给出运营建议。"
        "回答请使用简体中文，语气务实、简洁，分点说明时用短句。"
        "以下是工作台当前的数据快照（基于数据库实时统计）：\n"
        f"{_workbench_snapshot(db)}\n"
        "数据快照仅供回答问题时参考；如果用户问的问题与快照无关，正常回答即可。"
    )
    messages = [{"role": "system", "content": system_prompt}, *history]

    try:
        reply = chat_completion(cfg, messages, timeout=120.0)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    log_op(db, user, "ai", "对话", target_name="", detail=(history[-1]["content"][:60] if history else ""))
    return {"reply": reply}
