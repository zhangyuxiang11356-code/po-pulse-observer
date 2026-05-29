# coding=utf-8
"""X 平台 Playwright collector。"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from trendradar.social.models import SocialItem
from trendradar.utils.time import get_configured_time, is_same_local_date, is_within_days


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_URL_RE = re.compile(r"https?://\S+")
_MENTION_RE = re.compile(r"@([A-Za-z0-9_]{1,20})")
_BLOCKED_COMMENT_MARKERS = [
    "肛交",
    "阴毛",
    "陰毛",
    "死全家",
    "支那",
    "nmsl",
]


def _resolve_account_entries(source: Dict[str, Any]) -> List[Dict[str, str]]:
    accounts: List[Dict[str, str]] = []
    raw_values = []
    if source.get("username"):
        raw_values.append(source.get("username"))
    raw_values.extend(source.get("usernames", []) or [])

    seen = set()
    for value in raw_values:
        if isinstance(value, dict):
            normalized = str(value.get("username", "") or "").strip().lstrip("@")
            display_name = str(value.get("display_name", "") or "").strip()
        else:
            normalized = str(value).strip().lstrip("@")
            display_name = ""
        if normalized and normalized not in seen:
            seen.add(normalized)
            accounts.append(
                {
                    "username": normalized,
                    "display_name": display_name,
                }
            )
    return accounts


def _resolve_usernames(source: Dict[str, Any]) -> List[str]:
    return [item["username"] for item in _resolve_account_entries(source)]


def _resolve_display_name_map(source: Dict[str, Any]) -> Dict[str, str]:
    return {
        item["username"]: item.get("display_name", "")
        for item in _resolve_account_entries(source)
    }


def _parse_external_id(url: str) -> str:
    match = re.search(r"/status/(\d+)", url or "")
    return match.group(1) if match else ""


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_x_created_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    except Exception:
        return None


def _load_host_cache_items(
    source: Dict[str, Any],
    social_config: Dict[str, Any],
    timezone: str,
    ignore_age_limit: bool = False,
) -> List[SocialItem]:
    cache_path = Path("/app/output/social/x_items.json")
    if not cache_path.exists():
        return []

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[Social/X] 宿主机缓存读取失败: {exc}")
        return []

    display_name_map = _resolve_display_name_map(source)
    usernames = set(display_name_map.keys())
    cache_generated_at = str(payload.get("generated_at", "") or "")
    if not usernames:
        return []

    max_age_days = int(
        source.get("max_age_days")
        or social_config.get("max_age_days")
        or social_config.get("MAX_AGE_DAYS", 0)
        or 0
    )
    items: List[SocialItem] = []
    for row in payload.get("items", []) or []:
        metadata = dict(row.get("metadata") or {})
        username = str(metadata.get("username") or "").lstrip("@")
        if username not in usernames:
            continue
        display_name = str(metadata.get("display_name") or display_name_map.get(username, "") or "").strip()
        published_at = str(row.get("published_at") or "")
        if ignore_age_limit:
            if published_at and not is_same_local_date(published_at, timezone):
                continue
        elif max_age_days > 0 and published_at and not is_within_days(published_at, max_age_days, timezone):
            continue
        items.append(
            SocialItem(
                platform="x",
                source_id=source["id"],
                source_name=source.get("name", "X 观察名单"),
                author=row.get("author", display_name or f"@{username}"),
                external_id=row.get("external_id", ""),
                title=row.get("title", ""),
                content=row.get("content", ""),
                url=row.get("url", ""),
                published_at=published_at,
                engagement=row.get("engagement", {}) or {},
                tags=row.get("tags", []) or [],
                risk_flags=row.get("risk_flags", []) or [],
                representative_comments=row.get("representative_comments", []) or [],
                metadata={
                    **metadata,
                    "display_name": display_name,
                    "cache_generated_at": cache_generated_at,
                },
            )
        )

    if items:
        cache_mode = "同日兜底缓存" if ignore_age_limit else "宿主机登录态缓存"
        print(f"[Social/X] 读取{cache_mode} {len(items)} 条")
    return items
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _within_range(
    published_at: str,
    since: str = "",
    until: str = "",
    max_age_days: int = 0,
    timezone: str = "Asia/Shanghai",
) -> bool:
    published = _parse_dt(published_at)
    if published is None:
        return True

    if max_age_days > 0 and not is_within_days(published_at, max_age_days, timezone):
        return False

    if since:
        since_dt = _parse_dt(since)
        if since_dt and published < since_dt:
            return False
    if until:
        until_dt = _parse_dt(until)
        if until_dt and published > until_dt:
            return False
    return True


def _normalize_x_url(url: str) -> str:
    if not url:
        return ""
    return url if url.startswith("http") else f"https://x.com{url}"


def _parse_compact_int(value: str) -> int:
    raw = str(value or "").strip().replace(",", "")
    if not raw:
        return 0

    match = re.search(r"(\d+(?:\.\d+)?)\s*([KMB万萬千]?)", raw, re.IGNORECASE)
    if not match:
        return 0

    number = float(match.group(1))
    suffix = match.group(2).lower()
    multiplier = 1
    if suffix == "k" or suffix == "千":
        multiplier = 1_000
    elif suffix == "m":
        multiplier = 1_000_000
    elif suffix == "b":
        multiplier = 1_000_000_000
    elif suffix in {"万", "萬"}:
        multiplier = 10_000
    return int(number * multiplier)


def _extract_metric(article: Any, test_id: str) -> int:
    button = article.query_selector(f"[data-testid='{test_id}']")
    if not button:
        return 0
    try:
        text = button.inner_text().strip()
    except Exception:
        text = ""
    if not text:
        text = button.get_attribute("aria-label") or ""
    return _parse_compact_int(text)


def _resolve_playwright_launch_options() -> Dict[str, Any]:
    """优先使用系统 Chromium，避免依赖 Playwright 浏览器下载。"""
    options: Dict[str, Any] = {
        "headless": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
        ],
    }

    for candidate in [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium-headless-shell",
    ]:
        if os.path.exists(candidate):
            options["executable_path"] = candidate
            print(f"[Social/X] 使用系统 Chromium: {candidate}")
            break

    return options


def _resolve_storage_state_path(source: Dict[str, Any], social_config: Dict[str, Any]) -> str | None:
    raw_path = str(
        source.get("storage_state_path")
        or social_config.get("x_storage_state_path")
        or os.environ.get("X_STORAGE_STATE_PATH", "")
        or ""
    ).strip()
    if not raw_path:
        return None

    storage_path = Path(raw_path)
    if storage_path.exists():
        print(f"[Social/X] 使用登录态文件: {storage_path}")
        return str(storage_path)

    print(f"[Social/X] 登录态文件不存在，改用未登录浏览器: {storage_path}")
    return None


def _to_iso_utc(value: datetime) -> str:
    return value.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")


def _is_x_created_at_same_local_date(
    value: Any,
    timezone: str = "Asia/Shanghai",
    target_date: str | None = None,
) -> bool:
    parsed = _parse_x_created_at(str(value or ""))
    if parsed is None:
        return False
    local_tz = ZoneInfo(timezone)
    if target_date:
        filter_date = datetime.fromisoformat(target_date).date()
    else:
        filter_date = get_configured_time(timezone).date()
    return parsed.astimezone(local_tz).date() == filter_date


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _extract_tweets_from_any_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for node in _walk_json(payload or {}):
        legacy = node.get("legacy") or {}
        tweet_id = str(legacy.get("id_str") or "").strip()
        full_text = str(legacy.get("full_text") or "").strip()
        if not tweet_id or not full_text:
            continue
        user_result = (((node.get("core") or {}).get("user_results") or {}).get("result")) or {}
        core = user_result.get("core") or {}
        legacy_user = user_result.get("legacy") or {}
        rows[tweet_id] = {
            "id": tweet_id,
            "text": full_text,
            "username": str(core.get("screen_name") or legacy_user.get("screen_name") or "").strip(),
            "author": str(core.get("name") or legacy_user.get("name") or "").strip(),
            "created_at": str(legacy.get("created_at") or "").strip(),
            "reply_count": legacy.get("reply_count", 0),
            "favorite_count": legacy.get("favorite_count", 0),
            "retweet_count": legacy.get("retweet_count", 0),
            "conversation_id": str(legacy.get("conversation_id_str") or "").strip(),
            "in_reply_to_status_id": str(legacy.get("in_reply_to_status_id_str") or "").strip(),
            "in_reply_to_screen_name": str(legacy.get("in_reply_to_screen_name") or "").strip(),
            "mentions": [
                str(mention.get("screen_name") or "").strip()
                for mention in ((legacy.get("entities") or {}).get("user_mentions") or [])
                if str(mention.get("screen_name") or "").strip()
            ],
        }
    return list(rows.values())


def _cjk_count(text: str) -> int:
    return len(_CJK_RE.findall(text or ""))


def _clean_comment_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _comment_mentions_username(text: str, username: str) -> bool:
    if not username:
        return False
    lowered = username.lower().lstrip("@")
    return any(match.group(1).lower() == lowered for match in _MENTION_RE.finditer(text or ""))


def _is_reply_to_item(tweet: Dict[str, Any], item: SocialItem) -> bool:
    main_id = str(item.external_id or "")
    main_username = str((item.metadata or {}).get("username") or "").lower().lstrip("@")
    if not main_id:
        return False

    reply_to_id = str(tweet.get("in_reply_to_status_id") or "")
    conversation_id = str(tweet.get("conversation_id") or "")
    reply_to_screen_name = str(tweet.get("in_reply_to_screen_name") or "").lower().lstrip("@")
    mentions = {str(name or "").lower().lstrip("@") for name in tweet.get("mentions", [])}
    text = str(tweet.get("text") or "")

    if reply_to_id == main_id:
        return True
    if conversation_id == main_id:
        return True
    if main_username and (reply_to_screen_name == main_username or main_username in mentions):
        return True
    if main_username and _comment_mentions_username(text, main_username):
        return True
    return False


def _is_displayable_comment(text: str) -> bool:
    text = _clean_comment_text(text)
    if len(text) < 18:
        return False
    lowered = text.lower()
    if any(marker in lowered for marker in _BLOCKED_COMMENT_MARKERS):
        return False
    text_without_urls = _URL_RE.sub("", text).strip()
    cjk = _cjk_count(text_without_urls)
    if not text_without_urls or len(text_without_urls) < 12:
        return False
    if cjk == 0 and len(text_without_urls) < 45:
        return False
    if cjk and cjk < 6 and len(text_without_urls) < 28:
        return False
    if cjk == 0 and re.fullmatch(r"[\w\s@#:/.\-]+", text_without_urls):
        return False
    if text.count("http") > 1 and cjk < 10:
        return False
    return True


def _comment_stance(text: str) -> str:
    lowered = str(text or "").lower()
    question_markers = ["不明白", "为什么", "為什麼", "怎么", "怎麼", "凭什么", "憑什麼", "質疑", "质疑", "所谓", "所謂", "嗎", "吗", "？", "?"]
    emotion_markers = ["恨", "恶心", "噁心", "累了", "崩溃", "崩潰", "失联", "失聯", "保重", "😭", "😡", "垃圾", "操", "妈的", "媽的"]
    critical_markers = ["错", "錯", "不对", "不對", "牵强", "牽強", "扯", "荒谬", "荒謬", "离谱", "離譜", "丢人", "丟人", "洗地", "反共"]
    if any(marker in lowered for marker in question_markers):
        return "质疑"
    if any(marker in lowered for marker in emotion_markers):
        return "情绪"
    if any(marker in lowered for marker in critical_markers):
        return "批评"
    return "批评"


def _comment_score(comment: Dict[str, Any]) -> int:
    text = str(comment.get("text") or "")
    stance = str(comment.get("stance") or _comment_stance(text))
    cjk = _cjk_count(text)
    length = len(text)
    score = 0
    score += {"质疑": 18, "批评": 15, "情绪": 13}.get(stance, 8)
    score += min(cjk, 28)
    score += min(int(comment.get("favorite_count") or 0), 60) // 5
    score += min(int(comment.get("reply_count") or 0), 24) // 4
    if comment.get("direct_reply"):
        score += 10
    if 24 <= length <= 180:
        score += 10
    elif 18 <= length < 24:
        score += 2
    elif length > 240:
        score -= 8
    if cjk == 0:
        score -= 14
    if _URL_RE.search(text):
        score -= 4
    return score


def _select_representative_comments(
    tweets: List[Dict[str, Any]],
    item: SocialItem,
    limit: int,
    timezone: str,
) -> List[Dict[str, Any]]:
    main_id = str(item.external_id or "")
    main_username = str((item.metadata or {}).get("username") or "").lower()
    candidates: List[Dict[str, Any]] = []
    seen = set()
    for tweet in tweets:
        tweet_id = str(tweet.get("id") or "")
        text = _clean_comment_text(str(tweet.get("text") or ""))
        if not tweet_id or tweet_id == main_id or tweet_id in seen:
            continue
        if not _is_x_created_at_same_local_date(tweet.get("created_at"), timezone):
            continue
        if not _is_reply_to_item(tweet, item):
            continue
        if not _is_displayable_comment(text):
            continue
        username = str(tweet.get("username") or "").lower()
        if username and main_username and username == main_username:
            continue
        seen.add(tweet_id)
        candidates.append(
            {
                "author": tweet.get("author") or (f"@{tweet.get('username')}" if tweet.get("username") else "X 用户"),
                "username": tweet.get("username") or "",
                "text": text[:220],
                "stance": _comment_stance(text),
                "created_at": tweet.get("created_at") or "",
                "reply_count": tweet.get("reply_count", 0),
                "favorite_count": tweet.get("favorite_count", 0),
                "direct_reply": str(tweet.get("in_reply_to_status_id") or "") == main_id,
            }
        )
    candidates.sort(key=_comment_score, reverse=True)

    selected: List[Dict[str, Any]] = []
    used_ids = set()
    for stance in ["质疑", "批评", "情绪"]:
        for candidate in candidates:
            candidate_key = (candidate.get("username"), candidate.get("text"))
            if candidate.get("stance") == stance and candidate_key not in used_ids:
                selected.append(candidate)
                used_ids.add(candidate_key)
                break
        if len(selected) >= limit:
            break
    for candidate in candidates:
        if len(selected) >= limit:
            break
        candidate_key = (candidate.get("username"), candidate.get("text"))
        if candidate_key in used_ids:
            continue
        selected.append(candidate)
        used_ids.add(candidate_key)
    return selected[:limit]


def _fetch_representative_comments(
    context: Any,
    item: SocialItem,
    limit: int,
    timezone: str,
) -> List[Dict[str, Any]]:
    if not item.url:
        return []

    page = context.new_page()
    captures: List[Dict[str, Any]] = []

    def on_response(resp):
        if "TweetDetail" not in resp.url or resp.status != 200:
            return
        try:
            captures.extend(_extract_tweets_from_any_payload(resp.json()))
        except Exception:
            return

    page.on("response", on_response)
    try:
        page.goto(item.url, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(2200)
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(1400)
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(1000)
        return _select_representative_comments(captures, item, limit, timezone)
    except Exception as exc:
        print(f"[Social/X] {item.external_id}: 评论补抓失败: {exc}")
        return []
    finally:
        page.close()


def _resolve_comment_max_items(raw_value: Any) -> int | None:
    text = str(raw_value or "").strip().lower()
    if text in {"all", "全部", "*"}:
        return None
    try:
        return max(int(text or "0"), 0)
    except (TypeError, ValueError):
        return 0


def _enrich_items_with_representative_comments(
    context: Any,
    items: List[SocialItem],
    source: Dict[str, Any],
    timezone: str,
) -> None:
    max_items = _resolve_comment_max_items(source.get("comment_detail_max_items"))
    per_item = int(source.get("representative_comments_per_item") or 3)
    if max_items == 0:
        return

    candidates = [
        item
        for item in items
        if int((item.engagement or {}).get("reply_count") or 0) > 0
        and is_same_local_date(item.published_at, timezone)
    ]
    targets = candidates if max_items is None else candidates[:max_items]
    if not targets:
        print("[Social/X] 评论补抓：没有当天且带回复数的候选卡")
        return

    limit_label = "全部当天候选" if max_items is None else str(max_items)
    print(f"[Social/X] 评论补抓: 目标 {len(targets)}/{len(candidates)} 张当天 X 卡，配置上限={limit_label}，每卡最多 {per_item} 条")
    for item in targets:
        item.representative_comments = []
        comments = _fetch_representative_comments(context, item, per_item, timezone)
        if comments:
            item.representative_comments = comments
            print(f"[Social/X] {item.external_id}: 补抓评论 {len(comments)} 条")


def _parse_relative_time(value: str, timezone: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""

    now = datetime.now(ZoneInfo(timezone))
    if raw in {"just now", "now"}:
        return _to_iso_utc(now)
    if raw in {"a minute ago", "an minute ago"}:
        return _to_iso_utc(now - timedelta(minutes=1))
    if raw == "a day ago":
        return _to_iso_utc(now - timedelta(days=1))
    if raw == "a week ago":
        return _to_iso_utc(now - timedelta(days=7))
    if raw == "a month ago":
        return _to_iso_utc(now - timedelta(days=30))
    if raw == "a year ago":
        return _to_iso_utc(now - timedelta(days=365))

    match = re.match(r"(\d+)\s+(minute|minutes|hour|hours|day|days|week|weeks|month|months|year|years)\s+ago", raw)
    if not match:
        return ""

    amount = int(match.group(1))
    unit = match.group(2)
    if unit.startswith("minute"):
        delta = timedelta(minutes=amount)
    elif unit.startswith("hour"):
        delta = timedelta(hours=amount)
    elif unit.startswith("day"):
        delta = timedelta(days=amount)
    elif unit.startswith("week"):
        delta = timedelta(days=7 * amount)
    elif unit.startswith("month"):
        delta = timedelta(days=30 * amount)
    else:
        delta = timedelta(days=365 * amount)
    return _to_iso_utc(now - delta)


def _collect_profile_items(
    page: Any,
    source: Dict[str, Any],
    username: str,
    display_name: str,
    include_pinned: bool,
    per_username_max: int,
    since: str,
    until: str,
    max_age_days: int,
    timezone: str,
    items: List[SocialItem],
    seen_ids: set,
) -> int:
    articles = page.query_selector_all("article[data-testid='tweet']")
    collected = 0
    for article in articles:
        link_el = article.query_selector("a[href*='/status/']")
        if not link_el:
            continue

        href = link_el.get_attribute("href") or ""
        tweet_url = _normalize_x_url(href)
        external_id = _parse_external_id(tweet_url)
        if not external_id or external_id in seen_ids:
            continue

        text_el = article.query_selector("div[data-testid='tweetText']")
        content = text_el.inner_text().strip() if text_el else ""
        if not content:
            continue

        time_el = article.query_selector("time")
        published_at = time_el.get_attribute("datetime") if time_el else ""
        if not _within_range(
            published_at or "",
            since,
            until,
            max_age_days=max_age_days,
            timezone=timezone,
        ):
            continue

        social_context = article.query_selector("div[data-testid='socialContext']")
        social_context_text = social_context.inner_text().strip() if social_context else ""
        is_pinned = "Pinned" in social_context_text or "置顶" in social_context_text
        if is_pinned and not include_pinned:
            continue

        label = display_name or f"@{username}"
        title = f"{label}: {content[:80]}" + ("..." if len(content) > 80 else "")
        engagement = {
            "reply_count": _extract_metric(article, "reply"),
            "retweet_count": _extract_metric(article, "retweet"),
            "favorite_count": _extract_metric(article, "like"),
        }
        items.append(
            SocialItem(
                platform="x",
                source_id=source["id"],
                source_name=source.get("name", "X 观察名单"),
                author=label,
                external_id=external_id,
                title=title,
                content=content,
                url=tweet_url,
                published_at=published_at or "",
                engagement=engagement,
                metadata={
                    "username": username,
                    "display_name": display_name,
                    "is_pinned": is_pinned,
                    "source": "x_playwright",
                },
            )
        )
        seen_ids.add(external_id)
        collected += 1
        if collected >= per_username_max:
            break
    return collected


def _collect_twstalker_items(
    context: Any,
    source: Dict[str, Any],
    username: str,
    display_name: str,
    per_username_max: int,
    since: str,
    until: str,
    max_age_days: int,
    timezone: str,
    items: List[SocialItem],
    seen_ids: set,
) -> int:
    page = context.new_page()
    try:
        mirror_urls = [
            f"https://twstalker.com/{username}",
            f"https://w.twstalker.com/{username}",
        ]
        last_exc: Exception | None = None
        for mirror_url in mirror_urls:
            for _ in range(2):
                try:
                    page.goto(mirror_url, wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(2000)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    page.wait_for_timeout(1000)
            if last_exc is None:
                break
        if last_exc is not None:
            print(f"[Social/X] @{username}: TwStalker 回退加载失败: {last_exc}")
            return 0

        collected = 0
        time_links = page.query_selector_all(f"a[href^='/{username}/status/']")
        for link in time_links:
            relative_text = (link.inner_text() or "").strip()
            if not relative_text or "ago" not in relative_text:
                continue

            href = link.get_attribute("href") or ""
            tweet_url = _normalize_x_url(href)
            external_id = _parse_external_id(tweet_url)
            if not external_id or external_id in seen_ids:
                continue

            block = link.evaluate_handle("node => node.closest('div.activity-posts')")
            if not block:
                continue
            block_el = block.as_element()
            if block_el is None:
                continue

            content_el = block_el.query_selector(":scope > div.activity-descp > p")
            content = content_el.inner_text().strip() if content_el else ""
            if not content:
                continue

            published_at = _parse_relative_time(relative_text, timezone)
            if not _within_range(
                published_at,
                since,
                until,
                max_age_days=max_age_days,
                timezone=timezone,
            ):
                continue

            label = display_name or f"@{username}"
            title = f"{label}: {content[:80]}" + ("..." if len(content) > 80 else "")
            items.append(
                SocialItem(
                    platform="x",
                    source_id=source["id"],
                    source_name=source.get("name", "X 观察名单"),
                    author=label,
                    external_id=external_id,
                    title=title,
                    content=content,
                    url=tweet_url,
                    published_at=published_at,
                    metadata={
                        "username": username,
                        "display_name": display_name,
                        "is_pinned": False,
                        "source": "twstalker_fallback",
                        "relative_time": relative_text,
                    },
                )
            )
            seen_ids.add(external_id)
            collected += 1
            if collected >= per_username_max:
                break
        return collected
    finally:
        page.close()


def collect_x_items(source: Dict[str, Any], social_config: Dict[str, Any], timezone: str) -> List[SocialItem]:
    usernames = _resolve_usernames(source)
    display_name_map = _resolve_display_name_map(source)
    if not usernames:
        return []

    prefer_host_cache = source.get("prefer_host_cache", True)

    if prefer_host_cache:
        cached_items = _load_host_cache_items(
            source,
            social_config,
            timezone,
            ignore_age_limit=True,
        )
        if cached_items:
            print("[Social/X] 已启用宿主机桥接优先策略，跳过容器内浏览器抓取")
            return cached_items

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[Social/X] 未安装 playwright，无法抓取 X")
        return _load_host_cache_items(
            source,
            social_config,
            timezone,
            ignore_age_limit=True,
        )

    include_pinned = bool(source.get("include_pinned", False))
    per_username_max = int(
        source.get("per_username_max_items")
        or source.get("per_source_max_items")
        or social_config.get("MAX_ITEMS_PER_SOURCE", 10)
        or 10
    )
    overall_max = int(source.get("max_items") or 0)
    since = str(source.get("since", "")).strip()
    until = str(source.get("until", "")).strip()
    max_age_days = int(
        source.get("max_age_days")
        or social_config.get("max_age_days")
        or social_config.get("MAX_AGE_DAYS", 0)
        or 0
    )

    items: List[SocialItem] = []
    seen_ids = set()

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(**_resolve_playwright_launch_options())
        except Exception as exc:
            print(f"[Social/X] 浏览器启动失败: {exc}")
            return _load_host_cache_items(
                source,
                social_config,
                timezone,
                ignore_age_limit=True,
            )
        context_options: Dict[str, Any] = {
            "locale": "zh-CN",
            "timezone_id": timezone,
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            ),
            "viewport": {"width": 1440, "height": 2200},
        }
        storage_state_path = _resolve_storage_state_path(source, social_config)
        if storage_state_path:
            context_options["storage_state"] = storage_state_path
        context = browser.new_context(**context_options)
        page = context.new_page()

        try:
            for username in usernames:
                display_name = str(display_name_map.get(username, "") or "").strip()
                url = f"https://x.com/{username}"
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except PlaywrightTimeoutError:
                        pass
                    page.wait_for_selector("article[data-testid='tweet']", timeout=15000)
                except Exception as exc:
                    print(f"[Social/X] @{username}: 页面加载失败: {exc}")
                    continue

                collected = _collect_profile_items(
                    page,
                    source,
                    username,
                    display_name,
                    include_pinned,
                    per_username_max,
                    since,
                    until,
                    max_age_days,
                    timezone,
                    items,
                    seen_ids,
                )
                if collected < per_username_max:
                    fallback_collected = _collect_twstalker_items(
                        context,
                        source,
                        username,
                        display_name,
                        per_username_max - collected,
                        since,
                        until,
                        max_age_days,
                        timezone,
                        items,
                        seen_ids,
                    )
                    if fallback_collected > 0:
                        print(f"[Social/X] @{username}: TwStalker 回退补充 {fallback_collected} 条")

            min_dt = datetime.min.replace(tzinfo=dt_timezone.utc)
            items.sort(key=lambda item: _parse_dt(item.published_at or "") or min_dt, reverse=True)
            if overall_max > 0:
                del items[overall_max:]
            _enrich_items_with_representative_comments(context, items, source, timezone)
        finally:
            context.close()
            browser.close()

    if items:
        return items

    stale_cached_items = _load_host_cache_items(
        source,
        social_config,
        timezone,
        ignore_age_limit=True,
    )
    if stale_cached_items:
        print("[Social/X] 在线抓取为空，回退到同日缓存")
        if overall_max > 0:
            return stale_cached_items[:overall_max]
        return stale_cached_items
    return []
