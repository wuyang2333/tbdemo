"""OpenAI 兼容模型调用封装：统一处理请求、超时与用户可读的错误信息。"""

from __future__ import annotations

import httpx

# 常见服务商默认值：选择服务商后自动填充接口地址和模型名，也可手动修改。
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "dashscope": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "moonshot": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "custom": {"base_url": "", "model": ""},
}


class AIError(Exception):
    """带用户可读信息的调用错误。"""


def effective_base_url(cfg: dict) -> str:
    return (
        (cfg.get("base_url") or PROVIDER_DEFAULTS.get(cfg.get("provider", ""), {}).get("base_url") or "")
        .strip()
        .rstrip("/")
    )


def effective_model(cfg: dict) -> str:
    return cfg.get("model") or PROVIDER_DEFAULTS.get(cfg.get("provider", ""), {}).get("model") or ""


def chat_completion(cfg: dict, messages: list[dict], timeout: float = 60.0) -> str:
    """调用 OpenAI 兼容的 /chat/completions，返回助手回复文本。"""
    api_key = (cfg.get("api_key") or "").strip()
    base_url = effective_base_url(cfg)
    model = effective_model(cfg)

    if not api_key:
        raise AIError("还没有配置 API Key，请先到「模型配置」页面填写")
    if not base_url:
        raise AIError("还没有配置接口地址（base_url），请先到「模型配置」页面填写")
    if not model:
        raise AIError("还没有配置模型名称，请先到「模型配置」页面填写")

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(cfg.get("temperature") or 0.7),
    }

    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise AIError(f"无法连接模型服务，请检查接口地址和网络：{exc}") from exc

    if resp.status_code >= 400:
        snippet = resp.text.strip().replace("\n", " ")[:300]
        raise AIError(f"模型服务返回错误（HTTP {resp.status_code}）：{snippet}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        raise AIError("模型返回内容格式异常，请检查接口地址和模型名称是否正确") from exc

    if not content:
        raise AIError("模型返回了空内容，请换一个模型试试")
    return content
