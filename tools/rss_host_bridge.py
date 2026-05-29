# coding=utf-8
"""宿主机 RSS 抓取桥接脚本。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output" / "rss"
CACHE_PATH = OUTPUT_DIR / "rss_host_cache.json"
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trendradar.core import load_config
from trendradar.crawler.rss.fetcher import RSSFeedConfig, RSSFetcher


def _resolve_feeds(config: Dict[str, Any], only_ids: set[str] | None = None) -> List[RSSFeedConfig]:
    rss_config = config.get("RSS", {}) or config.get("rss", {}) or {}
    feeds_config = rss_config.get("FEEDS") or rss_config.get("feeds") or []
    freshness_config = rss_config.get("FRESHNESS_FILTER") or rss_config.get("freshness_filter") or {}
    fetcher = RSSFetcher.from_config(
        {
            "feeds": feeds_config,
            "request_interval": 0,
            "timeout": int(rss_config.get("TIMEOUT") or rss_config.get("timeout") or 15),
            "use_proxy": False,
            "proxy_url": "",
            "timezone": str(config.get("TIMEZONE", "Asia/Shanghai")),
            "freshness_filter": {
                "enabled": bool(freshness_config.get("ENABLED", freshness_config.get("enabled", True))),
                "max_age_days": int(freshness_config.get("MAX_AGE_DAYS", freshness_config.get("max_age_days", 3)) or 3),
            },
        }
    )
    feeds = fetcher.feeds
    if only_ids:
        feeds = [feed for feed in feeds if feed.id in only_ids]
    return feeds


def _row_from_item(item: Any) -> Dict[str, Any]:
    return {
        "title": item.title,
        "url": item.url,
        "published_at": item.published_at or "",
        "summary": item.summary or "",
        "author": item.author or "",
        "guid": getattr(item, "guid", "") or item.url or item.title,
    }


def fetch_flow(feed_ids: List[str] | None = None) -> int:
    config = load_config()
    feeds = _resolve_feeds(config, set(feed_ids or []))
    if not feeds:
        print("未找到可抓取的 RSS 源")
        return 1

    rss_config = config.get("RSS", {}) or config.get("rss", {}) or {}
    freshness_config = rss_config.get("FRESHNESS_FILTER") or rss_config.get("freshness_filter") or {}

    fetcher = RSSFetcher.from_config(
        {
            "feeds": [
                {
                    "id": feed.id,
                    "name": feed.name,
                    "url": feed.url,
                    "max_items": feed.max_items,
                    "enabled": True,
                    "max_age_days": feed.max_age_days,
                }
                for feed in feeds
            ],
            "request_interval": 0,
            "timeout": int(rss_config.get("TIMEOUT") or rss_config.get("timeout") or 15),
            "use_proxy": bool(rss_config.get("USE_PROXY", rss_config.get("use_proxy", False))),
            "proxy_url": str(rss_config.get("PROXY_URL", rss_config.get("proxy_url", "")) or ""),
            "timezone": str(config.get("TIMEZONE", "Asia/Shanghai")),
            "freshness_filter": {
                "enabled": bool(freshness_config.get("ENABLED", freshness_config.get("enabled", True))),
                "max_age_days": int(freshness_config.get("MAX_AGE_DAYS", freshness_config.get("max_age_days", 3)) or 3),
            },
        }
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "generated_at": datetime.now(dt_timezone.utc).isoformat().replace("+00:00", "Z"),
        "feeds": {},
        "errors": {},
        "source_status": {},
    }

    success = 0
    for feed in fetcher.feeds:
        items, error, source_status = fetcher.fetch_feed(feed)
        payload["source_status"][feed.id] = source_status
        if error:
            payload["errors"][feed.id] = {"name": feed.name, "error": error, "url": feed.url}
            print(f"{feed.name}: 失败 ({error})")
            continue
        payload["feeds"][feed.id] = [_row_from_item(item) for item in items]
        success += 1
        print(f"{feed.name}: 缓存 {len(items)} 条")

    CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入 RSS 缓存: {CACHE_PATH}")
    print(f"成功 {success}/{len(fetcher.feeds)} 个源")
    return 0 if success else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="宿主机 RSS 抓取桥接")
    parser.add_argument("--feed-id", action="append", dest="feed_ids", help="只抓取指定 feed id，可重复")
    args = parser.parse_args()
    return fetch_flow(args.feed_ids)


if __name__ == "__main__":
    raise SystemExit(main())
