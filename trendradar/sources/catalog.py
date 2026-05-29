# coding=utf-8
"""信源配置中心。"""

from __future__ import annotations

import base64
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from typing import Any, Dict, List


SOURCE_HOMEPAGE_MAP: Dict[str, str] = {
    "toutiao": "https://www.toutiao.com",
    "baidu": "https://www.baidu.com",
    "wallstreetcn-hot": "https://wallstreetcn.com",
    "thepaper": "https://www.thepaper.cn",
    "bilibili-hot-search": "https://www.bilibili.com",
    "cls-hot": "https://www.cls.cn",
    "ifeng": "https://www.ifeng.com",
    "tieba": "https://tieba.baidu.com",
    "wechat-tophub": "https://mp.weixin.qq.com",
    "zaker-tophub": "https://www.myzaker.com",
    "tieba-tophub": "https://tieba.baidu.com",
    "tencent-news-tophub": "https://news.qq.com",
    "kuaishou-tophub": "https://www.kuaishou.com",
    "hupu-tophub": "https://bbs.hupu.com",
    "huxiu-24h": "https://www.huxiu.com",
    "weibo": "https://weibo.com",
    "douyin": "https://www.douyin.com",
    "zhihu": "https://www.zhihu.com",
    "bbc": "https://www.bbc.com",
    "bbc-world": "https://www.bbc.com",
    "ap-politics": "https://apnews.com",
    "ap-world-news": "https://apnews.com",
    "ap-china": "https://apnews.com",
    "ft-china": "https://www.ft.com",
    "npr-world": "https://www.npr.org",
    "voa-chinese-1": "https://www.voachinese.com",
    "voa-chinese-2": "https://www.voachinese.com",
    "voa-chinese-3": "https://www.voachinese.com",
    "guardian-china": "https://www.theguardian.com",
    "scmp-china": "https://www.scmp.com",
    "inewsweek-politics": "https://www.inewsweek.cn",
    "inewsweek-world": "https://www.inewsweek.cn",
    "zaobao-china": "https://www.zaobao.com.sg",
    "zaobao-world": "https://www.zaobao.com.sg",
    "infzm": "https://www.infzm.com",
    "guancha-all": "https://www.guancha.cn",
    "rfi-china": "https://www.rfi.fr",
    "nyt-china-rss": "https://www.nytimes.com",
    "google-news-china": "https://news.google.com",
    "google-news-top": "https://news.google.com",
    "google-news-politics": "https://news.google.com",
    "google-news-world": "https://news.google.com",
    "caixin-politics": "https://www.caixin.com",
    "caixin-law": "https://www.caixin.com",
    "xinhua": "https://www.xinhuanet.com",
    "huanqiu-china": "https://www.huanqiu.com",
    "huanqiu-world": "https://www.huanqiu.com",
    "huanqiu-taiwan": "https://www.huanqiu.com",
    "changanjie-zhishi": "https://mp.weixin.qq.com",
    "woxun-data-center": "https://mp.weixin.qq.com",
    "hongwang": "https://www.rednet.cn",
    "zhengshier": "https://www.bjnews.com.cn",
    "fazhi-ribao": "http://www.legaldaily.com.cn",
    "reddit-watchlist": "https://www.reddit.com",
    "x-watchlist": "https://x.com",
}

SOURCE_LOGO_MAP: Dict[str, str] = {
    "x-watchlist": "https://abs.twimg.com/favicons/twitter.3.ico",
    "weibo": "https://weibo.com/favicon.ico",
    "zhihu": "https://static.zhihu.com/heifetz/favicon.ico",
    "douyin": "https://www.douyin.com/favicon.ico",
    "bilibili-hot-search": "https://www.bilibili.com/favicon.ico",
    "baidu": "https://www.baidu.com/favicon.ico",
    "tieba": "https://tb3.bdstatic.com/public/icon/favicon-v2.ico",
    "tieba-tophub": "https://tb3.bdstatic.com/public/icon/favicon-v2.ico",
    "tencent-news-tophub": "https://news.qq.com/favicon.ico",
    "ft-china": "https://www.ft.com/favicon.ico",
}

