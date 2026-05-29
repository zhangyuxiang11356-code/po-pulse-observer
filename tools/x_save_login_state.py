# coding=utf-8
"""Open a local browser, let the user log in to X, then save Playwright storage state."""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT_DIR = Path(__file__).resolve().parents[1]
SECRETS_DIR = ROOT_DIR / "secrets"
STATE_PATH = SECRETS_DIR / "x_storage_state.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy-server", default="", help="Optional browser proxy, e.g. http://127.0.0.1:7891")
    args = parser.parse_args()

    SECRETS_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        launch_options = {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--ignore-certificate-errors",
            ],
        }
        if args.proxy_server:
            launch_options["proxy"] = {"server": args.proxy_server}

        browser = playwright.chromium.launch(
            **launch_options,
        )
        context = browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1440, "height": 1000},
        )
        page = context.new_page()
        try:
            page.goto("https://x.com/i/flow/login", wait_until="commit", timeout=15000)
        except Exception as exc:
            print(f"自动打开 X 登录页超时或失败：{exc}")
            print("浏览器会保持打开。你可以在地址栏手动输入：https://x.com/i/flow/login")

        print("")
        print("浏览器已经打开。请在弹出的窗口里登录 X。")
        print("登录成功并能看到首页后，回到这个 PowerShell 窗口按 Enter。")
        print("不要在聊天里发送密码、验证码或 cookie。")
        input("")

        context.storage_state(path=str(STATE_PATH))
        browser.close()

    print("")
    print(f"已保存 X 登录态到: {STATE_PATH}")
    print("现在可以回到 Codex 告诉我：登录好了。")


if __name__ == "__main__":
    main()
