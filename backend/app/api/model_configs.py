"""模型配置：管理多个 AI 模型（增删改查）、切换默认模型、连通性测试。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.api.auth import get_current_user
from backend.app.core.ai_client import AIError, PROVIDER_DEFAULTS, chat_completion
from backend.app.core.db import get_db
from backend.app.core.logs import log_op

router = APIRouter()


class ModelConfigIn(BaseModel):
    name: str = "默认模型"
    provider: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.7


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return api_key[:4] + "****" + api_key[-4:]


def _payload(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "provider": row["provider"],
        "base_url": row["base_url"],
        "api_key": _mask_key(row["api_key"]),
        "model": row["model"],
        "temperature": row["temperature"],
        "is_default": bool(row["is_default"]),
        "configured": bool(row["api_key"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _get_config_by_id(db, config_id: int) -> dict | None:
    row = db.execute("SELECT * FROM model_configs WHERE id = ?", (config_id,)).fetchone()
    return dict(row) if row else None


def get_default_config(db) -> dict | None:
    """返回默认模型配置；没有默认时自动把第一个设为默认。"""
    row = db.execute("SELECT * FROM model_configs WHERE is_default = 1 ORDER BY id ASC LIMIT 1").fetchone()
    if row:
        return dict(row)
    row = db.execute("SELECT * FROM model_configs ORDER BY id ASC LIMIT 1").fetchone()
    if row:
        db.execute("UPDATE model_configs SET is_default = 0")
        db.execute("UPDATE model_configs SET is_default = 1 WHERE id = ?", (row["id"],))
        return dict(row)
    return None


@router.get("")
def list_model_configs(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    rows = db.execute("SELECT * FROM model_configs ORDER BY is_default DESC, id ASC").fetchall()
    return {"items": [_payload(r) for r in rows]}


@router.post("")
def create_model_config(
    body: ModelConfigIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    count = db.execute("SELECT COUNT(*) AS c FROM model_configs").fetchone()["c"]
    provider = body.provider.strip() or "openai"
    defaults = PROVIDER_DEFAULTS.get(provider, {})
    now = _now()
    cur = db.execute(
        """
        INSERT INTO model_configs (name, provider, base_url, api_key, model, temperature, is_default, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            body.name.strip() or "未命名模型",
            provider,
            (body.base_url or defaults.get("base_url") or "").strip(),
            body.api_key.strip(),
            (body.model or defaults.get("model") or "").strip(),
            body.temperature,
            1 if count == 0 else 0,
            now,
            now,
        ),
    )
    log_op(db, user, "model-configs", "新增模型", target_name=body.name.strip() or "未命名模型")
    row = db.execute("SELECT * FROM model_configs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _payload(row)


@router.put("/{config_id}")
def update_model_config(
    config_id: int,
    body: ModelConfigIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    existing = _get_config_by_id(db, config_id)
    if not existing:
        raise HTTPException(status_code=404, detail="模型不存在")
    api_key = body.api_key.strip() or existing["api_key"]
    provider = body.provider.strip() or existing["provider"]
    defaults = PROVIDER_DEFAULTS.get(provider, {})
    db.execute(
        """
        UPDATE model_configs
        SET name = ?, provider = ?, base_url = ?, api_key = ?, model = ?, temperature = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            body.name.strip() or existing["name"],
            provider,
            (body.base_url or defaults.get("base_url") or "").strip(),
            api_key,
            (body.model or defaults.get("model") or "").strip(),
            body.temperature,
            _now(),
            config_id,
        ),
    )
    log_op(db, user, "model-configs", "编辑模型", target_name=body.name.strip() or existing["name"])
    row = db.execute("SELECT * FROM model_configs WHERE id = ?", (config_id,)).fetchone()
    return _payload(row)


@router.delete("/{config_id}")
def delete_model_config(
    config_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    existing = _get_config_by_id(db, config_id)
    if not existing:
        raise HTTPException(status_code=404, detail="模型不存在")
    was_default = bool(existing["is_default"])
    db.execute("DELETE FROM model_configs WHERE id = ?", (config_id,))
    if was_default:
        first = db.execute("SELECT * FROM model_configs ORDER BY id ASC LIMIT 1").fetchone()
        if first:
            db.execute("UPDATE model_configs SET is_default = 0")
            db.execute("UPDATE model_configs SET is_default = 1 WHERE id = ?", (first["id"],))
    log_op(db, user, "model-configs", "删除模型", target_name=existing["name"])
    return {"ok": True}


@router.post("/{config_id}/default")
def set_default_model_config(
    config_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    existing = _get_config_by_id(db, config_id)
    if not existing:
        raise HTTPException(status_code=404, detail="模型不存在")
    db.execute("UPDATE model_configs SET is_default = 0")
    db.execute("UPDATE model_configs SET is_default = 1 WHERE id = ?", (config_id,))
    log_op(db, user, "model-configs", "设为默认", target_name=existing["name"])
    return {"ok": True, "id": config_id}


class TestIn(BaseModel):
    id: int | None = None
    name: str = "默认模型"
    provider: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.7


@router.post("/test")
def test_model_config(
    body: TestIn,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    saved = _get_config_by_id(db, body.id) if body.id else None
    provider = body.provider.strip() or (saved["provider"] if saved else "") or "openai"
    defaults = PROVIDER_DEFAULTS.get(provider, {})
    cfg = {
        "provider": provider,
        "base_url": (
            body.base_url.strip()
            or (saved["base_url"] if saved else "")
            or defaults.get("base_url")
            or ""
        ),
        "api_key": body.api_key.strip() or (saved["api_key"] if saved else ""),
        "model": (
            body.model.strip()
            or (saved["model"] if saved else "")
            or defaults.get("model")
            or ""
        ),
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
