"""模型配置：保存 AI 服务商、接口地址、API Key 与模型名，支持连通性测试。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import get_current_user
from backend.app.core.ai_client import AIError, PROVIDER_DEFAULTS, chat_completion
from backend.app.core.db import get_db

router = APIRouter()


class ModelConfigIn(BaseModel):
    provider: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.7


def _mask_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return api_key[:4] + "****" + api_key[-4:]


def _get_config(db) -> dict | None:
    row = db.execute("SELECT * FROM model_configs WHERE id = 1").fetchone()
    return dict(row) if row else None


def _payload(cfg: dict) -> dict:
    return {
        "provider": cfg["provider"],
        "base_url": cfg["base_url"],
        "api_key": _mask_key(cfg["api_key"]),
        "model": cfg["model"],
        "temperature": cfg["temperature"],
        "updated_at": cfg["updated_at"],
        "configured": bool(cfg["api_key"]),
    }


@router.get("")
def get_model_config(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cfg = _get_config(db)
    if not cfg:
        return {
            "provider": "openai",
            "base_url": "",
            "api_key": "",
            "model": "",
            "temperature": 0.7,
            "updated_at": None,
            "configured": False,
        }
    return _payload(cfg)


@router.put("")
def save_model_config(
    body: ModelConfigIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    existing = _get_config(db)
    api_key = body.api_key.strip()
    if not api_key and existing:
        api_key = existing["api_key"]

    provider = body.provider.strip() or "openai"
    defaults = PROVIDER_DEFAULTS.get(provider, {})
    base_url = (body.base_url or defaults.get("base_url") or "").strip()
    model = (body.model or defaults.get("model") or "").strip()
    now = datetime.now(timezone.utc).isoformat()

    if existing:
        db.execute(
            """
            UPDATE model_configs
            SET provider = ?, base_url = ?, api_key = ?, model = ?, temperature = ?, updated_at = ?
            WHERE id = 1
            """,
            (provider, base_url, api_key, model, body.temperature, now),
        )
    else:
        db.execute(
            """
            INSERT INTO model_configs (id, provider, base_url, api_key, model, temperature, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?)
            """,
            (provider, base_url, api_key, model, body.temperature, now),
        )
    cfg = _get_config(db)
    return _payload(cfg)


@router.post("/test")
def test_model_config(
    body: ModelConfigIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    existing = _get_config(db)
    api_key = body.api_key.strip() or (existing["api_key"] if existing else "")
    cfg = {
        "provider": body.provider.strip() or "openai",
        "base_url": body.base_url.strip(),
        "api_key": api_key,
        "model": body.model.strip(),
        "temperature": body.temperature,
    }
    try:
        reply = chat_completion(
            cfg,
            [{"role": "user", "content": "请只回复两个字：正常"}],
            timeout=30.0,
        )
    except AIError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "reply": reply}
