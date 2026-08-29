"""推广渠道维度：由平台场景或 bizCode 做可解释归一化。"""

from __future__ import annotations

from typing import Any, Mapping


CHANNEL_NAMES = {
    "whole_site": "全站推广",
    "search": "搜索推广",
    "audience": "人群推广",
    "content": "内容推广",
    "other": "其他渠道",
}

_CHANNEL_ALIASES = {
    "whole_site": "whole_site",
    "wholesite": "whole_site",
    "onebpsite": "whole_site",
    "site": "whole_site",
    "search": "search",
    "keyword": "search",
    "onebpsearch": "search",
    "audience": "audience",
    "crowd": "audience",
    "display": "audience",
    "onebpdisplay": "audience",
    "content": "content",
    "shortvideo": "content",
    "onebpshortvideo": "content",
    "other": "other",
}


def normalize_channel(value: str | None) -> str:
    """把渠道查询值或平台 bizCode 归一为固定渠道值；未知值归入 other。"""
    raw = str(value or "").strip()
    if not raw:
        return "other"
    compact = raw.lower().replace("-", "").replace("_", "").replace(" ", "")
    if compact in _CHANNEL_ALIASES:
        return _CHANNEL_ALIASES[compact]
    if "全站" in raw:
        return "whole_site"
    if "搜索" in raw or "关键词" in raw:
        return "search"
    if "人群" in raw:
        return "audience"
    if "内容" in raw or "短视频" in raw:
        return "content"
    return "other"


def channel_for_scene(scene: str | None, scene_name: str | None = "") -> str:
    """根据真实 scene/bizCode 和名称映射渠道，不推断不存在的平台数据。"""
    channel = normalize_channel(scene)
    if channel != "other" or str(scene or "").strip().lower() in {"other", "其他"}:
        return channel
    return normalize_channel(scene_name)


def channel_name(channel: str | None) -> str:
    return CHANNEL_NAMES[normalize_channel(channel)]


def with_channel(item: Mapping[str, Any]) -> dict[str, Any]:
    """复制返回项并补充 channel/channel_name。"""
    result = dict(item)
    channel = channel_for_scene(result.get("scene"), result.get("scene_name"))
    result["channel"] = channel
    result["channel_name"] = CHANNEL_NAMES[channel]
    return result


def channel_matches(channel: str | None, scene: str | None, scene_name: str | None = "") -> bool:
    """空查询不过滤；非空查询按归一化后的渠道匹配。"""
    if not str(channel or "").strip():
        return True
    return channel_for_scene(scene, scene_name) == normalize_channel(channel)