SOURCE_LOGO_ASSET_MAP: Dict[str, str] = {
    "toutiao": "toutiao.ico",
    "baidu": "baidu.ico",
    "wallstreetcn-hot": "wallstreetcn.png",
    "thepaper": "thepaper.png",
    "bilibili-hot-search": "bilibili.png",
    "cls-hot": "cls.png",
    "ifeng": "ifeng.ico",
    "tieba": "tieba.ico",
    "tieba-tophub": "tieba.ico",
    "wechat-tophub": "wechat-hot.svg",
    "zaker-tophub": "zaker.png",
    "tencent-news-tophub": "tencent-news.ico",
    "kuaishou-tophub": "kuaishou.ico",
    "hupu-tophub": "hupu.ico",
    "huxiu-24h": "huxiu.ico",
    "weibo": "weibo.ico",
    "douyin": "douyin.ico",
    "zhihu": "zhihu.ico",
    "bbc": "bbc.ico",
    "bbc-world": "bbc.ico",
    "ap-politics": "ap.png",
    "ap-world-news": "ap.png",
    "ap-china": "ap.png",
    "ft-china": "ft.png",
    "npr-world": "npr.ico",
    "voa-chinese-1": "voa.svg",
    "voa-chinese-2": "voa.svg",
    "voa-chinese-3": "voa.svg",
    "guardian-china": "guardian.ico",
    "scmp-china": "scmp.ico",
    "inewsweek-politics": "inewsweek.png",
    "inewsweek-world": "inewsweek.png",
    "zaobao-china": "zaobao.ico",
    "zaobao-world": "zaobao.ico",
    "infzm": "infzm.ico",
    "guancha-all": "guancha.png",
    "rfi-china": "rfi.ico",
    "nyt-china-rss": "nytimes.ico",
    "google-news-china": "google-news.png",
    "google-news-top": "google-news.png",
    "google-news-politics": "google-news.png",
    "google-news-world": "google-news.png",
    "caixin-politics": "caixin.jpg",
    "caixin-law": "caixin.jpg",
    "xinhua": "xinhua.png",
    "huanqiu-china": "huanqiu.ico",
    "huanqiu-world": "huanqiu.ico",
    "huanqiu-taiwan": "huanqiu.ico",
    "changanjie-zhishi": "changanjie.jpg",
    "woxun-data-center": "woxun.jpg",
    "hongwang": "hongwang.ico",
    "zhengshier": "zhengshier.ico",
    "fazhi-ribao": "fazhi-ribao.ico",
    "reddit-watchlist": "reddit.png",
    "x-watchlist": "x.ico",
}

_LOGO_DATA_URI_CACHE: Dict[str, str] = {}
_MEMBER_PROFILES_CACHE: Dict[str, Dict[str, Any]] | None = None


def infer_source_strategy(kind: str, source: Dict[str, Any]) -> str:
    """为信源推断维护策略标签。"""
    configured = str(source.get("strategy", "") or "").strip()
    if configured:
        return configured

    normalized_kind = str(kind or "").strip().upper()
    if normalized_kind == "SOCIAL":
        if str(source.get("platform", "")).strip().lower() == "x" and source.get("prefer_host_cache", False):
            return "只读宿主机缓存"
        return "优先直连"

    url = str(source.get("url", "") or source.get("fetch_url", "") or "").strip().lower()
    if any(host in url for host in ["8.130.99.172"]):
        return "优先桥接"
    if any(host in url for host in ["ft.com", "theguardian.com", "scmp.com", "voachinese.com", "rfi.fr", "nytimes.com"]):
        return "高风险源"
    return "优先直连"


def infer_source_health_policy(kind: str, source: Dict[str, Any]) -> str:
    """为信源生成默认健康策略。"""
    normalized_kind = str(kind or "").strip().upper()
    if normalized_kind == "SOCIAL":
        if str(source.get("platform", "")).strip().lower() == "x" and source.get("prefer_host_cache", False):
            return "cache_preferred"
        return "fresh_today"
    if normalized_kind == "RSS":
        return "cache_allowed"
    return "live_required"


def infer_social_member_ids(source: Dict[str, Any]) -> List[str]:
    platform = str(source.get("platform", "") or "").strip().lower()
    if platform == "x":
        members: List[str] = []
        for item in (source.get("usernames", []) or []):
            username = str((item or {}).get("username", "") or "").strip()
            if username:
                members.append(f"@{username}")
        return members

    if platform == "reddit":
        members = []
        for raw_url in (source.get("rss_urls", []) or []):
            subreddit = normalize_reddit_subreddit(raw_url)
            if subreddit:
                members.append(f"r/{subreddit}")
        return members

    return []


