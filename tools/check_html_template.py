#!/usr/bin/env python3
# coding: utf-8
"""Render a synthetic daily page and validate that the UI shell is healthy."""

from __future__ import annotations

import http.server
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trendradar.ai.analyzer import AIAnalysisResult
from trendradar.report.html import render_html_content


REQUIRED_TEXTS = [
    "AI Insight",
    "AI 洞察",
    "Media Watch",
    "媒体观测",
    "Hotlist Monitor",
    "热榜监测",
    "Website Monitor",
    "网站监测",
    "Source Directory",
    "信源汇总",
]


def build_sample_payload() -> dict:
    report_data = {
        "stats": [
            {
                "word": "国际涉华",
                "count": 2,
                "titles": [
                    {
                        "title": "示例热点：跨境供应链议题持续升温",
                        "source_name": "微博",
                        "time_display": "04-22 10:12",
                        "count": 2,
                        "ranks": [2, 4],
                        "rank_threshold": 10,
                        "url": "https://example.com/hotlist-1",
                        "mobile_url": "",
                        "is_new": True,
                    },
                    {
                        "title": "示例热点：国际舆论关注中国制造合作",
                        "source_name": "知乎",
                        "time_display": "04-22 10:28",
                        "count": 1,
                        "ranks": [6],
                        "rank_threshold": 10,
                        "url": "https://example.com/hotlist-2",
                        "mobile_url": "",
                        "is_new": False,
                    },
                ],
            },
            {
                "word": "宏观金融",
                "count": 1,
                "titles": [
                    {
                        "title": "示例热点：市场对新一轮政策预期升温",
                        "source_name": "财联社热门",
                        "time_display": "04-22 10:35",
                        "count": 1,
                        "ranks": [9],
                        "rank_threshold": 10,
                        "url": "https://example.com/hotlist-3",
                        "mobile_url": "",
                        "is_new": False,
                    }
                ],
            },
        ],
        "new_titles": [],
        "failed_ids": [],
        "total_new_count": 0,
    }

    rss_items = [
        {
            "word": "国际涉华",
            "count": 2,
            "titles": [
                {
                    "title": "示例网站：国际媒体追踪中企供应链布局",
                    "source_name": "美联社政治",
                    "time_display": "04-22 09:56",
                    "count": 1,
                    "ranks": [],
                    "rank_threshold": 10,
                    "url": "https://example.com/rss-1",
                    "mobile_url": "",
                    "is_new": False,
                },
                {
                    "title": "示例网站：涉华叙事在欧洲政策讨论中发酵",
                    "source_name": "BBC 国际",
                    "time_display": "04-22 10:05",
                    "count": 1,
                    "ranks": [],
                    "rank_threshold": 10,
                    "url": "https://example.com/rss-2",
                    "mobile_url": "",
                    "is_new": True,
                },
            ],
        },
        {
            "word": "科技治理",
            "count": 1,
            "titles": [
                {
                    "title": "示例网站：平台治理与出海监管出现新动向",
                    "source_name": "FT中文网 · 今日焦点",
                    "time_display": "04-22 10:18",
                    "count": 1,
                    "ranks": [],
                    "rank_threshold": 10,
                    "url": "https://example.com/rss-3",
                    "mobile_url": "",
                    "is_new": False,
                }
            ],
        },
    ]

    social_items = [
        {
            "platform": "x",
            "source_name": "@demo_watch",
            "author": "@demo_watch",
            "title": "示例社媒：跨平台讨论开始放大供应链议题",
            "content": "示例社媒：跨平台讨论开始放大供应链议题，评论区持续扩散。",
            "url": "https://example.com/social-x",
            "published_at": "2026-04-22 10:30",
            "metadata": {
                "display_name": "@demo_watch",
                "cache_generated_at": "2026-04-22T10:32:00+08:00",
            },
        },
        {
            "platform": "reddit",
            "source_name": "r/geopolitics",
            "author": "r/geopolitics",
            "title": "示例社媒：海外社区聚焦相关政策影响",
            "content": "示例社媒：海外社区聚焦相关政策影响，讨论出现明显分歧。",
            "url": "https://example.com/social-r",
            "published_at": "2026-04-22 10:22",
            "metadata": {
                "display_name": "geopolitics",
                "subreddit": "geopolitics",
                "cache_generated_at": "2026-04-22T10:31:00+08:00",
            },
        },
    ]

    standalone_data = {
        "platforms": [
            {
                "id": "weibo",
                "name": "微博热榜",
                "items": [
                    {
                        "title": "示例独立热榜：制造业外溢讨论持续升温",
                        "url": "https://example.com/standalone-hot",
                        "rank": 3,
                        "ranks": [3, 5],
                        "first_time": "09:50",
                        "last_time": "10:35",
                        "count": 2,
                    }
                ],
            }
        ],
        "rss_feeds": [
            {
                "id": "ap-politics",
                "name": "美联社政治",
                "items": [
                    {
                        "title": "示例独立网站：政策风向变化引发后续观察",
                        "url": "https://example.com/standalone-rss",
                        "published_at": "2026-04-22T10:20:00+08:00",
                        "author": "AP",
                    }
                ],
            }
        ],
        "source_catalog": {
            "hotlist": [
                {
                    "id": "weibo",
                    "name": "微博",
                    "kind": "WEB",
                    "healthy": True,
                    "status": "live_ok",
                    "last_synced": "2026-04-22T10:32:00+08:00",
                    "logo_url": "",
                },
                {
                    "id": "zhihu",
                    "name": "知乎",
                    "kind": "WEB",
                    "healthy": True,
                    "status": "live_ok",
                    "last_synced": "2026-04-22T10:28:00+08:00",
                    "logo_url": "",
                },
            ],
            "website": [
                {
                    "id": "ap-politics",
                    "name": "美联社政治",
                    "kind": "RSS",
                    "healthy": True,
                    "status": "live_ok",
                    "last_synced": "2026-04-22T10:20:00+08:00",
                    "logo_url": "",
                },
                {
                    "id": "bbc-world",
                    "name": "BBC 国际",
                    "kind": "RSS",
                    "healthy": True,
                    "status": "live_ok",
                    "last_synced": "2026-04-22T10:05:00+08:00",
                    "logo_url": "",
                },
            ],
            "media": [
                {
                    "id": "x-watch",
                    "name": "X 观察名单",
                    "kind": "SOCIAL",
                    "healthy": True,
                    "status": "live_ok",
                    "last_synced": "2026-04-22T10:32:00+08:00",
                    "logo_url": "",
                },
                {
                    "id": "reddit-watch",
                    "name": "Reddit 观察名单",
                    "kind": "SOCIAL",
                    "healthy": True,
                    "status": "live_ok",
                    "last_synced": "2026-04-22T10:31:00+08:00",
                    "logo_url": "",
                },
            ],
        },
    }

    ai_analysis = AIAnalysisResult(
        core_trends="1. 供应链与涉华合作讨论持续发酵\n2. 外部舆论对政策影响保持高关注",
        sentiment_controversy="1. 海外讨论聚焦合作与风险并存\n2. 社交平台观点分化明显",
        signals="1. 站点更新与社媒讨论在同一主题上开始汇流",
        rss_insights="1. 媒体报道补充了事件背景和政策上下文",
        outlook_strategy="1. 后续重点跟踪政策表述、企业回应和国际转载扩散",
        success=True,
        total_news=6,
        analyzed_news=6,
        max_news_limit=10,
        hotlist_count=3,
        rss_count=3,
        social_count=2,
        ai_mode="daily",
    )

    return {
        "report_data": report_data,
        "rss_items": rss_items,
        "social_items": social_items,
        "standalone_data": standalone_data,
        "ai_analysis": ai_analysis,
        "total_titles": 6,
    }


