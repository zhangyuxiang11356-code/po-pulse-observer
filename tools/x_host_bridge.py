# coding=utf-8
"""宿主机 X 登录态抓取桥接脚本。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trendradar.core import load_config
from trendradar.social.member_profiles import download_avatar_to_local, merge_member_profiles


OUTPUT_DIR = ROOT / "output" / "social"
SESSION_DIR = OUTPUT_DIR / "x_session"
CACHE_PATH = OUTPUT_DIR / "x_items.json"
os.chdir(ROOT)

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


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _resolve_local_timezone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name in {"Asia/Shanghai", "China Standard Time"}:
            return dt_timezone(timedelta(hours=8), name="Asia/Shanghai")
        raise


def _resolve_filter_date(target_date: str | None, local_tz: ZoneInfo):
    text = str(target_date or "").strip()
    if not text:
        return datetime.now(local_tz).date()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"target_date must be YYYY-MM-DD or ISO datetime, got: {target_date}") from exc
    if parsed.tzinfo is not None:
        return parsed.astimezone(local_tz).date()
    return parsed.date()


def _is_same_local_date(value: Any, timezone_name: str = "Asia/Shanghai", target_date: str | None = None) -> bool:
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    local_tz = _resolve_local_timezone(timezone_name)
    filter_date = _resolve_filter_date(target_date, local_tz)
    return parsed.astimezone(local_tz).date() == filter_date


def _is_x_created_at_same_local_date(value: Any, timezone_name: str = "Asia/Shanghai", target_date: str | None = None) -> bool:
    parsed = _parse_x_created_at(str(value or ""))
    if parsed is None:
        return False
    local_tz = _resolve_local_timezone(timezone_name)
    filter_date = _resolve_filter_date(target_date, local_tz)
    return parsed.astimezone(local_tz).date() == filter_date


def _resolve_x_source(config: Dict[str, Any]) -> Dict[str, Any]:
    social = config.get("SOCIAL_MEDIA", {}) or {}
    for source in social.get("SOURCES", []) or []:
        if str(source.get("platform", "")).lower() == "x" and source.get("enabled", True):
            return source
    return {}


def _resolve_account_entries(source: Dict[str, Any]) -> List[Dict[str, str]]:
    accounts: List[Dict[str, str]] = []
    seen = set()
    raw_values = []
    if source.get("username"):
        raw_values.append(source.get("username"))
    raw_values.extend(source.get("usernames", []) or [])

    for raw in raw_values:
        if isinstance(raw, dict):
            username = str(raw.get("username", "") or "").strip().lstrip("@")
            display_name = str(raw.get("display_name", "") or "").strip()
        else:
            username = str(raw or "").strip().lstrip("@")
            display_name = ""

        if username and username not in seen:
            seen.add(username)
            accounts.append(
                {
                    "username": username,
                    "display_name": display_name,
                }
            )
    return accounts


def _parse_external_id(url: str) -> str:
    match = re.search(r"/status/(\d+)", url or "")
    return match.group(1) if match else ""


def _to_iso_utc(dt_value: datetime | None) -> str:
    if dt_value is None:
        return ""
    return dt_value.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_x_created_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    except Exception:
        return None


def _extract_tweets_from_payload(payload: Dict[str, Any], username: str, display_name: str = "") -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    instructions = ((((payload or {}).get("data") or {}).get("user") or {}).get("result") or {}).get("timeline", {}).get("timeline", {}).get("instructions", [])
    for inst in instructions:
        entries = []
        if inst.get("entry"):
            entries.append(inst["entry"])
        entries.extend(inst.get("entries") or [])
        for ent in entries:
            content = ent.get("content") or {}
            item = content.get("itemContent") or (((content.get("content") or {}).get("itemContent")) or {})
            tweet = (((item.get("tweet_results") or {}).get("result")) or {})
            legacy = tweet.get("legacy") or {}
            if not legacy.get("id_str") or not legacy.get("full_text"):
                continue
            user_result = (((tweet.get("core") or {}).get("user_results") or {}).get("result")) or {}
            core = user_result.get("core") or {}
            screen_name = str(core.get("screen_name") or username).lstrip("@")
            if screen_name.lower() != username.lower():
                continue
            tweet_id = legacy.get("id_str")
            full_text = str(legacy.get("full_text") or "").strip()
            if not full_text:
                continue
            published_dt = _parse_x_created_at(str(legacy.get("created_at") or ""))
            label = display_name or f"@{screen_name}"
            rows[tweet_id] = {
                "platform": "x",
                "source_id": "x-watchlist",
                "source_name": "X 观察名单",
                "author": label,
                "external_id": tweet_id,
                "title": f"{label}: {full_text[:80]}" + ("..." if len(full_text) > 80 else ""),
                "content": full_text,
                "url": f"https://x.com/{screen_name}/status/{tweet_id}",
                "published_at": _to_iso_utc(published_dt),
                "engagement": {
                    "reply_count": legacy.get("reply_count", 0),
                    "retweet_count": legacy.get("retweet_count", 0),
                    "favorite_count": legacy.get("favorite_count", 0),
                    "quote_count": legacy.get("quote_count", 0),
                },
                "tags": [],
                "risk_flags": [],
                "metadata": {
                    "username": screen_name,
                    "display_name": display_name,
                    "source": "x_host_login",
                },
            }
    rows_list = list(rows.values())
    rows_list.sort(key=lambda item: item.get("published_at", ""), reverse=True)
    return rows_list


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


def _is_reply_to_item(tweet: Dict[str, Any], item: Dict[str, Any]) -> bool:
    main_id = str(item.get("external_id") or "")
    main_username = str((item.get("metadata") or {}).get("username") or "").lower().lstrip("@")
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
    item: Dict[str, Any],
    limit: int,
    timezone_name: str,
    target_date: str | None,
) -> List[Dict[str, Any]]:
    main_id = str(item.get("external_id") or "")
    main_username = str((item.get("metadata") or {}).get("username") or "").lower()
    candidates: List[Dict[str, Any]] = []
    seen = set()
    for tweet in tweets:
        tweet_id = str(tweet.get("id") or "")
        text = _clean_comment_text(str(tweet.get("text") or ""))
        if not tweet_id or tweet_id == main_id or tweet_id in seen:
            continue
        if not _is_x_created_at_same_local_date(tweet.get("created_at"), timezone_name, target_date):
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
    item: Dict[str, Any],
    limit: int,
    timezone_name: str,
    target_date: str | None,
) -> List[Dict[str, Any]]:
    url = str(item.get("url") or "").strip()
    if not url:
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
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(2500)
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(1800)
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(1200)
        return _select_representative_comments(captures, item, limit, timezone_name, target_date)
    except Exception as exc:
        print(f"{url}: 评论补抓失败: {exc}")
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


def _filter_items_for_target_date(
    items: List[Dict[str, Any]],
    source: Dict[str, Any],
    target_date: str | None = None,
) -> List[Dict[str, Any]]:
    timezone_name = str(source.get("timezone") or "Asia/Shanghai")
    return [
        item
        for item in items
        if str(item.get("platform", "")).lower() == "x"
        and _is_same_local_date(item.get("published_at"), timezone_name, target_date)
    ]


def _enrich_items_with_representative_comments(
    items: List[Dict[str, Any]],
    source: Dict[str, Any],
    target_date: str | None = None,
) -> None:
    max_items = _resolve_comment_max_items(source.get("comment_detail_max_items"))
    per_item = int(source.get("representative_comments_per_item") or 3)
    if max_items == 0:
        return
    timezone_name = str(source.get("timezone") or "Asia/Shanghai")
    candidates = [
        item
        for item in items
        if str(item.get("platform", "")).lower() == "x"
        and int((item.get("engagement") or {}).get("reply_count") or 0) > 0
        and _is_same_local_date(item.get("published_at"), timezone_name, target_date)
    ]
    targets = candidates if max_items is None else candidates[:max_items]
    if not targets:
        print("X 评论补抓：没有当天且带回复数的候选卡")
        return
    limit_label = "全部当天候选" if max_items is None else str(max_items)
    date_label = str(target_date or "").strip() or "当前日期"
    print(f"X 评论补抓：目标 {len(targets)}/{len(candidates)} 张当天 X 卡，目标日期={date_label}，配置上限={limit_label}，每卡最多 {per_item} 条")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(SESSION_DIR),
            headless=True,
            locale="zh-CN",
            viewport={"width": 1280, "height": 1200},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            for item in targets:
                item.pop("representative_comments", None)
                comments = _fetch_representative_comments(context, item, per_item, timezone_name, target_date)
                if comments:
                    item["representative_comments"] = comments
                    print(f"{item.get('external_id')}: 补抓代表性评论 {len(comments)} 条")
        finally:
            context.close()


def comments_flow(
    comment_max_items: str | int | None = None,
    comments_per_item: int | None = None,
    target_date: str | None = None,
) -> int:
    if not CACHE_PATH.exists():
        print(f"未找到 X 缓存: {CACHE_PATH}")
        return 1
    config = load_config()
    source = _resolve_x_source(config)
    if comment_max_items is not None:
        source["comment_detail_max_items"] = comment_max_items
    if comments_per_item is not None:
        source["representative_comments_per_item"] = comments_per_item
    if comment_max_items is None and _resolve_comment_max_items(source.get("comment_detail_max_items")) == 0:
        source["comment_detail_max_items"] = 4
    if int(source.get("representative_comments_per_item") or 0) <= 0:
        source["representative_comments_per_item"] = 3

    payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    items = payload.get("items") or []
    if not isinstance(items, list):
        print("X 缓存格式异常: items 不是列表")
        return 1
    filtered_items = _filter_items_for_target_date(items, source, target_date)
    if len(filtered_items) != len(items):
        date_label = str(target_date or "").strip() or "当前日期"
        print(f"X 缓存日期过滤：目标日期={date_label}，保留 {len(filtered_items)}/{len(items)} 条当天主帖")
        payload["items"] = filtered_items
        items = filtered_items
    _enrich_items_with_representative_comments(items, source, target_date)
    CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已更新 X 代表性评论: {CACHE_PATH}")
    return 0


def _extract_profile_meta(payload: Dict[str, Any], username: str, display_name: str = "") -> Dict[str, str]:
    user_result = ((((payload or {}).get("data") or {}).get("user") or {}).get("result")) or {}
    legacy = user_result.get("legacy") or {}
    core = user_result.get("core") or {}

    resolved_username = str(
        core.get("screen_name") or legacy.get("screen_name") or username
    ).strip().lstrip("@")
    resolved_display_name = str(
        core.get("name") or legacy.get("name") or display_name
    ).strip()
    avatar_url = str(
        core.get("avatar_image_url")
        or legacy.get("profile_image_url_https")
        or legacy.get("profile_image_url")
        or ""
    ).strip()
    if avatar_url:
        avatar_url = avatar_url.replace("_normal", "_400x400")

    return {
        "username": resolved_username or username,
        "display_name": resolved_display_name or display_name,
        "avatar_url": avatar_url,
    }


def _extract_profile_avatar_from_dom(page: Any, username: str) -> str:
    selectors = [
        f"a[href='/{username}/photo'] img",
        "img[src*='profile_images']",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() <= 0:
                continue
            src = str(locator.get_attribute("src") or "").strip()
            if src:
                return src.replace("_normal", "_400x400")
        except Exception:
            continue
    return ""


def login_flow() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(SESSION_DIR),
            headless=False,
            locale="zh-CN",
            viewport={"width": 1440, "height": 1000},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.new_page()
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60000)
        print("已打开 X 登录窗口。请在浏览器里完成登录，脚本会自动检测并保存登录态。")
        logged_in = False
        for _ in range(300):
            try:
                page.wait_for_timeout(2000)
                current_url = page.url
                if "login" in current_url:
                    continue
                if (
                    page.locator("[data-testid='AppTabBar_Home_Link']").count() > 0
                    or page.locator("[data-testid='SideNav_AccountSwitcher_Button']").count() > 0
                    or page.locator("a[href='/home']").count() > 0
                ):
                    logged_in = True
                    break
            except Exception:
                continue
        context.close()
    if not logged_in:
        print("登录检测超时，请重新运行 login 并在浏览器内完成登录。")
        return 1
    print(f"登录态已保存到: {SESSION_DIR}")
    return 0


def fetch_flow(target_date: str | None = None) -> int:
    config = load_config()
    source = _resolve_x_source(config)
    if not source:
        print("未找到启用的 X 信源配置")
        return 1

    accounts = _resolve_account_entries(source)
    if not accounts:
        print("X 观察名单为空")
        return 1

    if not SESSION_DIR.exists():
        print(f"未找到登录态目录: {SESSION_DIR}")
        print("请先运行: python tools/x_host_bridge.py login")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    collected: List[Dict[str, Any]] = []
    profile_updates: Dict[str, Dict[str, Any]] = {}
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(SESSION_DIR),
            headless=True,
            locale="zh-CN",
            viewport={"width": 1440, "height": 2200},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            for account in accounts:
                username = account["username"]
                display_name = account.get("display_name", "")
                payload_box: Dict[str, Any] = {}
                page = context.new_page()

                def on_response(resp):
                    if "UserTweets?" in resp.url and resp.status == 200:
                        try:
                            payload_box["payload"] = resp.json()
                        except Exception:
                            pass

                page.on("response", on_response)
                try:
                    page.goto(f"https://x.com/{username}", wait_until="domcontentloaded", timeout=60000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=12000)
                    except PlaywrightTimeoutError:
                        pass
                    page.wait_for_timeout(3000)
                    payload = payload_box.get("payload") or {}
                    rows = _extract_tweets_from_payload(payload, username, display_name)
                    profile_meta = _extract_profile_meta(payload, username, display_name)
                    avatar_url = profile_meta.get("avatar_url") or _extract_profile_avatar_from_dom(page, username)
                    local_asset = ""
                    if avatar_url:
                        try:
                            local_asset = download_avatar_to_local(
                                member_key=f"x:@{username}",
                                platform="x",
                                avatar_url=avatar_url,
                            )
                        except Exception as exc:
                            print(f"@{username}: 头像下载失败: {exc}")
                    profile_updates[f"x:@{username}"] = {
                        "platform": "x",
                        "member_id": f"@{username}",
                        "display_name": profile_meta.get("display_name") or display_name or f"@{username}",
                        "profile_url": f"https://x.com/{username}",
                        "avatar_url": avatar_url,
                        "local_asset_rel": local_asset,
                    }
                    if rows:
                        per_max = int(source.get("per_source_max_items") or 8)
                        collected.extend(rows[:per_max])
                        print(f"@{username}: 抓取 {min(len(rows), per_max)} 条")
                    else:
                        print(f"@{username}: 未抓到有效推文")
                finally:
                    page.close()
        finally:
            context.close()

    dedup: Dict[str, Dict[str, Any]] = {}
    for row in collected:
        dedup[row["external_id"]] = row
    all_items = sorted(dedup.values(), key=lambda item: item.get("published_at", ""), reverse=True)
    final_items = _filter_items_for_target_date(all_items, source, target_date)
    date_label = str(target_date or "").strip() or "当前日期"
    print(f"X 主帖日期过滤：目标日期={date_label}，保留 {len(final_items)}/{len(all_items)} 条当天主帖")
    _enrich_items_with_representative_comments(final_items, source, target_date)
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
    print(f"已写入 X 缓存: {CACHE_PATH}")
    print(f"总计 {len(final_items)} 条")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="宿主机 X 登录态桥接")
    parser.add_argument("mode", choices=["login", "fetch", "comments"], help="login=初始化登录态, fetch=抓取并写缓存, comments=为现有缓存补抓代表性评论")
    parser.add_argument("--comment-max-items", default=None, help="comments 模式补抓的最多帖子数；可填 all 表示当天会展示的 X 卡尽量全补")
    parser.add_argument("--comments-per-item", type=int, default=None, help="每条帖子保留的代表性评论数")
    parser.add_argument("--target-date", default=None, help="按这个本地日期筛选当天 X 卡，格式 YYYY-MM-DD；为空则使用当前日期")
    args = parser.parse_args()
    if args.mode == "login":
        return login_flow()
    if args.mode == "comments":
        return comments_flow(args.comment_max_items, args.comments_per_item, args.target_date)
    return fetch_flow(args.target_date)


if __name__ == "__main__":
    raise SystemExit(main())