def normalize_reddit_subreddit(raw_value: Any) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""

    match = re.search(r"/r/([^/?#]+)", value, flags=re.IGNORECASE)
    if match:
        value = str(match.group(1) or "").strip()

    value = re.sub(r"^\s*r/", "", value, flags=re.IGNORECASE)
    value = re.sub(r"/\.rss(\?.*)?$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\.rss(\?.*)?$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\?raw_json=1$", "", value, flags=re.IGNORECASE)
    value = value.strip().strip("/")
    return value


def infer_social_member_profiles(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    profile_cache = load_member_profiles_cache()
    platform = str(source.get("platform", "") or "").strip().lower()
    members: List[Dict[str, Any]] = []

    if platform == "x":
        for item in (source.get("usernames", []) or []):
            if isinstance(item, dict):
                username = str((item or {}).get("username", "") or "").strip().lstrip("@")
            else:
                username = str(item or "").strip().lstrip("@")
            if not username:
                continue
            member_id = f"@{username}"
            profile = dict(profile_cache.get(f"x:{member_id}") or {})
            members.append(
                {
                    "id": member_id,
                    "name": member_id,
                    "display_name": str(profile.get("display_name") or member_id),
                    "homepage": str(profile.get("profile_url") or f"https://x.com/{username}"),
                    "logo_url": infer_member_logo_url(profile),
                }
            )
        return members

    if platform == "reddit":
        dedup: Dict[str, Dict[str, Any]] = {}
        for raw_url in (source.get("rss_urls", []) or []):
            subreddit = normalize_reddit_subreddit(raw_url)
            if not subreddit:
                continue
            member_id = f"r/{subreddit}"
            profile = dict(profile_cache.get(f"reddit:{member_id}") or {})
            dedup[member_id] = {
                "id": member_id,
                "name": member_id,
                "display_name": str(profile.get("display_name") or member_id),
                "homepage": str(profile.get("profile_url") or f"https://www.reddit.com/{member_id}/"),
                "logo_url": infer_member_logo_url(profile),
            }
        return list(dedup.values())

    return []


def get_local_logo_data_uri(source_id: str) -> str:
    asset_name = SOURCE_LOGO_ASSET_MAP.get(source_id, "").strip()
    if not asset_name:
        return ""

    cached = _LOGO_DATA_URI_CACHE.get(asset_name, "")
    if cached:
        return cached

    asset_path = Path(__file__).resolve().parents[2] / "docs" / "assets" / "source-logos" / asset_name
    if not asset_path.exists():
        return ""

    suffix = asset_path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")

    payload = base64.b64encode(asset_path.read_bytes()).decode("ascii")
    data_uri = f"data:{mime};base64,{payload}"
    _LOGO_DATA_URI_CACHE[asset_name] = data_uri
    return data_uri


def _get_file_data_uri(asset_path: Path) -> str:
    cache_key = str(asset_path.resolve())
    cached = _LOGO_DATA_URI_CACHE.get(cache_key, "")
    if cached:
        return cached

    if not asset_path.exists():
        return ""

    suffix = asset_path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "application/octet-stream")

    payload = base64.b64encode(asset_path.read_bytes()).decode("ascii")
    data_uri = f"data:{mime};base64,{payload}"
    _LOGO_DATA_URI_CACHE[cache_key] = data_uri
    return data_uri


def load_member_profiles_cache() -> Dict[str, Dict[str, Any]]:
    global _MEMBER_PROFILES_CACHE
    if _MEMBER_PROFILES_CACHE is not None:
        return _MEMBER_PROFILES_CACHE

    cache_path = Path(__file__).resolve().parents[2] / "output" / "social" / "member_profiles.json"
    if not cache_path.exists():
        _MEMBER_PROFILES_CACHE = {}
        return _MEMBER_PROFILES_CACHE

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        _MEMBER_PROFILES_CACHE = {}
        return _MEMBER_PROFILES_CACHE

    profiles = payload.get("profiles") or {}
    _MEMBER_PROFILES_CACHE = profiles if isinstance(profiles, dict) else {}
    return _MEMBER_PROFILES_CACHE


def infer_member_logo_url(profile: Dict[str, Any]) -> str:
    asset_rel = str(profile.get("local_asset_rel") or "").strip()
    if not asset_rel:
        return ""
    asset_path = Path(__file__).resolve().parents[2] / "output" / "social" / Path(asset_rel)
    return _get_file_data_uri(asset_path)


