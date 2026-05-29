# coding=utf-8
"""Export X/Twitter cookies from a local Chromium browser profile to Playwright storage state."""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import win32crypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ROOT_DIR = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT_DIR / "secrets" / "x_storage_state.json"
WINDOWS_EPOCH_OFFSET = 11644473600


def _profile_root(browser: str) -> Path:
    local_app_data = Path.home() / "AppData" / "Local"
    if browser == "edge":
        return local_app_data / "Microsoft" / "Edge" / "User Data"
    if browser == "chrome":
        return local_app_data / "Google" / "Chrome" / "User Data"
    raise ValueError(f"Unsupported browser: {browser}")


def _get_master_key(user_data_dir: Path) -> bytes:
    local_state = user_data_dir / "Local State"
    payload = json.loads(local_state.read_text(encoding="utf-8"))
    encrypted_key = base64.b64decode(payload["os_crypt"]["encrypted_key"])
    if encrypted_key.startswith(b"DPAPI"):
        encrypted_key = encrypted_key[5:]
    return win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]


def _decrypt_cookie(encrypted_value: bytes, master_key: bytes) -> str:
    if encrypted_value.startswith((b"v10", b"v11", b"v20")):
        nonce = encrypted_value[3:15]
        ciphertext = encrypted_value[15:]
        return AESGCM(master_key).decrypt(nonce, ciphertext, None).decode("utf-8")

    return win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1].decode("utf-8")


def _chrome_time_to_unix(value: int) -> float:
    if not value:
        return -1
    return max(0, value / 1_000_000 - WINDOWS_EPOCH_OFFSET)


def _same_site(value: int) -> str:
    if value == 2:
        return "Strict"
    if value == 3:
        return "None"
    return "Lax"


def export_state(browser: str, profile: str, output_path: Path) -> dict[str, Any]:
    user_data_dir = _profile_root(browser)
    profile_dir = user_data_dir / profile
    cookies_db = profile_dir / "Network" / "Cookies"
    if not cookies_db.exists():
        raise SystemExit(f"Cookies DB not found: {cookies_db}")

    master_key = _get_master_key(user_data_dir)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_db = Path(tmp_dir) / "Cookies"
        shutil.copy2(cookies_db, tmp_db)
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT host_key, name, path, expires_utc, is_secure, is_httponly, samesite, encrypted_value
            FROM cookies
            WHERE host_key LIKE '%x.com'
               OR host_key LIKE '%twitter.com'
               OR host_key LIKE '%twimg.com'
            """
        ).fetchall()
        conn.close()

    cookies = []
    failed = []
    for row in rows:
        try:
            value = _decrypt_cookie(row["encrypted_value"], master_key)
        except Exception:
            failed.append(f"{row['host_key']}:{row['name']}")
            continue
        if not value:
            continue
        cookies.append(
            {
                "name": row["name"],
                "value": value,
                "domain": row["host_key"],
                "path": row["path"] or "/",
                "expires": _chrome_time_to_unix(int(row["expires_utc"] or 0)),
                "httpOnly": bool(row["is_httponly"]),
                "secure": bool(row["is_secure"]),
                "sameSite": _same_site(int(row["samesite"] or 0)),
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"cookies": cookies, "origins": []}
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    names = {cookie["name"] for cookie in cookies}
    return {
        "output": str(output_path),
        "cookie_count": len(cookies),
        "has_auth_token": "auth_token" in names,
        "has_ct0": "ct0" in names,
        "failed_count": len(failed),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", choices=["edge", "chrome"], default="edge")
    parser.add_argument("--profile", default="Default")
    parser.add_argument("--output", default=str(STATE_PATH))
    args = parser.parse_args()

    result = export_state(args.browser, args.profile, Path(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
