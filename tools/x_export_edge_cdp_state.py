# coding=utf-8
"""Export X login state by connecting to a running Edge profile over CDP."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


ROOT_DIR = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT_DIR / "secrets" / "x_storage_state.json"
EDGE_PATH = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
EDGE_USER_DATA = Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data"


def wait_for_cdp(port: int, timeout_seconds: int = 20) -> None:
    deadline = time.time() + timeout_seconds
    last_exc: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_exc = exc
            time.sleep(0.5)
    raise RuntimeError(f"Edge CDP endpoint did not open on port {port}: {last_exc}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--profile", default="Default")
    args = parser.parse_args()

    if not EDGE_PATH.exists():
        raise SystemExit(f"Edge not found: {EDGE_PATH}")

    subprocess.Popen(
        [
            str(EDGE_PATH),
            f"--remote-debugging-port={args.port}",
            f"--user-data-dir={EDGE_USER_DATA}",
            f"--profile-directory={args.profile}",
            "https://x.com/home",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    wait_for_cdp(args.port)
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{args.port}")
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(3000)

        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(STATE_PATH))
        browser.close()

    payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    cookie_names = {cookie.get("name", "") for cookie in payload.get("cookies", [])}
    print(
        json.dumps(
            {
                "output": str(STATE_PATH),
                "cookie_count": len(payload.get("cookies", [])),
                "has_auth_token": "auth_token" in cookie_names,
                "has_ct0": "ct0" in cookie_names,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
