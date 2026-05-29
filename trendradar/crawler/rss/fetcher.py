# coding=utf-8
"""
RSS 抓取器

负责从配置的 RSS 源抓取数据并转换为标准格式
"""

import time
import random
import json
import os
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

import requests

from .parser import RSSParser
from trendradar.storage.base import RSSItem, RSSData
from trendradar.utils.time import get_configured_time, is_same_local_date, is_within_days, DEFAULT_TIMEZONE


@dataclass
class RSSFeedConfig:
    """RSS 源配置"""
    id: str                     # 源 ID
    name: str                   # 显示名称
    url: str                    # RSS URL
    max_items: int = 0          # 最大条目数（0=不限制）
    enabled: bool = True        # 是否启用
    max_age_days: Optional[int] = None  # 文章最大年龄（天），覆盖全局设置；None=使用全局，0=禁用过滤


class RSSFetcher:
    """RSS 抓取器"""

    def __init__(
        self,
        feeds: List[RSSFeedConfig],
        request_interval: int = 2000,
        timeout: int = 15,
        use_proxy: bool = False,
        proxy_url: str = "",
        timezone: str = DEFAULT_TIMEZONE,
        freshness_enabled: bool = True,
        default_max_age_days: int = 3,
    ):
        """
        初始化抓取器

        Args:
            feeds: RSS 源配置列表
            request_interval: 请求间隔（毫秒）
            timeout: 请求超时（秒）
            use_proxy: 是否使用代理
            proxy_url: 代理 URL
            timezone: 时区配置（如 'Asia/Shanghai'）
            freshness_enabled: 是否启用新鲜度过滤
            default_max_age_days: 默认最大文章年龄（天）
        """
        self.feeds = [f for f in feeds if f.enabled]
        self.request_interval = request_interval
        self.timeout = timeout
        self.use_proxy = use_proxy
        self.proxy_url = proxy_url
        self.timezone = timezone
        self.freshness_enabled = freshness_enabled
        self.default_max_age_days = default_max_age_days

        self.parser = RSSParser()
        self.session = self._create_session()
        self._rss_agent_viewer_api_base = os.environ.get("RSS_AGENT_VIEWER_API_BASE", "").strip().rstrip("/")
        self._rss_agent_viewer_parser_path = self._find_rss_agent_viewer_parser_path()
        self._host_cache_path = Path("/app/output/rss/rss_host_cache.json")

    def _create_session(self) -> requests.Session:
        """创建请求会话"""
        session = requests.Session()
        session.headers.update({
            "User-Agent": "TrendRadar/2.0 RSS Reader (https://github.com/trendradar)",
            "Accept": "application/feed+json, application/json, application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

        if self.use_proxy and self.proxy_url:
            session.proxies = {
                "http": self.proxy_url,
                "https": self.proxy_url,
            }

        return session

    def _find_rss_agent_viewer_parser_path(self) -> Optional[str]:
        """定位 rss-agent-viewer 的底层 parser.js，作为首要抓取方式。"""
        candidates = []

        env_path = os.environ.get("RSS_AGENT_VIEWER_PARSER_PATH", "").strip()
        if env_path:
            candidates.append(env_path)

        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            candidates.append(os.path.join(
                appdata,
                "npm",
                "node_modules",
                "rss-agent-viewer",
                "dist",
                "core",
                "parser.js",
            ))

        npm_path = shutil.which("npm")
        if npm_path:
            try:
                npm_root = subprocess.run(
                    [npm_path, "root", "-g"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    check=False,
                )
                npm_root_dir = (npm_root.stdout or "").strip()
                if npm_root_dir:
                    candidates.append(os.path.join(
                        npm_root_dir,
                        "rss-agent-viewer",
                        "dist",
                        "core",
                        "parser.js",
                    ))
            except Exception:
                pass

        candidates.extend([
            "/usr/lib/node_modules/rss-agent-viewer/dist/core/parser.js",
            "/usr/local/lib/node_modules/rss-agent-viewer/dist/core/parser.js",
        ])

        for path in candidates:
            if path and os.path.exists(path):
                return path
        return None

    def _fetch_via_rss_agent_viewer(self, feed: RSSFeedConfig) -> Optional[List[Dict]]:
        """优先使用 rss-agent-viewer 的 parser API 抓取。"""
        if self._rss_agent_viewer_api_base:
            try:
                response = self.session.get(
                    f"{self._rss_agent_viewer_api_base}/parse",
                    params={"url": feed.url, "timeout_ms": self.timeout * 1000},
                    timeout=max(self.timeout + 5, 10),
                )
                response.raise_for_status()
                parsed = response.json()
                items = parsed.get("items", [])
                if items:
                    print(f"[RSS] {feed.name}: rss-agent-viewer 桥接获取 {len(items)} 条")
                return items
            except Exception as e:
                print(f"[RSS] {feed.name}: rss-agent-viewer 桥接失败，回退本地/内置抓取 ({e})")

        node_path = shutil.which("node")
        parser_path = self._rss_agent_viewer_parser_path
        if not node_path or not parser_path:
            return None

        script = """
import { pathToFileURL } from 'node:url';
const parserPath = process.argv[1];
const feedUrl = process.argv[2];
const timeoutMs = Number(process.argv[3] || '10000');
const mod = await import(pathToFileURL(parserPath).href);
const parsed = await mod.parseFeed(feedUrl, timeoutMs);
process.stdout.write(JSON.stringify(parsed));
"""
        try:
            result = subprocess.run(
                [node_path, "--input-type=module", "-e", script, parser_path, feed.url, str(self.timeout * 1000)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(self.timeout + 5, 10),
                check=False,
            )
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                if stderr:
                    print(f"[RSS] {feed.name}: rss-agent-viewer 失败，回退内置抓取 ({stderr.splitlines()[-1]})")
                return None
            payload = (result.stdout or "").strip()
            if not payload:
                return None
            parsed = json.loads(payload)
            items = parsed.get("items", [])
            if items:
                print(f"[RSS] {feed.name}: rss-agent-viewer 获取 {len(items)} 条")
            return items
        except Exception as e:
            print(f"[RSS] {feed.name}: rss-agent-viewer 异常，回退内置抓取 ({e})")
            return None

    def _fetch_via_builtin_skill(self, feed: RSSFeedConfig) -> str:
        """内置 skill/SOP 路线：requests 直连 + RSSParser 解析。"""
        response = self.session.get(feed.url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def _normalize_items_from_rss_agent_viewer(self, items: List[Dict]) -> List:
        """将 rss-agent-viewer 的返回结构转换为 ParsedRSSItem 列表。"""
        normalized = []
        for item in items:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            url = (
                item.get("link")
                or item.get("url")
                or item.get("guid")
                or ""
            )
            published_at = (
                item.get("pubDate")
                or item.get("publishedAt")
                or item.get("published_at")
                or item.get("date_published")
                or item.get("isoDate")
                or item.get("published")
                or item.get("updated")
                or item.get("updatedAt")
            )
            summary = (
                item.get("contentSnippet")
                or item.get("content")
                or item.get("summary")
                or item.get("description")
                or ""
            )
            normalized.append(type("AgentViewerItem", (), {
                "title": title,
                "url": url,
                "published_at": published_at,
                "summary": summary,
                "author": item.get("author") or "",
                "guid": url or title,
            })())
        return normalized

    def _load_host_cache_items(self, feed: RSSFeedConfig) -> Tuple[Optional[List], str]:
        """从宿主机同步缓存中读取指定 feed。"""
        if not self._host_cache_path.exists():
            return None, ""
        try:
            payload = json.loads(self._host_cache_path.read_text(encoding="utf-8"))
            generated_at = str(payload.get("generated_at", "") or "")
            rows = (payload.get("feeds") or {}).get(feed.id) or []
            if not rows:
                return None, generated_at
            normalized = []
            for item in rows:
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                normalized.append(type("HostCacheItem", (), {
                    "title": title,
                    "url": item.get("url", "") or "",
                    "published_at": item.get("published_at"),
                    "summary": item.get("summary") or "",
                    "author": item.get("author") or "",
                    "guid": item.get("guid") or item.get("url", "") or title,
                })())
            if normalized:
                print(f"[RSS] {feed.name}: 读取宿主机 RSS 缓存 {len(normalized)} 条")
            return normalized or None, generated_at
        except Exception as e:
            print(f"[RSS] {feed.name}: 宿主机 RSS 缓存读取失败 ({e})")
            return None, ""

    def _filter_by_freshness(
        self,
        items: List[RSSItem],
        feed: RSSFeedConfig,
    ) -> Tuple[List[RSSItem], int]:
        """
        根据新鲜度过滤文章

        Args:
            items: 待过滤的文章列表
            feed: RSS 源配置

        Returns:
            (过滤后的文章列表, 被过滤的文章数)
        """
        # 如果全局禁用，直接返回
        if not self.freshness_enabled:
            return items, 0

        # 确定此 feed 的 max_age_days
        max_days = feed.max_age_days
        if max_days is None:
            max_days = self.default_max_age_days

        # 如果设为 0，禁用此 feed 的过滤
        if max_days == 0:
            return items, 0

        # 过滤逻辑：无发布时间的文章保留
        filtered = []
        for item in items:
            if not item.published_at:
                # 无发布时间，保留
                filtered.append(item)
            elif is_within_days(item.published_at, max_days, self.timezone):
                # 在指定天数内，保留
                filtered.append(item)
            # 否则过滤掉

        filtered_count = len(items) - len(filtered)
        return filtered, filtered_count

    def _build_rss_items_from_parsed(
        self,
        feed: RSSFeedConfig,
        parsed_items: List,
    ) -> List[RSSItem]:
        """将解析结果统一转换为 RSSItem。"""
        if feed.max_items > 0:
            parsed_items = parsed_items[:feed.max_items]

        now = get_configured_time(self.timezone)
        crawl_time = now.strftime("%H:%M")
        items: List[RSSItem] = []

        for parsed in parsed_items:
            items.append(
                RSSItem(
                    title=parsed.title,
                    feed_id=feed.id,
                    feed_name=feed.name,
                    url=parsed.url,
                    published_at=parsed.published_at or "",
                    summary=parsed.summary or "",
                    author=parsed.author or "",
                    crawl_time=crawl_time,
                    first_time=crawl_time,
                    last_time=crawl_time,
                    count=1,
                )
            )

        print(f"[RSS] {feed.name}: 获取 {len(items)} 条")
        return items

    def _fallback_to_host_cache(
        self,
        feed: RSSFeedConfig,
        reason: str,
    ) -> Tuple[List[RSSItem], Optional[str], Dict[str, object]]:
        """在线抓取失败时统一回退宿主机缓存。"""
        cached_items, generated_at = self._load_host_cache_items(feed)
        if cached_items is None:
            return [], reason, {
                "status": "failed",
                "healthy": False,
                "count": 0,
                "last_synced": generated_at,
                "error": reason,
                "fetch_mode": "failed",
                "fresh_today": False,
            }

        fresh_today = bool(generated_at and is_same_local_date(generated_at, self.timezone))
        if not fresh_today:
            stale_reason = f"{reason}；宿主机缓存不是当天最新 ({generated_at or 'unknown'})"
            print(f"[RSS] {feed.name}: 宿主机缓存已过期，不纳入当天结果")
            return [], stale_reason, {
                "status": "stale_cache",
                "healthy": False,
                "count": len(cached_items),
                "last_synced": generated_at,
                "error": stale_reason,
                "fetch_mode": "host_cache",
                "fresh_today": False,
            }

        print(f"[RSS] {feed.name}: 在线抓取失败，回退宿主机 RSS 缓存")
        return self._build_rss_items_from_parsed(feed, cached_items), None, {
            "status": "cache_fallback",
            "healthy": True,
            "count": len(cached_items),
            "last_synced": generated_at,
            "error": reason,
            "fetch_mode": "host_cache",
            "fresh_today": fresh_today,
        }

    def fetch_feed(self, feed: RSSFeedConfig) -> Tuple[List[RSSItem], Optional[str], Dict[str, object]]:
        """
        抓取单个 RSS 源

        Args:
            feed: RSS 源配置

        Returns:
            (条目列表, 错误信息) 元组
        """
        try:
            parsed_items = []
            agent_viewer_items = self._fetch_via_rss_agent_viewer(feed)
            if agent_viewer_items is not None:
                parsed_items = self._normalize_items_from_rss_agent_viewer(agent_viewer_items)
            else:
                content = self._fetch_via_builtin_skill(feed)
                parsed_items = self.parser.parse(content, feed.url)

            return self._build_rss_items_from_parsed(feed, parsed_items), None, {
                "status": "live_ok",
                "healthy": True,
                "count": len(parsed_items),
                "last_synced": get_configured_time(self.timezone).isoformat(),
                "error": "",
                "fetch_mode": "live",
                "fresh_today": True,
            }

        except requests.Timeout:
            error = f"请求超时 ({self.timeout}s)"
            print(f"[RSS] {feed.name}: {error}")
            return self._fallback_to_host_cache(feed, error)

        except requests.RequestException as e:
            error = f"请求失败: {e}"
            print(f"[RSS] {feed.name}: {error}")
            return self._fallback_to_host_cache(feed, error)

        except ValueError as e:
            error = f"解析失败: {e}"
            print(f"[RSS] {feed.name}: {error}")
            return self._fallback_to_host_cache(feed, error)

        except Exception as e:
            error = f"未知错误: {e}"
            print(f"[RSS] {feed.name}: {error}")
            return self._fallback_to_host_cache(feed, error)

    def fetch_all(self) -> RSSData:
        """
        抓取所有 RSS 源

        Returns:
            RSSData 对象
        """
        all_items: Dict[str, List[RSSItem]] = {}
        id_to_name: Dict[str, str] = {}
        failed_ids: List[str] = []
        source_status: Dict[str, Dict[str, object]] = {}

        # 使用配置的时区
        now = get_configured_time(self.timezone)
        crawl_time = now.strftime("%H:%M")
        crawl_date = now.strftime("%Y-%m-%d")

        print(f"[RSS] 开始抓取 {len(self.feeds)} 个 RSS 源...")

        for i, feed in enumerate(self.feeds):
            # 请求间隔（带随机波动）
            if i > 0:
                interval = self.request_interval / 1000
                jitter = random.uniform(-0.2, 0.2) * interval
                time.sleep(interval + jitter)

            items, error, feed_status = self.fetch_feed(feed)

            id_to_name[feed.id] = feed.name
            source_status[feed.id] = feed_status

            if error:
                failed_ids.append(feed.id)
            else:
                all_items[feed.id] = items

        total_items = sum(len(items) for items in all_items.values())
        print(f"[RSS] 抓取完成: {len(all_items)} 个源成功, {len(failed_ids)} 个失败, 共 {total_items} 条")

        return RSSData(
            date=crawl_date,
            crawl_time=crawl_time,
            items=all_items,
            id_to_name=id_to_name,
            failed_ids=failed_ids,
            source_status=source_status,
        )

    @classmethod
    def from_config(cls, config: Dict) -> "RSSFetcher":
        """
        从配置字典创建抓取器

        Args:
            config: 配置字典，格式如下：
                {
                    "enabled": true,
                    "request_interval": 2000,
                    "freshness_filter": {
                        "enabled": true,
                        "max_age_days": 3
                    },
                    "feeds": [
                        {"id": "hacker-news", "name": "Hacker News", "url": "...", "max_age_days": 1}
                    ]
                }

        Returns:
            RSSFetcher 实例
        """
        # 读取新鲜度过滤配置
        freshness_config = config.get("freshness_filter", {})
        freshness_enabled = freshness_config.get("enabled", True)  # 默认启用
        default_max_age_days = freshness_config.get("max_age_days", 3)  # 默认3天

        feeds = []
        for feed_config in config.get("feeds", []):
            # 读取并验证单个 feed 的 max_age_days（可选）
            max_age_days_raw = feed_config.get("max_age_days")
            max_age_days = None
            if max_age_days_raw is not None:
                try:
                    max_age_days = int(max_age_days_raw)
                    if max_age_days < 0:
                        feed_id = feed_config.get("id", "unknown")
                        print(f"[警告] RSS feed '{feed_id}' 的 max_age_days 为负数，将使用全局默认值")
                        max_age_days = None
                except (ValueError, TypeError):
                    feed_id = feed_config.get("id", "unknown")
                    print(f"[警告] RSS feed '{feed_id}' 的 max_age_days 格式错误：{max_age_days_raw}")
                    max_age_days = None

            feed = RSSFeedConfig(
                id=feed_config.get("id", ""),
                name=feed_config.get("name", ""),
                url=feed_config.get("url", ""),
                max_items=feed_config.get("max_items", 0),  # 0=不限制
                enabled=feed_config.get("enabled", True),
                max_age_days=max_age_days,  # None=使用全局，0=禁用，>0=覆盖
            )
            if feed.id and feed.url:
                feeds.append(feed)

        return cls(
            feeds=feeds,
            request_interval=config.get("request_interval", 2000),
            timeout=config.get("timeout", 15),
            use_proxy=config.get("use_proxy", False),
            proxy_url=config.get("proxy_url", ""),
            timezone=config.get("timezone", DEFAULT_TIMEZONE),
            freshness_enabled=freshness_enabled,
            default_max_age_days=default_max_age_days,
        )
