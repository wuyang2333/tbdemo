from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("")
def list_model_configs() -> dict:
    return {"items": [], "message": "模型配置 · 待开发（支持 OpenAI 兼容 / 阿里云百炼等）"}
