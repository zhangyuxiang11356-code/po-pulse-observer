# coding=utf-8
"""基于 RSS 的 Reddit 采集。"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse, urlsplit, urlunsplit

import requests

from trendradar.crawler.rss.parser import RSSParser
from trendradar.social.models import SocialItem
from trendradar.utils.time import get_configured_time, is_same_local_date, is_within_days


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 TrendRadar/2.0",
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
}

REDDIT_JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0 TrendRadar/2.0 comment-enrichment",
    "Accept": "application/json, text/plain, */*",
}

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_URL_RE = re.compile(r"https?://\S+")
_AUTOMOD_AUTHORS = {"automoderator", "autowikibot", "[deleted]"}
_BLOCKED_COMMENT_BODIES = {"[deleted]", "[removed]"}


def _build_reddit_rss_urls(source: Dict[str, Any]) -> List[str]:
    urls = list(source.get("rss_urls", []) or [])
    for subreddit in source.get("subreddits", []) or []:
        slug = str(subreddit).strip().strip("/")
        if not slug:
            continue
        urls.append(f"https://www.reddit.com/r/{slug}/.rss")

    deduped: List[str] = []
    seen = set()
    for url in urls:
        normalized = str(url).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)

    normalized_urls: List[str] = []
    for url in deduped:
        if "reddit.com" in url and "raw_json=1" not in url:
            separator = "&" if "?" in url else "?"
            normalized_urls.append(f"{url}{separator}raw_json=1")
        else:
            normalized_urls.append(url)
    return normalized_urls


def _extract_subreddit(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) >= 2 and parts[0].lower() == "r":
        return parts[1]
    return ""


def _extract_external_id(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if "comments" in parts:
        idx = parts.index("comments")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return parts[-1] if parts else ""


def _sort_key(value: str) -> datetime:
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min


def _resolve_comment_max_items(raw_value: Any) -> int | None:
    text = str(raw_value or "").strip().lower()
    if text in {"all", "全部", "*"}:
        return None
    try:
        return max(int(text or "0"), 0)
    except (TypeError, ValueError):
        return 0


def _reddit_json_url(url: str) -> str:
    parts = urlsplit(str(url or "").strip())
    path = parts.path.rstrip("/")
    if not path.endswith(".json"):
        path = f"{path}.json"
    return urlunsplit(
        (
            parts.scheme or "https",
            parts.netloc or "www.reddit.com",
            path,
            "raw_json=1&limit=50&sort=top",
            "",
        )
    )


def _walk_reddit_comments(node: Any):
    if isinstance(node, dict):
        kind = node.get("kind")
        data = node.get("data") or {}
        if kind == "t1":
            yield data
        children = data.get("children")
        if isinstance(children, list):
            for child in children:
                yield from _walk_reddit_comments(child)
        replies = data.get("replies")
        if isinstance(replies, dict):
            yield from _walk_reddit_comments(replies)
    elif isinstance(node, list):
        for child in node:
            yield from _walk_reddit_comments(child)


def _cjk_count(text: str) -> int:
    return len(_CJK_RE.findall(text or ""))


def _clean_comment_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = re.sub(r"^>+\s*", "", text).strip()
    return text


def _is_displayable_comment(text: str, author: str) -> bool:
    body = _clean_comment_text(text)
    if not body or body.lower() in _BLOCKED_COMMENT_BODIES:
        return False
    if str(author or "").strip().lower() in _AUTOMOD_AUTHORS:
        return False
    lowered = body.lower()
    if "notice: see below for a copy of the original post" in lowered:
        return False
    if "users posting and/or commenting on politically charged topics" in lowered:
        return False
    body_without_urls = _URL_RE.sub("", body).strip()
    cjk = _cjk_count(body_without_urls)
    if not body_without_urls or len(body_without_urls) < 10:
        return False
    if cjk == 0 and len(body_without_urls) < 35:
        return False
    if cjk and cjk < 6 and len(body_without_urls) < 18:
        return False
    return True


def _comment_stance(text: str) -> str:
    lowered = str(text or "").lower()
    question_markers = ["为什么", "為什麼", "怎么", "怎麼", "吗", "嗎", "？", "?", "why", "how", "what"]
    emotion_markers = ["可怜", "悲哀", "恶心", "噁心", "笑死", "离谱", "離譜", "ridiculous", "sad", "lol"]
    critical_markers = ["错", "錯", "不对", "不對", "扯", "荒谬", "荒謬", "critic", "wrong", "bullshit"]
    if any(marker in lowered for marker in question_markers):
        return "质疑"
    if any(marker in lowered for marker in critical_markers):
        return "批评"
    if any(marker in lowered for marker in emotion_markers):
        return "情绪"
    return "评论"


def _comment_score(comment: Dict[str, Any]) -> int:
    text = str(comment.get("text") or "")
    score = int(comment.get("score") or 0)
    cjk = _cjk_count(text)
    length = len(text)
    stance = str(comment.get("stance") or "")
    value = min(max(score, 0), 200)
    value += {"质疑": 18, "批评": 15, "情绪": 12, "评论": 8}.get(stance, 8)
    value += min(cjk, 24)
    if 24 <= length <= 220:
        value += 10
    elif length > 320:
        value -= 12
    if _URL_RE.search(text):
        value -= 4
    return value


def _fetch_representative_comments(
    item: SocialItem,
    limit: int,
    timeout: int,
    proxies: Dict[str, str] | None,
) -> List[Dict[str, Any]]:
    if not item.url:
        return []
    try:
        response = requests.get(
            _reddit_json_url(item.url),
            headers=REDDIT_JSON_HEADERS,
            proxies=proxies,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print(f"[Social/Reddit] {item.external_id}: 评论补抓失败: {exc}")
        return []

    raw_comments = _walk_reddit_comments(payload[1]) if isinstance(payload, list) and len(payload) > 1 else []
    comments: List[Dict[str, Any]] = []
    seen = set()
    for raw in raw_comments:
        author = str(raw.get("author") or "").strip()
        text = _clean_comment_text(raw.get("body") or "")
        if not _is_displayable_comment(text, author):
            continue
        key = (author.lower(), text)
        if key in seen:
            continue
        seen.add(key)
        created_utc = raw.get("created_utc")
        created_at = ""
        if created_utc:
            try:
                created_at = datetime.fromtimestamp(float(created_utc), tz=dt_timezone.utc).isoformat().replace("+00:00", "Z")
            except (TypeError, ValueError, OSError):
                created_at = ""
        comments.append(
            {
                "author": author or "Reddit 用户",
                "text": text[:260],
                "stance": _comment_stance(text),
                "created_at": created_at,
                "score": int(raw.get("score") or 0),
            }
        )
    comments.sort(key=_comment_score, reverse=True)
    return comments[:limit]


def _enrich_items_with_representative_comments(
    items: List[SocialItem],
    source: Dict[str, Any],
    timeout: int,
    request_interval_ms: int,
    proxies: Dict[str, str] | None,
) -> None:
    max_items = _resolve_comment_max_items(source.get("comment_detail_max_items"))
    per_item = int(source.get("representative_comments_per_item") or 3)
    if max_items == 0:
        return
    targets = items if max_items is None else items[:max_items]
    if not targets:
        return
    limit_label = "全部候选" if max_items is None else str(max_items)
    print(f"[Social/Reddit] 评论补抓: 目标 {len(targets)}/{len(items)} 张卡，配置上限={limit_label}，每卡最多 {per_item} 条")
    for index, item in enumerate(targets, 1):
        comments = _fetch_representative_comments(item, per_item, timeout, proxies)
        item.representative_comments = comments
        if comments:
            print(f"[Social/Reddit] {item.external_id}: 补抓评论 {len(comments)} 条")
        if index < len(targets) and request_interval_ms > 0:
            time.sleep(request_interval_ms / 1000)


def _load_host_cache_items(
    source: Dict[str, Any],
    social_config: Dict[str, Any],
    timezone: str,
    ignore_age_limit: bool = False,
) -> List[SocialItem]:
    cache_path = Path("/app/output/social/reddit_items.json")
    if not cache_path.exists():
        return []

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[Social/Reddit] 宿主机缓存读取失败: {exc}")
        return []

    source_id = source.get("id", "")
    cache_generated_at = str(payload.get("generated_at", "") or "")
    max_age_days = int(source.get("max_age_days") or social_config.get("MAX_AGE_DAYS", 0) or 0)
    per_source_max = int(source.get("per_source_max_items") or social_config.get("MAX_ITEMS_PER_SOURCE", 10) or 10)

    items: List[SocialItem] = []
    for raw in payload.get("items", []) or []:
        if str(raw.get("source_id", "")) != source_id:
            continue
        published_at = str(raw.get("published_at", "") or "")
        if ignore_age_limit:
            if published_at and not is_same_local_date(published_at, timezone):
                continue
        elif max_age_days > 0 and not is_within_days(published_at, max_age_days, timezone):
            continue
        items.append(
            SocialItem(
                platform=str(raw.get("platform", "reddit") or "reddit"),
                source_id=source_id,
                source_name=str(raw.get("source_name", source.get("name", "Reddit 观察名单")) or source.get("name", "Reddit 观察名单")),
                author=str(raw.get("author", "") or ""),
                external_id=str(raw.get("external_id", "") or ""),
                title=str(raw.get("title", "") or ""),
                content=str(raw.get("content", "") or ""),
                url=str(raw.get("url", "") or ""),
                published_at=published_at,
                engagement=raw.get("engagement", {}) or {},
                tags=list(raw.get("tags", []) or []),
                risk_flags=list(raw.get("risk_flags", []) or []),
                representative_comments=list(raw.get("representative_comments", []) or []),
                metadata={
                    **(raw.get("metadata", {}) or {}),
                    "cache_generated_at": cache_generated_at,
                },
            )
        )

    items.sort(key=lambda current: _sort_key(current.published_at), reverse=True)
    if items:
        cache_mode = "同日兜底缓存" if ignore_age_limit else "宿主机缓存"
        print(f"[Social/Reddit] 读取{cache_mode} {len(items[:per_source_max])} 条")
    return items[:per_source_max]


def collect_reddit_items(source: Dict[str, Any], social_config: Dict[str, Any], timezone: str) -> List[SocialItem]:
    urls = _build_reddit_rss_urls(source)
    if not urls:
        return []

    prefer_host_cache = bool(source.get("prefer_host_cache", False))
    if prefer_host_cache:
        cached_items = _load_host_cache_items(source, social_config, timezone)
        if cached_items:
            print("[Social/Reddit] 已启用宿主机缓存优先策略，跳过在线 RSS 抓取")
            return cached_items

    parser = RSSParser()
    per_source_max = int(source.get("per_source_max_items") or social_config.get("MAX_ITEMS_PER_SOURCE", 10) or 10)
    max_age_days = int(source.get("max_age_days") or social_config.get("MAX_AGE_DAYS", 0) or 0)
    timeout = int(social_config.get("TIMEOUT", 15))
    request_interval_ms = int(social_config.get("REQUEST_INTERVAL", 1000) or 1000)
    use_proxy = bool(social_config.get("USE_PROXY", False))
    proxy_url = social_config.get("PROXY_URL", "") or ""
    proxies = {"http": proxy_url, "https": proxy_url} if use_proxy and proxy_url else None
    crawl_time = get_configured_time(timezone).strftime("%H:%M")

    items: List[SocialItem] = []
    all_failed = True
    for index, url in enumerate(urls, 1):
        subreddit = _extract_subreddit(url)
        feed_name = f"r/{subreddit}" if subreddit else f"Reddit 源 {index}"
        try:
            response = requests.get(url, headers=DEFAULT_HEADERS, proxies=proxies, timeout=timeout)
            response.raise_for_status()
            parsed_items = parser.parse(response.text, url)
            all_failed = False
        except Exception as exc:
            print(f"[Social/Reddit] {feed_name}: 抓取失败: {exc}")
            continue

        for parsed in parsed_items[:per_source_max]:
            if max_age_days > 0 and not is_within_days(parsed.published_at or "", max_age_days, timezone):
                continue
            community_label = subreddit or source.get("name", "Reddit")
            content = parsed.summary or parsed.title
            items.append(
                SocialItem(
                    platform="reddit",
                    source_id=source["id"],
                    source_name=source.get("name", "Reddit 观察名单"),
                    author=community_label,
                    external_id=_extract_external_id(parsed.url),
                    title=parsed.title,
                    content=content,
                    url=parsed.url,
                    published_at=parsed.published_at or "",
                    tags=[f"r/{subreddit}"] if subreddit else [],
                    metadata={
                        "subreddit": subreddit,
                        "feed_name": feed_name,
                        "crawl_time": crawl_time,
                        "cache_generated_at": "",
                        "source": "reddit_live_rss",
                    },
                )
            )

    items.sort(key=lambda current: _sort_key(current.published_at), reverse=True)
    if items:
        final_items = items[:per_source_max]
        _enrich_items_with_representative_comments(
            final_items,
            source,
            timeout,
            request_interval_ms,
            proxies,
        )
        return final_items

    if all_failed:
        stale_cached_items = _load_host_cache_items(
            source,
            social_config,
            timezone,
            ignore_age_limit=True,
        )
        if stale_cached_items:
            print("[Social/Reddit] 在线抓取失败，回退到同日缓存")
            return stale_cached_items

    return []