def infer_source_homepage(source_id: str, source: Dict[str, Any]) -> str:
    configured = str(source.get("homepage", "") or "").strip()
    if configured:
        return configured

    mapped = SOURCE_HOMEPAGE_MAP.get(source_id, "").strip()
    if mapped:
        return mapped

    raw_url = str(source.get("url", "") or source.get("fetch_url", "") or "").strip()
    if not raw_url:
        return ""

    parsed = urlparse(raw_url)
    host = (parsed.netloc or "").strip().lower()
    if not host:
        return ""
    if any(host.endswith(bridge) for bridge in ("8.130.99.172:1200", "supsub.net")):
        return ""

    scheme = parsed.scheme or "https"
    return f"{scheme}://{host}"


def infer_logo_url(source_id: str, homepage: str, source: Dict[str, Any]) -> str:
    configured = str(source.get("logo_url", "") or "").strip()
    if configured:
        return configured

    local_data_uri = get_local_logo_data_uri(source_id)
    if local_data_uri:
        return local_data_uri

    mapped = SOURCE_LOGO_MAP.get(source_id, "").strip()
    if mapped:
        return mapped

    if not homepage:
        return ""

    parsed = urlparse(homepage)
    host = (parsed.netloc or "").strip()
    if not host:
        return ""
    scheme = parsed.scheme or "https"
    return f"{scheme}://{host}/favicon.ico"


def _build_catalog_entry(
    *,
    source_id: str,
    name: str,
    kind: str,
    group: str,
    source: Dict[str, Any],
) -> Dict[str, Any]:
    display_name = str(source.get("display_name", "") or name).strip() or name
    homepage = infer_source_homepage(source_id, source)
    return {
        "id": source_id,
        "name": name,
        "display_name": display_name,
        "kind": kind,
        "group": group,
        "platform": str(source.get("platform", "") or "").strip().lower(),
        "homepage": homepage,
        "logo_url": infer_logo_url(source_id, homepage, source),
        "strategy": infer_source_strategy(kind, source),
        "health_policy": infer_source_health_policy(kind, source),
        "enabled": bool(source.get("enabled", True)),
        "member_ids": infer_social_member_ids(source) if str(kind or "").strip().upper() == "SOCIAL" else [],
        "member_profiles": infer_social_member_profiles(source) if str(kind or "").strip().upper() == "SOCIAL" else [],
    }


def build_source_catalog(config_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从原始配置生成统一信源目录。"""
    entries: List[Dict[str, Any]] = []

    platforms_config = config_data.get("platforms", {}) or {}
    if not platforms_config and config_data.get("PLATFORMS"):
        platforms_config = {"sources": config_data.get("PLATFORMS", []) or []}

    rss_config = config_data.get("rss", {}) or {}
    if not rss_config and config_data.get("RSS"):
        rss_config = {
            "feeds": (config_data.get("RSS", {}) or {}).get("FEEDS", []) or []
        }

    social_config = config_data.get("social_media", {}) or {}
    if not social_config and config_data.get("SOCIAL_MEDIA"):
        social_config = {
            "sources": (config_data.get("SOCIAL_MEDIA", {}) or {}).get("SOURCES", []) or []
        }

    for source in (platforms_config.get("sources", []) or []):
        source_id = str(source.get("id", "") or "").strip()
        name = str(source.get("name", "") or source_id).strip()
        if not source_id or not name:
            continue
        entries.append(
            _build_catalog_entry(
                source_id=source_id,
                name=name,
                kind="WEB",
                group="hotlist",
                source=source,
            )
        )

    for source in (rss_config.get("feeds", []) or []):
        source_id = str(source.get("id", "") or "").strip()
        name = str(source.get("name", "") or source_id).strip()
        if not source_id or not name:
            continue
        entries.append(
            _build_catalog_entry(
                source_id=source_id,
                name=name,
                kind="RSS",
                group="website",
                source=source,
            )
        )

    for source in (social_config.get("sources", []) or []):
        source_id = str(source.get("id", "") or "").strip()
        name = str(source.get("name", "") or source_id or source.get("platform", "unknown")).strip()
        if not source_id or not name:
            continue
        entries.append(
            _build_catalog_entry(
                source_id=source_id,
                name=name,
                kind="SOCIAL",
                group="media",
                source=source,
            )
        )

    return entries


def group_source_catalog(entries: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """将信源目录按页面分组。"""
    groups = {
        "hotlist": [],
        "website": [],
        "media": [],
    }
    for entry in entries:
        group = str(entry.get("group", "") or "").strip().lower()
        if group in groups:
            groups[group].append(dict(entry))
    return groups
