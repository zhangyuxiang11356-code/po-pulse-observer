# coding=utf-8
"""社交媒体成员头像与资料缓存。"""

from __future__ import annotations

import json
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import requests


ROOT = Path(__file__).resolve().parents[2]
SOCIAL_OUTPUT_DIR = ROOT / "output" / "social"
PROFILE_CACHE_PATH = SOCIAL_OUTPUT_DIR / "member_profiles.json"
PROFILE_ASSET_DIR = SOCIAL_OUTPUT_DIR / "profile_assets"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", str(value or "").strip())
    cleaned = cleaned.strip("-._")
    return cleaned or "profile"


def _guess_extension(url: str, content_type: str) -> str:
    parsed_path = urlparse(url or "").path
    suffix = Path(parsed_path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico"}:
        return suffix

    mime = (content_type or "").split(";", 1)[0].strip().lower()
    guessed = mimetypes.guess_extension(mime) or ""
    if guessed == ".jpe":
        guessed = ".jpg"
    if guessed:
        return guessed
    return ".png"


def load_member_profiles() -> Dict[str, Any]:
    if not PROFILE_CACHE_PATH.exists():
        return {"generated_at": "", "profiles": {}}

    try:
        payload = json.loads(PROFILE_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"generated_at": "", "profiles": {}}

    profiles = payload.get("profiles") or {}
    if not isinstance(profiles, dict):
        profiles = {}
    return {
        "generated_at": str(payload.get("generated_at") or ""),
        "profiles": profiles,
    }


def write_member_profiles(profiles: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    SOCIAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": _utc_now(),
        "profiles": profiles,
    }
    PROFILE_CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def merge_member_profiles(updates: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    cache = load_member_profiles()
    profiles = dict(cache.get("profiles") or {})

    for member_key, update in (updates or {}).items():
        if not member_key or not isinstance(update, dict):
            continue
        current = dict(profiles.get(member_key) or {})
        merged = {**current}
        for key, value in update.items():
            if value in (None, "", [], {}):
                continue
            merged[key] = value
        merged["member_key"] = member_key
        merged["updated_at"] = _utc_now()
        profiles[member_key] = merged

    return write_member_profiles(profiles)


def download_avatar_to_local(
    *,
    member_key: str,
    platform: str,
    avatar_url: str,
    timeout: int = 20,
    headers: Dict[str, str] | None = None,
) -> str:
    avatar_url = str(avatar_url or "").strip()
    if not avatar_url:
        return ""

    response = requests.get(
        avatar_url,
        timeout=timeout,
        headers=headers or {"User-Agent": "Mozilla/5.0 TrendRadar/2.0"},
    )
    response.raise_for_status()

    ext = _guess_extension(avatar_url, response.headers.get("content-type", ""))
    platform_slug = _safe_slug(platform)
    filename = f"{_safe_slug(member_key)}{ext}"
    target_dir = PROFILE_ASSET_DIR / platform_slug
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    target_path.write_bytes(response.content)

    return str(target_path.relative_to(SOCIAL_OUTPUT_DIR)).replace("\\", "/")
