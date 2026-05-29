# coding=utf-8
"""社交媒体聚合服务。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Tuple

from trendradar.social.collectors import collect_reddit_items, collect_x_items
from trendradar.social.models import SocialItem
from trendradar.utils.time import get_configured_time, is_same_local_date


def _infer_last_synced(items: List[SocialItem], timezone: str) -> str:
    for item in items:
        cache_generated_at = str((item.metadata or {}).get("cache_generated_at", "") or "").strip()
        if cache_generated_at:
            return cache_generated_at

    published_values = [item.published_at for item in items if item.published_at]
    if published_values:
        return max(published_values)

    return get_configured_time(timezone).isoformat()


def _infer_runtime_status(
    platform: str,
    items: List[SocialItem],
    source: Dict[str, Any],
    fresh_today: bool,
) -> Dict[str, str]:
    if not items:
        return {"status": "failed", "fetch_mode": "failed"}

    metadata_sources = {
        str((item.metadata or {}).get("source", "")).strip()
        for item in items
        if item.metadata
    }
    has_cache_timestamp = any(
        str((item.metadata or {}).get("cache_generated_at", "")).strip()
        for item in items
    )
    if platform == "x" and source.get("prefer_host_cache", False):
        return {"status": "cache_fallback", "fetch_mode": "host_cache"}
    if has_cache_timestamp and any(source_name not in {"x_playwright", "twstalker_fallback", "reddit_live_rss"} for source_name in metadata_sources if source_name):
        return {"status": "cache_fallback", "fetch_mode": "host_cache"}
    if metadata_sources.intersection({"x_playwright", "twstalker_fallback", "reddit_live_rss"}):
        return {"status": "live_ok", "fetch_mode": "live"}
    if fresh_today:
        return {"status": "live_ok", "fetch_mode": "live"}
    return {"status": "stale_cache", "fetch_mode": "cache"}


def collect_social_media(
    social_config: Dict[str, Any], timezone: str
) -> Tuple[List[SocialItem], Dict[str, Dict[str, Any]]]:
    if not social_config.get("ENABLED", False):
        return [], {}

    sources = social_config.get("SOURCES", []) or []
    if not sources:
        print("[Social] 未配置任何社交媒体源")
        return [], {}

    all_items: List[SocialItem] = []
    source_status: Dict[str, Dict[str, Any]] = {}
    for source in sources:
        if not source.get("enabled", True):
            continue

        platform = str(source.get("platform", "")).strip().lower()
        source_name = source.get("name", source.get("id", platform))
        try:
            if platform == "reddit":
                items = collect_reddit_items(source, social_config, timezone)
            elif platform == "x":
                items = collect_x_items(source, social_config, timezone)
            else:
                print(f"[Social] 跳过未知平台: {platform or 'unknown'}")
                items = []
                source_status[str(source_name)] = {
                    "platform": platform or "unknown",
                    "healthy": False,
                    "count": 0,
                    "error": "unknown-platform",
                    "status": "failed",
                    "fetch_mode": "failed",
                    "last_synced": "",
                    "fresh_today": False,
                }
                continue
        except Exception as exc:
            print(f"[Social] {source_name} 抓取失败: {exc}")
            source_status[str(source_name)] = {
                "platform": platform or "unknown",
                "healthy": False,
                "count": 0,
                "error": str(exc),
                "status": "failed",
                "fetch_mode": "failed",
                "last_synced": "",
                "fresh_today": False,
            }
            items = []

        if items:
            all_items.extend(items)
            print(f"[Social] {source_name}: 获取 {len(items)} 条")
        last_synced = _infer_last_synced(items, timezone) if items else ""
        fresh_today = bool(last_synced and is_same_local_date(last_synced, timezone))
        source_status[str(source_name)] = {
            "platform": platform or "unknown",
            "healthy": bool(items) and fresh_today,
            "count": len(items),
            "error": "",
            "last_synced": last_synced,
            "fresh_today": fresh_today,
            "strategy": str(source.get("strategy", "") or "").strip(),
            **_infer_runtime_status(platform, items, source, fresh_today),
        }

    all_items.sort(key=lambda item: item.published_at or "", reverse=True)
    print(f"[Social] 总计获取 {len(all_items)} 条社交媒体内容")
    return all_items, source_status