def render_sample_html() -> str:
    payload = build_sample_payload()
    html = render_html_content(
        report_data=payload["report_data"],
        total_titles=payload["total_titles"],
        mode="daily",
        rss_items=payload["rss_items"],
        rss_new_items=[],
        standalone_data=payload["standalone_data"],
        ai_analysis=payload["ai_analysis"],
        social_items=payload["social_items"],
    )
    return html


def run_static_checks(html: str) -> None:
    if len(html) < 20000:
        raise RuntimeError(f"page_too_small:{len(html)}")
    if "sourceCatalog" not in html:
        raise RuntimeError("sourceCatalog_missing")
    if 'class="ai-error"' in html or "AI 分析失败" in html:
        raise RuntimeError("ai_block_failed")
    missing = [token for token in REQUIRED_TEXTS if token not in html]
    if missing:
        raise RuntimeError("required_text_missing:" + ",".join(missing))


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def run_browser_checks(root_dir: Path) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - environment-dependent fallback
        return f"skipped:{exc.__class__.__name__}"

    errors: list[str] = []
    console_errors: list[str] = []

    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(root_dir), **kwargs)
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1200})
                page.on("pageerror", lambda exc: errors.append(str(exc)))

                def handle_console(msg) -> None:
                    if msg.type != "error":
                        return
                    text = msg.text or ""
                    ignored = (
                        "fonts.googleapis.com",
                        "fonts.gstatic.com",
                        "cdnjs.cloudflare.com",
                    )
                    if any(token in text for token in ignored):
                        return
                    console_errors.append(text)

                page.on("console", handle_console)
                page.goto(f"http://127.0.0.1:{port}/index.html", wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(1200)

                for text in ["AI 洞察", "媒体观测", "热榜监测", "网站监测", "信源汇总"]:
                    if page.locator(f"text={text}").count() == 0:
                        raise RuntimeError(f"browser_text_missing:{text}")

                if page.locator(".ai-error").count():
                    raise RuntimeError("browser_ai_error_present")

                if page.locator(".dashboard-ai .ai-grid-card").count() < 3:
                    raise RuntimeError("browser_ai_cards_missing")

                if page.locator(".pulse-static-source-card").count() == 0:
                    raise RuntimeError("browser_source_cards_missing")

                if page.locator(".pulse-static-archive-day, .pulse-static-archive-empty").count() == 0:
                    raise RuntimeError("browser_archive_shell_missing")

                if errors:
                    raise RuntimeError("page_errors:" + " | ".join(errors[:5]))
                if console_errors:
                    raise RuntimeError("console_errors:" + " | ".join(console_errors[:5]))

                browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)

    return "ok"


def main() -> int:
    html = render_sample_html()
    run_static_checks(html)

    with tempfile.TemporaryDirectory(prefix="trendradar-template-check-") as temp_dir:
        root_dir = Path(temp_dir)
        (root_dir / "index.html").write_text(html, encoding="utf-8")
        archive_dir = root_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / "manifest.json").write_text('{"days":[{"date":"2026-04-22"}]}', encoding="utf-8")
        (archive_dir / "2026-04-22.html").write_text(
            "<!DOCTYPE html><html><body><h1>Archive Day</h1></body></html>",
            encoding="utf-8",
        )
        browser_status = run_browser_checks(root_dir)

    print(f"static_length={len(html)}")
    print(f"browser_check={browser_status}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"template_check_failed={exc}", file=sys.stderr)
        raise SystemExit(1)
