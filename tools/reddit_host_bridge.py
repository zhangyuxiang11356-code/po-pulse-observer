# coding=utf-8
"""宿主机 Reddit RSS 抓取桥接脚本。"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlsplit, urlunsplit

import requests

from trendradar.core import load_config
from trendradar.crawler.rss.parser import RSSParser
from trendradar.social.member_profiles import download_avatar_to_local, merge_member_profiles
from trendradar.social.models import SocialItem
from trendradar.utils.time import get_configured_time, is_within_days


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output" / "social"
CACHE_PATH = OUTPUT_DIR / "reddit_items.json"
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


def _resolve_reddit_source(config: Dict[str, Any]) -> Dict[str, Any]:
    social = config.get("SOCIAL_MEDIA", {}) or {}
    for source in social.get("SOURCES", []) or []:
        if str(source.get("platform", "")).lower() == "reddit" and source.get("enabled", True):
            return source
    return {}


def _build_urls(source: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    seen = set()
    for raw in source.get("rss_urls", []) or []:
        url = str(raw or "").strip()
        if not url:
            continue
        if "reddit.com" in url and "raw_json=1" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}raw_json=1"
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _extract_subreddit(url: str) -> str:
    match = re.search(r"/r/([^/?#]+)", str(url or ""), flags=re.IGNORECASE)
    if not match:
        return ""
    subreddit = str(match.group(1) or "").strip()
    subreddit = re.sub(r"\.rss(\?.*)?$", "", subreddit, flags=re.IGNORECASE)
    subreddit = re.sub(r"\?raw_json=1$", "", subreddit, flags=re.IGNORECASE)
    return subreddit.strip()


def _extract_external_id(url: str) -> str:
    parts = [part for part in url.split("/") if part]
    if "comments" in parts:
        idx = parts.index("comments")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return parts[-1] if parts else ""


def _fetch_subreddit_profile(subreddit: str, timeout: int) -> Dict[str, str]:
    if not subreddit:
        return {}

    url = f"https://www.reddit.com/r/{subreddit}/about.json"
    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {}

    data = payload.get("data") or {}
    avatar_url = str(
        data.get("community_icon")
        or data.get("icon_img")
        or data.get("header_img")
        or ""
    ).strip()
    if avatar_url:
        avatar_url = avatar_url.split("?", 1)[0].strip()

    return {
        "display_name": str(data.get("display_name_prefixed") or f"r/{subreddit}").strip(),
        "profile_url": f"https://www.reddit.com/r/{subreddit}/",
        "avatar_url": avatar_url,
    }


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
    return urlunsplit((parts.scheme or "https", parts.netloc or "www.reddit.com", path, "raw_json=1&limit=50&sort=top", ""))


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


def _fetch_representative_comments(item: Dict[str, Any], limit: int, timeout: int) -> List[Dict[str, Any]]:
    url = str(item.get("url") or "").strip()
    if not url:
        return []
    try:
        response = requests.get(_reddit_json_url(url), headers=REDDIT_JSON_HEADERS, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print(f"{item.get('external_id')}: Reddit 评论补抓失败: {exc}")
        return []

    comments: List[Dict[str, Any]] = []
    if isinstance(payload, list) and len(payload) > 1:
        raw_comments = _walk_reddit_comments(payload[1])
    else:
        raw_comments = []
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
    items: List[Dict[str, Any]],
    source: Dict[str, Any],
    timeout: int,
    request_interval_ms: int,
) -> None:
    max_items = _resolve_comment_max_items(source.get("comment_detail_max_items"))
    per_item = int(source.get("representative_comments_per_item") or 3)
    if max_items == 0:
        return
    candidates = [item for item in items if str(item.get("platform", "")).lower() == "reddit" and item.get("url")]
    targets = candidates if max_items is None else candidates[:max_items]
    if not targets:
        print("Reddit 评论补抓：没有候选卡")
        return
    limit_label = "全部候选" if max_items is None else str(max_items)
    print(f"Reddit 评论补抓：目标 {len(targets)}/{len(candidates)} 张卡，配置上限={limit_label}，每卡最多 {per_item} 条")
    for index, item in enumerate(targets, 1):
        comments = _fetch_representative_comments(item, per_item, timeout)
        item["representative_comments"] = comments
        if comments:
            print(f"{item.get('external_id')}: 补抓 Reddit 评论 {len(comments)} 条")
        if index < len(targets) and request_interval_ms > 0:
            time.sleep(request_interval_ms / 1000)


def fetch_flow() -> int:
    config = load_config()
    source = _resolve_reddit_source(config)
    if not source:
        print("未找到启用的 Reddit 信源配置")
        return 1

    social_cfg = config.get("SOCIAL_MEDIA", {}) or {}
    timezone = config.get("TIMEZONE", "Asia/Shanghai")
    per_source_max = int(source.get("per_source_max_items") or social_cfg.get("MAX_ITEMS_PER_SOURCE", 10) or 10)
    max_age_days = int(source.get("max_age_days") or social_cfg.get("MAX_AGE_DAYS", 0) or 0)
    timeout = int(social_cfg.get("TIMEOUT", 15) or 15)
    request_interval_ms = int(social_cfg.get("REQUEST_INTERVAL", 1000) or 1000)
    crawl_time = get_configured_time(timezone).strftime("%H:%M")
    parser = RSSParser()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    items: List[SocialItem] = []
    profile_updates: Dict[str, Dict[str, Any]] = {}
    for index, url in enumerate(_build_urls(source), 1):
        subreddit = _extract_subreddit(url)
        feed_name = f"r/{subreddit}" if subreddit else f"Reddit 源 {index}"
        profile_meta = _fetch_subreddit_profile(subreddit, timeout)
        avatar_url = profile_meta.get("avatar_url", "")
        local_asset = ""
        if subreddit and avatar_url:
            try:
                local_asset = download_avatar_to_local(
                    member_key=f"reddit:r/{subreddit}",
                    platform="reddit",
                    avatar_url=avatar_url,
                    timeout=timeout,
                    headers=DEFAULT_HEADERS,
                )
            except Exception as exc:
                print(f"{feed_name}: 头像下载失败: {exc}")
        if subreddit:
            profile_updates[f"reddit:r/{subreddit}"] = {
                "platform": "reddit",
                "member_id": f"r/{subreddit}",
                "display_name": profile_meta.get("display_name") or f"r/{subreddit}",
                "profile_url": profile_meta.get("profile_url") or f"https://www.reddit.com/r/{subreddit}/",
                "avatar_url": avatar_url,
                "local_asset_rel": local_asset,
            }
        try:
            response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            response.raise_for_status()
            parsed_items = parser.parse(response.text, url)
        except Exception as exc:
            print(f"{feed_name}: 抓取失败: {exc}")
            continue

        for parsed in parsed_items[:per_source_max]:
            if max_age_days > 0 and not is_within_days(parsed.published_at or "", max_age_days, timezone):
                continue
            author = parsed.author or (f"r/{subreddit}" if subreddit else "")
            content = parsed.summary or parsed.title
            items.append(
                SocialItem(
                    platform="reddit",
                    source_id=str(source.get("id", "reddit-watchlist")),
                    source_name=str(source.get("name", "Reddit 观察名单")),
                    author=author,
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
                        "source": "reddit_host_rss",
                    },
                )
            )

    items.sort(key=lambda item: item.published_at or "", reverse=True)
    final_items = [item.to_dict() for item in items[:per_source_max]]
    _enrich_items_with_representative_comments(final_items, source, timeout, request_interval_ms)
    CACHE_PATH.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(dt_timezone.utc).isoformat().replace("+00:00", "Z"),
                "items": final_items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    merge_member_profiles(profile_updates)
    print(f"已写入 Reddit 缓存: {CACHE_PATH}")
    print(f"总计 {len(final_items)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(fetch_flow())
