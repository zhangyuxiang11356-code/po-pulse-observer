# coding=utf-8
"""
HTML 报告渲染模块

提供 HTML 格式的热点新闻报告生成功能
"""

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Callable, Tuple
from urllib.parse import quote

import yaml

from trendradar.report.helpers import html_escape
from trendradar.sources.catalog import infer_member_logo_url, load_member_profiles_cache, normalize_reddit_subreddit
from trendradar.utils.time import convert_time_for_display
from trendradar.ai.formatter import render_ai_analysis_html_rich


def render_html_content(
    report_data: Dict,
    total_titles: int,
    mode: str = "daily",
    update_info: Optional[Dict] = None,
    *,
    region_order: Optional[List[str]] = None,
    get_time_func: Optional[Callable[[], datetime]] = None,
    rss_items: Optional[List[Dict]] = None,
    rss_new_items: Optional[List[Dict]] = None,
    display_mode: str = "keyword",
    standalone_data: Optional[Dict] = None,
    ai_analysis: Optional[Any] = None,
    social_items: Optional[List[Dict]] = None,
    show_new_section: bool = True,
) -> str:
    """渲染HTML内容

    Args:
        report_data: 报告数据字典，包含 stats, new_titles, failed_ids, total_new_count
        total_titles: 新闻总数
        mode: 报告模式 ("daily", "current", "incremental")
        update_info: 更新信息（可选）
        region_order: 区域显示顺序列表
        get_time_func: 获取当前时间的函数（可选，默认使用 datetime.now）
        rss_items: RSS 统计条目列表（可选）
        rss_new_items: RSS 新增条目列表（可选）
        display_mode: 显示模式 ("keyword"=按关键词分组, "platform"=按平台分组)
        standalone_data: 独立展示区数据（可选），包含 platforms 和 rss_feeds
        ai_analysis: AI 分析结果对象（可选），AIAnalysisResult 实例
        show_new_section: 是否显示新增热点区域

    Returns:
        渲染后的 HTML 字符串
    """
    # 默认区域顺序
    default_region_order = ["hotlist", "rss", "new_items", "standalone", "ai_analysis", "social_media"]
    if region_order is None:
        region_order = default_region_order

    def load_filter_snapshot() -> Dict[str, Any]:
        config_path = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
        interests_path = Path(__file__).resolve().parents[2] / "config" / "ai_interests.txt"

        min_score = 0.85
        rss_age_days = 1
        social_age_days = 2
        topics: List[str] = []

        try:
            if config_path.exists():
                config_data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                ai_filter = config_data.get("ai_filter", {}) or {}
                rss_cfg = config_data.get("rss", {}) or {}
                social_cfg = config_data.get("social_media", {}) or {}
                freshness = rss_cfg.get("freshness_filter", {}) or {}
                min_score = float(ai_filter.get("min_score", min_score) or min_score)
                rss_age_days = int(freshness.get("max_age_days", rss_age_days) or rss_age_days)
                social_age_days = int(social_cfg.get("max_age_days", social_age_days) or social_age_days)
        except Exception:
            pass

        try:
            if interests_path.exists():
                for raw_line in interests_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    match = re.match(r"^\d+\.\s*(.+)$", line)
                    if match:
                        topics.append(match.group(1).strip())
            topics = topics[:5]
        except Exception:
            topics = []

        if not topics:
            topics = [
                "国际涉华叙事与跨境争议",
                "港澳台海与周边局势",
                "宏观经济、地产债务与市场金融争议",
                "公共安全、事故灾害与突发风险",
                "社会民生与科技治理争议",
            ]

        return {
            "min_score": min_score,
            "rss_age_days": rss_age_days,
            "social_age_days": social_age_days,
            "topics": topics,
        }

    source_catalog_json = json.dumps(
        (standalone_data or {}).get("source_catalog", {}),
        ensure_ascii=False,
    )

    favicon_svg = quote(
        """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 88 88">
  <defs>
    <linearGradient id="pulse-radar-favicon" x1="17" y1="18" x2="70" y2="71" gradientUnits="userSpaceOnUse">
      <stop stop-color="#A1E0C8"/>
      <stop offset="0.46" stop-color="#84D5D1"/>
      <stop offset="1" stop-color="#77A6E5"/>
    </linearGradient>
  </defs>
  <rect width="88" height="88" rx="22" fill="#F5F9FF"/>
  <circle cx="44" cy="44" r="30" stroke="url(#pulse-radar-favicon)" stroke-width="5.5" fill="none"/>
  <circle cx="44" cy="44" r="18" stroke="#D6E4F3" stroke-width="4" fill="none"/>
  <path d="M44 44L65 25" stroke="#365B91" stroke-width="5.5" stroke-linecap="round"/>
  <circle cx="65" cy="25" r="6" fill="#77A6E5"/>
  <path d="M22 57.5C26.2 57.5 27.7 50 31.8 50C35.2 50 36.4 56.2 40.4 56.2C45.1 56.2 46.7 45.2 50.8 45.2C54 45.2 55.3 50.8 60.5 50.8" stroke="#86D3CF" stroke-width="4.3" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
</svg>
        """.strip()
    )

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@500;700;900&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <title>Pulse Observer</title>
        <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,__PULSE_FAVICON_DATA__">
        <script defer src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js" integrity="sha512-BNaRQnYJYiPSqHHDb58B0yaPfCu+Wgds8Gp/gU33kqBtgNS4tSPHuGibyoeqMV/TJlSKda6FXzoEyYGjTe+vXA==" crossorigin="anonymous" referrerpolicy="no-referrer"></script>
        <style>
            :root {
                --page-bg: #e1e9f1;
                --page-bg-soft: #edf2f7;
                --card-bg: rgba(255, 255, 255, 0.985);
                --card-bg-strong: rgba(250, 252, 255, 0.995);
                --card-border: rgba(193, 208, 226, 0.9);
                --card-shadow: 0 18px 40px rgba(101, 122, 150, 0.12);
                --card-shadow-soft: 0 10px 24px rgba(101, 122, 150, 0.08);
                --text-main: #213148;
                --text-soft: #5e7390;
                --accent: #6887b0;
                --accent-soft: #dfe8f2;
                --green-soft: #e3edf5;
            }

            * { box-sizing: border-box; }
            body {
                font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
                margin: 0;
                padding: clamp(48px, 6vw, 96px);
                background:
                    radial-gradient(circle at 12% 14%, rgba(233, 200, 169, 0.38), transparent 22%),
                    radial-gradient(circle at 88% 8%, rgba(214, 228, 219, 0.32), transparent 18%),
                    radial-gradient(circle at 18% 88%, rgba(245, 224, 201, 0.34), transparent 24%),
                    linear-gradient(180deg, #f4eadc 0%, #f7efe4 44%, #f8f3eb 100%);
                color: var(--text-main);
                line-height: 1.6;
            }

            body.pulse-static {
                padding: 0;
                background:
                    radial-gradient(circle at 14% 10%, rgba(173, 193, 214, 0.32), transparent 18%),
                    radial-gradient(circle at 82% 18%, rgba(191, 210, 226, 0.28), transparent 24%),
                    linear-gradient(180deg, #dfe8f0 0%, #e6edf4 42%, #edf2f7 100%);
                --po-main-pad: 24px;
                --po-header-pad-x: 30px;
                --po-header-pad-y: 18px;
                --po-header-pad-bottom: 12px;
                --po-overview-width: 1320px;
                --po-overview-margin-top: 16px;
                --po-overview-gap: 15px;
                --po-stat-chart-gap: 18px;
                --po-chart-topic-gap: 18px;
                --po-stat-height: 112px;
                --po-stat-gap: 14px;
                --po-stat-pad-x: 18px;
                --po-stat-pad-y: 14px;
                --po-stat-value-size: 40px;
                --po-stat-radius: 16px;
                --po-chart-height: 78px;
                --po-chart-pad-x: 8px;
                --po-chart-pad-y: 15px;
                --po-chart-row-gap: 12px;
                --po-chart-col-gap: 16px;
                --po-chart-bar-gap: 8px;
                --po-chart-bar-height: 8px;
                --po-topic-pad-y: 10px;
                --po-topic-height: 42px;
                --po-topic-width: 126px;
                --po-topic-gap: 18px;
                --po-topic-track-pad-x: 82px;
                --po-topic-icon-size: 32px;
                --po-topic-glyph-size: 22px;
                --po-topic-speed: 100s;
                --po-panel-radius: 20px;
            }

            body.pulse-static.is-overview-active {
                height: 100vh;
                overflow: hidden;
            }

            body.pulse-static .pulse-static-sidebar {
                position: fixed;
                left: 0;
                top: 0;
                bottom: 0;
                width: 286px;
                padding: 20px 20px 28px;
                background: linear-gradient(180deg, rgba(228, 236, 245, 0.98) 0%, rgba(219, 229, 240, 0.96) 100%);
                border-right: 1px solid rgba(185, 198, 216, 0.92);
                backdrop-filter: blur(18px);
                z-index: 20;
            }

            body.pulse-static .pulse-static-brand {
                --brand-x: 0px;
                --brand-y: 0px;
                --brand-gap: 14px;
                --logo-size: 68px;
                --ring-inset: 9.7px;
                --logo-x: 0px;
                --logo-y: 0px;
                --title-size: 25px;
                --title-x: -8px;
                --title-y: 0px;
                --title-tracking: -0.07em;
                --tagline-size: 14px;
                --tagline-x: -8px;
                --tagline-y: -0.5px;
                --tagline-tracking: 0.045em;
                padding: 2px 0 28px;
                display: block;
                transform: translate(var(--brand-x), var(--brand-y));
            }

            body.pulse-static .pulse-static-brand-head {
                display: grid;
                grid-template-columns: var(--logo-size) minmax(0, 1fr);
                align-items: start;
                column-gap: var(--brand-gap);
            }

            body.pulse-static .pulse-static-brand-mark {
                position: relative;
                width: var(--logo-size);
                height: var(--logo-size);
                flex: 0 0 auto;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                transform: translate(var(--logo-x), var(--logo-y));
            }

            body.pulse-static .pulse-static-brand-mark::after {
                content: "";
                position: absolute;
                inset: 10px;
                border-radius: 999px;
                background: radial-gradient(circle, rgba(132, 213, 209, 0.22) 0%, rgba(119, 166, 229, 0.18) 48%, rgba(119, 166, 229, 0) 78%);
                opacity: 0;
                transform: scale(0.84);
                transition: opacity 220ms ease, transform 320ms ease;
                pointer-events: none;
            }

            body.pulse-static .pulse-static-brand-mark svg {
                width: var(--logo-size);
                height: var(--logo-size);
                display: block;
                transform-origin: center;
                transition: transform 260ms ease, filter 260ms ease;
            }

            body.pulse-static .pulse-static-brand-mark:hover::after {
                opacity: 1;
                transform: scale(1.12);
            }

            body.pulse-static .pulse-static-brand-mark:hover svg {
                transform: scale(1.06) rotate(-6deg);
                filter: drop-shadow(0 10px 16px rgba(79, 120, 168, 0.2));
            }

            body.pulse-static .pulse-static-title {
                margin: 0;
                white-space: nowrap;
                font-size: var(--title-size);
                font-weight: 900;
                color: #13253d;
                letter-spacing: var(--title-tracking);
                line-height: 1;
                transform: translate(var(--title-x), var(--title-y));
            }

            body.pulse-static .pulse-static-note {
                margin: 0;
                padding-left: 0;
                color: #627895;
                font-family: 'Plus Jakarta Sans', 'Microsoft YaHei', sans-serif;
                font-size: var(--tagline-size);
                line-height: 1.18;
                font-weight: 400;
                letter-spacing: var(--tagline-tracking);
                white-space: nowrap;
                transform: translate(var(--tagline-x), var(--tagline-y));
            }

            body.pulse-static .pulse-static-brand-copy {
                height: calc(var(--logo-size) - (var(--ring-inset) * 2));
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                min-width: 0;
                margin-top: var(--ring-inset);
            }

            body.pulse-static .pulse-static-nav {
                display: grid;
                gap: 10px;
            }

            body.pulse-static .pulse-static-nav a {
                display: flex;
                align-items: center;
                justify-content: space-between;
                min-height: 48px;
                padding: 0 16px;
                border-radius: 16px;
                font-size: 16px;
                font-weight: 600;
                color: #49607e;
                text-decoration: none;
                transition: all 0.18s ease;
                position: relative;
                background: rgba(240, 245, 250, 0.68);
                border: 1px solid transparent;
            }

            body.pulse-static .pulse-static-nav a:hover,
            body.pulse-static .pulse-static-nav a.is-active {
                color: #102238;
                background: rgba(255, 255, 255, 0.86);
                border-color: rgba(190, 203, 221, 0.94);
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.86);
            }

            body.pulse-static .pulse-static-nav a.is-active::after {
                content: "";
                width: 10px;
                height: 10px;
                border-radius: 999px;
                background: linear-gradient(180deg, #9ad4c7 0%, #79acd5 100%);
                box-shadow:
                    0 0 0 4px rgba(121, 172, 213, 0.16),
                    0 0 10px rgba(121, 172, 213, 0.32);
                flex: 0 0 auto;
            }

            body.pulse-static .pulse-static-main {
                margin-left: 286px;
                min-height: 100vh;
                padding: var(--po-main-pad);
                box-sizing: border-box;
            }

            body.pulse-static .container {
                max-width: none;
                margin: 0;
                border-radius: 0;
                background: transparent;
                border: none;
                box-shadow: none;
            }

            body.pulse-static.is-overview-active .container {
                height: calc(100vh - (var(--po-main-pad) * 2));
                overflow: hidden;
            }

            body.pulse-static .header {
                margin-bottom: 14px;
                padding: var(--po-header-pad-y) var(--po-header-pad-x) var(--po-header-pad-bottom);
                background:
                    radial-gradient(circle at 88% 12%, rgba(200, 217, 233, 0.58), transparent 20%),
                    linear-gradient(180deg, rgba(244,248,252,0.98) 0%, rgba(238,244,249,0.98) 100%);
                border: 1px solid rgba(186, 201, 220, 0.9);
                border-radius: 30px;
                box-shadow: 0 10px 24px rgba(104, 124, 151, 0.08);
            }

            body.pulse-static .header.is-active {
                min-height: auto;
                display: block;
            }

            body.pulse-static.is-overview-active .header.is-active {
                height: 100%;
                margin-bottom: 0;
                overflow: hidden;
                display: flex;
                flex-direction: column;
            }

            body.pulse-static .header-title {
                font-family: 'Noto Serif SC', serif;
                font-size: clamp(42px, 4.4vw, 66px);
                line-height: 1.02;
                letter-spacing: -0.04em;
                color: #172943;
                margin-bottom: 12px;
            }

            body.pulse-static .pulse-static-subtitle {
                color: #556d8a;
                font-size: 16px;
                margin: 0 0 2px;
                max-width: 760px;
                margin-left: 0;
                display: inline-flex;
                align-items: center;
                gap: 14px;
            }

            body.pulse-static .pulse-subtitle-text {
                display: inline-block;
            }

            body.pulse-static .pulse-subtitle-ornament {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 14px;
                height: 36px;
                border-radius: 6px;
                background: linear-gradient(180deg, rgba(116, 187, 168, 0.96) 0%, rgba(118, 170, 193, 0.96) 52%, rgba(123, 152, 216, 0.96) 100%);
                box-shadow: inset 0 0 0 1px rgba(255,255,255,0.7);
                flex: 0 0 auto;
            }

            body.pulse-static .header-shell {
                grid-template-columns: 1fr;
                gap: 18px;
                margin-top: 0;
            }

            body.pulse-static .filter-card {
                display: none;
            }

            body.pulse-static .save-buttons {
                top: 24px;
                right: 24px;
            }

            body.pulse-static .content {
                padding: 0;
            }

            body.pulse-static .dashboard-card,
            body.pulse-static .social-section,
            body.pulse-static .rss-section,
            body.pulse-static .hotlist-section {
                scroll-margin-top: 24px;
            }

            body.pulse-static .dashboard-grid {
                gap: 24px;
                margin-top: 24px;
            }

            body.pulse-static .dashboard-card,
            body.pulse-static .dashboard-hotlist,
            body.pulse-static .dashboard-rss,
            body.pulse-static .dashboard-ai,
            body.pulse-static .dashboard-social,
            body.pulse-static .pulse-static-sources {
                border-radius: 30px;
                border: 1px solid rgba(208, 220, 235, 0.9);
                background: rgba(255, 255, 255, 0.88);
                box-shadow: 0 20px 46px rgba(180, 194, 214, 0.13);
            }

            body.pulse-static .dashboard-ai,
            body.pulse-static .dashboard-social,
            body.pulse-static .dashboard-hotlist,
            body.pulse-static .dashboard-rss,
            body.pulse-static .pulse-static-sources {
                margin-top: 24px;
            }

            body.pulse-static .pulse-static-sources {
                margin-top: 24px;
                padding: 24px;
            }

            body.pulse-static .pulse-static-source-tabs {
                display: flex;
                flex-wrap: wrap;
                gap: 12px;
                margin-bottom: 22px;
            }

            body.pulse-static .pulse-static-source-tab {
                display: inline-flex;
                align-items: center;
                gap: 8px;
                min-height: 46px;
                padding: 0 18px;
                border-radius: 999px;
                background: rgba(234, 240, 247, 0.94);
                color: #556f8c;
                border: 1px solid rgba(199, 211, 227, 0.95);
                font-size: 15px;
                font-weight: 700;
                cursor: pointer;
                transition: all 0.18s ease;
            }

            body.pulse-static .pulse-static-source-tab.is-active {
                background: #15223b;
                color: #f6f8fc;
                box-shadow: 0 10px 24px rgba(21, 34, 59, 0.16);
                border-color: #15223b;
            }

            body.pulse-static .pulse-static-source-tab-count {
                opacity: 0.78;
                font-weight: 800;
            }

            body.pulse-static .pulse-static-sources-grid {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 18px;
            }

            body.pulse-static .pulse-static-source-card {
                padding: 18px 18px 20px;
                border-radius: 24px;
                border: 1px solid rgba(199, 212, 227, 0.95);
                background: rgba(255, 255, 255, 0.985);
                box-shadow: 0 10px 22px rgba(111, 130, 155, 0.09);
            }

            body.pulse-static .pulse-stat-card,
            body.pulse-static .pulse-filter-card,
            body.pulse-static .news-item,
            body.pulse-static .rss-item,
            body.pulse-static .social-item,
            body.pulse-static .ai-grid-card,
            body.pulse-static .pulse-static-source-card,
            body.pulse-enabled .pulse-source-card {
                transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
            }

            body.pulse-static .pulse-stat-card:hover,
            body.pulse-static .pulse-filter-card:hover,
            body.pulse-static .news-item:hover,
            body.pulse-static .rss-item:hover,
            body.pulse-static .social-item:hover,
            body.pulse-static .ai-grid-card:not(.ai-flip-card):hover,
            body.pulse-static .pulse-static-source-card:hover,
            body.pulse-enabled .pulse-source-card:hover {
                transform: translateY(-4px);
                box-shadow: 0 16px 36px rgba(96, 123, 171, 0.12);
                border-color: rgba(177, 196, 225, 0.95);
            }

            body.pulse-static .pulse-static-source-head {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
                margin-bottom: 18px;
            }

            body.pulse-static .pulse-static-source-brand {
                display: flex;
                align-items: center;
                gap: 14px;
                min-width: 0;
            }

            body.pulse-static .pulse-static-source-icon {
                width: 44px;
                height: 44px;
                border-radius: 50%;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                padding: 7px;
                box-sizing: border-box;
                background: rgba(255, 255, 255, 0.98);
                border: 1px solid rgba(214, 225, 236, 0.96);
                color: #7083a0;
                font-size: 22px;
                flex: 0 0 auto;
                overflow: hidden;
                position: relative;
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.96);
            }

            body.pulse-static .pulse-static-source-icon img {
                width: 100%;
                height: 100%;
                object-fit: contain;
                display: block;
                background: transparent;
                border-radius: 0;
            }

            body.pulse-static .pulse-static-source-icon-fallback {
                width: 100%;
                height: 100%;
                display: inline-flex;
                align-items: center;
                justify-content: center;
            }

            body.pulse-static .pulse-static-source-name {
                font-size: 16px;
                font-weight: 700;
                color: #20314c;
                line-height: 1.3;
                word-break: break-word;
            }

            body.pulse-static .pulse-static-source-status {
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 6px 12px;
                border-radius: 999px;
                background: rgba(244, 249, 244, 0.96);
                color: #627c72;
                font-size: 13px;
                font-weight: 700;
                white-space: nowrap;
            }

            body.pulse-static .pulse-static-source-status-dot {
                width: 10px;
                height: 10px;
                border-radius: 999px;
                background: #16c15d;
                flex: 0 0 auto;
            }

            body.pulse-static .pulse-static-source-card.is-unhealthy .pulse-static-source-status {
                background: rgba(255, 239, 239, 0.96);
                color: #b24a4a;
            }

            body.pulse-static .pulse-static-source-card.is-unhealthy .pulse-static-source-status-dot {
                background: #e15454;
            }

            body.pulse-static .pulse-static-source-card.is-unhealthy .pulse-static-source-icon {
                color: #e15454;
                border-color: rgba(237, 201, 201, 0.96);
                background: rgba(255, 246, 246, 0.98);
            }

            body.pulse-static .pulse-static-source-tag {
                display: inline-flex;
                align-items: center;
                min-height: 32px;
                padding: 0 12px;
                border-radius: 12px;
                background: rgba(241, 246, 252, 0.96);
                color: #4d6382;
                font-size: 12px;
                font-weight: 800;
                margin-bottom: 18px;
            }

            body.pulse-static .pulse-static-source-tag[data-kind="RSS"] {
                background: rgba(233, 242, 255, 0.98);
                color: #2e66ff;
            }

            body.pulse-static .pulse-static-source-tag[data-kind="SOCIAL"] {
                background: rgba(255, 241, 231, 0.98);
                color: #ea6a2e;
            }

            body.pulse-static .pulse-static-source-tag[data-kind="WEB"] {
                background: rgba(245, 247, 250, 0.98);
                color: #60738e;
            }

            body.pulse-static .pulse-static-source-meta,
            body.pulse-static .pulse-static-source-extra {
                font-size: 13px;
                line-height: 1.7;
                color: #70819b;
            }

            body.pulse-static .pulse-overview-shell {
                width: min(var(--po-overview-width), calc(100% - 40px));
                margin: var(--po-overview-margin-top) auto 0;
                display: grid;
                gap: 0;
                box-sizing: border-box;
                position: relative;
                transform: none;
            }

            body.pulse-static.is-overview-active .pulse-overview-shell {
                flex: 1 1 auto;
            }

            body.pulse-static .pulse-overview-shell > * {
                position: relative;
                z-index: 1;
            }

            body.pulse-static .pulse-overview-card,
            body.pulse-static .pulse-overview-stats {
                border-radius: 30px;
                border: 1px solid rgba(190, 204, 221, 0.92);
                background: linear-gradient(180deg, rgba(237,243,249,0.98) 0%, rgba(233,239,246,0.98) 100%);
                box-shadow: 0 10px 24px rgba(124, 140, 165, 0.08);
                padding: 28px;
            }

            body.pulse-static .pulse-overview-card {
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                min-height: 408px;
                padding: 36px 34px;
                background:
                    radial-gradient(circle at 84% 18%, rgba(204, 219, 235, 0.72), transparent 20%),
                    linear-gradient(180deg, rgba(239,244,249,0.98) 0%, rgba(233,239,246,0.98) 100%);
            }

            body.pulse-static .pulse-overview-eyebrow {
                display: inline-flex;
                align-items: center;
                min-height: 34px;
                padding: 0 14px;
                border-radius: 999px;
                background: rgba(223, 232, 243, 0.96);
                color: #4f6786;
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 0.08em;
                text-transform: uppercase;
            }

            body.pulse-static .pulse-overview-heading {
                font-family: 'Noto Serif SC', serif;
                font-size: clamp(30px, 3vw, 46px);
                line-height: 1.18;
                color: #1c2b45;
                margin: 18px 0 10px;
                letter-spacing: -0.04em;
            }

            body.pulse-static .pulse-overview-copy {
                color: #556c89;
                font-size: 16px;
                line-height: 1.9;
                max-width: 620px;
            }

            body.pulse-static .pulse-overview-lead {
                margin-top: 18px;
                color: #21334d;
                font-size: 20px;
                line-height: 1.7;
                font-weight: 600;
                max-width: 700px;
            }

            body.pulse-static .pulse-overview-matrix {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 14px;
                margin-top: 22px;
            }

            body.pulse-static .pulse-overview-matrix-card {
                min-height: 128px;
                padding: 18px 20px;
                border-radius: 20px;
                border: 1px solid rgba(196, 209, 224, 0.94);
                background: rgba(248, 251, 254, 0.98);
                box-shadow: 0 10px 22px rgba(111, 130, 155, 0.08);
            }

            body.pulse-static .pulse-overview-matrix-kicker {
                color: #7b8fae;
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 0.08em;
                text-transform: uppercase;
            }

            body.pulse-static .pulse-overview-matrix-title {
                margin-top: 8px;
                color: #1d2c47;
                font-size: 17px;
                font-weight: 700;
            }

            body.pulse-static .pulse-overview-matrix-copy {
                margin-top: 6px;
                color: #627894;
                font-size: 13px;
                line-height: 1.7;
            }

            body.pulse-static .pulse-overview-stats {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: var(--po-stat-gap);
                align-content: start;
                background: transparent;
                padding: 0;
                border: none;
                box-shadow: none;
                margin-bottom: var(--po-stat-chart-gap);
            }

            body.pulse-static .pulse-overview-stat {
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                padding: var(--po-stat-pad-y) var(--po-stat-pad-x);
                min-height: var(--po-stat-height);
                border-radius: var(--po-stat-radius);
                background: linear-gradient(180deg, rgba(255,255,255,0.995) 0%, rgba(248,251,254,0.995) 100%);
                border: 1px solid rgba(193, 208, 226, 0.9);
                box-shadow: 0 7px 16px rgba(107, 126, 151, 0.04), inset 0 1px 0 rgba(255,255,255,0.72);
            }

            body.pulse-static .pulse-overview-stat-label {
                color: #647a96;
                font-size: 14px;
                font-weight: 800;
                margin-bottom: 8px;
            }

            body.pulse-static .pulse-overview-stat-value {
                color: #172742;
                font-size: var(--po-stat-value-size);
                line-height: 0.98;
                font-weight: 800;
                letter-spacing: -0.05em;
            }

            body.pulse-static .pulse-overview-stat-note {
                margin-top: 10px;
                color: #5f7793;
                font-size: 11px;
                line-height: 1.35;
                font-weight: 450;
            }

            body.pulse-static .pulse-overview-chart-card {
                margin-bottom: var(--po-chart-topic-gap);
                padding: var(--po-chart-pad-y) var(--po-chart-pad-x);
                border-radius: var(--po-panel-radius);
                border: 1px solid rgba(193, 208, 226, 0.9);
                background:
                    linear-gradient(180deg, rgba(255,255,255,0.9), rgba(242,248,252,0.92)),
                    radial-gradient(circle at 90% 12%, rgba(132, 213, 209, 0.16), transparent 26%);
                box-shadow: 0 12px 26px rgba(107, 126, 151, 0.06);
            }

            body.pulse-static .pulse-overview-chart {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                column-gap: var(--po-chart-col-gap);
                row-gap: var(--po-chart-row-gap);
                align-content: center;
                min-height: var(--po-chart-height);
            }

            body.pulse-static .pulse-overview-chart-row {
                display: grid;
                grid-template-columns: 78px minmax(150px, 1fr) 36px;
                gap: var(--po-chart-bar-gap);
                align-items: center;
            }

            body.pulse-static .pulse-overview-chart-label {
                color: #516b89;
                font-size: 13px;
                font-weight: 850;
                line-height: 1;
                text-align: right;
                white-space: nowrap;
            }

            body.pulse-static .pulse-overview-chart-track {
                height: var(--po-chart-bar-height);
                border-radius: 999px;
                background: #e3edf6;
                overflow: hidden;
                box-shadow: inset 0 1px 1px rgba(88, 112, 141, 0.08);
            }

            body.pulse-static .pulse-overview-chart-fill {
                position: relative;
                display: block;
                height: 100%;
                border-radius: inherit;
                background: linear-gradient(90deg, #84d5d1 0%, #77a6e5 100%);
                overflow: hidden;
                animation: pulseOverviewBarSettle 760ms ease both;
            }

            body.pulse-static .pulse-overview-chart-fill::after {
                content: "";
                position: absolute;
                inset: 0;
                background: linear-gradient(90deg, transparent, rgba(255,255,255,0.48), transparent);
                transform: translateX(-120%);
                animation: pulseOverviewBarSweep 980ms cubic-bezier(.2,.72,.22,1) both;
            }

            body.pulse-static .pulse-overview-chart-row:nth-child(1) .pulse-overview-chart-fill::after { animation-delay: 80ms; }
            body.pulse-static .pulse-overview-chart-row:nth-child(2) .pulse-overview-chart-fill::after { animation-delay: 150ms; }
            body.pulse-static .pulse-overview-chart-row:nth-child(3) .pulse-overview-chart-fill::after { animation-delay: 220ms; }
            body.pulse-static .pulse-overview-chart-row:nth-child(4) .pulse-overview-chart-fill::after { animation-delay: 290ms; }
            body.pulse-static .pulse-overview-chart-row:nth-child(5) .pulse-overview-chart-fill::after { animation-delay: 360ms; }
            body.pulse-static .pulse-overview-chart-row:nth-child(6) .pulse-overview-chart-fill::after { animation-delay: 430ms; }

            body.pulse-static .pulse-overview-chart-count {
                color: #6f879f;
                font-style: normal;
                font-size: 12px;
                font-weight: 900;
                line-height: 1;
                text-align: left;
                white-space: nowrap;
            }

            @keyframes pulseOverviewBarSettle {
                from { opacity: 0.72; }
                to { opacity: 1; }
            }

            @keyframes pulseOverviewBarSweep {
                from { transform: translateX(-120%); }
                to { transform: translateX(140%); }
            }

            body.pulse-static .pulse-topic-carousel {
                padding: var(--po-topic-pad-y) 0;
                position: relative;
                overflow: hidden;
                border-radius: var(--po-panel-radius);
                border: 1px solid rgba(193, 208, 226, 0.9);
                background: rgba(255,255,255,0.62);
                box-shadow: 0 12px 26px rgba(107, 126, 151, 0.06);
            }

            body.pulse-static .pulse-topic-track-shell {
                position: relative;
                overflow: hidden;
                mask-image: linear-gradient(90deg, transparent 0, #000 18px, #000 calc(100% - 18px), transparent 100%);
                -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 18px, #000 calc(100% - 18px), transparent 100%);
            }

            body.pulse-static .pulse-topic-track-shell::before,
            body.pulse-static .pulse-topic-track-shell::after {
                content: "";
                position: absolute;
                top: 0;
                bottom: 0;
                width: 28px;
                z-index: 2;
                pointer-events: none;
            }

            body.pulse-static .pulse-topic-track-shell::before {
                left: 0;
                background: linear-gradient(90deg, rgba(247,251,255,0.94) 0%, rgba(247,251,255,0));
            }

            body.pulse-static .pulse-topic-track-shell::after {
                right: 0;
                background: linear-gradient(270deg, rgba(247,251,255,0.94) 0%, rgba(247,251,255,0));
            }

            body.pulse-static .pulse-topic-track {
                display: flex;
                width: max-content;
                gap: var(--po-topic-gap);
                padding: 0 var(--po-topic-track-pad-x);
                animation: pulseTopicMarquee var(--po-topic-speed) linear infinite;
                will-change: transform;
            }

            body.pulse-static .pulse-topic-track-shell:hover .pulse-topic-track {
                animation-play-state: paused;
            }

            body.pulse-static .pulse-topic-pill {
                flex: 0 0 auto;
                min-height: var(--po-topic-height);
                min-width: var(--po-topic-width);
                padding: 0 18px 0 10px;
                border-radius: 999px;
                display: inline-flex;
                align-items: center;
                justify-content: flex-start;
                gap: 8px;
                color: #3e5874;
                background: rgba(255, 255, 255, 0.82);
                border: 1px solid rgba(188, 204, 222, 0.82);
                box-shadow: 0 7px 14px rgba(107, 126, 151, 0.035), inset 0 1px 0 rgba(255,255,255,0.68);
                font-size: 14px;
                font-weight: 850;
                line-height: 1;
                white-space: nowrap;
            }

            body.pulse-static .pulse-topic-pill.is-hot {
                color: #163452;
                background: rgba(255, 255, 255, 0.9);
                border-color: rgba(149, 190, 207, 0.72);
            }

            body.pulse-static .pulse-topic-pill::before {
                content: "";
                width: var(--po-topic-icon-size);
                height: var(--po-topic-icon-size);
                border-radius: 50%;
                border: none;
                background: var(--topic-glyph) center / var(--po-topic-glyph-size) var(--po-topic-glyph-size) no-repeat;
                box-shadow: none;
                flex: 0 0 auto;
            }

            body.pulse-static .pulse-overview-status-band {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 18px;
                place-items: center;
                min-height: 68px;
                padding: 18px 16px 8px;
            }

            body.pulse-static .pulse-overview-status-item {
                min-width: 0;
                display: grid;
                grid-template-columns: auto 1fr;
                grid-template-rows: auto auto;
                gap: 5px 10px;
                align-items: center;
                justify-content: center;
                width: max-content;
                max-width: 100%;
                color: #49627f;
                font-size: 11px;
                line-height: 1.2;
            }

            body.pulse-static .pulse-overview-status-dot {
                grid-column: 1;
                grid-row: 1;
                width: 10px;
                height: 10px;
                border-radius: 50%;
                background: #2eb8bd;
                box-shadow: 0 0 0 4px rgba(46, 184, 189, 0.12);
            }

            body.pulse-static .pulse-overview-status-label {
                color: #6a8099;
                font-size: 10px;
                font-weight: 850;
                letter-spacing: 0.06em;
                text-transform: uppercase;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }

            body.pulse-static .pulse-overview-status-value {
                grid-column: 1 / -1;
                grid-row: 2;
                color: #18324f;
                font-size: 15px;
                font-weight: 900;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }

            body.pulse-static .pulse-topic-pill[data-icon="globe"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.1' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='8'/%3E%3Cpath d='M4 12h16M12 4c2.2 2.4 3.3 5.1 3.3 8s-1.1 5.6-3.3 8M12 4c-2.2 2.4-3.3 5.1-3.3 8s1.1 5.6 3.3 8'/%3E%3Cpath d='M7 15.5h4l1.2-3.2 1.6 4.7 1.2-2.6h2' stroke='%230c9fbd'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="shield"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.15' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 3l7 3v5.4c0 4.6-2.8 7.6-7 9.6-4.2-2-7-5-7-9.6V6l7-3z'/%3E%3Cpath d='M12 8v5' stroke='%230c9fbd'/%3E%3Cpath d='M12 16h.01' stroke='%230c9fbd'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="dialogue"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 6.5h9a4 4 0 014 4v.5a4 4 0 01-4 4H9l-4 3v-3a4 4 0 01-3-3.8v-1.2a4 4 0 014-4z'/%3E%3Cpath d='M9 9.5h6M9 12.5h4' stroke='%230c9fbd'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="people"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='8' r='3'/%3E%3Cpath d='M5 19a7 7 0 0114 0'/%3E%3Ccircle cx='5.5' cy='10.5' r='2' stroke='%230c9fbd'/%3E%3Ccircle cx='18.5' cy='10.5' r='2' stroke='%230c9fbd'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="chart"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.15' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M4 19h16M6 16l4-4 3 3 5-7' stroke='%230c9fbd'/%3E%3Cpath d='M16 8h2v2' stroke='%230c9fbd'/%3E%3Cpath d='M7 18v-3M12 18v-5M17 18v-8'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="chip"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='7' y='7' width='10' height='10' rx='2'/%3E%3Crect x='10' y='10' width='4' height='4' rx='1' stroke='%230c9fbd'/%3E%3Cpath d='M4 9h3M4 15h3M17 9h3M17 15h3M9 4v3M15 4v3M9 17v3M15 17v3'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="book"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M4 5.5c3.2-.8 5.8-.3 8 1.5v12c-2.2-1.8-4.8-2.3-8-1.5v-12zM20 5.5c-3.2-.8-5.8-.3-8 1.5v12c2.2-1.8 4.8-2.3 8-1.5v-12z'/%3E%3Cpath d='M12 7v12' stroke='%230c9fbd'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="risk"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 4l8 14H4L12 4z'/%3E%3Cpath d='M12 9v4M12 16h.01' stroke='%230c9fbd'/%3E%3Cpath d='M5 7l3 2M19 7l-3 2' stroke='%230c9fbd'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="wave"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='2.2'/%3E%3Cpath d='M8 12a4 4 0 018 0M5 12a7 7 0 0114 0M2.5 12a9.5 9.5 0 0119 0' stroke='%230c9fbd'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="strait"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M7 4c-2 2-2 5 0 7s2 5 0 9M17 4c2 2 2 5 0 7s-2 5 0 9'/%3E%3Cpath d='M10 10h4M10 14h4' stroke='%230c9fbd'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="policy"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M6 4h9l3 3v13H6V4zM15 4v4h3'/%3E%3Cpath d='M8.5 11h7M8.5 15h7M11 10v2M14 14v2' stroke='%230c9fbd'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="govern"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 18h14M7 9h10M8 18v-7M12 18v-7M16 18v-7M6 9l6-4 6 4'/%3E%3Cpath d='M4 20h16' stroke='%230c9fbd'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="media"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 20V9M8 20h8M9 9a3 3 0 016 0'/%3E%3Cpath d='M6 11a6 6 0 0112 0M3.5 12a8.5 8.5 0 0117 0' stroke='%230c9fbd'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="spark"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%230c9fbd' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z'/%3E%3Cpath d='M7 18c3 1.8 7 1.8 10 0M8.5 21c2.2.8 4.8.8 7 0' stroke='%23365b91'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="lock"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 3l7 3v5.5c0 4.3-2.7 7.2-7 9.5-4.3-2.3-7-5.2-7-9.5V6l7-3z'/%3E%3Crect x='8.5' y='11' width='7' height='5.5' rx='1.2' stroke='%230c9fbd'/%3E%3Cpath d='M10 11V9.5a2 2 0 014 0V11' stroke='%230c9fbd'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="alert"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 4l9 16H3L12 4z'/%3E%3Cpath d='M12 10v4M12 17h.01' stroke='%230c9fbd'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="med"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%230c9fbd' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M10 4h4v6h6v4h-6v6h-4v-6H4v-4h6V4z'/%3E%3Cpath d='M15 17c2.8-.4 4.6-2 5-5-3 .4-4.6 2.2-5 5z' stroke='%23365b91'/%3E%3C/svg%3E"); }
            body.pulse-static .pulse-topic-pill[data-icon="map"] { --topic-glyph: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23365b91' stroke-width='2.05' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='8'/%3E%3Cpath d='M15.5 8.5l-2.2 5.1-5 2.1 2.1-5 5.1-2.2z' stroke='%230c9fbd'/%3E%3Cpath d='M12 4v2M12 18v2M4 12h2M18 12h2'/%3E%3C/svg%3E"); }

            @keyframes pulseTopicMarquee {
                from { transform: translateX(0); }
                to { transform: translateX(-50%); }
            }

            body.pulse-static .pulse-live-tuner {
                position: fixed;
                right: 18px;
                top: 18px;
                width: 360px;
                z-index: 9999;
                overflow: auto;
                padding: 16px;
                max-height: calc(100vh - 36px);
                border-radius: 20px;
                border: 1px solid rgba(177, 196, 216, 0.96);
                background:
                    radial-gradient(circle at 92% 4%, rgba(132, 213, 209, 0.18), transparent 28%),
                    linear-gradient(180deg, rgba(248,251,255,0.98), rgba(235,242,249,0.98));
                box-shadow: 0 24px 60px rgba(45, 67, 94, 0.18);
                backdrop-filter: blur(18px);
            }

            body.pulse-static .pulse-live-tuner-toolbar {
                position: sticky;
                top: -16px;
                z-index: 3;
                margin: -16px -16px 12px;
                padding: 14px 16px 10px;
                border-bottom: 1px solid rgba(193, 208, 226, 0.78);
                background:
                    radial-gradient(circle at 92% 4%, rgba(132, 213, 209, 0.2), transparent 32%),
                    linear-gradient(180deg, rgba(248,251,255,0.98), rgba(239,246,252,0.96));
                box-shadow: 0 12px 26px rgba(75, 101, 130, 0.1);
                backdrop-filter: blur(18px);
            }

            body.pulse-static .pulse-live-tuner-head {
                display: grid;
                grid-template-columns: 1fr auto;
                gap: 10px;
                align-items: start;
                margin: 0 0 10px;
                cursor: grab;
                user-select: none;
                touch-action: none;
            }

            body.pulse-static .pulse-live-tuner-head:active {
                cursor: grabbing;
            }

            body.pulse-static .pulse-live-tuner h2 {
                margin: 0;
                color: #102238;
                font-size: 20px;
                line-height: 1.2;
                letter-spacing: -0.04em;
            }

            body.pulse-static .pulse-live-tuner p {
                margin: 8px 0 14px;
                color: #617995;
                font-size: 12px;
                line-height: 1.65;
            }

            body.pulse-static .pulse-live-tuner-handle {
                flex: 0 0 auto;
                min-width: 48px;
                min-height: 30px;
                border-radius: 10px;
                border: 1px solid rgba(170, 190, 211, 0.92);
                background: rgba(255,255,255,0.84);
                color: #355a7d;
                font-size: 12px;
                font-weight: 900;
                cursor: grab;
            }

            body.pulse-static .pulse-live-tuner-presets {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 8px;
                margin: 0 0 8px;
            }

            body.pulse-static .pulse-live-tuner-presets button {
                min-height: 34px;
                border-radius: 10px;
                font-size: 12px;
            }

            body.pulse-static .pulse-live-tuner-presets button.is-active {
                border-color: rgba(36, 143, 184, 0.72);
                background: linear-gradient(180deg, rgba(231,248,251,0.98), rgba(211,236,247,0.96));
                color: #0e5572;
                box-shadow: inset 0 0 0 1px rgba(255,255,255,0.85);
            }

            body.pulse-static .pulse-live-tuner-status {
                min-height: 18px;
                margin: 0;
                color: #1d6d88;
                font-size: 12px;
                font-weight: 900;
            }

            body.pulse-static .pulse-live-tuner-group {
                margin-bottom: 12px;
                padding: 12px;
                border-radius: 16px;
                border: 1px solid rgba(193, 208, 226, 0.9);
                background: rgba(255,255,255,0.78);
                box-shadow: 0 8px 18px rgba(107, 126, 151, 0.045);
            }

            body.pulse-static .pulse-live-tuner-title {
                margin-bottom: 8px;
                color: #213a5a;
                font-size: 13px;
                font-weight: 900;
            }

            body.pulse-static .pulse-live-tuner-control {
                display: grid;
                grid-template-columns: 1fr auto;
                gap: 6px 10px;
                align-items: center;
                margin: 9px 0;
            }

            body.pulse-static .pulse-live-tuner-control label {
                color: #4f6786;
                font-size: 12px;
                font-weight: 800;
            }

            body.pulse-static .pulse-live-tuner-control output {
                color: #17304e;
                font-size: 11px;
                font-weight: 900;
                font-variant-numeric: tabular-nums;
            }

            body.pulse-static .pulse-live-tuner-control input {
                grid-column: 1 / -1;
                width: 100%;
                accent-color: #72a9df;
            }

            body.pulse-static .pulse-live-tuner-actions {
                display: flex;
                gap: 8px;
                position: sticky;
                bottom: -16px;
                padding: 12px 0 16px;
                background: linear-gradient(180deg, transparent, rgba(239,246,252,0.98) 30%);
            }

            body.pulse-static .pulse-live-tuner button {
                flex: 1;
                min-height: 36px;
                border-radius: 12px;
                border: 1px solid rgba(170, 190, 211, 0.92);
                background: rgba(255,255,255,0.88);
                color: #203956;
                font-weight: 900;
                cursor: pointer;
            }

            body.pulse-static .pulse-live-tuner pre {
                margin: 10px 0 0;
                max-height: 210px;
                overflow: auto;
                padding: 10px;
                border-radius: 14px;
                border: 1px solid rgba(193, 208, 226, 0.9);
                background: #f8fbff;
                color: #2f4b68;
                font-size: 11px;
                line-height: 1.5;
                white-space: pre-wrap;
            }

            body.pulse-static .pulse-filter-card {
                position: relative;
                overflow: hidden;
                border-radius: 26px;
                border: 1px solid rgba(193, 208, 226, 0.9);
                background: linear-gradient(180deg, rgba(255,255,255,0.995) 0%, rgba(248,251,254,0.995) 100%);
                box-shadow: 0 6px 16px rgba(107, 126, 151, 0.05);
                padding: 20px 24px;
            }

            body.pulse-static .pulse-filter-title {
                color: #4f6786;
                font-size: 14px;
                font-weight: 800;
                letter-spacing: 0.06em;
                text-transform: uppercase;
            }

            body.pulse-static .pulse-filter-pills {
                position: relative;
                z-index: 1;
                display: grid;
                grid-template-columns: repeat(9, minmax(0, 1fr));
                gap: 14px 16px;
                justify-content: stretch;
                align-items: center;
            }

            body.pulse-static .pulse-filter-pill {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                min-height: 30px;
                padding: 0 12px;
                border-radius: 999px;
                background: linear-gradient(180deg, rgba(252,254,255,0.995) 0%, rgba(245,249,253,0.99) 100%);
                border: 1px solid rgba(200, 213, 228, 0.94);
                color: #48617d;
                font-size: 12px;
                font-weight: 700;
                white-space: nowrap;
            }

            body.pulse-static .pulse-overview-radar {
                position: absolute;
                right: -18px;
                bottom: -28px;
                width: 320px;
                height: 142px;
                pointer-events: none;
                z-index: 0;
                opacity: 0.72;
            }

            body.pulse-static .pulse-overview-radar-floor {
                position: absolute;
                inset: 0;
                border-radius: 28px;
                background:
                    linear-gradient(180deg, rgba(238, 245, 251, 0.02), rgba(232, 239, 247, 0.18)),
                    radial-gradient(circle at 74% 106%, rgba(124, 214, 210, 0.16), transparent 28%);
            }

            body.pulse-static .pulse-overview-radar-floor::before {
                content: "";
                position: absolute;
                width: 410px;
                height: 410px;
                left: 30%;
                bottom: -324px;
                border-radius: 50%;
                border: 1px solid rgba(136, 164, 189, 0.16);
                box-shadow:
                    0 0 0 44px rgba(136, 164, 189, 0.08),
                    0 0 0 88px rgba(136, 164, 189, 0.05),
                    0 0 0 132px rgba(136, 164, 189, 0.03);
            }

            body.pulse-static .pulse-overview-radar-floor::after {
                content: "";
                position: absolute;
                inset: 0;
                background-image:
                    linear-gradient(rgba(146, 171, 196, 0.08) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(146, 171, 196, 0.05) 1px, transparent 1px);
                background-size: 100% 18px, 36px 100%;
                opacity: 0.34;
                mask-image: linear-gradient(180deg, transparent 0%, rgba(0, 0, 0, 0.68) 44%, rgba(0, 0, 0, 0.92) 100%);
            }

            body.pulse-static .pulse-overview-radar-sweep {
                position: absolute;
                width: 310px;
                height: 310px;
                left: 50%;
                bottom: -242px;
                transform-origin: 0% 100%;
                background: linear-gradient(52deg, transparent 16%, rgba(123, 214, 210, 0.08) 38%, rgba(123, 214, 210, 0.32) 58%, transparent 76%);
                clip-path: polygon(0% 100%, 16% 0%, 100% 0%, 100% 100%);
                filter: blur(2px);
                animation: pulseOverviewRadarSweep 8.2s linear infinite;
            }

            body.pulse-static .pulse-overview-radar-trace {
                position: absolute;
                left: 56%;
                bottom: 30%;
                width: 7px;
                height: 7px;
                border-radius: 50%;
                background: rgba(123, 214, 210, 0.78);
                box-shadow:
                    76px -18px 0 0 rgba(123, 214, 210, 0.26),
                    152px -44px 0 0 rgba(107, 144, 216, 0.2),
                    214px -26px 0 0 rgba(123, 214, 210, 0.16);
                animation: pulseOverviewRadarTrace 3.8s ease-in-out infinite;
            }

            @keyframes pulseOverviewRadarSweep {
                0% { transform: rotate(-28deg); opacity: 0.14; }
                50% { transform: rotate(36deg); opacity: 1; }
                100% { transform: rotate(-28deg); opacity: 0.14; }
            }

            @keyframes pulseOverviewRadarTrace {
                0%, 100% { opacity: 0.36; transform: scale(0.92); }
                50% { opacity: 1; transform: scale(1.14); }
            }

            body.pulse-static .content {
                display: flex;
                flex-direction: column;
                gap: 24px;
                padding: 0;
            }

            body.pulse-static.pulse-static-booting .pulse-static-main {
                opacity: 0;
                pointer-events: none;
            }

            body.pulse-static.pulse-static-booting .content {
                opacity: 0;
                pointer-events: none;
                min-height: 420px;
            }

            body.pulse-static.pulse-static-booting .save-buttons {
                visibility: hidden;
            }

            body.pulse-static .pulse-panel {
                display: none;
                scroll-margin-top: 24px;
                padding: 22px;
                border-radius: 30px;
                border: 1px solid rgba(178, 194, 212, 0.86);
                background: rgba(235, 242, 248, 0.96);
                box-shadow: 0 18px 42px rgba(104, 124, 151, 0.12);
            }

            body.pulse-static #ai-insight.pulse-panel {
                background:
                    radial-gradient(circle at 91% 12%, rgba(145, 195, 221, 0.10), transparent 18%),
                    linear-gradient(180deg, rgba(239,244,249,0.98) 0%, rgba(234,240,246,0.98) 100%);
                border-color: rgba(178, 194, 212, 0.86);
            }

            body.pulse-static #media.pulse-panel {
                background:
                    radial-gradient(circle at 91% 12%, rgba(135, 192, 181, 0.10), transparent 18%),
                    linear-gradient(180deg, rgba(239,244,249,0.98) 0%, rgba(234,240,246,0.98) 100%);
                border-color: rgba(178, 194, 212, 0.86);
            }

            body.pulse-static #hotlist.pulse-panel {
                background:
                    radial-gradient(circle at 91% 12%, rgba(129, 179, 213, 0.10), transparent 18%),
                    linear-gradient(180deg, rgba(239,244,249,0.98) 0%, rgba(234,240,246,0.98) 100%);
                border-color: rgba(178, 194, 212, 0.86);
            }

            body.pulse-static #website.pulse-panel {
                background:
                    radial-gradient(circle at 91% 12%, rgba(113, 167, 205, 0.09), transparent 18%),
                    linear-gradient(180deg, rgba(239,244,249,0.98) 0%, rgba(234,240,246,0.98) 100%);
                border-color: rgba(178, 194, 212, 0.86);
            }

            body.pulse-static .pulse-panel.is-active {
                display: block;
            }

            body.pulse-static .header {
                display: none;
            }

            body.pulse-static .header.is-active {
                display: block;
            }

            body.pulse-static .pulse-panel-head {
                display: flex;
                align-items: flex-end;
                justify-content: space-between;
                gap: 18px;
                margin-bottom: 18px;
            }

            body.pulse-static .pulse-panel-copy {
                flex: 1 1 auto;
                min-width: 0;
            }

            body.pulse-static .pulse-panel-kicker {
                color: #617995;
                display: inline-flex;
                align-items: center;
                gap: 8px;
                font-size: 14px;
                font-weight: 800;
                letter-spacing: 0.05em;
                line-height: 1;
                text-transform: uppercase;
            }

            body.pulse-static .pulse-panel-copy {
                display: flex;
                align-items: center;
                gap: 16px;
                min-width: 0;
                flex-wrap: wrap;
            }

            body.pulse-static .pulse-panel-copy::after {
                content: "";
                width: 1px;
                align-self: stretch;
                min-height: 22px;
                background: linear-gradient(180deg, rgba(139, 159, 186, 0.18) 0%, rgba(139, 159, 186, 0.82) 18%, rgba(139, 159, 186, 0.82) 82%, rgba(139, 159, 186, 0.18) 100%);
                flex: 0 0 auto;
                order: 2;
            }

            body.pulse-static #ai-insight .pulse-panel-kicker::before {
                content: "";
                width: 22px;
                height: 22px;
                display: inline-block;
                flex: 0 0 auto;
                background: center / contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none'%3E%3Cpath d='M5.2 6.2L9.4 10M9.4 10L14.8 5.3M9.4 10L14.6 14.6' stroke='%236E86A6' stroke-width='1.5' stroke-linecap='round'/%3E%3Ccircle cx='5.2' cy='6.2' r='1.5' fill='%236E86A6'/%3E%3Ccircle cx='14.8' cy='5.3' r='1.5' fill='%236E86A6'/%3E%3Ccircle cx='14.6' cy='14.6' r='1.5' fill='%236E86A6'/%3E%3Ccircle cx='9.4' cy='10' r='2.2' fill='%238FC7E8'/%3E%3C/svg%3E");
            }

            body.pulse-static #media .pulse-panel-kicker::before {
                content: "";
                width: 22px;
                height: 22px;
                display: inline-block;
                flex: 0 0 auto;
                background: center / contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none'%3E%3Cpath d='M3.5 5.4C3.5 4.18 4.48 3.2 5.7 3.2H11.3C12.52 3.2 13.5 4.18 13.5 5.4V8.05C13.5 9.27 12.52 10.25 11.3 10.25H8.55L5.6 12.45V10.25H5.7C4.48 10.25 3.5 9.27 3.5 8.05V5.4Z' fill='%236E86A6'/%3E%3Cpath d='M8.15 10.95C8.15 9.95 8.96 9.15 9.95 9.15H14.25C15.24 9.15 16.05 9.95 16.05 10.95V13.25C16.05 14.24 15.24 15.05 14.25 15.05H12.7L10.2 16.85V15.05H9.95C8.96 15.05 8.15 14.24 8.15 13.25V10.95Z' fill='%2389BBA8'/%3E%3Cpath d='M5.9 5.9H10.95M5.9 7.6H9.85M10.35 11.65H13.8M10.35 13.2H12.9' stroke='white' stroke-width='1.15' stroke-linecap='round'/%3E%3Ccircle cx='14.7' cy='5' r='1.45' fill='%238FC7E8'/%3E%3C/svg%3E");
            }

            body.pulse-static #hotlist .pulse-panel-kicker::before {
                content: "";
                width: 22px;
                height: 22px;
                display: inline-block;
                flex: 0 0 auto;
                background: center / contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none'%3E%3Crect x='3' y='11.5' width='3' height='5.5' rx='1.2' fill='%238FC7E8'/%3E%3Crect x='8.5' y='8' width='3' height='9' rx='1.2' fill='%236E86A6'/%3E%3Crect x='14' y='4.5' width='3' height='12.5' rx='1.2' fill='%2389BBA8'/%3E%3C/svg%3E");
            }

            body.pulse-static #website .pulse-panel-kicker::before {
                content: "";
                width: 22px;
                height: 22px;
                display: inline-block;
                flex: 0 0 auto;
                background: center / contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none'%3E%3Cpath d='M5.2 3.5H12.9L15.8 6.4V15.4C15.8 16 15.3 16.5 14.7 16.5H5.2C4.6 16.5 4.1 16 4.1 15.4V4.6C4.1 4 4.6 3.5 5.2 3.5Z' stroke='%236E86A6' stroke-width='1.45'/%3E%3Cpath d='M12.7 3.7V6.5H15.5' stroke='%238FC7E8' stroke-width='1.45' stroke-linecap='round' stroke-linejoin='round'/%3E%3Cpath d='M7 9.2H13.2M7 12H11.7' stroke='%2389BBA8' stroke-width='1.35' stroke-linecap='round'/%3E%3C/svg%3E");
            }

            body.pulse-static #sources .pulse-panel-kicker::before {
                content: "";
                width: 22px;
                height: 22px;
                display: inline-block;
                flex: 0 0 auto;
                background: center / contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none'%3E%3Crect x='4.1' y='4.2' width='11.8' height='11.6' rx='2.1' stroke='%236E86A6' stroke-width='1.45'/%3E%3Ccircle cx='6.95' cy='7.45' r='1.1' fill='%238FC7E8'/%3E%3Ccircle cx='6.95' cy='10.15' r='1.1' fill='%2389BBA8'/%3E%3Ccircle cx='6.95' cy='12.85' r='1.1' fill='%236E86A6'/%3E%3Cpath d='M9.3 7.45H13.3M9.3 10.15H13.9M9.3 12.85H12.6' stroke='%236E86A6' stroke-width='1.3' stroke-linecap='round'/%3E%3C/svg%3E");
            }

            body.pulse-static #archive .pulse-panel-kicker::before {
                content: "";
                width: 22px;
                height: 22px;
                display: inline-block;
                flex: 0 0 auto;
                background: center / contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20' fill='none'%3E%3Crect x='4.15' y='4.7' width='11.7' height='10.9' rx='2' stroke='%236E86A6' stroke-width='1.45'/%3E%3Cpath d='M7 3.65V5.55M13 3.65V5.55' stroke='%238FC7E8' stroke-width='1.45' stroke-linecap='round'/%3E%3Cpath d='M4.85 7.75H15.15' stroke='%2389BBA8' stroke-width='1.3' stroke-linecap='round'/%3E%3Ccircle cx='10' cy='11.2' r='2.15' stroke='%236E86A6' stroke-width='1.25'/%3E%3Cpath d='M10 9.95V11.2L11.1 11.95' stroke='%236E86A6' stroke-width='1.25' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
            }

            body.pulse-static .pulse-panel-desc {
                margin-top: 0;
                color: #596f8b;
                font-size: 14px;
                max-width: 68ch;
                line-height: 1.75;
                flex: 1 1 420px;
                min-width: min(100%, 280px);
                order: 3;
            }

            body.pulse-static .pulse-panel-meta {
                color: #5f7893;
                font-size: 13px;
                font-weight: 700;
                white-space: nowrap;
            }

            body.pulse-static .pulse-panel-body > .dashboard-card,
            body.pulse-static .pulse-panel-body > .pulse-static-sources {
                margin-top: 0;
                border: none;
                box-shadow: none;
                background: transparent;
                padding: 0;
            }

            body.pulse-static .pulse-panel-body > .dashboard-card .dashboard-card-header,
            body.pulse-static .pulse-panel-body > .pulse-static-sources .dashboard-card-header {
                display: none;
            }

            body.pulse-static .dashboard-ai .ai-section-header,
            body.pulse-static .dashboard-social .rss-section-header,
            body.pulse-static .dashboard-rss .rss-section-header {
                display: none !important;
            }

            body.pulse-static .dashboard-grid {
                display: none !important;
            }

            body.pulse-static .pulse-static-source-card {
                min-height: 188px;
            }

            @media (max-width: 1500px) {
                body.pulse-static .pulse-overview-shell {
                    width: min(1180px, calc(100% - 32px));
                    gap: 0;
                }

                body.pulse-static .pulse-overview-stats {
                    gap: var(--po-stat-gap);
                }

                body.pulse-static .pulse-overview-stat {
                    min-height: var(--po-stat-height);
                    padding: var(--po-stat-pad-y) var(--po-stat-pad-x);
                }

                body.pulse-static .pulse-overview-stat-value {
                    font-size: var(--po-stat-value-size);
                }

                body.pulse-static .pulse-filter-pills {
                    grid-template-columns: repeat(6, minmax(0, 1fr));
                    gap: 12px 14px;
                }

                body.pulse-static .pulse-filter-pill {
                    font-size: 11px;
                    padding: 0 10px;
                }

                body.pulse-static .pulse-overview-radar {
                    right: -30px;
                    bottom: -34px;
                    width: 280px;
                    height: 122px;
                    opacity: 0.58;
                }
            }

            @media (max-width: 1250px) {
                body.pulse-static .pulse-static-main {
                    padding: 18px;
                }

                body.pulse-static .header {
                    padding: 16px 20px 10px;
                }

                body.pulse-static .pulse-overview-shell {
                    width: min(1040px, calc(100% - 16px));
                }

                body.pulse-static .pulse-overview-stat {
                    min-height: var(--po-stat-height);
                    padding: var(--po-stat-pad-y) var(--po-stat-pad-x);
                }

                body.pulse-static .pulse-overview-stat-value {
                    font-size: var(--po-stat-value-size);
                }

                body.pulse-static .pulse-overview-stat-note {
                    font-size: 12px;
                }
            }

            @media (max-width: 1100px) {
                body.pulse-static .pulse-static-sidebar {
                    position: relative;
                    width: auto;
                    height: auto;
                    min-height: auto;
                    border-right: none;
                    border-bottom: 1px solid rgba(205, 217, 232, 0.9);
                }

                body.pulse-static .pulse-static-main {
                    margin-left: 0;
                }

                body.pulse-static .pulse-overview-shell {
                    grid-template-columns: 1fr;
                }

                body.pulse-static .pulse-overview-stats {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }

                body.pulse-static .pulse-overview-status-band {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }

                body.pulse-static .pulse-overview-chart {
                    grid-template-columns: 1fr;
                    min-height: auto;
                }

                body.pulse-static .pulse-topic-pill {
                    min-width: 156px;
                }

                body.pulse-static .pulse-filter-pills {
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                }

                body.pulse-static .pulse-overview-radar {
                    width: 240px;
                    height: 108px;
                    opacity: 0.44;
                }

                body.pulse-static .pulse-overview-matrix {
                    grid-template-columns: 1fr;
                }

                body.pulse-static .pulse-static-sources-grid {
                    grid-template-columns: 1fr;
                }

                body.pulse-static .pulse-panel-copy {
                    align-items: flex-start;
                    gap: 10px;
                }

                body.pulse-static .pulse-panel-copy::after {
                    min-height: 14px;
                }
            }

            @media (max-width: 1100px) and (min-width: 721px) {
                body.pulse-static .pulse-static-sidebar {
                    position: fixed;
                    top: 0;
                    left: 0;
                    width: 286px;
                    height: 100vh;
                    min-height: 100vh;
                    border-right: 1px solid rgba(205, 217, 232, 0.9);
                    border-bottom: none;
                }

                body.pulse-static .pulse-static-main {
                    margin-left: 286px;
                }
            }

            @media (max-width: 720px) {
                body.pulse-static .pulse-static-sidebar {
                    display: none;
                }

                body.pulse-static .pulse-static-main {
                    margin-left: 0;
                    padding: 8px;
                    overflow: hidden;
                }

                body.pulse-static .header {
                    max-height: calc(100vh - 16px);
                    padding: 12px;
                    border-radius: 20px;
                    overflow: hidden;
                }

                body.pulse-static.is-overview-active .container {
                    height: calc(100vh - 16px);
                }

                body.pulse-static .pulse-static-subtitle {
                    font-size: 16px;
                    line-height: 1.45;
                }

                body.pulse-static .pulse-overview-shell {
                    width: 100%;
                    margin-top: 10px;
                }

                body.pulse-static .pulse-filter-card {
                    padding: 16px;
                }

                body.pulse-static .pulse-overview-stats {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }

                body.pulse-static .pulse-overview-stat {
                    min-height: 88px;
                    padding: 10px 12px;
                }

                body.pulse-static .pulse-overview-stat-label {
                    font-size: 12px;
                    margin-bottom: 5px;
                }

                body.pulse-static .pulse-overview-stat-value {
                    font-size: 30px;
                }

                body.pulse-static .pulse-overview-stat-note {
                    margin-top: 6px;
                    font-size: 10px;
                }

                body.pulse-static .pulse-overview-status-band {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                    min-height: 74px;
                    padding: 10px 10px 4px;
                }

                body.pulse-static .pulse-overview-chart-card {
                    padding: 8px 10px;
                }

                body.pulse-static .pulse-overview-chart {
                    min-height: 76px;
                }

                body.pulse-static .pulse-overview-chart-row {
                    grid-template-columns: 72px minmax(110px, 1fr) 34px;
                    gap: 12px;
                }

                body.pulse-static .pulse-overview-chart-label,
                body.pulse-static .pulse-overview-chart-count {
                    font-size: 11px;
                }

                body.pulse-static .pulse-topic-track {
                    padding: 0 58px;
                    gap: 12px;
                }

                body.pulse-static .pulse-topic-pill {
                    min-width: 144px;
                    min-height: 42px;
                    font-size: 12px;
                }

                body.pulse-static .pulse-topic-pill::before {
                    width: 32px;
                    height: 32px;
                    background-size: 18px 18px, auto;
                }

                body.pulse-static .pulse-filter-pills {
                    gap: 10px;
                }

                body.pulse-static .pulse-filter-pill {
                    min-height: 32px;
                    font-size: 11px;
                    padding: 0 8px;
                }

                body.pulse-static .pulse-overview-radar {
                    width: 190px;
                    height: 88px;
                    opacity: 0.34;
                }
            }

            @media (prefers-reduced-motion: reduce) {
                body.pulse-static .pulse-overview-radar-sweep,
                body.pulse-static .pulse-overview-radar-trace,
                .source-strip.is-marquee .source-strip-rail {
                    animation: none;
                }
            }

            .container {
                max-width: 1060px;
                margin: 0 auto;
                background: rgba(255, 250, 244, 0.62);
                border-radius: 34px;
                border: 1px solid rgba(228, 214, 194, 0.7);
                overflow: hidden;
                box-shadow: 0 30px 80px rgba(129, 100, 70, 0.08);
                backdrop-filter: blur(14px);
            }

            .header {
                background:
                    radial-gradient(circle at 88% 16%, rgba(216, 231, 224, 0.32), transparent 16%),
                    radial-gradient(circle at 8% 12%, rgba(242, 222, 203, 0.34), transparent 18%),
                    linear-gradient(135deg, rgba(255,253,249,0.98) 0%, rgba(250,244,236,0.96) 100%);
                color: var(--text-main);
                padding: 34px 34px 34px;
                text-align: left;
                position: relative;
                border-bottom: 1px solid rgba(226, 212, 194, 0.76);
            }

            .header-shell {
                display: grid;
                grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
                align-items: stretch;
                gap: 26px;
                margin-top: 14px;
            }

            .header-left {
                min-width: 0;
                width: 100%;
                max-width: none;
                display: flex;
            }

            .header-right {
                min-width: 0;
                width: 100%;
                max-width: none;
                display: flex;
            }

            .save-buttons {
                position: absolute;
                top: 16px;
                right: 16px;
                display: flex;
                gap: 8px;
            }

            .save-btn {
                background: rgba(255, 250, 244, 0.98);
                border: 1px solid rgba(223, 204, 182, 0.94);
                color: #5d4c3e;
                padding: 10px 17px;
                border-radius: 999px;
                cursor: pointer;
                font-size: 13px;
                font-weight: 700;
                transition: all 0.2s ease;
                backdrop-filter: blur(10px);
                white-space: nowrap;
                box-shadow: 0 10px 22px rgba(154, 120, 82, 0.08);
            }

            .save-btn:hover {
                background: #fffdfa;
                border-color: rgba(190, 177, 156, 0.9);
                transform: translateY(-1px);
            }

            .save-btn:active {
                transform: translateY(0);
            }

            .save-btn:disabled {
                opacity: 0.6;
                cursor: not-allowed;
            }

            .header-title {
                font-family: 'Noto Serif SC', serif;
                font-size: 26px;
                font-weight: 900;
                letter-spacing: 0.02em;
                margin: 0 0 20px;
                color: #241c16;
                max-width: 680px;
            }

            .header-info {
                display: grid;
                grid-template-columns: 1fr 1fr;
                grid-auto-rows: 1fr;
                gap: 16px;
                font-size: 13px;
                opacity: 0.95;
                width: 100%;
                max-width: none;
                margin: 0;
                height: 100%;
            }

            .info-item {
                text-align: left;
                padding: 18px 18px;
                border-radius: 22px;
                background: var(--card-bg-strong);
                border: 1px solid var(--card-border);
                box-shadow: var(--card-shadow-soft), inset 0 1px 0 rgba(255,255,255,0.8);
                display: flex;
                flex-direction: column;
                justify-content: center;
                min-height: 108px;
            }

            .info-label {
                display: block;
                font-size: 11px;
                color: #8b7b69;
                opacity: 1;
                margin-bottom: 8px;
                letter-spacing: 0.05em;
                font-weight: 700;
            }

            .info-value {
                font-weight: 800;
                font-size: 16px;
                color: #30261e;
            }

            .filter-card {
                min-width: 0;
                width: 100%;
                height: 100%;
                padding: 20px 22px;
                border-radius: 28px;
                border: 1px solid var(--card-border);
                background:
                    linear-gradient(180deg, rgba(255,252,247,0.98) 0%, rgba(250,245,238,0.97) 100%),
                    radial-gradient(circle at 84% 16%, rgba(225, 236, 230, 0.3), transparent 22%);
                box-shadow: var(--card-shadow);
            }

            .filter-card-body {
                display: grid;
                grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
                gap: 12px 14px;
                align-items: start;
            }

            .filter-card-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
                margin-bottom: 12px;
            }

            .filter-card-title {
                font-family: 'Noto Serif SC', serif;
                font-size: 20px;
                font-weight: 900;
                color: #2b2119;
            }

            .filter-card-badge {
                display: inline-flex;
                align-items: center;
                padding: 5px 11px;
                border-radius: 999px;
                background: var(--green-soft);
                color: #50675c;
                font-size: 12px;
                font-weight: 700;
            }

            .filter-card-block {
                padding: 14px 15px;
                border: 1px solid rgba(223, 208, 188, 0.72);
                border-radius: 20px;
                background: rgba(255, 251, 246, 0.92);
                min-width: 0;
            }

            .filter-card-block-topics {
                grid-column: 1 / -1;
            }

            .filter-card-label {
                font-size: 11px;
                letter-spacing: 0.06em;
                color: #8a7f72;
                margin-bottom: 8px;
                font-weight: 700;
            }

            .filter-topic-list,
            .filter-step-list {
                display: flex;
                flex-wrap: wrap;
                gap: 8px 10px;
            }

            .filter-topic-item,
            .filter-step-item {
                font-size: 13px;
                color: #4c4d45;
                line-height: 1.65;
            }

            .filter-topic-item {
                display: inline-flex;
                align-items: center;
                padding: 6px 12px;
                border-radius: 999px;
                background: rgba(244, 236, 225, 0.92);
                border: 1px solid rgba(223, 205, 183, 0.88);
                white-space: nowrap;
            }

            .filter-step-list {
                display: grid;
                gap: 6px;
            }

            .filter-rule-text {
                font-size: 13px;
                color: #5c564c;
                line-height: 1.72;
            }

            .filter-metrics {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                margin-top: 10px;
            }

            .filter-metric {
                display: inline-flex;
                align-items: center;
                padding: 6px 11px;
                border-radius: 999px;
                background: rgba(247, 238, 225, 0.96);
                border: 1px solid rgba(220, 206, 185, 0.88);
                font-size: 12px;
                color: #645a4f;
                font-weight: 600;
            }

            body.pulse-enabled {
                padding: 0;
                background:
                    radial-gradient(circle at 16% 14%, rgba(211, 224, 242, 0.38), transparent 20%),
                    radial-gradient(circle at 78% 18%, rgba(244, 226, 210, 0.42), transparent 24%),
                    linear-gradient(180deg, #eef4fd 0%, #f5f8fc 36%, #fafbfd 100%);
            }

            body.pulse-enabled .container {
                max-width: none;
                margin: 0;
                min-height: 100vh;
                border-radius: 0;
                border: none;
                box-shadow: none;
                background: transparent;
                overflow: visible;
            }

            body.pulse-enabled .pulse-shell {
                display: grid;
                grid-template-columns: 276px minmax(0, 1fr);
                min-height: 100vh;
            }

            body.pulse-enabled .pulse-sidebar {
                position: sticky;
                top: 0;
                align-self: start;
                min-height: 100vh;
                padding: 28px 22px;
                border-right: 1px solid rgba(205, 217, 232, 0.9);
                background: linear-gradient(180deg, rgba(241, 246, 253, 0.96) 0%, rgba(233, 240, 250, 0.94) 100%);
                backdrop-filter: blur(18px);
            }

            body.pulse-enabled .pulse-brand {
                padding: 6px 4px 24px;
            }

            body.pulse-enabled .pulse-brand-title {
                font-size: 26px;
                font-weight: 800;
                letter-spacing: -0.03em;
                color: #18263d;
            }

            body.pulse-enabled .pulse-brand-note {
                margin-top: 8px;
                font-size: 13px;
                color: #75839a;
            }

            body.pulse-enabled .pulse-nav {
                display: grid;
                gap: 10px;
                margin-top: 8px;
            }

            body.pulse-enabled .pulse-nav-link {
                display: flex;
                align-items: center;
                min-height: 48px;
                padding: 0 16px;
                border-radius: 16px;
                color: #4e607c;
                font-size: 16px;
                font-weight: 600;
                text-decoration: none;
                transition: all 0.18s ease;
            }

            body.pulse-enabled .pulse-nav-link:hover,
            body.pulse-enabled .pulse-nav-link.active {
                color: #132238;
                background: rgba(255, 255, 255, 0.72);
                box-shadow: inset 0 0 0 1px rgba(203, 216, 233, 0.82);
            }

            body.pulse-enabled .pulse-main {
                position: relative;
                padding: 28px 34px 44px;
            }

            body.pulse-enabled .pulse-save-buttons {
                position: sticky;
                top: 14px;
                justify-content: flex-end;
                margin-bottom: 14px;
                z-index: 10;
            }

            body.pulse-enabled .pulse-section {
                margin-bottom: 26px;
            }

            body.pulse-enabled .pulse-section-head {
                display: flex;
                justify-content: space-between;
                align-items: flex-end;
                gap: 16px;
                margin-bottom: 14px;
            }

            body.pulse-enabled .pulse-section-kicker {
                font-family: 'Noto Serif SC', serif;
                font-size: 26px;
                font-weight: 700;
                color: #1d2b45;
                letter-spacing: -0.03em;
            }

            body.pulse-enabled .pulse-section-note {
                color: #7e8ca3;
                font-size: 14px;
                text-align: right;
            }

            body.pulse-enabled .header.pulse-overview-panel {
                padding: 30px;
                border: 1px solid rgba(204, 215, 231, 0.9);
                border-radius: 34px;
                background:
                    radial-gradient(circle at 86% 16%, rgba(231, 239, 248, 0.95), transparent 22%),
                    linear-gradient(180deg, rgba(255,255,255,0.95) 0%, rgba(248,250,253,0.96) 100%);
                box-shadow: 0 24px 56px rgba(163, 179, 201, 0.16);
            }

            body.pulse-enabled .header.pulse-overview-panel .header-title {
                font-size: clamp(44px, 5vw, 72px);
                line-height: 1.02;
                margin-bottom: 12px;
                color: #1d2c47;
                max-width: none;
            }

            body.pulse-enabled .pulse-overview-subtitle {
                margin: -2px 0 18px;
                color: #5f7291;
                font-size: 18px;
                max-width: 760px;
            }

            body.pulse-enabled .header.pulse-overview-panel .header-shell {
                grid-template-columns: minmax(0, 1.25fr) minmax(260px, 0.75fr);
                gap: 24px;
                margin-top: 0;
            }

            body.pulse-enabled .pulse-overview-main {
                display: flex;
                flex-direction: column;
            }

            body.pulse-enabled .header.pulse-overview-panel .header-info {
                max-width: none;
                gap: 18px;
            }

            body.pulse-enabled .header.pulse-overview-panel .info-item {
                min-height: 126px;
                border-radius: 24px;
                padding: 22px 20px;
                background: rgba(255, 255, 255, 0.78);
                border: 1px solid rgba(207, 218, 234, 0.9);
                box-shadow: 0 18px 34px rgba(188, 202, 221, 0.12);
            }

            body.pulse-enabled .header.pulse-overview-panel .info-label {
                font-size: 12px;
                color: #7a8aa1;
            }

            body.pulse-enabled .header.pulse-overview-panel .info-value {
                font-size: 28px;
                color: #1a2a42;
                letter-spacing: -0.03em;
            }

            body.pulse-enabled .pulse-summary-card {
                border-radius: 26px;
                padding: 22px;
                border: 1px solid rgba(209, 220, 236, 0.9);
                background: rgba(245, 249, 255, 0.86);
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.9);
            }

            body.pulse-enabled .pulse-summary-label {
                display: inline-flex;
                align-items: center;
                height: 30px;
                padding: 0 12px;
                border-radius: 999px;
                background: rgba(255,255,255,0.92);
                border: 1px solid rgba(205, 217, 231, 0.9);
                color: #5f7492;
                font-size: 12px;
                font-weight: 700;
            }

            body.pulse-enabled .pulse-summary-title {
                margin-top: 18px;
                font-size: 28px;
                line-height: 1.18;
                letter-spacing: -0.03em;
                color: #20314f;
                font-weight: 700;
            }

            body.pulse-enabled .pulse-summary-text {
                margin-top: 12px;
                color: #6f8098;
                font-size: 14px;
                line-height: 1.75;
            }

            body.pulse-enabled .dashboard-card,
            body.pulse-enabled .pulse-source-grid {
                padding: 24px;
                border-radius: 30px;
                border: 1px solid rgba(206, 218, 233, 0.9);
                background: rgba(255, 255, 255, 0.9);
                box-shadow: 0 24px 48px rgba(173, 188, 208, 0.14);
            }

            body.pulse-enabled .dashboard-grid {
                display: block;
                margin-top: 0;
            }

            body.pulse-enabled .dashboard-column + .dashboard-column {
                margin-top: 0;
            }

            body.pulse-enabled .dashboard-card-header {
                margin-bottom: 14px;
            }

            body.pulse-enabled .dashboard-card-title,
            body.pulse-enabled .rss-section-title,
            body.pulse-enabled .ai-section-title,
            body.pulse-enabled .social-section-title {
                font-family: 'Noto Serif SC', serif;
                font-size: 24px;
                font-weight: 700;
                color: #1d2b45;
            }

            body.pulse-enabled .rank-explain,
            body.pulse-enabled .social-sources {
                padding: 14px 16px;
                border-radius: 18px;
                background: rgba(245, 249, 255, 0.82);
                border: 1px solid rgba(210, 220, 236, 0.86);
                color: #687a93;
            }

            body.pulse-enabled .dashboard-card-meta,
            body.pulse-enabled .rss-section-count,
            body.pulse-enabled .social-section-count {
                display: none !important;
            }

            body.pulse-enabled .news-item,
            body.pulse-enabled .rss-item,
            body.pulse-enabled .social-item {
                border-radius: 18px !important;
                border: 1px solid rgba(216, 225, 238, 0.92) !important;
                background: linear-gradient(180deg, rgba(250, 252, 255, 0.98) 0%, rgba(255,255,255,0.96) 100%) !important;
                box-shadow: 0 10px 24px rgba(190, 202, 220, 0.1) !important;
            }

            body.pulse-enabled .pulse-source-grid {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 16px;
            }

            body.pulse-enabled .pulse-source-card {
                min-width: 0;
                padding: 18px;
                border-radius: 22px;
                border: 1px solid rgba(210, 220, 235, 0.88);
                background: rgba(247, 250, 255, 0.86);
            }

            body.pulse-enabled .pulse-source-title {
                font-size: 17px;
                font-weight: 700;
                color: #21314c;
                margin-bottom: 10px;
            }

            body.pulse-enabled .pulse-source-text {
                font-size: 14px;
                line-height: 1.8;
                color: #68809c;
            }

            @media (max-width: 1100px) {
                body.pulse-enabled .pulse-shell {
                    grid-template-columns: 1fr;
                }

                body.pulse-enabled .pulse-sidebar {
                    position: relative;
                    min-height: auto;
                    border-right: none;
                    border-bottom: 1px solid rgba(205, 217, 232, 0.9);
                }

                body.pulse-enabled .pulse-nav {
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                }

                body.pulse-enabled .pulse-main {
                    padding: 22px;
                }

                body.pulse-enabled .header.pulse-overview-panel .header-shell,
                body.pulse-enabled .pulse-source-grid {
                    grid-template-columns: 1fr;
                }
            }

            @media (max-width: 720px) {
                body.pulse-enabled .pulse-nav {
                    grid-template-columns: 1fr 1fr;
                }

                body.pulse-enabled .header.pulse-overview-panel .header-info {
                    grid-template-columns: 1fr;
                }

                body.pulse-enabled .pulse-section-head {
                    flex-direction: column;
                    align-items: flex-start;
                }

                body.pulse-enabled .pulse-section-note {
                    text-align: left;
                }
            }

            .content {
                padding: 28px;
            }

            .dashboard-grid {
                display: grid;
                grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
                gap: 20px;
                align-items: start;
                margin-top: 28px;
            }

            .dashboard-column {
                min-width: 0;
            }

            .dashboard-card {
                min-width: 0;
                padding: 24px;
                border-radius: 28px;
                border: 1px solid var(--card-border);
                box-shadow: var(--card-shadow);
                background: linear-gradient(180deg, rgba(246, 250, 253, 0.98) 0%, rgba(239, 245, 250, 0.98) 100%);
            }

            .dashboard-hotlist {
                background: transparent;
                border-color: transparent;
                box-shadow: none;
            }

            .dashboard-hotlist .news-item {
                background:
                    linear-gradient(180deg, rgba(255,255,255,0.995) 0%, rgba(248,251,254,0.995) 100%);
                border: 1px solid rgba(193, 208, 226, 0.9);
                box-shadow:
                    inset 0 1px 0 rgba(255,255,255,0.96),
                    0 12px 24px rgba(107, 126, 151, 0.09);
            }

            .dashboard-rss {
                background: transparent;
                border-color: transparent;
                box-shadow: none;
            }

            body.pulse-static .dashboard-rss .rss-item {
                display: grid;
                grid-template-columns: 28px minmax(0, 1fr);
                align-items: start;
                gap: 12px;
            }

            body.pulse-static .dashboard-rss .rss-item-body {
                min-width: 0;
            }

            body.pulse-static .dashboard-rss .news-number {
                margin-top: 2px;
            }

            .dashboard-ai {
                background: transparent;
                border-color: transparent;
                box-shadow: none;
            }

            .dashboard-social {
                margin-top: 24px;
                background: transparent;
                border-color: transparent;
                box-shadow: none;
            }

            .social-sources {
                margin: 0 0 18px;
                padding: 0;
                background: transparent;
                border: none;
                box-shadow: none;
            }

            .social-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 18px;
                align-items: stretch;
            }

            .social-item {
                display: grid;
                grid-template-rows: minmax(0, 1fr) auto;
                background: linear-gradient(180deg, rgba(255,255,255,0.995) 0%, rgba(248,251,254,0.995) 100%);
                border: 1px solid rgba(193, 208, 226, 0.9);
                border-radius: 14px;
                padding: 0;
                margin-bottom: 0;
                height: 270px;
                min-height: 270px;
                overflow: hidden;
                box-shadow: 0 12px 24px rgba(107, 126, 151, 0.09);
            }

            .social-item-has-comments {
                display: grid;
                grid-template-rows: minmax(0, 1fr) auto;
                gap: 0;
                overflow: hidden;
                padding: 0 !important;
            }

            .social-post-side {
                min-width: 0;
                display: flex;
                flex-direction: column;
                gap: 12px;
                overflow: hidden;
                padding: 16px 18px 12px;
            }

            .social-item-has-comments .social-post-side {
                padding: 16px 18px 12px;
            }

            .social-item .news-number {
                display: none;
            }

            .social-item .news-content {
                min-width: 0;
                height: 100%;
                padding-right: 0;
                display: flex;
                flex-direction: column;
            }

            .social-item .news-header {
                display: none;
            }

            .social-platform {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 32px;
                height: 32px;
                border-radius: 999px;
                overflow: hidden;
                flex: 0 0 auto;
                background: linear-gradient(180deg, rgba(236, 242, 248, 0.96) 0%, rgba(225, 233, 243, 0.96) 100%);
                border: 1px solid rgba(192, 206, 224, 0.92);
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.94);
            }

            .social-platform img {
                width: 100%;
                height: 100%;
                object-fit: cover;
                display: block;
            }

            .social-platform-fallback {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 100%;
                height: 100%;
                color: #5a7b9f;
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 0.03em;
            }

            .social-author {
                color: #5f7893;
                font-size: 12px;
                font-weight: 500;
            }

            .social-excerpt {
                margin-top: 0;
                color: #132940;
                font-size: 15px;
                line-height: 1.62;
                display: -webkit-box;
                -webkit-line-clamp: 4;
                -webkit-box-orient: vertical;
                overflow: hidden;
                word-break: break-word;
            }

            .social-text-link {
                display: block;
                color: inherit;
                text-decoration: none;
            }

            .social-text-link:hover .social-excerpt {
                color: #2d748d;
                text-decoration: underline;
            }

            .social-meta-line {
                display: flex;
                align-items: center;
                gap: 12px;
                flex-wrap: wrap;
                margin-bottom: 6px;
            }

            .social-time {
                color: #8b8277;
                font-size: 11px;
            }

            .social-comment-list {
                display: grid;
                grid-template-rows: repeat(3, minmax(0, 1fr));
                gap: 7px;
                align-items: start;
                min-width: 0;
                height: 104px;
                box-sizing: border-box;
                overflow: hidden;
                overscroll-behavior: contain;
                padding: 12px 18px 14px;
                border-radius: 0;
                background: linear-gradient(180deg, rgba(239, 247, 250, 0.78), rgba(232, 243, 248, 0.88));
            }

            .social-comment-item {
                display: grid;
                grid-template-columns: auto minmax(0, 1fr);
                align-items: center;
                gap: 10px;
                min-width: 0;
                min-height: 0;
                padding: 0;
                border-radius: 11px;
                background: transparent;
                border: 0;
            }

            .social-comment-meta {
                display: flex;
                align-items: center;
                gap: 8px;
                color: #6c8098;
                font-size: 11px;
                font-weight: 800;
            }

            .social-comment-stance {
                color: #246f89;
                background: rgba(125, 206, 207, 0.16);
                border-radius: 999px;
                padding: 2px 7px;
                white-space: nowrap;
            }

            .social-comment-text {
                position: relative;
                color: #172b42;
                font-size: 13px;
                line-height: 1.45;
                min-width: 0;
                overflow-x: hidden;
                overflow-y: hidden;
                overscroll-behavior: auto;
                cursor: grab;
                scrollbar-width: none;
                white-space: nowrap;
                word-break: keep-all;
                user-select: none;
            }

            .social-comment-content {
                display: inline-block;
                min-width: max-content;
                white-space: nowrap;
                will-change: transform;
                transform: translate3d(0, 0, 0);
            }

            .social-comment-text[data-comment-empty="1"] {
                color: #7b8fa5;
                cursor: default;
                user-select: text;
            }

            .social-comment-text.is-dragging {
                cursor: grabbing;
            }

            .social-comment-text::-webkit-scrollbar {
                display: none;
            }

            .social-comment-empty {
                color: #627894;
                font-size: 12px;
                line-height: 1.7;
                padding: 12px;
                border-radius: 12px;
                background: rgba(236, 244, 250, 0.7);
            }

            .dashboard-card .hotlist-section,
            .dashboard-card .rss-section,
            .dashboard-card .ai-section,
            .dashboard-card .standalone-section,
            .dashboard-card .new-section,
            .dashboard-card .section-divider {
                margin-top: 0;
                padding-top: 0;
                border-top: none;
            }

            .word-group {
                margin-bottom: 28px;
                padding: 0;
                border-radius: 0;
                background: transparent;
                border: none;
            }

            .word-group:first-child {
                margin-top: 0;
            }

            .word-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 16px;
                padding: 0 2px 8px;
                border-bottom: 1px solid rgba(66, 137, 167, 0.10);
            }

            .word-info {
                display: flex;
                align-items: center;
                gap: 12px;
            }

            .word-name {
                font-family: 'Noto Serif SC', serif;
                font-size: 17px;
                font-weight: 700;
                color: #21465b;
                letter-spacing: 0.01em;
            }

            .word-count {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
                min-height: 34px;
                padding: 0 14px 0 12px;
                border-radius: 999px;
                background: linear-gradient(180deg, rgba(251, 254, 253, 0.98) 0%, rgba(242, 248, 246, 0.98) 100%);
                border: 1px solid rgba(219, 232, 227, 0.96);
                color: #667d73;
                font-size: 12px;
                font-weight: 700;
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.92);
                letter-spacing: 0.01em;
            }

            .word-count::before {
                content: "";
                width: 10px;
                height: 10px;
                border-radius: 50%;
                background: #33c466;
                box-shadow: 0 0 0 4px rgba(51, 196, 102, 0.10);
                flex-shrink: 0;
            }

            .word-count.hot { color: #667d73; font-weight: 700; }
            .word-count.warm { color: #667d73; font-weight: 700; }

            .word-index {
                color: #7e95a7;
                font-size: 12px;
            }

            .news-item {
                margin-bottom: 20px;
                padding: 16px 18px;
                border-bottom: none;
                position: relative;
                display: flex;
                gap: 12px;
                align-items: center;
                border-radius: 16px;
            }

            .news-item:last-child {
                border-bottom: none;
            }

            .news-item.new::after {
                content: "NEW";
                position: absolute;
                top: 12px;
                right: 0;
                background: #fbbf24;
                color: #92400e;
                font-size: 9px;
                font-weight: 700;
                padding: 3px 6px;
                border-radius: 4px;
                letter-spacing: 0.5px;
            }

            .news-number {
                color: #5f7c8f;
                font-size: 13px;
                font-weight: 600;
                min-width: 20px;
                text-align: center;
                flex-shrink: 0;
                background: linear-gradient(180deg, #f4fbff 0%, #dceef8 100%);
                border-radius: 50%;
                width: 24px;
                height: 24px;
                display: flex;
                align-items: center;
                justify-content: center;
                align-self: flex-start;
                margin-top: 8px;
                border: 1px solid rgba(102, 167, 198, 0.22);
            }

            .news-content {
                flex: 1;
                min-width: 0;
            }

            .news-item.new .news-content {
                padding-right: 50px;
            }

            .news-header {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 8px;
                flex-wrap: wrap;
            }

            .source-name {
                color: #6e879a;
                font-size: 12px;
                font-weight: 500;
            }

            .keyword-tag {
                color: #587766;
                font-size: 12px;
                font-weight: 600;
                background: #edf4ef;
                padding: 2px 6px;
                border-radius: 999px;
            }

            .rank-num {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 7px;
                color: #667d73;
                background: linear-gradient(180deg, rgba(251, 254, 253, 0.98) 0%, rgba(242, 248, 246, 0.98) 100%);
                font-size: 11px;
                font-weight: 700;
                padding: 0 10px 0 9px;
                min-height: 28px;
                border-radius: 999px;
                min-width: 68px;
                text-align: center;
                border: 1px solid rgba(219, 232, 227, 0.96);
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.92);
                letter-spacing: 0.01em;
            }

            .rank-num::before {
                content: "";
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: #33c466;
                box-shadow: 0 0 0 4px rgba(51, 196, 102, 0.10);
                flex-shrink: 0;
            }

            .rank-num.top {
                color: #5f756c;
                background: linear-gradient(180deg, rgba(251, 254, 253, 0.99) 0%, rgba(239, 247, 243, 0.98) 100%);
                border-color: rgba(212, 228, 221, 0.98);
            }
            .rank-num.high {
                color: #637970;
                background: linear-gradient(180deg, rgba(251, 254, 253, 0.985) 0%, rgba(241, 248, 244, 0.98) 100%);
                border-color: rgba(216, 230, 224, 0.98);
            }

            .time-info {
                color: #7890a2;
                font-size: 11px;
            }

            .count-info {
                color: #059669;
                font-size: 11px;
                font-weight: 500;
            }

            .news-title {
                font-size: 15px;
                line-height: 1.55;
                color: #1c2c3f;
                margin: 0;
            }

            .news-link {
                color: #1f3f5e;
                text-decoration: none;
            }

            .news-link:hover {
                text-decoration: underline;
            }

            .news-link:visited {
                color: #6c665e;
            }

            /* 通用区域分割线样式 */
            .section-divider {
                margin-top: 32px;
                padding-top: 24px;
                border-top: 2px solid #e5e7eb;
            }

            /* 热榜统计区样式 */
            .hotlist-section {
                /* 默认无边框，由 section-divider 动态添加 */
            }

            .new-section {
                margin-top: 40px;
                padding-top: 24px;
            }

            .new-section-title {
                color: #1a1a1a;
                font-size: 16px;
                font-weight: 600;
                margin: 0 0 20px 0;
            }

            .new-source-group {
                margin-bottom: 24px;
            }

            .new-source-title {
                color: #666;
                font-size: 13px;
                font-weight: 500;
                margin: 0 0 12px 0;
                padding-bottom: 6px;
                border-bottom: 1px solid #f5f5f5;
            }

            .new-item {
                display: flex;
                align-items: center;
                gap: 12px;
                padding: 8px 0;
                border-bottom: 1px solid #f9f9f9;
            }

            .new-item:last-child {
                border-bottom: none;
            }

            .new-item-number {
                color: #999;
                font-size: 12px;
                font-weight: 600;
                min-width: 18px;
                text-align: center;
                flex-shrink: 0;
                background: #f8f9fa;
                border-radius: 50%;
                width: 20px;
                height: 20px;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .new-item-rank {
                color: #fff;
                background: #6b7280;
                font-size: 10px;
                font-weight: 700;
                padding: 3px 6px;
                border-radius: 8px;
                min-width: 20px;
                text-align: center;
                flex-shrink: 0;
            }

            .new-item-rank.top { background: #dc2626; }
            .new-item-rank.high { background: #ea580c; }

            .new-item-content {
                flex: 1;
                min-width: 0;
            }

            .new-item-title {
                font-size: 14px;
                line-height: 1.4;
                color: #1a1a1a;
                margin: 0;
            }

            .error-section {
                background: #fef2f2;
                border: 1px solid #fecaca;
                border-radius: 8px;
                padding: 16px;
                margin-bottom: 24px;
            }

            .error-title {
                color: #dc2626;
                font-size: 14px;
                font-weight: 600;
                margin: 0 0 8px 0;
            }

            .error-list {
                list-style: none;
                padding: 0;
                margin: 0;
            }

            .error-item {
                color: #991b1b;
                font-size: 13px;
                padding: 2px 0;
                font-family: 'SF Mono', Consolas, monospace;
            }

            .footer {
                margin-top: 32px;
                padding: 20px 24px;
                background: rgba(247, 241, 231, 0.85);
                border-top: 1px solid rgba(216, 205, 188, 0.8);
                text-align: center;
            }

            .footer-content {
                font-size: 13px;
                color: #82786b;
                line-height: 1.6;
            }

            .footer-link {
                color: #4d6a5d;
                text-decoration: none;
                font-weight: 500;
                transition: color 0.2s ease;
            }

            .footer-link:hover {
                color: #3f584d;
                text-decoration: underline;
            }

            .project-name {
                font-weight: 600;
                color: #595348;
            }

            .dashboard-card-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 20px;
                padding-bottom: 14px;
                border-bottom: 1px solid rgba(219, 209, 192, 0.92);
            }

            .dashboard-card-title {
                font-family: 'Noto Serif SC', serif;
                font-size: 20px;
                font-weight: 700;
                color: #2e302b;
                letter-spacing: 0.01em;
            }

            .dashboard-card-meta {
                color: #667d73;
                background: linear-gradient(180deg, rgba(251, 254, 253, 0.98) 0%, rgba(242, 248, 246, 0.98) 100%);
                font-size: 12px;
                font-weight: 700;
                padding: 0 14px 0 12px;
                min-height: 34px;
                border-radius: 999px;
                border: 1px solid rgba(219, 232, 227, 0.96);
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.92);
                letter-spacing: 0.01em;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
            }

            .dashboard-card-meta::before {
                content: "";
                width: 10px;
                height: 10px;
                border-radius: 50%;
                background: #33c466;
                box-shadow: 0 0 0 4px rgba(51, 196, 102, 0.10);
                flex-shrink: 0;
            }

            .rank-explain {
                margin: 0 0 18px;
                padding: 0;
                background: transparent;
                border: none;
                box-shadow: none;
            }

            body.pulse-static .dashboard-hotlist > .rank-explain,
            body.pulse-static .dashboard-rss > .rank-explain {
                transform: none;
            }

            .source-strip {
                position: relative;
                padding: 0;
                border: none;
                background: transparent;
                box-shadow: none;
                overflow: visible;
                isolation: isolate;
            }

            .source-strip-shell {
                position: relative;
                overflow: hidden;
                border-radius: 18px;
            }

            .source-strip-shell::before,
            .source-strip-shell::after {
                content: "";
                position: absolute;
                top: 0;
                bottom: 0;
                width: 14px;
                pointer-events: none;
                z-index: 2;
            }

            .source-strip-shell::before {
                left: 0;
                background: linear-gradient(
                    90deg,
                    rgba(236, 242, 248, 0.98) 0%,
                    rgba(236, 242, 248, 0.92) 28%,
                    rgba(236, 242, 248, 0) 100%
                );
            }

            .source-strip-shell::after {
                right: 0;
                background: linear-gradient(
                    270deg,
                    rgba(236, 242, 248, 0.98) 0%,
                    rgba(236, 242, 248, 0.92) 28%,
                    rgba(236, 242, 248, 0) 100%
                );
            }

            .source-strip-rail {
                display: flex;
                gap: 10px;
                overflow-x: auto;
                padding: 0 4px 4px;
                scroll-padding-inline: 4px;
                scroll-behavior: smooth;
                scrollbar-width: none;
                cursor: grab;
                scroll-snap-type: x proximity;
            }

            .source-strip.is-marquee .source-strip-rail {
                width: max-content;
                overflow: visible;
                padding-right: 10px;
                scroll-snap-type: none;
                cursor: default;
                animation: sourceStripLogoMarquee 116s linear infinite;
                will-change: transform;
            }

            .source-strip.is-marquee .source-strip-chip {
                scroll-snap-align: none;
            }

            .source-strip-clone {
                display: contents;
            }

            .source-strip-rail::-webkit-scrollbar {
                display: none;
            }

            .source-strip-rail.is-dragging {
                cursor: grabbing;
            }

            .source-strip-chip {
                flex: 0 0 auto;
                display: inline-flex;
                align-items: center;
                gap: 10px;
                scroll-snap-align: start;
                min-height: 42px;
                padding: 0 15px 0 11px;
                border-radius: 999px;
                background: linear-gradient(180deg, rgba(255,255,255,0.995) 0%, rgba(248,251,254,0.995) 100%);
                border: 1px solid rgba(193, 208, 226, 0.9);
                box-shadow: 0 10px 20px rgba(111, 130, 155, 0.08);
                color: #18324d;
                font-size: 12px;
                font-weight: 700;
                white-space: nowrap;
                user-select: none;
            }

            .source-strip-chip.is-summary {
                color: #5c7490;
                background: linear-gradient(180deg, rgba(244,248,252,0.98) 0%, rgba(238,244,249,0.98) 100%);
            }

            .source-strip-chip-logo {
                width: 22px;
                height: 22px;
                border-radius: 50%;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                overflow: hidden;
                background: linear-gradient(180deg, #8fa5c0 0%, #667f9d 100%);
                color: #ffffff;
                font-size: 10px;
                font-weight: 800;
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.18);
                flex: 0 0 auto;
            }

            .source-strip-chip-logo.has-image {
                padding: 2px;
                box-sizing: border-box;
                background: rgba(255, 255, 255, 0.98);
                border: 1px solid rgba(214, 225, 236, 0.96);
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.96);
            }

            .source-strip-chip-logo img {
                width: 100%;
                height: 100%;
                object-fit: contain;
                display: block;
                border-radius: 50%;
                background: transparent;
            }

            .source-strip-chip-fallback {
                width: 100%;
                height: 100%;
                display: inline-flex;
                align-items: center;
                justify-content: center;
            }

            @keyframes sourceStripLogoMarquee {
                from { transform: translateX(0); }
                to { transform: translateX(-50%); }
            }

            .ai-grid {
                display: grid;
                grid-template-columns: 1fr;
                gap: 14px;
            }

            .ai-overview-summary {
                padding: 20px 22px 22px;
                border-radius: 20px;
                border: 1px solid rgba(150, 176, 208, 0.98);
                background:
                    radial-gradient(circle at 92% 8%, rgba(171, 206, 228, 0.58), transparent 30%),
                    linear-gradient(180deg, rgba(242,248,253,0.998) 0%, rgba(225,237,247,0.996) 100%);
                box-shadow: 0 18px 38px rgba(78, 104, 138, 0.16);
                position: relative;
            }

            .ai-overview-summary::before {
                content: "";
                position: absolute;
                left: 0;
                top: 18px;
                bottom: 18px;
                width: 4px;
                border-radius: 999px;
                background: linear-gradient(180deg, #6eaebf 0%, #678fc7 100%);
            }

            .ai-overview-summary-head,
            .ai-grid-head {
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: 16px;
            }

            .ai-grid-head {
                margin-bottom: 10px;
            }

            .ai-overview-summary-title {
                margin-bottom: 0;
                color: #223d59;
                font-size: 16px;
                font-weight: 900;
                min-height: 1px;
            }

            .ai-overview-summary-text {
                color: #0f1a27;
                font-size: 14px;
                line-height: 1.85;
                font-weight: 800;
                white-space: pre-wrap;
            }

            .ai-overview-summary-meta,
            .ai-overview-event-meta {
                display: flex;
                align-items: center;
                flex-wrap: wrap;
                gap: 8px;
                margin-top: 0;
                justify-content: flex-end;
                flex: 0 0 auto;
            }

            .ai-overview-summary-meta {
                flex-direction: column;
                align-items: flex-end;
                gap: 10px;
            }

            .ai-overview-pill {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                min-height: 28px;
                padding: 0 10px;
                border-radius: 999px;
                border: 1px solid rgba(199, 213, 229, 0.96);
                background: linear-gradient(180deg, rgba(249,252,255,0.98) 0%, rgba(241,247,252,0.98) 100%);
                color: #617a96;
                font-size: 11px;
                font-weight: 700;
                white-space: nowrap;
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.94);
            }

            .ai-overview-pill-combined {
                display: inline-flex;
                align-items: center;
                gap: 10px;
            }

            .ai-overview-pill-combined-label {
                display: inline-flex;
                align-items: center;
                white-space: nowrap;
            }

            .ai-overview-pill-divider {
                width: 1px;
                height: 12px;
                background: rgba(152, 171, 194, 0.7);
                flex: 0 0 auto;
            }

            .ai-overview-events {
                display: grid;
                gap: 14px;
                padding-left: 0;
            }

            .ai-toggle {
                width: 100%;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
                margin-bottom: 16px;
                padding: 14px 16px;
                border: 1px solid rgba(66, 137, 167, 0.14);
                border-radius: 18px;
                background: rgba(255, 255, 255, 0.76);
                color: #4e7083;
                font-size: 14px;
                font-weight: 700;
                cursor: pointer;
            }

            .ai-toggle-note {
                font-size: 12px;
                font-weight: 600;
                color: #587084;
            }

            .ai-panel.collapsed {
                display: none;
            }

            .ai-grid-card {
                height: auto;
                padding: 18px 18px 16px;
                border-radius: 16px;
                border: 1px solid rgba(193, 208, 226, 0.9);
                background: linear-gradient(180deg, rgba(255,255,255,0.995) 0%, rgba(248,251,254,0.995) 100%);
                box-shadow: 0 12px 24px rgba(107, 126, 151, 0.09);
            }

            .ai-flip-card {
                padding: 0;
                border: 0;
                background: transparent;
                box-shadow: none;
                perspective: 1600px;
                min-height: 324px;
            }

            .ai-flip-card-inner {
                position: relative;
                min-height: 324px;
                width: 100%;
                transform-style: preserve-3d;
                transition: transform 0.58s cubic-bezier(0.22, 0.61, 0.36, 1);
            }

            .ai-flip-card.is-flipped .ai-flip-card-inner {
                transform: rotateY(180deg);
            }

            .ai-flip-card-face {
                position: absolute;
                inset: 0;
                display: grid;
                grid-template-rows: auto minmax(0, 1fr) auto;
                align-content: start;
                gap: 14px;
                padding: 18px 18px 16px;
                border-radius: 16px;
                border: 1px solid rgba(193, 208, 226, 0.9);
                background: linear-gradient(180deg, rgba(255,255,255,0.995) 0%, rgba(248,251,254,0.995) 100%);
                box-shadow: 0 12px 24px rgba(107, 126, 151, 0.09);
                backface-visibility: hidden;
                -webkit-backface-visibility: hidden;
            }

            .ai-flip-card-front {
                cursor: default;
            }

            .ai-flip-card-front:focus-visible {
                outline: 2px solid rgba(102, 140, 194, 0.72);
                outline-offset: 2px;
            }

            .ai-flip-card-back {
                transform: rotateY(180deg);
                overflow: hidden;
            }

            .ai-grid-title {
                margin-bottom: 0;
                font-size: 14px;
                font-weight: 800;
                color: #22405c;
            }

            .ai-grid-content {
                font-size: 13px;
                line-height: 1.8;
                color: #161f2b;
                white-space: pre-wrap;
                text-align: justify;
                text-justify: inter-ideograph;
            }

            .ai-overview-event-row {
                display: grid;
                gap: 14px;
                align-items: start;
                min-height: 0;
            }

            .ai-overview-main {
                display: grid;
                gap: 12px;
            }

            .ai-overview-pill-button,
            .ai-flip-card-back-button {
                appearance: none;
                border: 1px solid rgba(193, 208, 226, 0.96);
                background: linear-gradient(180deg, rgba(249,252,255,0.98) 0%, rgba(241,247,252,0.98) 100%);
                color: #365775;
                border-radius: 999px;
                min-height: 32px;
                padding: 0 12px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                font-size: 12px;
                font-weight: 800;
                cursor: pointer;
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.94);
            }

            .ai-overview-pill-button {
                position: relative;
                gap: 10px;
                overflow: hidden;
            }

            .ai-overview-pill-button::after,
            .ai-flip-card-back-button::before {
                content: "›";
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 12px;
                height: 12px;
                flex: 0 0 auto;
                font-size: 15px;
                line-height: 12px;
                color: rgba(67, 104, 142, 0.78);
                transform: translate3d(0, -0.5px, 0);
                transition: transform 180ms ease, color 180ms ease;
                animation: ai-pill-nudge 1.8s ease-in-out infinite;
            }

            .ai-flip-card-back-button {
                gap: 8px;
            }

            .ai-flip-card-back-button::before {
                content: "‹";
                animation-direction: reverse;
            }

            @keyframes ai-pill-nudge {
                0%, 100% { transform: translate3d(0, -0.5px, 0); opacity: 0.72; }
                50% { transform: translate3d(2px, -0.5px, 0); opacity: 1; }
            }

            .ai-overview-pill-button:hover,
            .ai-flip-card-back-button:hover {
                border-color: rgba(165, 189, 217, 0.98);
                color: #274766;
            }

            .ai-overview-pill-button:hover::after,
            .ai-flip-card-back-button:hover::before {
                color: #274766;
                transform: translate3d(3px, -0.5px, 0);
            }

            .ai-flip-card-back-button:hover::before {
                transform: translate3d(-3px, -0.5px, 0);
            }

            .ai-overview-pill-button:focus-visible,
            .ai-flip-card-back-button:focus-visible {
                outline: 2px solid rgba(102, 140, 194, 0.56);
                outline-offset: 2px;
            }

            .ai-flip-card-back-head {
                align-items: center;
            }

            .ai-flip-card-back-subtitle {
                margin-top: 4px;
                color: #6c8098;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.04em;
            }

            .ai-cluster-event-shell {
                display: flex;
                min-height: 0;
                padding-bottom: 12px;
            }

            .ai-cluster-event-list {
                list-style: none;
                display: grid;
                flex: 1 1 auto;
                gap: 10px;
                margin: 0;
                min-height: 0;
                padding: 0 4px 24px 0;
                max-height: none;
                overflow: auto;
                overscroll-behavior: contain;
                -webkit-overflow-scrolling: touch;
                scroll-padding-bottom: 24px;
            }

            .ai-cluster-event-item {
                display: grid;
                gap: 6px;
                padding: 12px 12px 10px;
                border-radius: 12px;
                border: 1px solid rgba(208, 219, 234, 0.92);
                background: linear-gradient(180deg, rgba(250,252,255,0.98) 0%, rgba(244,248,252,0.98) 100%);
            }

            .ai-cluster-event-item:last-child {
                margin-bottom: 8px;
            }

            .ai-cluster-event-meta {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
                font-size: 11px;
                line-height: 1.5;
            }

            .ai-cluster-event-source {
                color: #5d7894;
                font-weight: 700;
            }

            .ai-cluster-event-time {
                color: #7f92a7;
                font-weight: 600;
                white-space: nowrap;
                text-align: right;
            }

            .ai-cluster-event-link,
            .ai-cluster-event-text {
                color: #16202c;
                font-size: 13px;
                line-height: 1.72;
                font-weight: 700;
                text-decoration: none;
            }

            .ai-cluster-event-link:hover {
                color: #0e1824;
                text-decoration: underline;
            }

            .ai-cluster-event-placeholder {
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 132px;
                border-radius: 14px;
                border: 1px dashed rgba(194, 207, 225, 0.96);
                background: linear-gradient(180deg, rgba(249,252,255,0.98) 0%, rgba(242,247,252,0.98) 100%);
                color: #617b98;
                font-size: 13px;
                font-weight: 700;
            }

            .ai-overview-detail-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 12px;
            }

            .ai-overview-detail {
                min-height: 100%;
                padding: 14px 14px 12px;
                border-radius: 14px;
                border: 1px solid rgba(203, 217, 232, 0.94);
                background: linear-gradient(180deg, rgba(248,251,255,0.98) 0%, rgba(240,246,252,0.98) 100%);
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
            }

            .ai-overview-detail-label {
                color: #617b9b;
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 0.06em;
                text-transform: uppercase;
            }

            .ai-overview-detail-text {
                margin-top: 6px;
                color: #1d2f47;
                font-size: 12px;
                line-height: 1.72;
            }

            body.pulse-static .news-title,
            body.pulse-static .rss-title,
            body.pulse-static .rss-summary,
            body.pulse-static .social-excerpt,
            body.pulse-static .ai-grid-content {
                color: #151c26;
            }

            body.pulse-static .news-link,
            body.pulse-static .rss-link,
            body.pulse-static .social-text-link {
                color: #151c26;
            }

            body.pulse-static .news-link:hover,
            body.pulse-static .rss-link:hover,
            body.pulse-static .social-text-link:hover .social-excerpt {
                color: #0f1722;
            }

            body.pulse-static .dashboard-hotlist .news-title,
            body.pulse-static .dashboard-hotlist .news-link {
                color: #121821;
                font-weight: 700;
            }

            body.pulse-static .dashboard-hotlist .source-name {
                color: #587a9d;
                font-size: 12px;
                font-weight: 600;
            }

            body.pulse-static .header {
                margin-bottom: 14px !important;
                box-shadow: 0 10px 24px rgba(104, 124, 151, 0.08) !important;
            }

            body.pulse-static .pulse-filter-card {
                box-shadow: 0 6px 16px rgba(107, 126, 151, 0.05) !important;
            }

            body.pulse-static .dashboard-rss .rss-item {
                display: grid !important;
                grid-template-columns: 28px minmax(0, 1fr) !important;
                align-items: start !important;
                gap: 12px !important;
            }

            body.pulse-static .dashboard-rss .rss-item > :not(.news-number) {
                min-width: 0;
            }

            body.pulse-static .dashboard-rss .news-number {
                margin-top: 2px;
            }

            @media (max-width: 1120px) {
                .header-shell {
                    grid-template-columns: 1fr;
                }

                .header-left,
                .header-right {
                    max-width: none;
                    width: 100%;
                }

                .dashboard-grid {
                    grid-template-columns: 1fr;
                }

                .ai-grid {
                    grid-template-columns: 1fr;
                }

                .social-grid {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }

                .social-item-has-comments {
                    grid-template-columns: 1fr;
                }

                .social-item-has-comments .social-post-side {
                    padding: 18px 18px 16px;
                }
            }

            @media (max-width: 760px) {
                .ai-overview-detail-grid {
                    grid-template-columns: 1fr;
                }

                .ai-flip-card {
                    min-height: 396px;
                }

                .ai-flip-card-inner {
                    min-height: 396px;
                }

                .ai-overview-summary-head,
                .ai-grid-head {
                    display: grid;
                    gap: 10px;
                }

                .ai-overview-summary-meta,
                .ai-overview-event-meta {
                    justify-content: flex-start;
                }

                .ai-overview-summary-meta {
                    align-items: flex-start;
                }

                .ai-cluster-event-meta {
                    display: grid;
                    gap: 2px;
                }

                .ai-cluster-event-time {
                    text-align: left;
                }

            }

            @media (max-width: 480px) {
                body { padding: 12px; }
                .header { padding: 24px 20px; }
                .header-shell { gap: 16px; }
                .content { padding: 16px; }
                .footer { padding: 16px 20px; }
                .header-info { grid-template-columns: 1fr; gap: 12px; }
                .header-title { padding-right: 0; }
                .filter-card-body { grid-template-columns: 1fr; }
                .news-header { gap: 6px; }
                .news-item { gap: 8px; }
                .new-item { gap: 8px; }
                .news-number { width: 20px; height: 20px; font-size: 12px; }
                .dashboard-card { padding: 16px; border-radius: 18px; }
                .save-buttons {
                    position: static;
                    margin-bottom: 16px;
                    display: flex;
                    gap: 8px;
                    justify-content: center;
                    flex-direction: column;
                    width: 100%;
                }
                .save-btn {
                    width: 100%;
                }

                .social-grid {
                    grid-template-columns: 1fr;
                }

                .social-item {
                    height: 270px;
                    min-height: 270px;
                    padding: 0;
                }

                .social-item.social-item-has-comments {
                    padding: 0;
                }

                .social-post-side {
                    padding: 15px 16px 11px;
                }
            }

            /* RSS 订阅内容样式 */
            .rss-section {
                margin-top: 32px;
                padding-top: 24px;
            }

            .rss-section-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 20px;
                padding-bottom: 12px;
                border-bottom: 1px solid #dbe4ee;
            }

            .rss-section-title {
                font-family: 'Noto Serif SC', serif;
                font-size: 20px;
                font-weight: 700;
                color: #2e302b;
                letter-spacing: 0.01em;
            }

            .rss-section-count {
                color: #6b7280;
                font-size: 14px;
            }

            .feed-group {
                margin-bottom: 18px;
                padding: 0;
                border-radius: 0;
                background: transparent;
                border: none;
            }

            .feed-group:last-child {
                margin-bottom: 0;
            }

            .feed-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 12px;
                padding: 0 2px 10px;
                border-bottom: 1px solid rgba(186, 201, 220, 0.72);
            }

            .feed-name {
                font-family: 'Noto Serif SC', serif;
                font-size: 17px;
                font-weight: 700;
                color: #274663;
                letter-spacing: 0.01em;
            }

            .feed-count {
                color: #5d7691;
                background: linear-gradient(180deg, rgba(246, 250, 253, 0.98) 0%, rgba(238, 244, 249, 0.98) 100%);
                font-size: 12px;
                font-weight: 700;
                min-height: 34px;
                padding: 0 14px 0 12px;
                border-radius: 999px;
                border: 1px solid rgba(195, 208, 224, 0.96);
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.92);
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
                letter-spacing: 0.01em;
            }

            .feed-count::before {
                content: "";
                width: 10px;
                height: 10px;
                border-radius: 50%;
                background: #6fa58d;
                box-shadow: 0 0 0 4px rgba(111, 165, 141, 0.12);
                flex-shrink: 0;
            }

            .rss-item {
                margin-bottom: 12px;
                padding: 14px;
                background: linear-gradient(180deg, rgba(255,255,255,0.995) 0%, rgba(248,251,254,0.995) 100%);
                border-radius: 14px;
                border: 1px solid rgba(193, 208, 226, 0.9);
                box-shadow: 0 12px 24px rgba(107, 126, 151, 0.09);
                position: relative;
            }

            .rss-item:last-child {
                margin-bottom: 0;
            }

            .rss-meta {
                display: flex;
                align-items: center;
                gap: 12px;
                margin-bottom: 6px;
                flex-wrap: wrap;
            }

            .rss-time {
                color: #5f7893;
                font-size: 12px;
            }

            .rss-author {
                color: #587a9d;
                font-size: 12px;
                font-weight: 600;
            }

            .rss-title {
                font-size: 14px;
                line-height: 1.5;
                margin-bottom: 6px;
            }

            .rss-link {
                color: #183450;
                text-decoration: none;
                font-weight: 600;
            }

            .rss-link:hover {
                color: #2d748d;
                text-decoration: underline;
            }

            .rss-summary {
                font-size: 13px;
                color: #47617c;
                line-height: 1.5;
                margin: 0;
                display: -webkit-box;
                -webkit-line-clamp: 2;
                -webkit-box-orient: vertical;
                overflow: hidden;
            }

            /* 独立展示区样式 - 复用热点词汇统计区样式 */
            .standalone-section {
                margin-top: 32px;
                padding-top: 24px;
            }

            .standalone-section-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 20px;
            }

            .standalone-section-title {
                font-size: 18px;
                font-weight: 600;
                color: #059669;
            }

            .standalone-section-count {
                color: #6b7280;
                font-size: 14px;
            }

            .standalone-group {
                margin-bottom: 40px;
            }

            .standalone-group:last-child {
                margin-bottom: 0;
            }

            .standalone-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 20px;
                padding-bottom: 8px;
                border-bottom: 1px solid #f0f0f0;
            }

            .standalone-name {
                font-size: 17px;
                font-weight: 600;
                color: #1a1a1a;
            }

            .standalone-count {
                color: #666;
                font-size: 13px;
                font-weight: 500;
            }

            /* AI 分析区块样式 */
            .ai-section {
                margin-top: 32px;
                padding: 0;
                background: transparent;
                border-radius: 0;
                border: none;
            }

            .ai-section-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 20px;
                padding-bottom: 12px;
                border-bottom: 1px solid #dbe4ee;
            }

            .ai-section-title {
                font-family: 'Noto Serif SC', serif;
                font-size: 20px;
                font-weight: 700;
                color: #1f2d46;
                letter-spacing: 0.01em;
            }

            .ai-section-badge {
                background: linear-gradient(180deg, #eefaff 0%, #dceff8 100%);
                color: #2b6f89;
                font-size: 11px;
                font-weight: 700;
                padding: 4px 9px;
                border-radius: 999px;
                border: 1px solid rgba(102, 167, 198, 0.24);
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.84);
            }

            .ai-block {
                margin-bottom: 14px;
                padding: 16px 18px;
                background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
                border-radius: 16px;
                border: 1px solid #e2e8f0;
                box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
            }

            .ai-block:last-child {
                margin-bottom: 0;
            }

            .ai-block-title {
                font-size: 14px;
                font-weight: 700;
                color: #24435d;
                margin-bottom: 10px;
            }

            .ai-block-content {
                font-size: 13px;
                line-height: 1.7;
                color: #233247;
                font-weight: 500;
                white-space: pre-wrap;
            }

            .ai-error {
                padding: 16px;
                background: #fef2f2;
                border: 1px solid #fecaca;
                border-radius: 8px;
                color: #991b1b;
                font-size: 14px;
            }

            body.pulse-static .pulse-static-archive-days {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 18px;
            }

            body.pulse-static .pulse-static-archive-day {
                display: flex;
                flex-direction: column;
                align-items: flex-start;
                justify-content: space-between;
                min-height: 168px;
                padding: 18px 18px 20px;
                border-radius: 24px;
                border: 1px solid rgba(220, 228, 238, 0.94);
                background: rgba(255, 255, 255, 0.98);
                box-shadow: 0 10px 26px rgba(184, 196, 214, 0.11);
                cursor: pointer;
                transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
                text-decoration: none;
            }

            body.pulse-static .pulse-static-archive-day:hover {
                transform: translateY(-4px);
                box-shadow: 0 16px 36px rgba(96, 123, 171, 0.12);
                border-color: rgba(177, 196, 225, 0.95);
            }

            body.pulse-static .pulse-static-archive-date {
                font-weight: 800;
                font-size: 28px;
                color: #0f172a;
                letter-spacing: -0.01em;
                line-height: 1.05;
                text-align: left;
            }

            body.pulse-static .pulse-static-archive-label {
                display: inline-flex;
                align-items: center;
                min-height: 32px;
                padding: 0 12px;
                border-radius: 12px;
                background: rgba(241, 246, 252, 0.96);
                color: #4d6382;
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 0.04em;
                text-transform: uppercase;
            }

            body.pulse-static .pulse-static-archive-copy {
                color: #70819b;
                font-size: 13px;
                line-height: 1.7;
            }

            body.pulse-static .pulse-static-archive-empty {
                padding: 14px 14px;
                border-radius: 16px;
                border: 1px dashed rgba(148, 163, 184, 0.7);
                background: rgba(248, 250, 252, 0.85);
                color: rgba(71, 85, 105, 0.9);
                font-size: 13px;
                font-weight: 700;
                line-height: 1.7;
            }

            @media (max-width: 1040px) {
                body.pulse-static .pulse-static-archive-days {
                    grid-template-columns: 1fr;
                }
            }

            /* 全站圆角收敛：保留头像、LOGO、状态点等圆形元素，只收卡片/按钮/标签。 */
            body.pulse-static .header,
            body.pulse-static .dashboard-card,
            body.pulse-static .dashboard-hotlist,
            body.pulse-static .dashboard-rss,
            body.pulse-static .dashboard-ai,
            body.pulse-static .dashboard-social,
            body.pulse-static .pulse-static-sources,
            body.pulse-static .pulse-panel,
            body.pulse-static .pulse-overview-card,
            body.pulse-static .pulse-overview-stats,
            body.pulse-static .pulse-overview-radar-floor,
            body.pulse-static .pulse-overview-chart-card,
            body.pulse-static .pulse-topic-carousel {
                border-radius: 20px !important;
            }

            body.pulse-static .pulse-overview-stat,
            body.pulse-static .pulse-filter-card,
            body.pulse-static .pulse-static-source-card,
            body.pulse-static .pulse-static-archive-day,
            body.pulse-static .ai-overview-summary,
            body.pulse-static .ai-grid-card,
            body.pulse-static .ai-flip-card-face,
            body.pulse-static .filter-card,
            body.pulse-static .info-item {
                border-radius: 16px !important;
            }

            body.pulse-static .pulse-overview-stat {
                border-radius: var(--po-stat-radius) !important;
            }

            body.pulse-static .pulse-overview-matrix-card,
            body.pulse-static .news-item,
            body.pulse-static .rss-item,
            body.pulse-static .social-item,
            body.pulse-static .ai-block,
            body.pulse-static .source-strip-shell,
            body.pulse-static .ai-overview-detail,
            body.pulse-static .ai-cluster-event-placeholder,
            body.pulse-static .pulse-static-archive-empty {
                border-radius: 12px !important;
            }

            body.pulse-static .pulse-static-nav a,
            body.pulse-static .pulse-static-source-tab,
            body.pulse-static .pulse-static-source-status,
            body.pulse-static .pulse-static-source-tag,
            body.pulse-static .pulse-overview-eyebrow,
            body.pulse-static .pulse-filter-pill,
            body.pulse-static .word-count,
            body.pulse-static .rank-num,
            body.pulse-static .keyword-tag,
            body.pulse-static .dashboard-card-meta,
            body.pulse-static .feed-count,
            body.pulse-static .ai-section-badge,
            body.pulse-static .source-strip-chip,
            body.pulse-static .ai-overview-pill,
            body.pulse-static .ai-overview-pill-button,
            body.pulse-static .ai-flip-card-back-button,
            body.pulse-static .pulse-static-archive-label,
            body.pulse-static .save-btn {
                border-radius: 10px !important;
            }

            body.pulse-static .ai-cluster-event-item,
            body.pulse-static .ai-overview-detail,
            body.pulse-static .new-item-rank,
            body.pulse-static .error-section,
            body.pulse-static .ai-error {
                border-radius: 8px !important;
            }

            body.pulse-static .source-strip-chip {
                border-radius: 999px !important;
            }
        </style>
    </head>
        <body class="pulse-static pulse-static-booting">
        <aside class="pulse-static-sidebar">
            <div class="pulse-static-brand">
                <div class="pulse-static-brand-head">
                    <div class="pulse-static-brand-mark" aria-hidden="true">
                        <svg viewBox="0 0 88 88" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <defs>
                                <linearGradient id="pulse-radar-brand" x1="17" y1="18" x2="70" y2="71" gradientUnits="userSpaceOnUse">
                                    <stop stop-color="#A1E0C8"/>
                                    <stop offset="0.46" stop-color="#84D5D1"/>
                                    <stop offset="1" stop-color="#77A6E5"/>
                                </linearGradient>
                            </defs>
                            <circle cx="44" cy="44" r="30" stroke="url(#pulse-radar-brand)" stroke-width="5.5"/>
                            <circle cx="44" cy="44" r="18" stroke="#D6E4F3" stroke-width="4"/>
                            <path d="M44 44L65 25" stroke="#365B91" stroke-width="5.5" stroke-linecap="round"/>
                            <circle cx="65" cy="25" r="6" fill="#77A6E5"/>
                            <path d="M22 57.5C26.2 57.5 27.7 50 31.8 50C35.2 50 36.4 56.2 40.4 56.2C45.1 56.2 46.7 45.2 50.8 45.2C54 45.2 55.3 50.8 60.5 50.8" stroke="#86D3CF" stroke-width="4.3" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </div>
                    <div class="pulse-static-brand-copy">
                        <div class="pulse-static-title">Pulse Observer</div>
                        <div class="pulse-static-note">你的每日舆情动向观察台</div>
                    </div>
                </div>
            </div>
            <nav class="pulse-static-nav">
                <a href="#overview" class="is-active">首页概览</a>
                <a href="#ai-insight">AI 洞察</a>
                <a href="#media">媒体观测</a>
                <a href="#hotlist">热榜监测</a>
                <a href="#website">网站监测</a>
                <a href="#sources">信源汇总</a>
                <a href="#archive">查看归档</a>
            </nav>
        </aside>
        <div class="pulse-static-main">
        <div class="container">
            <div class="header">
                <div class="header-title">Pulse Observer</div>
                <div class="pulse-static-subtitle">在一个界面里浏览媒体观测、热榜监测、网站监测与 AI 洞察。</div>
                <div class="header-shell">
                    <div class="header-left">
                        <div class="header-info">
                    <div class="info-item">
                        <span class="info-label">报告类型</span>
                        <span class="info-value">"""

    # 处理报告类型显示（根据 mode 直接显示）
    if mode == "current":
        html += "当前榜单"
    elif mode == "incremental":
        html += "增量分析"
    else:
        html += "全天汇总"

    html += """</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">新闻总数</span>
                        <span class="info-value">"""

    html += f"{total_titles} 条"

    # 计算最终入选的热榜+网站新闻数量
    hotlist_selected_count = sum(
        len(stat.get("titles", [])) for stat in report_data.get("stats", [])
    )
    rss_selected_count = sum(
        len(stat.get("titles", [])) for stat in (rss_items or [])
    )
    selected_news_count = hotlist_selected_count + rss_selected_count

    html += """</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">入选新闻</span>
                        <span class="info-value">"""

    html += f"{selected_news_count} 条"

    html += """</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">生成时间</span>
                        <span class="info-value">"""

    # 使用提供的时间函数或默认 datetime.now
    if get_time_func:
        now = get_time_func()
    else:
        now = datetime.now()
    html += now.strftime("%m-%d %H:%M")

    filter_snapshot = load_filter_snapshot()
    topic_items_html = "".join(
        f'<div class="filter-topic-item">{idx}. {html_escape(topic)}</div>'
        for idx, topic in enumerate(filter_snapshot["topics"], start=1)
    )
    process_items_html = "".join(
        [
            '<div class="filter-step-item">1. 全量抓取热榜与重点网站原始内容。</div>',
            '<div class="filter-step-item">2. 仅围绕涉华争议、风险信号、跨平台扩散议题做 AI 分类。</div>',
            f'<div class="filter-step-item">3. 相关度分数需达到 score ≥ {filter_snapshot["min_score"]:.2f} 才进入最终展示。</div>',
            f'<div class="filter-step-item">4. RSS 仅保留近 {filter_snapshot["rss_age_days"]} 天内容。</div>',
            '<div class="filter-step-item">5. 过滤普通通知、常规科普、低信息量奇闻、营销导流和弱涉华内容。</div>',
        ]
    )
    filter_card_html = f"""
                    <div class="filter-card">
                        <div class="filter-card-header">
                            <div class="filter-card-title">筛选过程</div>
                            <div class="filter-card-badge">本轮规则</div>
                        </div>
                        <div class="filter-card-body">
                            <div class="filter-card-block filter-card-block-topics">
                                <div class="filter-card-label">主题焦点</div>
                                <div class="filter-topic-list">{topic_items_html}</div>
                            </div>
                            <div class="filter-card-block">
                                <div class="filter-card-label">判定标准</div>
                                <div class="filter-rule-text">优先保留可能引发公共争议、情绪波动、跨平台传播、持续发酵和涉华叙事升级的内容；弱争议、弱涉华、低信息量内容默认降权过滤。</div>
                                <div class="filter-metrics">
                                    <span class="filter-metric">AI 阈值 {filter_snapshot["min_score"]:.2f}</span>
                                    <span class="filter-metric">RSS {filter_snapshot["rss_age_days"]} 天内</span>
                                </div>
                            </div>
                            <div class="filter-card-block">
                                <div class="filter-card-label">执行流程</div>
                                <div class="filter-step-list">{process_items_html}</div>
                            </div>
                        </div>
                    </div>"""

    html += """</span>
                    </div>
                </div>
                    </div>"""

    html += f"""
                    <div class="header-right">
                        {filter_card_html}
                    </div>"""

    html += """
                </div>
            </div>

            <div class="content">"""

    priority_topic_order = ["国际涉华", "港澳台海"]
    deferred_topic_order = ["宏观经济", "地产债务", "市场金融", "外贸供应链", "能源商品"]

    def sort_topic_groups(groups: List[Dict]) -> List[Dict]:
        if not groups:
            return []

        priority_rank = {name: idx for idx, name in enumerate(priority_topic_order)}
        deferred_rank = {name: idx for idx, name in enumerate(deferred_topic_order)}

        def sort_key(group: Dict) -> tuple:
            name = group.get("word", "")
            if name in priority_rank:
                return (0, priority_rank[name], 0)
            if name in deferred_rank:
                return (2, deferred_rank[name], 0)
            return (1, 0, 0)

        return sorted(groups, key=sort_key)

    # 生成热点词汇统计部分的HTML
    stats_html = ""
    if report_data["stats"]:
        sorted_stats = sort_topic_groups(report_data["stats"])
        total_count = len(sorted_stats)

        for i, stat in enumerate(sorted_stats, 1):
            count = stat["count"]

            # 确定热度等级
            if count >= 10:
                count_class = "hot"
            elif count >= 5:
                count_class = "warm"
            else:
                count_class = ""

            escaped_word = html_escape(stat["word"])

            stats_html += f"""
                <div class="word-group">
                    <div class="word-header">
                        <div class="word-info">
                            <div class="word-name">{escaped_word}</div>
                            <div class="word-count {count_class}">{count} 条</div>
                        </div>
                        <div class="word-index">{i}/{total_count}</div>
                    </div>"""

            # 处理每个词组下的新闻标题，给每条新闻标上序号
            for j, title_data in enumerate(stat["titles"], 1):
                stats_html += f"""
                    <div class="news-item">
                        <div class="news-number">{j}</div>
                        <div class="news-content">
                            <div class="news-header">"""

                # 根据 display_mode 决定显示来源还是关键词
                if display_mode == "keyword":
                    # keyword 模式：显示来源
                    stats_html += f'<span class="source-name">{html_escape(title_data["source_name"])}</span>'
                else:
                    # platform 模式：显示关键词
                    matched_keyword = title_data.get("matched_keyword", "")
                    if matched_keyword:
                        stats_html += f'<span class="keyword-tag">[{html_escape(matched_keyword)}]</span>'

                # 处理排名显示
                ranks = title_data.get("ranks", [])
                if ranks:
                    min_rank = min(ranks)
                    max_rank = max(ranks)
                    rank_threshold = title_data.get("rank_threshold", 10)

                    # 确定排名等级
                    if min_rank <= 3:
                        rank_class = "top"
                    elif min_rank <= rank_threshold:
                        rank_class = "high"
                    else:
                        rank_class = ""

                    if min_rank == max_rank:
                        rank_text = str(min_rank)
                    else:
                        rank_text = f"{min_rank}-{max_rank}"

                    stats_html += f'<span class="rank-num {rank_class}">{rank_text}</span>'

                # 处理时间显示
                time_display = title_data.get("time_display", "")
                if time_display:
                    # 简化时间显示格式，将波浪线替换为~
                    simplified_time = (
                        time_display.replace(" ~ ", "~")
                        .replace("[", "")
                        .replace("]", "")
                    )
                    stats_html += (
                        f'<span class="time-info">{html_escape(simplified_time)}</span>'
                    )

                # 处理出现次数
                count_info = title_data.get("count", 1)
                if count_info > 1:
                    pass

                stats_html += """
                            </div>
                            <div class="news-title">"""

                # 处理标题和链接
                escaped_title = html_escape(title_data["title"])
                link_url = title_data.get("mobile_url") or title_data.get("url", "")

                if link_url:
                    escaped_url = html_escape(link_url)
                    stats_html += f'<a href="{escaped_url}" target="_blank" class="news-link">{escaped_title}</a>'
                else:
                    stats_html += escaped_title

                stats_html += """
                                </div>
                            </div>
                    </div>"""

            stats_html += """
                </div>"""

    # 给热榜统计添加外层包装
    if stats_html:
        stats_html = f"""
                <div class="hotlist-section">{stats_html}
                </div>"""

    # 生成新增新闻区域的HTML
    new_titles_html = ""
    if show_new_section and report_data["new_titles"]:
        new_titles_html += f"""
                <div class="new-section">
                    <div class="new-section-title">本次新增热点 (共 {report_data['total_new_count']} 条)</div>"""

        for source_data in report_data["new_titles"]:
            escaped_source = html_escape(source_data["source_name"])
            titles_count = len(source_data["titles"])

            new_titles_html += f"""
                    <div class="new-source-group">
                        <div class="new-source-title">{escaped_source} · {titles_count}条</div>"""

            # 为新增新闻也添加序号
            for idx, title_data in enumerate(source_data["titles"], 1):
                ranks = title_data.get("ranks", [])

                # 处理新增新闻的排名显示
                rank_class = ""
                if ranks:
                    min_rank = min(ranks)
                    if min_rank <= 3:
                        rank_class = "top"
                    elif min_rank <= title_data.get("rank_threshold", 10):
                        rank_class = "high"

                    if len(ranks) == 1:
                        rank_text = str(ranks[0])
                    else:
                        rank_text = f"{min(ranks)}-{max(ranks)}"
                else:
                    rank_text = "?"

                new_titles_html += f"""
                        <div class="new-item">
                            <div class="new-item-number">{idx}</div>
                            <div class="new-item-rank {rank_class}">{rank_text}</div>
                            <div class="new-item-content">
                                <div class="new-item-title">"""

                # 处理新增新闻的链接
                escaped_title = html_escape(title_data["title"])
                link_url = title_data.get("mobile_url") or title_data.get("url", "")

                if link_url:
                    escaped_url = html_escape(link_url)
                    new_titles_html += f'<a href="{escaped_url}" target="_blank" class="news-link">{escaped_title}</a>'
                else:
                    new_titles_html += escaped_title

                new_titles_html += """
                                </div>
                            </div>
                        </div>"""

            new_titles_html += """
                    </div>"""

        new_titles_html += """
                </div>"""

    # 生成 RSS 统计内容
    def render_rss_stats_html(stats: List[Dict], title: str = "RSS 订阅更新") -> str:
        """渲染 RSS 统计区块 HTML

        Args:
            stats: RSS 分组统计列表，格式与热榜一致：
                [
                    {
                        "word": "关键词",
                        "count": 5,
                        "titles": [
                            {
                                "title": "标题",
                                "source_name": "Feed 名称",
                                "time_display": "12-29 08:20",
                                "url": "...",
                                "is_new": True/False
                            }
                        ]
                    }
                ]
            title: 区块标题

        Returns:
            渲染后的 HTML 字符串
        """
        if not stats:
            return ""

        stats = sort_topic_groups(stats)

        # 计算总条目数
        total_count = sum(stat.get("count", 0) for stat in stats)
        if total_count == 0:
            return ""

        rss_html = f"""
                <div class="rss-section">
                    <div class="rss-section-header">
                        <div class="rss-section-title">{title}</div>
                        <div class="rss-section-count">{total_count} 条</div>
                    </div>"""

        # 按关键词分组渲染（与热榜格式一致）
        for stat in stats:
            keyword = stat.get("word", "")
            titles = stat.get("titles", [])
            if not titles:
                continue

            keyword_count = len(titles)

            rss_html += f"""
                    <div class="feed-group">
                        <div class="feed-header">
                            <div class="feed-name">{html_escape(keyword)}</div>
                            <div class="feed-count">{keyword_count} 条</div>
                        </div>"""

            for idx, title_data in enumerate(titles, 1):
                item_title = title_data.get("title", "")
                url = title_data.get("url", "")
                time_display = title_data.get("time_display", "") or now.strftime("%m-%d %H:%M")
                source_name = title_data.get("source_name", "")

                rss_html += """
                        <div class="rss-item">
                            <div class="news-number">""" + str(idx) + """</div>
                            <div class="rss-item-body">
                                <div class="rss-meta">"""

                if source_name:
                    rss_html += f'<span class="rss-author">{html_escape(source_name)}</span>'

                if time_display:
                    rss_html += f'<span class="rss-time">{html_escape(time_display)}</span>'

                rss_html += """
                                </div>
                                <div class="rss-title">"""

                escaped_title = html_escape(item_title)
                if url:
                    escaped_url = html_escape(url)
                    rss_html += f'<a href="{escaped_url}" target="_blank" class="rss-link">{escaped_title}</a>'
                else:
                    rss_html += escaped_title

                rss_html += """
                                </div>
                            </div>
                        </div>"""

            rss_html += """
                    </div>"""

        rss_html += """
                </div>"""
        return rss_html

    # 生成独立展示区内容
    def render_standalone_html(data: Optional[Dict]) -> str:
        """渲染独立展示区 HTML（复用热点词汇统计区样式）

        Args:
            data: 独立展示数据，格式：
                {
                    "platforms": [
                        {
                            "id": "zhihu",
                            "name": "知乎热榜",
                            "items": [
                                {
                                    "title": "标题",
                                    "url": "链接",
                                    "rank": 1,
                                    "ranks": [1, 2, 1],
                                    "first_time": "08:00",
                                    "last_time": "12:30",
                                    "count": 3,
                                }
                            ]
                        }
                    ],
                    "rss_feeds": [
                        {
                            "id": "hacker-news",
                            "name": "Hacker News",
                            "items": [
                                {
                                    "title": "标题",
                                    "url": "链接",
                                    "published_at": "2025-01-07T08:00:00",
                                    "author": "作者",
                                }
                            ]
                        }
                    ]
                }

        Returns:
            渲染后的 HTML 字符串
        """
        if not data:
            return ""

        platforms = data.get("platforms", [])
        rss_feeds = data.get("rss_feeds", [])

        if not platforms and not rss_feeds:
            return ""

        # 计算总条目数
        total_platform_items = sum(len(p.get("items", [])) for p in platforms)
        total_rss_items = sum(len(f.get("items", [])) for f in rss_feeds)
        total_count = total_platform_items + total_rss_items

        if total_count == 0:
            return ""

        standalone_html = f"""
                <div class="standalone-section">
                    <div class="standalone-section-header">
                        <div class="standalone-section-title">独立展示区</div>
                        <div class="standalone-section-count">{total_count} 条</div>
                    </div>"""

        # 渲染热榜平台（复用 word-group 结构）
        for platform in platforms:
            platform_name = platform.get("name", platform.get("id", ""))
            items = platform.get("items", [])
            if not items:
                continue

            standalone_html += f"""
                    <div class="standalone-group">
                        <div class="standalone-header">
                            <div class="standalone-name">{html_escape(platform_name)}</div>
                            <div class="standalone-count">{len(items)} 条</div>
                        </div>"""

            # 渲染每个条目（复用 news-item 结构）
            for j, item in enumerate(items, 1):
                title = item.get("title", "")
                url = item.get("url", "") or item.get("mobileUrl", "")
                rank = item.get("rank", 0)
                ranks = item.get("ranks", [])
                first_time = item.get("first_time", "")
                last_time = item.get("last_time", "")
                count = item.get("count", 1)

                standalone_html += f"""
                        <div class="news-item">
                            <div class="news-number">{j}</div>
                            <div class="news-content">
                                <div class="news-header">"""

                # 排名显示（复用 rank-num 样式，无 # 前缀）
                if ranks:
                    min_rank = min(ranks)
                    max_rank = max(ranks)

                    # 确定排名等级
                    if min_rank <= 3:
                        rank_class = "top"
                    elif min_rank <= 10:
                        rank_class = "high"
                    else:
                        rank_class = ""

                    if min_rank == max_rank:
                        rank_text = str(min_rank)
                    else:
                        rank_text = f"{min_rank}-{max_rank}"

                    standalone_html += f'<span class="rank-num {rank_class}">{rank_text}</span>'
                elif rank > 0:
                    if rank <= 3:
                        rank_class = "top"
                    elif rank <= 10:
                        rank_class = "high"
                    else:
                        rank_class = ""
                    standalone_html += f'<span class="rank-num {rank_class}">{rank}</span>'

                # 时间显示（复用 time-info 样式，将 HH-MM 转换为 HH:MM）
                if first_time and last_time and first_time != last_time:
                    first_time_display = convert_time_for_display(first_time)
                    last_time_display = convert_time_for_display(last_time)
                    standalone_html += f'<span class="time-info">{html_escape(first_time_display)}~{html_escape(last_time_display)}</span>'
                elif first_time:
                    first_time_display = convert_time_for_display(first_time)
                    standalone_html += f'<span class="time-info">{html_escape(first_time_display)}</span>'

                # 出现次数（复用 count-info 样式）
                if count > 1:
                    pass

                standalone_html += """
                                </div>
                                <div class="news-title">"""

                # 标题和链接（复用 news-link 样式）
                escaped_title = html_escape(title)
                if url:
                    escaped_url = html_escape(url)
                    standalone_html += f'<a href="{escaped_url}" target="_blank" class="news-link">{escaped_title}</a>'
                else:
                    standalone_html += escaped_title

                standalone_html += """
                                </div>
                            </div>
                        </div>"""

            standalone_html += """
                    </div>"""

        # 渲染 RSS 源（复用相同结构）
        for feed in rss_feeds:
            feed_name = feed.get("name", feed.get("id", ""))
            items = feed.get("items", [])
            if not items:
                continue

            standalone_html += f"""
                    <div class="standalone-group">
                        <div class="standalone-header">
                            <div class="standalone-name">{html_escape(feed_name)}</div>
                            <div class="standalone-count">{len(items)} 条</div>
                        </div>"""

            for j, item in enumerate(items, 1):
                title = item.get("title", "")
                url = item.get("url", "")
                published_at = item.get("published_at", "")
                author = item.get("author", "")

                standalone_html += f"""
                        <div class="news-item">
                            <div class="news-number">{j}</div>
                            <div class="news-content">
                                <div class="news-header">"""

                # 时间显示（格式化 ISO 时间）
                if published_at:
                    try:
                        from datetime import datetime as dt
                        if "T" in published_at:
                            dt_obj = dt.fromisoformat(published_at.replace("Z", "+00:00"))
                            time_display = dt_obj.strftime("%m-%d %H:%M")
                        else:
                            time_display = published_at
                    except:
                        time_display = published_at

                    standalone_html += f'<span class="time-info">{html_escape(time_display)}</span>'

                # 作者显示
                if author:
                    standalone_html += f'<span class="source-name">{html_escape(author)}</span>'

                standalone_html += """
                                </div>
                                <div class="news-title">"""

                escaped_title = html_escape(title)
                if url:
                    escaped_url = html_escape(url)
                    standalone_html += f'<a href="{escaped_url}" target="_blank" class="news-link">{escaped_title}</a>'
                else:
                    standalone_html += escaped_title

                standalone_html += """
                                </div>
                            </div>
                        </div>"""

            standalone_html += """
                    </div>"""

        standalone_html += """
                </div>"""
        return standalone_html

    def render_social_media_html(items: Optional[List[Dict]]) -> str:
        """生成社交媒体观察区。"""
        if not items:
            return ""

        member_profile_cache = load_member_profiles_cache()

        def normalize_reddit_subreddit(raw_value: Any) -> str:
            label = str(raw_value or "").strip()
            if not label:
                return ""
            match = re.search(r"/r/([^/?#]+)", label, flags=re.IGNORECASE)
            if match:
                label = str(match.group(1) or "").strip()
            label = re.sub(r"^\s*r/", "", label, flags=re.IGNORECASE)
            label = re.sub(r"^https?://(?:www\.)?reddit\.com/r/", "", label, flags=re.IGNORECASE)
            label = re.sub(r"/\.rss(\?.*)?$", "", label, flags=re.IGNORECASE)
            label = re.sub(r"\.rss(\?.*)?$", "", label, flags=re.IGNORECASE)
            label = re.sub(r"\?raw_json=1$", "", label, flags=re.IGNORECASE)
            label = label.strip().strip("/")
            return label

        def normalize_reddit_community_label(item: Dict) -> str:
            metadata = item.get("metadata", {}) or {}
            display_name = str(metadata.get("display_name", "") or "").strip()
            if display_name:
                return display_name
            candidates = [
                metadata.get("subreddit", ""),
                metadata.get("feed_name", ""),
            ]
            tags = item.get("tags", []) or []
            if tags:
                candidates.append(tags[0])

            for raw in candidates:
                label = str(raw or "").strip()
                if not label:
                    continue
                label = re.sub(r"^\s*r/", "", label, flags=re.IGNORECASE)
                label = re.sub(r"\.rss(\?.*)?$", "", label, flags=re.IGNORECASE)
                label = re.sub(r"\?raw_json=1$", "", label, flags=re.IGNORECASE)
                label = re.sub(r"^Reddit\s+源\s+\d+$", "", label, flags=re.IGNORECASE)
                if label:
                    return label

            source_name = str(item.get("source_name", "")).strip()
            if source_name:
                return source_name
            return "Reddit"

        def resolve_social_profile(item: Dict) -> Dict[str, str]:
            metadata = item.get("metadata", {}) or {}
            raw_platform = str(item.get("platform", "")).strip().lower()
            profile: Dict[str, Any] = {}

            if raw_platform == "x":
                username = str(metadata.get("username", "") or "").strip().lstrip("@")
                if not username:
                    match = re.search(r"x\.com/([^/?#]+)/status/", str(item.get("url", "") or ""), flags=re.IGNORECASE)
                    username = str(match.group(1) if match else "").strip().lstrip("@")
                if username:
                    profile = dict(member_profile_cache.get(f"x:@{username}") or {})
                display_name = str(
                    profile.get("display_name")
                    or metadata.get("display_name")
                    or item.get("author")
                    or item.get("source_name")
                    or ""
                ).strip()
                return {
                    "display_name": display_name,
                    "logo_url": infer_member_logo_url(profile),
                    "fallback": "X",
                }

            if raw_platform == "reddit":
                subreddit = ""
                for candidate in (
                    metadata.get("subreddit"),
                    metadata.get("feed_name"),
                    *(item.get("tags", []) or []),
                    item.get("url"),
                ):
                    subreddit = normalize_reddit_subreddit(candidate)
                    if subreddit:
                        break
                if subreddit:
                    profile = dict(member_profile_cache.get(f"reddit:r/{subreddit}") or {})
                display_name = str(profile.get("display_name") or "").strip() or normalize_reddit_community_label(item)
                return {
                    "display_name": display_name,
                    "logo_url": infer_member_logo_url(profile),
                    "fallback": "R",
                }

            display_name = str(metadata.get("display_name", "") or item.get("author", "") or item.get("source_name", "")).strip()
            fallback = str(item.get("platform", "")).upper().strip() or "S"
            return {
                "display_name": display_name,
                "logo_url": "",
                "fallback": fallback[:2],
            }

        def render_social_avatar(item: Dict) -> str:
            profile = resolve_social_profile(item)
            logo_url = html_escape(profile.get("logo_url", ""))
            fallback = html_escape(profile.get("fallback", "S"))
            label = html_escape(profile.get("display_name", fallback))
            if logo_url:
                return f'<span class="social-platform" aria-label="{label}"><img src="{logo_url}" alt="{label}"></span>'
            return f'<span class="social-platform" aria-label="{label}"><span class="social-platform-fallback">{fallback}</span></span>'

        platforms = []
        source_names = []
        seen_platforms = set()
        seen_sources = set()
        for item in items:
            platform = str(item.get("platform", "")).strip()
            source_name = str(item.get("source_name", "")).strip()
            if platform and platform not in seen_platforms:
                seen_platforms.add(platform)
                platforms.append(platform.upper() if platform.lower() == "x" else platform.capitalize())
            if source_name and source_name not in seen_sources:
                seen_sources.add(source_name)
                source_names.append(source_name)

        source_updates: Dict[str, str] = {}
        for item in items:
            source_name = str(item.get("source_name", "")).strip()
            if not source_name:
                continue
            metadata = item.get("metadata", {}) or {}
            sync_value = str(metadata.get("cache_generated_at", "") or item.get("published_at", "") or "").strip()
            if not sync_value:
                continue
            current = source_updates.get(source_name, "")
            if not current or sync_value > current:
                source_updates[source_name] = sync_value

        total_count = len(items)
        html_parts = [
            """
                <div class="social-section">
                    <div class="rss-section-header">
                        <div class="rss-section-title">社交媒体观察</div>
                        <div class="rss-section-count">"""
            + f"{total_count} 条"
            + """</div>
                    </div>
            """
        ]

        if source_names:
            html_parts.append(
                '<div class="social-sources">观察来源：'
                + html_escape("、".join(source_names))
                + "。"
                + (f" 平台：{html_escape(' / '.join(platforms))}。" if platforms else "")
                + "</div>"
            )

        def format_social_date(raw_value: Any) -> str:
            value = str(raw_value or "").strip()
            if not value:
                return ""
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return f"{parsed.month}月{parsed.day}日"
            except Exception:
                match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
                if match:
                    return f"{int(match.group(2))}月{int(match.group(3))}日"
            return value

        def clean_social_comment_text(raw_value: Any) -> str:
            text = re.sub(r"\s+", " ", str(raw_value or "")).strip()
            return re.sub(r"^(?:@[A-Za-z0-9_]{1,20}\s*)+", "", text).strip()

        def get_display_comments(item: Dict) -> List[str]:
            comments = item.get("representative_comments") or []
            display_comments: List[str] = []
            if isinstance(comments, list):
                for comment in comments[:3]:
                    if isinstance(comment, dict):
                        comment_text = clean_social_comment_text(comment.get("text", ""))
                    else:
                        comment_text = clean_social_comment_text(comment)
                    if not comment_text or comment_text == "暂无评论":
                        continue
                    display_comments.append(comment_text)
                    if len(display_comments) >= 3:
                        break
            return display_comments

        def social_sort_key(pair: Tuple[int, Dict]) -> Tuple[int, int]:
            index, item = pair
            has_comments = 1 if get_display_comments(item) else 0
            return (-has_comments, index)

        sorted_items = [item for _, item in sorted(enumerate(items), key=social_sort_key)]

        html_parts.append('<div class="social-grid">')
        for item in sorted_items:
            raw_platform = str(item.get("platform", "")).strip().lower()
            metadata = item.get("metadata", {}) or {}
            display_name = str(metadata.get("display_name", "") or "").strip()
            if raw_platform == "reddit":
                platform_text = "R"
                author_text = normalize_reddit_community_label(item)
            elif raw_platform == "x":
                platform_text = "X"
                author_text = display_name or str(item.get("author", "")).strip() or str(item.get("source_name", "")).strip()
            else:
                platform_text = str(item.get("platform", "")).upper() or "SOCIAL"
                author_text = display_name or str(item.get("author", "")).strip() or str(item.get("source_name", "")).strip()

            platform = render_social_avatar(item)
            author = html_escape(author_text)
            published_at = html_escape(format_social_date(item.get("published_at", "")))
            content = str(item.get("content", "")).strip()
            title = str(item.get("title", "")).strip()
            body_text = html_escape(content or title)
            url = html_escape(str(item.get("url", "")).strip())
            time_html = f'<span class="social-time">{published_at}</span>' if published_at else ""
            display_comments = get_display_comments(item)
            while len(display_comments) < 3:
                display_comments.append("暂无评论")
            comment_rows = []
            for index, comment_text in enumerate(display_comments, start=1):
                is_empty_comment = comment_text == "暂无评论"
                empty_attr = ' data-comment-empty="1"' if is_empty_comment else ""
                comment_rows.append(
                    f"""
                        <div class="social-comment-item">
                            <div class="social-comment-meta">
                                <span class="social-comment-stance">评论{index}</span>
                            </div>
                            <div class="social-comment-text"{empty_attr}><span class="social-comment-content">{html_escape(comment_text)}</span></div>
                        </div>
                    """
                )
            body_html = f'<a href="{url}" target="_blank" class="social-text-link"><div class="social-excerpt">{body_text}</div></a>' if url else f'<div class="social-excerpt">{body_text}</div>'
            comments_html = '<div class="social-comment-list">' + "".join(comment_rows) + "</div>"
            html_parts.append(
                f"""
                    <div class="rss-item social-item social-item-has-comments">
                        <div class="social-post-side">
                            <div class="news-content">
                                <div class="rss-meta social-meta-line">
                                    {platform}
                                    <span class="rss-author social-author">{author}</span>
                                    {time_html}
                                </div>
                                {body_html}
                            </div>
                        </div>
                        {comments_html}
                    </div>
                """
            )

        html_parts.append("</div></div>")
        return "".join(html_parts)

    # 生成 RSS 统计和新增 HTML
    rss_stats_html = render_rss_stats_html(rss_items, "RSS 订阅更新") if rss_items else ""
    rss_new_html = render_rss_stats_html(rss_new_items, "RSS 新增更新") if rss_new_items else ""

    # 生成独立展示区 HTML
    standalone_html = render_standalone_html(standalone_data)

    # 生成 AI 分析 HTML
    ai_html = render_ai_analysis_html_rich(ai_analysis) if ai_analysis else ""
    social_html = render_social_media_html(social_items) if social_items else ""

    # 准备各区域内容映射
    region_contents = {
        "hotlist": stats_html,
        "rss": rss_stats_html,
        "new_items": (new_titles_html, rss_new_html),  # 元组，分别处理
        "standalone": standalone_html,
        "ai_analysis": ai_html,
        "social_media": social_html,
    }

    def add_section_divider(content: str) -> str:
        """为内容的外层 div 添加 section-divider 类"""
        if not content or 'class="' not in content:
            return content
        first_class_pos = content.find('class="')
        if first_class_pos != -1:
            insert_pos = first_class_pos + len('class="')
            return content[:insert_pos] + "section-divider " + content[insert_pos:]
        return content

    dashboard_regions = {"hotlist", "rss", "ai_analysis"}
    dashboard_columns = {"hotlist": "", "rss": "", "ai_analysis": ""}
    full_width_regions: List[str] = []

    # 按 region_order 顺序组装内容，正文优先采用三列看板布局
    has_previous_content = False
    for region in region_order:
        content = region_contents.get(region, "")
        if region == "new_items":
            new_html, rss_new = content
            if new_html:
                if has_previous_content or full_width_regions:
                    new_html = add_section_divider(new_html)
                full_width_regions.append(new_html)
                has_previous_content = True
            if rss_new:
                if has_previous_content or full_width_regions:
                    rss_new = add_section_divider(rss_new)
                full_width_regions.append(rss_new)
                has_previous_content = True
        elif content:
            if region in dashboard_regions:
                card_class = {
                    "hotlist": "dashboard-hotlist",
                    "rss": "dashboard-rss",
                    "ai_analysis": "dashboard-ai",
                }[region]
                dashboard_columns[region] = (
                    f'<div class="dashboard-card {card_class}">{content}</div>'
                )
                has_previous_content = True
            else:
                if has_previous_content or full_width_regions:
                    content = add_section_divider(content)
                full_width_regions.append(content)
                has_previous_content = True

    if any(dashboard_columns.values()):
        html += """
                <div class="dashboard-grid">"""

        if dashboard_columns["hotlist"]:
            html += f"""
                    <div class="dashboard-column dashboard-column-hotlist">{dashboard_columns["hotlist"]}</div>"""

        if dashboard_columns["rss"]:
            html += f"""
                    <div class="dashboard-column dashboard-column-rss">{dashboard_columns["rss"]}</div>"""

        if dashboard_columns["ai_analysis"]:
            html += f"""
                    <div class="dashboard-column dashboard-column-ai">{dashboard_columns["ai_analysis"]}</div>"""

        html += """
                </div>"""

    for content in full_width_regions:
        html += content

    html += """
            </div>

        </div>

        <script>
            const sourceCatalog = __SOURCE_CATALOG_JSON__;
            const escapeSourceHtml = (value) => String(value ?? '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');

            const parseSourceList = (rawText, prefix = '') => {
                const text = String(rawText || '').replace(prefix, '').trim();
                if (!text) return [];
                return text
                    .split(/[、，,]\s*/)
                    .map((item) => item.trim())
                    .filter(Boolean);
            };

            const normalizeCatalogItems = (items, fallbackNames, kind) => {
                const normalizedKind = String(kind || '').trim().toUpperCase() || 'WEB';
                if (Array.isArray(items) && items.length) {
                    return items.map((item) => ({
                        id: item?.id || item?.name || '',
                        name: item?.name || '',
                        display_name: item?.display_name || item?.name || '',
                        homepage: item?.homepage || '',
                        logo_url: item?.logo_url || '',
                        kind: item?.kind || normalizedKind,
                        healthy: item?.healthy !== false,
                        status: item?.status || '',
                        strategy: item?.strategy || '',
                        lastSynced: item?.last_synced || '',
                        fetchMode: item?.fetch_mode || '',
                        freshToday: item?.fresh_today !== false,
                        platform: item?.platform || '',
                        member_ids: Array.isArray(item?.member_ids) ? item.member_ids : [],
                        member_profiles: Array.isArray(item?.member_profiles) ? item.member_profiles : [],
                    })).filter((item) => item.name);
                }
                return (Array.isArray(fallbackNames) ? fallbackNames : []).map((name) => ({
                    id: name,
                    name,
                    display_name: name,
                    homepage: '',
                    logo_url: '',
                    kind: normalizedKind,
                    healthy: true,
                    status: 'live_ok',
                    strategy: '',
                    lastSynced: '',
                    fetchMode: 'live',
                    freshToday: true,
                    platform: '',
                    member_ids: [],
                    member_profiles: [],
                }));
            };

            const sourceFallbackLabel = (item, fallbackKind = 'WEB') => {
                const platform = String(item?.platform || '').trim().toLowerCase();
                if (platform === 'x') return 'X';
                if (platform === 'reddit') return 'R';
                const joinedAscii = (String(item?.name || '').match(/[A-Za-z]+/g) || []).join('');
                if (joinedAscii) return joinedAscii.slice(0, 2).toUpperCase();
                const compact = String(item?.name || '').replace(/[·・\s]/g, '').trim();
                if (compact) return compact.slice(0, 1);
                if (fallbackKind === 'RSS') return 'R';
                if (fallbackKind === 'SOCIAL') return 'S';
                return '源';
            };

            const renderSourceStrip = ({ items, summaryLabel = '', marquee = false }) => {
                const safeItems = Array.isArray(items) ? items.filter((item) => item?.name) : [];
                if (!safeItems.length) {
                    return `
                        <div class="source-strip is-empty" data-source-strip data-source-names="">
                            <div class="source-strip-rail" data-source-rail></div>
                        </div>
                    `;
                }

                const sourceNames = safeItems.map((item) => item.display_name || item.name).join('|');
                const chips = safeItems.map((item) => {
                    const fallbackKind = String(item.kind || '').trim().toUpperCase() || 'WEB';
                    const fallback = sourceFallbackLabel(item, fallbackKind);
                    const logoUrl = String(item.logo_url || '').trim();
                    const chipLabel = String(item.display_name || item.name || '').trim();
                    const logoHtml = logoUrl
                        ? `<span class="source-strip-chip-logo has-image${item.healthy ? '' : ' is-alert'}">
                                <img src="${escapeSourceHtml(logoUrl)}" alt="${escapeSourceHtml(chipLabel)} logo" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display='none'; this.nextElementSibling.style.display='inline-flex';">
                                <span class="source-strip-chip-fallback" style="display:none;">${escapeSourceHtml(fallback)}</span>
                           </span>`
                        : `<span class="source-strip-chip-logo${item.healthy ? '' : ' is-alert'}"><span class="source-strip-chip-fallback">${escapeSourceHtml(fallback)}</span></span>`;
                    return `<div class="source-strip-chip">${logoHtml}<span>${escapeSourceHtml(chipLabel || item.name)}</span></div>`;
                }).join('');

                const summaryHtml = summaryLabel
                    ? `<div class="source-strip-chip is-summary">${escapeSourceHtml(summaryLabel)}</div>`
                    : '';
                const railItems = `${chips}${summaryHtml}`;
                const shouldMarquee = Boolean(marquee && safeItems.length > 3);
                const marqueeClone = shouldMarquee
                    ? `<div class="source-strip-clone" aria-hidden="true">${railItems}</div>`
                    : '';

                return `
                    <div class="source-strip${shouldMarquee ? ' is-marquee' : ''}" data-source-strip data-source-names="${escapeSourceHtml(sourceNames)}">
                        <div class="source-strip-shell">
                            <div class="source-strip-rail" data-source-rail>
                                ${railItems}
                                ${marqueeClone}
                            </div>
                        </div>
                    </div>
                `;
            };

            const decodeAiText = (html = '') => {
                const normalized = String(html || '').replace(/<br\s*\/?>/gi, '\\n');
                const temp = document.createElement('div');
                temp.innerHTML = normalized;
                return (temp.textContent || '')
                    .replace(/\u00a0/g, ' ')
                    .replace(/\\r/g, '')
                    .trim();
            };

            const cleanAiEntry = (text = '') => String(text || '')
                .replace(/\\s*\\n\\s*/g, ' ')
                .replace(/\s{2,}/g, ' ')
                .trim();

            const splitAiEntries = (html = '') => {
                const text = decodeAiText(html);
                if (!text) return [];
                return text
                    .split(/\\n\\s*\\n+/)
                    .map((entry) => cleanAiEntry(entry))
                    .filter(Boolean);
            };

            const deriveClusterTitle = (text = '', fallback = '重点事件簇') => {
                const compact = cleanAiEntry(text)
                    .replace(/^\d+\.\s*/, '')
                    .replace(/^[【\[][^】\]]+[】\]][:：]?\s*/, '')
                    .trim();
                if (!compact) return fallback;
                const firstSegment = compact.split(/[。；;，,:：]/).find(Boolean) || compact;
                const title = firstSegment.replace(/\s+/g, '').slice(0, 12);
                return title || fallback;
            };

            const buildAiOverviewHtml = (blockMap = {}) => {
                const coreEntries = splitAiEntries(blockMap['核心热点态势']);
                const sentimentEntries = splitAiEntries(blockMap['舆论风向争议']);
                const signalEntries = splitAiEntries(blockMap['异动与弱信号']);
                const rssEntries = splitAiEntries(blockMap['RSS 深度洞察']);
                const outlookEntries = splitAiEntries(blockMap['研判策略建议']);

                const usedPrimary = new Set();
                const takeUnique = (candidates = []) => {
                    for (const entry of candidates) {
                        const cleaned = cleanAiEntry(entry);
                        if (cleaned && !usedPrimary.has(cleaned)) {
                            usedPrimary.add(cleaned);
                            return cleaned;
                        }
                    }
                    return '';
                };

                const summaryCandidates = [
                    ...coreEntries,
                    ...rssEntries,
                    ...sentimentEntries,
                    ...signalEntries,
                ].map((entry) => cleanAiEntry(entry)).filter(Boolean);

                const summaryText = summaryCandidates.slice(0, 2).join(' ') || '暂无显著信号';

                const clusters = [
                    {
                        tone: '主线事件簇',
                        primary: takeUnique([...coreEntries, ...rssEntries]),
                        risk: cleanAiEntry(sentimentEntries[0] || signalEntries[0] || ''),
                        action: cleanAiEntry(outlookEntries[0] || ''),
                    },
                    {
                        tone: '争议事件簇',
                        primary: takeUnique([...sentimentEntries, ...signalEntries, ...coreEntries]),
                        risk: cleanAiEntry(signalEntries[0] || sentimentEntries[1] || ''),
                        action: cleanAiEntry(outlookEntries[1] || outlookEntries[0] || ''),
                    },
                    {
                        tone: '增量事件簇',
                        primary: takeUnique([...rssEntries, ...signalEntries, ...outlookEntries, ...coreEntries]),
                        risk: cleanAiEntry(sentimentEntries[1] || signalEntries[1] || ''),
                        action: cleanAiEntry(outlookEntries[2] || rssEntries[1] || outlookEntries[0] || ''),
                    },
                ].filter((cluster) => cluster.primary);

                const clusterHtml = (clusters.length ? clusters : [{
                    primary: '暂无显著信号',
                    risk: '',
                    action: '',
                }]).map((cluster, index) => {
                    const clusterTitle = deriveClusterTitle(cluster.primary, `重点事件簇 ${index + 1}`);
                    const eventCountRaw = String(cluster.event_count || cluster.related_count || cluster.count || '1').trim();
                    const eventCount = /^\d+$/.test(eventCountRaw) ? eventCountRaw : '1';
                    const sourceMix = String(cluster.source_mix || '').trim();
                    const riskText = cluster.risk || '暂无显著争议风险。';
                    const actionText = cluster.action || '暂无显著后续观察建议。';
                    return `
                        <div class="ai-grid-card">
                            <div class="ai-grid-head">
                                <div class="ai-grid-title">${escapeSourceHtml(clusterTitle)}</div>
                                <div class="ai-overview-event-meta">
                                    <span class="ai-overview-pill ai-overview-pill-combined">
                                        <span class="ai-overview-pill-combined-label">相关事件数 ${escapeSourceHtml(eventCount)} 条</span>
                                        ${sourceMix ? `<span class="ai-overview-pill-divider" aria-hidden="true"></span><span class="ai-overview-pill-combined-label">${escapeSourceHtml(sourceMix)}</span>` : ''}
                                    </span>
                                </div>
                            </div>
                            <div class="ai-overview-event-row">
                                <div class="ai-overview-main">
                                    <div class="ai-grid-content">${escapeSourceHtml(cluster.primary)}</div>
                                </div>
                                <div class="ai-overview-detail-grid">
                                    <div class="ai-overview-detail">
                                        <div class="ai-overview-detail-label">风险点</div>
                                        <div class="ai-overview-detail-text">${escapeSourceHtml(riskText)}</div>
                                    </div>
                                    <div class="ai-overview-detail">
                                        <div class="ai-overview-detail-label">建议动作</div>
                                        <div class="ai-overview-detail-text">${escapeSourceHtml(actionText)}</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');

                return `
                        <div class="ai-grid-card ai-overview-summary">
                            <div class="ai-overview-summary-text">${escapeSourceHtml(summaryText)}</div>
                        </div>
                        <div class="ai-overview-events">
                            ${clusterHtml}
                        </div>
                `;
            };

            const enableSourceStripInteractions = (scope = document) => {
                scope.querySelectorAll('[data-source-rail]').forEach((rail) => {
                    if (rail.dataset.sourceRailBound === '1') return;
                    rail.dataset.sourceRailBound = '1';
                    if (rail.closest('.source-strip.is-marquee')) return;

                    let isDragging = false;
                    let startX = 0;
                    let startScroll = 0;

                    rail.addEventListener('mousedown', (event) => {
                        isDragging = true;
                        startX = event.pageX;
                        startScroll = rail.scrollLeft;
                        rail.classList.add('is-dragging');
                    });

                    rail.addEventListener('mouseleave', () => {
                        isDragging = false;
                        rail.classList.remove('is-dragging');
                    });

                    rail.addEventListener('mouseup', () => {
                        isDragging = false;
                        rail.classList.remove('is-dragging');
                    });

                    rail.addEventListener('mousemove', (event) => {
                        if (!isDragging) return;
                        event.preventDefault();
                        rail.scrollLeft = startScroll - (event.pageX - startX);
                    });

                    rail.addEventListener('wheel', (event) => {
                        if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
                            rail.scrollLeft += event.deltaY;
                            event.preventDefault();
                        }
                    }, { passive: false });

                });
            };

            (() => {
                const content = document.querySelector('.content');
                const hotlist = content?.querySelector('.hotlist-section');
                const rss = content?.querySelector('.rss-section');
                const ai = content?.querySelector('.ai-section');
                const social = content?.querySelector('.social-section');
                const originalGrid = content?.querySelector('.dashboard-grid');

                const sourceMap = {
                    'Zaobao China': '联合早报涉华',
                    'Zaobao World': '联合早报国际',
                    'NYT China RSS': '纽约时报涉华',
                    'RFI China': '法广涉华',
                    'SCMP China': '南华早报涉华',
                    'Guancha All': '观察者网',
                    'Financial Times China': '金融时报涉华',
                    'BBC': 'BBC 英文网',
                    'BBC World': 'BBC 国际',
                    'AP Politics': '美联社政治',
                    'AP World News': '美联社国际',
                    'NPR World': 'NPR 国际',
                    'The Guardian China': '卫报涉华',
                    'VOA Chinese 1': '新闻 - 美国之音',
                    'VOA Chinese 2': '港澳 - 美国之音',
                    'VOA Chinese 3': '台湾 - 美国之音',
                    'iNewsweek Politics': '新闻周刊政治',
                    'iNewsweek World': '新闻周刊国际',
                    'Infzm': '南方周末'
                };

                document.querySelectorAll('.rss-author').forEach((el) => {
                    const text = el.textContent.trim();
                    if (sourceMap[text]) el.textContent = sourceMap[text];
                });

                if (social) {
                    const socialSources = social.querySelector('.social-sources');
                    if (socialSources) {
                        socialSources.textContent = socialSources.textContent
                            .replace('观察来源', '信源')
                            .replace('瑙傚療鏉ユ簮', '信源');
                    }

                    social.querySelectorAll('.social-platform').forEach((el) => {
                        const platform = el.textContent.trim().toUpperCase();
                        if (platform === 'REDDIT') {
                            el.textContent = 'R';
                        } else if (platform === 'R') {
                            el.textContent = 'R';
                        } else if (platform === 'SOCIAL') {
                            el.textContent = '社媒';
                        } else if (platform === 'X') {
                            el.textContent = 'X';
                        }
                    });
                }

                const socialSourceFallbacks = parseSourceList(
                    (social?.querySelector('.social-sources')?.textContent || '')
                        .replace(/^信源：/u, '')
                        .replace(/^观察来源：/u, '')
                        .replace(/平台：.*$/u, '')
                        .trim(),
                    ''
                );
                const hotlistSourceItems = normalizeCatalogItems(sourceCatalog.hotlist, [], 'WEB');
                const websiteSourceItems = normalizeCatalogItems(sourceCatalog.website, [], 'RSS');
                const mediaGroupItems = normalizeCatalogItems(sourceCatalog.media, socialSourceFallbacks, 'SOCIAL');
                const mediaSourceItems = mediaGroupItems.flatMap((groupItem) => {
                    const memberProfiles = Array.isArray(groupItem.member_profiles)
                        ? groupItem.member_profiles.filter((profile) => profile?.name)
                        : [];
                    if (memberProfiles.length) {
                        return memberProfiles.map((profile) => ({
                            ...groupItem,
                            id: `${groupItem.id}:${profile.id || profile.name}`,
                            name: profile.name || profile.id || '',
                            display_name: profile.display_name || profile.name || profile.id || '',
                            homepage: profile.homepage || groupItem.homepage || '',
                            logo_url: profile.logo_url || '',
                            member_ids: [],
                            member_profiles: [],
                        })).filter((item) => item.name);
                    }
                    const memberIds = Array.isArray(groupItem.member_ids) ? groupItem.member_ids.filter(Boolean) : [];
                    if (memberIds.length) {
                        return memberIds.map((memberId) => ({
                            ...groupItem,
                            id: `${groupItem.id}:${memberId}`,
                            name: memberId,
                            logo_url: '',
                            member_ids: [],
                            member_profiles: [],
                        }));
                    }
                    return [groupItem];
                });

                if (!(content && hotlist && rss && ai)) return;

                const economicTopics = ['宏观经济', '地产债务', '市场金融', '外贸供应链', '能源商品'];
                const priorityTopics = ['国际涉华', '港澳台海'];
                const reorderTopics = (container, selector, nameSelector, indexSelector) => {
                    const groups = Array.from(container.querySelectorAll(selector));
                    const priorityGroups = priorityTopics
                        .map((topic) => groups.find((group) => {
                            const name = group.querySelector(nameSelector)?.textContent.trim() || '';
                            return name === topic;
                        }))
                        .filter(Boolean);
                    const middleGroups = groups.filter((group) => {
                        const name = group.querySelector(nameSelector)?.textContent.trim() || '';
                        return !priorityTopics.includes(name) && !economicTopics.includes(name);
                    });
                    const deferredGroups = groups.filter((group) => {
                        const name = group.querySelector(nameSelector)?.textContent.trim() || '';
                        return economicTopics.includes(name);
                    });
                    [...priorityGroups, ...middleGroups, ...deferredGroups].forEach((group) => container.appendChild(group));
                    const reordered = Array.from(container.querySelectorAll(selector));
                    reordered.forEach((group, index) => {
                        if (indexSelector) {
                            const indexEl = group.querySelector(indexSelector);
                            if (indexEl) indexEl.textContent = `${index + 1}/${reordered.length}`;
                        }
                    });
                    return reordered;
                };

                const reorderedGroups = reorderTopics(hotlist, '.word-group', '.word-name', '.word-index');
                reorderTopics(rss, '.feed-group', '.feed-name', null);
                const hotlistTotalCount = hotlist.querySelectorAll('.news-item').length;

                reorderedGroups.forEach((group) => {
                    const header = group.querySelector('.word-header');
                    const info = group.querySelector('.word-info');
                    const count = group.querySelector('.word-count');
                    const indexEl = group.querySelector('.word-index');
                    if (indexEl) indexEl.remove();
                    if (header && info && count) {
                        header.style.justifyContent = 'space-between';
                        header.appendChild(count);
                    }
                });

                hotlist.querySelectorAll('.rank-num').forEach((el) => {
                    const text = el.textContent.trim();
                    if (text.includes('-')) {
                        const [start, end] = text.split('-');
                        el.textContent = `排名 ${start}-${end}`;
                        el.title = '表示该话题在监测时段内位于该平台热榜的排名区间，数字越小越靠前';
                    } else if (text) {
                        el.textContent = `排名 ${text}`;
                        el.title = '表示该话题在该平台热榜的最高排名，数字越小越靠前';
                    }
                });

                hotlist.querySelectorAll('.news-item').forEach((item) => {
                    item.style.display = 'grid';
                    item.style.gridTemplateColumns = '28px minmax(0, 1fr)';
                    item.style.alignItems = 'flex-start';
                    item.style.gap = '12px';
                    item.style.padding = '14px';
                    item.style.marginBottom = '12px';
                    item.style.border = '1px solid #e2e8f0';
                    item.style.borderRadius = '14px';
                    item.style.background = 'linear-gradient(180deg, #f8fafc 0%, #ffffff 100%)';
                    item.style.overflow = 'visible';
                    item.style.borderBottom = '1px solid #e2e8f0';
                });

                hotlist.querySelectorAll('.news-number').forEach((el) => {
                    el.style.marginTop = '0';
                    el.style.alignSelf = 'start';
                });

                hotlist.querySelectorAll('.news-content').forEach((el) => {
                    el.style.paddingRight = '0';
                    el.style.minWidth = '0';
                });

                hotlist.querySelectorAll('.news-item.new .news-content').forEach((el) => {
                    el.style.paddingRight = '28px';
                });

                hotlist.querySelectorAll('.news-title').forEach((el) => {
                    el.style.lineHeight = '1.55';
                    el.style.overflow = 'visible';
                    el.style.wordBreak = 'break-word';
                });

                hotlist.querySelectorAll('.news-link').forEach((el) => {
                    el.style.display = 'block';
                });

                const aiGridDirect = ai.querySelector('.ai-grid.ai-panel[data-ai-direct="1"]');
                if (!aiGridDirect) {
                    const blockMap = {};
                    ai.querySelectorAll('.ai-block').forEach((block) => {
                        const title = block.querySelector('.ai-block-title')?.textContent.trim();
                        const html = block.querySelector('.ai-block-content')?.innerHTML || '';
                        if (title) blockMap[title] = html;
                    });

                    const aiHeader = ai.querySelector('.ai-section-header');
                    ai.innerHTML = '';
                    if (aiHeader) {
                        const titleEl = aiHeader.querySelector('.ai-section-title');
                        if (titleEl) titleEl.textContent = '';
                        ai.appendChild(aiHeader);
                    }

                    const aiGrid = document.createElement('div');
                    aiGrid.className = 'ai-grid ai-panel';
                    aiGrid.innerHTML = buildAiOverviewHtml(blockMap);
                    ai.appendChild(aiGrid);
                }

                const aiCard = document.createElement('div');
                aiCard.className = 'dashboard-card dashboard-ai';
                aiCard.appendChild(ai);
                content.prepend(aiCard);

                let socialCard = null;
                if (social) {
                    const socialHeader = social.querySelector('.rss-section-header');
                    if (socialHeader) socialHeader.remove();
                    const socialSources = social.querySelector('.social-sources');
                    if (socialSources) {
                        socialSources.innerHTML = renderSourceStrip({
                            items: mediaSourceItems,
                            marquee: true,
                        });
                    }

                    socialCard = document.createElement('div');
                    socialCard.className = 'dashboard-card dashboard-social';
                    socialCard.appendChild(social);
                    aiCard.insertAdjacentElement('afterend', socialCard);
                }

                const grid = document.createElement('div');
                grid.className = 'dashboard-grid';
                grid.style.gridTemplateColumns = 'minmax(0, 1fr) minmax(0, 1fr)';
                grid.style.marginTop = '28px';

                const hotlistColumn = document.createElement('div');
                hotlistColumn.className = 'dashboard-column';
                hotlistColumn.innerHTML = `
                    <div class="dashboard-card dashboard-hotlist">
                        <div class="dashboard-card-header">
                            <div class="dashboard-card-title">各平台热榜</div>
                            <div class="dashboard-card-meta">${hotlistTotalCount} 条</div>
                        </div>
                        <div class="rank-explain">${renderSourceStrip({
                            items: hotlistSourceItems,
                            marquee: true,
                        })}</div>
                    </div>`;
                const hotlistCard = hotlistColumn.firstElementChild;
                hotlistCard.appendChild(hotlist);

                const rssColumn = document.createElement('div');
                rssColumn.className = 'dashboard-column';
                rssColumn.innerHTML = `<div class="dashboard-card dashboard-rss"></div>`;
                const rssCard = rssColumn.firstElementChild;
                rssCard.appendChild(rss);
                const rssTitle = rss.querySelector('.rss-section-title');
                if (rssTitle) rssTitle.textContent = '';
                const rssCountEl = rss.querySelector('.rss-section-count');
                if (rssCountEl) rssCountEl.className = 'dashboard-card-meta';
                const rssSources = document.createElement('div');
                rssSources.className = 'rank-explain';
                rssSources.innerHTML = renderSourceStrip({
                    items: websiteSourceItems,
                    marquee: true,
                });
                const rssHeader = rss.querySelector('.rss-section-header');
                if (rssHeader) {
                    rssHeader.insertAdjacentElement('afterend', rssSources);
                } else {
                    rssCard.insertBefore(rssSources, rss);
                }

                if (originalGrid) {
                    originalGrid.remove();
                }

                grid.appendChild(hotlistColumn);
                grid.appendChild(rssColumn);
                content.appendChild(grid);
                enableSourceStripInteractions(content);
            })();

            async function saveAsImage() {
                const button = event.target;
                const originalText = button.textContent;

                try {
                    button.textContent = '生成中...';
                    button.disabled = true;
                    window.scrollTo(0, 0);

                    // 等待页面稳定
                    await new Promise(resolve => setTimeout(resolve, 200));

                    // 截图前隐藏按钮
                    const buttons = document.querySelector('.save-buttons');
                    buttons.style.visibility = 'hidden';

                    // 再次等待确保按钮完全隐藏
                    await new Promise(resolve => setTimeout(resolve, 100));

                    const container = document.querySelector('.container');

                    const canvas = await html2canvas(container, {
                        backgroundColor: '#ffffff',
                        scale: 1.5,
                        useCORS: true,
                        allowTaint: false,
                        imageTimeout: 10000,
                        removeContainer: false,
                        foreignObjectRendering: false,
                        logging: false,
                        width: container.offsetWidth,
                        height: container.offsetHeight,
                        x: 0,
                        y: 0,
                        scrollX: 0,
                        scrollY: 0,
                        windowWidth: window.innerWidth,
                        windowHeight: window.innerHeight
                    });

                    buttons.style.visibility = 'visible';

                    const link = document.createElement('a');
                    const now = new Date();
                    const filename = `TrendRadar_热点新闻分析_${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}.png`;

                    link.download = filename;
                    link.href = canvas.toDataURL('image/png', 1.0);

                    // 触发下载
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);

                    button.textContent = '保存成功!';
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.disabled = false;
                    }, 2000);

                } catch (error) {
                    const buttons = document.querySelector('.save-buttons');
                    buttons.style.visibility = 'visible';
                    button.textContent = '保存失败';
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.disabled = false;
                    }, 2000);
                }
            }

            async function saveAsMultipleImages() {
                const button = event.target;
                const originalText = button.textContent;
                const container = document.querySelector('.container');
                const scale = 1.5;
                const maxHeight = 5000 / scale;

                try {
                    button.textContent = '分析中...';
                    button.disabled = true;

                    // 获取所有可能的分割元素
                    const newsItems = Array.from(container.querySelectorAll('.news-item'));
                    const wordGroups = Array.from(container.querySelectorAll('.word-group'));
                    const newSection = container.querySelector('.new-section');
                    const errorSection = container.querySelector('.error-section');
                    const header = container.querySelector('.header');
                    const footer = container.querySelector('.footer');

                    // 计算元素位置和高度
                    const containerRect = container.getBoundingClientRect();
                    const elements = [];

                    // 添加header作为必须包含的元素
                    elements.push({
                        type: 'header',
                        element: header,
                        top: 0,
                        bottom: header.offsetHeight,
                        height: header.offsetHeight
                    });

                    // 添加错误信息（如果存在）
                    if (errorSection) {
                        const rect = errorSection.getBoundingClientRect();
                        elements.push({
                            type: 'error',
                            element: errorSection,
                            top: rect.top - containerRect.top,
                            bottom: rect.bottom - containerRect.top,
                            height: rect.height
                        });
                    }

                    // 按word-group分组处理news-item
                    wordGroups.forEach(group => {
                        const groupRect = group.getBoundingClientRect();
                        const groupNewsItems = group.querySelectorAll('.news-item');

                        // 添加word-group的header部分
                        const wordHeader = group.querySelector('.word-header');
                        if (wordHeader) {
                            const headerRect = wordHeader.getBoundingClientRect();
                            elements.push({
                                type: 'word-header',
                                element: wordHeader,
                                parent: group,
                                top: groupRect.top - containerRect.top,
                                bottom: headerRect.bottom - containerRect.top,
                                height: headerRect.height
                            });
                        }

                        // 添加每个news-item
                        groupNewsItems.forEach(item => {
                            const rect = item.getBoundingClientRect();
                            elements.push({
                                type: 'news-item',
                                element: item,
                                parent: group,
                                top: rect.top - containerRect.top,
                                bottom: rect.bottom - containerRect.top,
                                height: rect.height
                            });
                        });
                    });

                    // 添加新增新闻部分
                    if (newSection) {
                        const rect = newSection.getBoundingClientRect();
                        elements.push({
                            type: 'new-section',
                            element: newSection,
                            top: rect.top - containerRect.top,
                            bottom: rect.bottom - containerRect.top,
                            height: rect.height
                        });
                    }

                    // 添加footer
                    const footerRect = footer.getBoundingClientRect();
                    elements.push({
                        type: 'footer',
                        element: footer,
                        top: footerRect.top - containerRect.top,
                        bottom: footerRect.bottom - containerRect.top,
                        height: footer.offsetHeight
                    });

                    // 计算分割点
                    const segments = [];
                    let currentSegment = { start: 0, end: 0, height: 0, includeHeader: true };
                    let headerHeight = header.offsetHeight;
                    currentSegment.height = headerHeight;

                    for (let i = 1; i < elements.length; i++) {
                        const element = elements[i];
                        const potentialHeight = element.bottom - currentSegment.start;

                        // 检查是否需要创建新分段
                        if (potentialHeight > maxHeight && currentSegment.height > headerHeight) {
                            // 在前一个元素结束处分割
                            currentSegment.end = elements[i - 1].bottom;
                            segments.push(currentSegment);

                            // 开始新分段
                            currentSegment = {
                                start: currentSegment.end,
                                end: 0,
                                height: element.bottom - currentSegment.end,
                                includeHeader: false
                            };
                        } else {
                            currentSegment.height = potentialHeight;
                            currentSegment.end = element.bottom;
                        }
                    }

                    // 添加最后一个分段
                    if (currentSegment.height > 0) {
                        currentSegment.end = container.offsetHeight;
                        segments.push(currentSegment);
                    }

                    button.textContent = `生成中 (0/${segments.length})...`;

                    // 隐藏保存按钮
                    const buttons = document.querySelector('.save-buttons');
                    buttons.style.visibility = 'hidden';

                    // 为每个分段生成图片
                    const images = [];
                    for (let i = 0; i < segments.length; i++) {
                        const segment = segments[i];
                        button.textContent = `生成中 (${i + 1}/${segments.length})...`;

                        // 创建临时容器用于截图
                        const tempContainer = document.createElement('div');
                        tempContainer.style.cssText = `
                            position: absolute;
                            left: -9999px;
                            top: 0;
                            width: ${container.offsetWidth}px;
                            background: white;
                        `;
                        tempContainer.className = 'container';

                        // 克隆容器内容
                        const clonedContainer = container.cloneNode(true);

                        // 移除克隆内容中的保存按钮
                        const clonedButtons = clonedContainer.querySelector('.save-buttons');
                        if (clonedButtons) {
                            clonedButtons.style.display = 'none';
                        }

                        tempContainer.appendChild(clonedContainer);
                        document.body.appendChild(tempContainer);

                        // 等待DOM更新
                        await new Promise(resolve => setTimeout(resolve, 100));

                        // 使用html2canvas截取特定区域
                        const canvas = await html2canvas(clonedContainer, {
                            backgroundColor: '#ffffff',
                            scale: scale,
                            useCORS: true,
                            allowTaint: false,
                            imageTimeout: 10000,
                            logging: false,
                            width: container.offsetWidth,
                            height: segment.end - segment.start,
                            x: 0,
                            y: segment.start,
                            windowWidth: window.innerWidth,
                            windowHeight: window.innerHeight
                        });

                        images.push(canvas.toDataURL('image/png', 1.0));

                        // 清理临时容器
                        document.body.removeChild(tempContainer);
                    }

                    // 恢复按钮显示
                    buttons.style.visibility = 'visible';

                    // 下载所有图片
                    const now = new Date();
                    const baseFilename = `TrendRadar_热点新闻分析_${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}`;

                    for (let i = 0; i < images.length; i++) {
                        const link = document.createElement('a');
                        link.download = `${baseFilename}_part${i + 1}.png`;
                        link.href = images[i];
                        document.body.appendChild(link);
                        link.click();
                        document.body.removeChild(link);

                        // 延迟一下避免浏览器阻止多个下载
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }

                    button.textContent = `已保存 ${segments.length} 张图片!`;
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.disabled = false;
                    }, 2000);

                } catch (error) {
                    console.error('分段保存失败:', error);
                    const buttons = document.querySelector('.save-buttons');
                    buttons.style.visibility = 'visible';
                    button.textContent = '保存失败';
                    setTimeout(() => {
                        button.textContent = originalText;
                        button.disabled = false;
                    }, 2000);
                }
            }

            (() => {
                window.scrollTo(0, 0);
                const finishBoot = () => {
                    window.requestAnimationFrame(() => {
                        window.requestAnimationFrame(() => {
                            document.body.classList.remove('pulse-static-booting');
                        });
                    });
                };

                const header = document.querySelector('.header');
                const content = document.querySelector('.content');
                const socialCard = document.querySelector('.dashboard-social');
                const aiCard = document.querySelector('.dashboard-ai');
                const hotlistCard = document.querySelector('.dashboard-hotlist');
                const rssCard = document.querySelector('.dashboard-rss');

                if (header) header.id = 'overview';

                let sourceSection = document.querySelector('#sources');
                if (content && !sourceSection) {
                    const parseSourceList = (rawText, prefix) => {
                        const text = (rawText || '').replace(prefix, '').trim();
                        if (!text) return [];
                        return text
                            .split(/[、，,]\s*/)
                            .map((item) => item.trim())
                            .filter(Boolean);
                    };

                    const hotlistSourceAttr = hotlistCard?.querySelector('.source-strip')?.dataset?.sourceNames || '';
                    const rssSourceAttr = rssCard?.querySelector('.source-strip')?.dataset?.sourceNames || '';
                    const socialSourceAttr = socialCard?.querySelector('.source-strip')?.dataset?.sourceNames || '';
                    const hotlistSources = hotlistSourceAttr
                        ? hotlistSourceAttr.split('|').map((item) => item.trim()).filter(Boolean)
                        : parseSourceList(hotlistCard?.querySelector('.rank-explain')?.textContent?.trim(), '热榜来源：');
                    const rssSources = rssSourceAttr
                        ? rssSourceAttr.split('|').map((item) => item.trim()).filter(Boolean)
                        : parseSourceList(rssCard?.querySelector('.rank-explain')?.textContent?.trim(), '网站来源：');
                    const socialSources = socialSourceAttr
                        ? socialSourceAttr.split('|').map((item) => item.trim()).filter(Boolean)
                        : parseSourceList(
                            (socialCard?.querySelector('.social-sources')?.textContent || '')
                                .replace(/^信源：/u, '')
                                .replace(/^观察来源：/u, '')
                                .replace(/平台：.*$/u, '')
                                .trim(),
                            ''
                        );

                    const normalizeCatalogItems = (items, fallbackNames, kind) => {
                        if (Array.isArray(items) && items.length) {
                            return items.map((item) => ({
                                id: item.id || item.name || '',
                                name: item.name || '',
                                logo_url: item.logo_url || '',
                                kind: item.kind || kind,
                                healthy: item.healthy !== false,
                                status: item.status || '',
                                strategy: item.strategy || '',
                                lastSynced: item.last_synced || '',
                                fetchMode: item.fetch_mode || '',
                                freshToday: item.fresh_today !== false,
                            })).filter((item) => item.name);
                        }
                        return fallbackNames.map((name) => ({
                            id: name,
                            name,
                            logo_url: '',
                            kind,
                            healthy: true,
                            status: 'live_ok',
                            strategy: '',
                            lastSynced: '本轮报告',
                            fetchMode: 'live',
                            freshToday: true,
                        }));
                    };

                    const sourceGroups = [
                        { key: 'all', label: '全部信源', items: [] },
                        {
                            key: 'hotlist',
                            label: '热榜监测',
                            kind: 'WEB',
                            items: normalizeCatalogItems(sourceCatalog.hotlist, hotlistSources, 'WEB'),
                        },
                        {
                            key: 'website',
                            label: '网站监测',
                            kind: 'RSS',
                            items: normalizeCatalogItems(sourceCatalog.website, rssSources, 'RSS'),
                        },
                        {
                            key: 'media',
                            label: '媒体观测',
                            kind: 'SOCIAL',
                            items: normalizeCatalogItems(sourceCatalog.media, socialSources, 'SOCIAL'),
                        },
                    ];
                    sourceGroups[0].items = [
                        ...sourceGroups[1].items,
                        ...sourceGroups[2].items,
                        ...sourceGroups[3].items,
                    ];

                    const iconForKind = (kind) => {
                        if (kind === 'SOCIAL') return '◉';
                        if (kind === 'RSS') return '◎';
                        return '◌';
                    };

                    const formatSyncValue = (raw) => {
                        if (!raw) return '';
                        if (raw === '本轮报告') return raw;
                        const parsed = new Date(raw);
                        if (Number.isNaN(parsed.getTime())) return raw;
                        const month = String(parsed.getMonth() + 1).padStart(2, '0');
                        const day = String(parsed.getDate()).padStart(2, '0');
                        const hour = String(parsed.getHours()).padStart(2, '0');
                        const minute = String(parsed.getMinutes()).padStart(2, '0');
                        return `${month}-${day} ${hour}:${minute}`;
                    };

                    const displaySyncText = (item) => {
                        const raw = (item.lastSynced || '').trim();
                        if (!raw) return '最近同步：未知';
                        return `最近同步：${formatSyncValue(raw) || raw}`;
                    };

                    const buildCards = (groupKey) => {
                        const groups = groupKey === 'all'
                            ? sourceGroups.filter((group) => group.key !== 'all')
                            : sourceGroups.filter((group) => group.key === groupKey);

                        const escapeAttr = (value) => String(value || '')
                            .replace(/&/g, '&amp;')
                            .replace(/"/g, '&quot;')
                            .replace(/</g, '&lt;')
                            .replace(/>/g, '&gt;');

                        const renderSourceIcon = (item, group) => {
                            const fallback = iconForKind(item.kind || group.kind);
                            const logoUrl = (item.logo_url || '').trim();
                            if (!logoUrl) {
                                return `<div class="pulse-static-source-icon"><span class="pulse-static-source-icon-fallback">${fallback}</span></div>`;
                            }
                            return `<div class="pulse-static-source-icon">
                                <img src="${escapeAttr(logoUrl)}" alt="${escapeAttr(item.name)} logo" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display='none'; this.nextElementSibling.style.display='inline-flex';">
                                <span class="pulse-static-source-icon-fallback" style="display:none;">${fallback}</span>
                            </div>`;
                        };

                        return groups.flatMap((group) => group.items.map((item) => `
                            <article class="pulse-static-source-card${item.healthy ? '' : ' is-unhealthy'}">
                                <div class="pulse-static-source-head">
                                    <div class="pulse-static-source-brand">
                                        ${renderSourceIcon(item, group)}
                                        <div class="pulse-static-source-name">${item.name}</div>
                                    </div>
                                    <div class="pulse-static-source-status">
                                        <span class="pulse-static-source-status-dot"></span>
                                        ${item.healthy ? 'Healthy' : 'Unhealthy'}
                                    </div>
                                </div>
                                <div class="pulse-static-source-tag" data-kind="${item.kind || group.kind}">${item.kind || group.kind}</div>
                                <div class="pulse-static-source-meta">${displaySyncText(item)}</div>
                                <div class="pulse-static-source-extra">分组：${group.label} · 状态：${item.status || (item.healthy ? 'live_ok' : 'failed')}${item.strategy ? ` · 策略：${item.strategy}` : ''}</div>
                            </article>
                        `)).join('');
                    };

                    sourceSection = document.createElement('section');
                    sourceSection.id = 'sources';
                    sourceSection.className = 'pulse-static-sources';
                    sourceSection.innerHTML = `
                        <div class="dashboard-card-header">
                            <div class="dashboard-card-title">信源汇总</div>
                        </div>
                        <div class="pulse-static-source-tabs">
                            ${sourceGroups.map((group, index) => `
                                <button type="button" class="pulse-static-source-tab${index === 0 ? ' is-active' : ''}" data-group="${group.key}">
                                    <span>${group.label}</span>
                                    <span class="pulse-static-source-tab-count">${group.items.length}</span>
                                </button>
                            `).join('')}
                        </div>
                        <div class="pulse-static-sources-grid">
                            ${buildCards('all')}
                        </div>
                    `;
                    content.appendChild(sourceSection);

                    const tabs = Array.from(sourceSection.querySelectorAll('.pulse-static-source-tab'));
                    const grid = sourceSection.querySelector('.pulse-static-sources-grid');
                    tabs.forEach((tab) => {
                        tab.addEventListener('click', () => {
                            tabs.forEach((button) => button.classList.toggle('is-active', button === tab));
                            if (grid) {
                                grid.innerHTML = buildCards(tab.dataset.group || 'all');
                            }
                        });
                    });
                }

                let archiveSection = document.querySelector('#archive');
                if (content && !archiveSection) {
                    archiveSection = document.createElement('section');
                    archiveSection.id = 'archive';
                    archiveSection.className = 'pulse-static-archive';
                    archiveSection.innerHTML = `
                        <div class="pulse-static-archive-days">
                            <div class="pulse-static-archive-empty">正在加载归档列表...</div>
                        </div>
                    `;
                    content.appendChild(archiveSection);

                    const listEl = archiveSection.querySelector('.pulse-static-archive-days');

                    const renderArchiveList = (days) => {
                        if (!listEl) return;
                        if (!Array.isArray(days) || !days.length) {
                            listEl.innerHTML = `
                                <div class="pulse-static-archive-empty">
                                    暂无归档。归档只会保留每天最后一个时间点的快照。<br/>
                                    你也可以直接访问 <a href="/#archive" data-external="true">最新日报归档分区</a>。
                                </div>
                            `;
                            return;
                        }

                        listEl.innerHTML = days.map((day) => {
                            const date = String(day.date || '');
                            const path = date ? `/archive/${date}.html` : '';
                            return `
                                <a class="pulse-static-archive-day" href="${path}">
                                    <div class="pulse-static-archive-label">Archive Day</div>
                                    <div class="pulse-static-archive-date">${date}</div>
                                    <div class="pulse-static-archive-copy">点击进入当天归档详情</div>
                                </a>
                            `;
                        }).join('');
                    };

                    const loadArchive = async () => {
                        try {
                            const resp = await fetch('/archive/manifest.json', { cache: 'no-store' });
                            if (!resp.ok) throw new Error(`manifest http ${resp.status}`);
                            const manifest = await resp.json();
                            renderArchiveList(manifest?.days || []);
                        } catch (e) {
                            try {
                                const resp = await fetch('/', { cache: 'no-store' });
                                if (!resp.ok) throw new Error(`archive index http ${resp.status}`);
                                const html = await resp.text();
                                const doc = new DOMParser().parseFromString(html, 'text/html');
                                const cards = Array.from(doc.querySelectorAll('.archive-day-card'));
                                const fallbackDays = cards.map((card) => {
                                    const href = String(card.getAttribute('href') || '');
                                    const fromHref = href.replace(/^\.\//, '').replace(/\.html$/, '').trim();
                                    const date = (card.querySelector('.archive-day-pill')?.textContent || fromHref || '').trim();
                                    return {
                                        date,
                                    };
                                }).filter((day) => day.date);
                                renderArchiveList(fallbackDays);
                            } catch (e2) {
                                if (listEl) {
                                    listEl.innerHTML = `
                                        <div class="pulse-static-archive-empty">
                                            归档列表加载失败。你可以直接访问 <a href="/#archive" data-external="true">最新日报归档分区</a>。<br/>
                                            也可能是服务端还未生成 <code>/archive/manifest.json</code>。
                                        </div>
                                    `;
                                }
                            }
                        }
                    };

                    loadArchive();
                }

                const buildOverview = () => {
                    if (!header) return;
                    const title = header.querySelector('.header-title');
                    const subtitle = header.querySelector('.pulse-static-subtitle');
                    const headerShell = header.querySelector('.header-shell');
                    const infoItems = Array.from(header.querySelectorAll('.info-item')).map((item) => ({
                        label: item.querySelector('.info-label')?.textContent?.trim() || '',
                        value: item.querySelector('.info-value')?.textContent?.trim() || '',
                    })).filter((item) => item.label && item.value && item.label !== '报告类型');

                    if (title) title.textContent = '';
                    if (subtitle) {
                        subtitle.innerHTML = '<span class="pulse-subtitle-ornament" aria-hidden="true"></span><span class="pulse-subtitle-text">把热榜、网站、社交讨论和 AI 研判收进一个真正可导航的观察台</span>';
                    }
                    if (headerShell) headerShell.remove();
                    if (header.querySelector('.pulse-overview-shell')) return;

                    const noteMap = {
                        '新闻总数': '本轮共探测到的新闻总数',
                        '入选新闻': '筛选后入选条数',
                        '生成日期': '本轮探测生成日期',
                        '生成时间': '本轮探测生成时间',
                    };

                    const escapeHtml = (value) => String(value || '')
                        .replace(/&/g, '&amp;')
                        .replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;')
                        .replace(/"/g, '&quot;')
                        .replace(/'/g, '&#39;');

                    const parseCount = (value) => {
                        const match = String(value || '').match(/\d+/);
                        return match ? Number(match[0]) : 0;
                    };

                    const normalizeGeneratedTime = (value) => {
                        const raw = String(value || '').trim();
                        const match = raw.match(/(?:(\d{4})[-/.])?(\d{1,2})[-/.](\d{1,2})\s+(\d{1,2}:\d{2})/);
                        if (!match) {
                            return { date: raw || '今日', time: raw || '--:--' };
                        }
                        return {
                            date: `${Number(match[2])}月${Number(match[3])}日`,
                            time: match[4],
                        };
                    };

                    const buildStatItems = () => {
                        const items = [];
                        const total = infoItems.find((item) => item.label === '新闻总数');
                        const selected = infoItems.find((item) => item.label === '入选新闻');
                        const generated = infoItems.find((item) => item.label === '生成时间') || infoItems.find((item) => item.label === '生成日期');
                        const generatedParts = normalizeGeneratedTime(generated?.value || '');
                        if (total) items.push(total);
                        if (selected) items.push(selected);
                        items.push({ label: '生成日期', value: generatedParts.date });
                        items.push({ label: '生成时间', value: generatedParts.time });
                        return items.slice(0, 4);
                    };

                    const topicMeta = [
                        { label: '涉华叙事', icon: 'globe' },
                        { label: '周边局势', icon: 'map' },
                        { label: '宏观金融', icon: 'chart' },
                        { label: '公共安全', icon: 'shield' },
                        { label: '社会民生', icon: 'people' },
                        { label: '科技治理', icon: 'chip' },
                        { label: '历史文化', icon: 'book' },
                        { label: '结构风险', icon: 'risk' },
                        { label: '扩散信号', icon: 'wave' },
                        { label: '台海局势', icon: 'strait' },
                        { label: '政策监管', icon: 'policy' },
                        { label: '公共治理', icon: 'govern' },
                        { label: '国际传播', icon: 'media' },
                        { label: '外交博弈', icon: 'dialogue' },
                        { label: '舆情发酵', icon: 'spark' },
                        { label: '内容安全', icon: 'lock' },
                        { label: '突发灾害', icon: 'alert' },
                        { label: '食品医药', icon: 'med' },
                    ];

                    const topicIconMap = new Map(topicMeta.map((item) => [item.label, item.icon]));

                    const collectTopicStats = () => {
                        const counts = new Map();
                        document.querySelectorAll('.hotlist-section .word-group').forEach((group) => {
                            const name = group.querySelector('.word-name')?.textContent?.trim() || '';
                            const count = parseCount(group.querySelector('.word-count')?.textContent || '');
                            if (name && count) counts.set(name, (counts.get(name) || 0) + count);
                        });
                        document.querySelectorAll('.rss-section .feed-group').forEach((group) => {
                            const name = group.querySelector('.feed-name')?.textContent?.trim() || '';
                            const count = parseCount(group.querySelector('.feed-count')?.textContent || '');
                            if (name && count) counts.set(name, (counts.get(name) || 0) + count);
                        });
                        const fallback = [
                            ['涉华叙事', 28],
                            ['公共安全', 21],
                            ['外交博弈', 17],
                            ['社会民生', 14],
                            ['宏观金融', 12],
                            ['扩散信号', 8],
                        ];
                        if (!counts.size) {
                            fallback.forEach(([name, count]) => counts.set(name, count));
                        }
                        return Array.from(counts.entries())
                            .map(([label, count]) => ({
                                label,
                                count,
                                icon: topicIconMap.get(label) || 'wave',
                            }))
                            .sort((a, b) => b.count - a.count)
                            .slice(0, 6);
                    };

                    const statItems = buildStatItems();
                    const chartItems = collectTopicStats();
                    const maxChartCount = Math.max(1, ...chartItems.map((item) => item.count));
                    const chartHtml = chartItems.map((item) => {
                        const width = Math.max(8, Math.round((item.count / maxChartCount) * 100));
                        return `
                            <div class="pulse-overview-chart-row">
                                <div class="pulse-overview-chart-label">${escapeHtml(item.label)}</div>
                                <div class="pulse-overview-chart-track"><span class="pulse-overview-chart-fill" style="width:${width}%"></span></div>
                                <div class="pulse-overview-chart-count">${item.count}条</div>
                            </div>
                        `;
                    }).join('');
                    const topicPills = topicMeta.map((item, index) => `
                        <span class="pulse-topic-pill ${index < 3 ? 'is-hot' : ''}" data-icon="${item.icon}">${escapeHtml(item.label)}</span>
                    `).join('');
                    const sourceItems = [
                        ...normalizeCatalogItems(sourceCatalog.hotlist, [], 'WEB'),
                        ...normalizeCatalogItems(sourceCatalog.website, [], 'RSS'),
                        ...normalizeCatalogItems(sourceCatalog.media, [], 'SOCIAL'),
                    ];
                    const healthySourceCount = sourceItems.filter((item) => item.healthy && item.freshToday).length || sourceItems.length;
                    const statusItems = [
                        { label: 'SOURCE ONLINE', value: `${healthySourceCount || '--'} / ${sourceItems.length || '--'} 信源` },
                        { label: 'TOPIC COVERAGE', value: `${chartItems.length} / ${topicMeta.length} 主题` },
                        { label: 'ARCHIVE DAYS', value: '归档读取中' },
                        { label: 'AI ANALYSIS', value: document.querySelector('.ai-section, .dashboard-ai, .ai-grid-card') ? '已完成' : '待更新' },
                    ];

                    const overviewShell = document.createElement('div');
                    overviewShell.className = 'pulse-overview-shell';
                    overviewShell.innerHTML = `
                        <div class="pulse-overview-stats">
                            ${statItems.map((item) => `
                                <div class="pulse-overview-stat">
                                    <div class="pulse-overview-stat-label">${escapeHtml(item.label)}</div>
                                    <div class="pulse-overview-stat-value">${escapeHtml(item.value)}</div>
                                    <div class="pulse-overview-stat-note">${noteMap[item.label] || '实时报告概览'}</div>
                                </div>
                            `).join('')}
                        </div>
                        <div class="pulse-overview-chart-card">
                            <div class="pulse-overview-chart">${chartHtml}</div>
                        </div>
                        <div class="pulse-topic-carousel">
                            <div class="pulse-topic-track-shell">
                                <div class="pulse-topic-track">
                                    ${topicPills}${topicPills}
                                </div>
                            </div>
                        </div>
                        <div class="pulse-overview-status-band">
                            ${statusItems.map((item) => `
                                <div class="pulse-overview-status-item">
                                    <span class="pulse-overview-status-dot" aria-hidden="true"></span>
                                    <span class="pulse-overview-status-label">${escapeHtml(item.label)}</span>
                                    <span class="pulse-overview-status-value"${item.label === 'ARCHIVE DAYS' ? ' data-overview-archive-days' : ''}>${escapeHtml(item.value)}</span>
                                </div>
                            `).join('')}
                        </div>
                    `;
                    header.appendChild(overviewShell);
                    const archiveDaysEl = overviewShell.querySelector('[data-overview-archive-days]');
                    if (archiveDaysEl) {
                        fetch('/archive/manifest.json', { cache: 'no-store' })
                            .then((resp) => resp.ok ? resp.json() : Promise.reject(new Error(`archive http ${resp.status}`)))
                            .then((manifest) => {
                                const count = Array.isArray(manifest?.days) ? manifest.days.length : 0;
                                archiveDaysEl.textContent = count ? `${count} 天可查` : '暂无归档';
                            })
                            .catch(() => {
                                const count = document.querySelectorAll('.archive-day-card').length;
                                archiveDaysEl.textContent = count ? `${count} 天可查` : '归档待同步';
                            });
                    }
                };

                const addRssItemNumbers = () => {
                    document.querySelectorAll('.dashboard-rss .feed-group').forEach((group) => {
                        Array.from(group.querySelectorAll('.rss-item')).forEach((item, index) => {
                            const firstChild = item.firstElementChild;
                            if (firstChild && firstChild.classList.contains('news-number')) {
                                firstChild.textContent = String(index + 1);
                                return;
                            }
                            const number = document.createElement('div');
                            number.className = 'news-number';
                            number.textContent = String(index + 1);
                            item.insertBefore(number, item.firstChild);
                        });
                    });
                };

                const bindSocialCommentRails = () => {
                    if (document.body.dataset.socialCommentRailBound === '1') return;
                    document.body.dataset.socialCommentRailBound = '1';

                    let activeText = null;
                    let startX = 0;
                    let startOffset = 0;
                    let lastFrameTs = performance.now();
                    const marqueeSpeed = 0.012;
                    const getCommentContent = (text) => text?.querySelector('.social-comment-content');
                    const getCommentMetrics = (text) => {
                        const content = getCommentContent(text);
                        if (!text || !content) return { content: null, viewportWidth: 0, contentWidth: 0, maxOffset: 0 };
                        const viewportWidth = Math.max(text.clientWidth, text.getBoundingClientRect().width);
                        const contentWidth = Math.max(content.scrollWidth, content.getBoundingClientRect().width);
                        const maxOffset = Math.max(0, contentWidth - viewportWidth);
                        return { content, viewportWidth, contentWidth, maxOffset };
                    };
                    const getCommentOffset = (text) => Number(text?.dataset.marqueeOffset || '0');
                    const setCommentOffset = (text, offset) => {
                        const { content, maxOffset } = getCommentMetrics(text);
                        if (!content) return;
                        const nextOffset = Math.max(0, Math.min(offset, maxOffset));
                        text.dataset.marqueeOffset = String(nextOffset);
                        content.style.transform = `translate3d(${-nextOffset}px, 0, 0)`;
                    };

                    document.addEventListener('pointerdown', (event) => {
                        const text = event.target.closest('.social-comment-text');
                        const { maxOffset } = getCommentMetrics(text);
                        if (!text || maxOffset <= 2) return;
                        activeText = text;
                        startX = event.clientX;
                        startOffset = getCommentOffset(text);
                        text.dataset.marqueeReset = '0';
                        text.classList.add('is-dragging');
                        text.setPointerCapture?.(event.pointerId);
                    });

                    document.addEventListener('pointermove', (event) => {
                        if (!activeText) return;
                        const deltaX = event.clientX - startX;
                        if (Math.abs(deltaX) > 2) {
                            setCommentOffset(activeText, startOffset - deltaX);
                            activeText.dataset.marqueePauseUntil = String(performance.now() + 1800);
                            event.preventDefault();
                        }
                    }, { passive: false });

                    const stopDrag = () => {
                        if (!activeText) return;
                        activeText.dataset.marqueePauseUntil = String(performance.now() + 1800);
                        activeText.classList.remove('is-dragging');
                        activeText = null;
                    };

                    document.addEventListener('pointerup', stopDrag);
                    document.addEventListener('pointercancel', stopDrag);

                    document.addEventListener('wheel', (event) => {
                        const text = event.target.closest('.social-comment-text');
                        if (!text) return;
                        text.dataset.marqueePauseUntil = String(performance.now() + 1200);
                        const absX = Math.abs(event.deltaX);
                        const absY = Math.abs(event.deltaY);
                        if (absY >= absX && absY > 0) {
                            const multiplier = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? window.innerHeight : 1;
                            window.scrollBy({ top: event.deltaY * multiplier, left: 0, behavior: 'auto' });
                            event.preventDefault();
                            return;
                        }
                        const { maxOffset } = getCommentMetrics(text);
                        if (absX > 0 && maxOffset > 2) {
                            text.dataset.marqueeReset = '0';
                            setCommentOffset(text, getCommentOffset(text) + event.deltaX);
                            event.preventDefault();
                        }
                    }, { passive: false });

                    const tickMarquee = (timestamp) => {
                        const elapsed = Math.min(48, timestamp - lastFrameTs);
                        lastFrameTs = timestamp;
                        document.querySelectorAll('.social-comment-text:not([data-comment-empty="1"])').forEach((text) => {
                            if (text === activeText) return;
                            const { viewportWidth, maxOffset } = getCommentMetrics(text);
                            if (viewportWidth <= 2) return;
                            if (maxOffset <= 2) {
                                setCommentOffset(text, 0);
                                text.removeAttribute('data-comment-marquee');
                                return;
                            }
                            text.dataset.commentMarquee = '1';
                            const pauseUntil = Number(text.dataset.marqueePauseUntil || '0');
                            if (timestamp < pauseUntil) return;
                            if (text.dataset.marqueeReset === '1') {
                                setCommentOffset(text, 0);
                                text.dataset.marqueeReset = '0';
                                text.dataset.marqueePauseUntil = String(timestamp + 900);
                                return;
                            }
                            const speed = marqueeSpeed;
                            const nextOffset = getCommentOffset(text) + (elapsed * speed);
                            if (nextOffset >= maxOffset) {
                                setCommentOffset(text, maxOffset);
                                text.dataset.marqueeReset = '1';
                                text.dataset.marqueePauseUntil = String(timestamp + 1400);
                            } else {
                                setCommentOffset(text, nextOffset);
                            }
                        });
                        window.requestAnimationFrame(tickMarquee);
                    };
                    window.requestAnimationFrame(tickMarquee);
                };

                const bindAiFlipCards = () => {
                    if (document.body.dataset.aiFlipBound === '1') return;
                    document.body.dataset.aiFlipBound = '1';

                    const setFlipState = (card, nextState) => {
                        if (!card) return;
                        card.classList.toggle('is-flipped', nextState);
                        const front = card.querySelector('[data-ai-flip-card-toggle]');
                        if (front) {
                            front.setAttribute('aria-pressed', nextState ? 'true' : 'false');
                        }
                    };

                    document.addEventListener('click', (event) => {
                        if (event.target.closest('.ai-cluster-event-link')) {
                            return;
                        }

                        const backButton = event.target.closest('[data-ai-flip-card-back]');
                        if (backButton) {
                            event.preventDefault();
                            setFlipState(backButton.closest('[data-ai-flip-card]'), false);
                            return;
                        }

                        const toggle = event.target.closest('[data-ai-flip-card-toggle]');
                        if (toggle) {
                            event.preventDefault();
                            const card = toggle.closest('[data-ai-flip-card]');
                            if (card) {
                                setFlipState(card, !card.classList.contains('is-flipped'));
                            }
                        }
                    });

                    document.addEventListener('keydown', (event) => {
                        const toggle = event.target.closest('[data-ai-flip-card-toggle]');
                        if (toggle && (event.key === 'Enter' || event.key === ' ')) {
                            event.preventDefault();
                            const card = toggle.closest('[data-ai-flip-card]');
                            if (card) {
                                setFlipState(card, !card.classList.contains('is-flipped'));
                            }
                            return;
                        }

                        if (event.key === 'Escape') {
                            document.querySelectorAll('[data-ai-flip-card].is-flipped').forEach((card) => {
                                setFlipState(card, false);
                            });
                        }
                    });

                    document.querySelectorAll('[data-ai-cluster-event-list], .ai-cluster-event-list').forEach((list) => {
                        if (list.dataset.aiClusterWheelBound === '1') return;
                        list.dataset.aiClusterWheelBound = '1';
                        list.addEventListener('wheel', (event) => {
                            const maxScrollTop = list.scrollHeight - list.clientHeight;
                            if (maxScrollTop <= 0 || Math.abs(event.deltaY) <= Math.abs(event.deltaX)) {
                                return;
                            }

                            const previousScrollTop = list.scrollTop;
                            const nextScrollTop = Math.min(
                                maxScrollTop,
                                Math.max(0, previousScrollTop + event.deltaY)
                            );

                            if (nextScrollTop !== previousScrollTop) {
                                list.scrollTop = nextScrollTop;
                                event.preventDefault();
                                event.stopPropagation();
                            }
                        }, { passive: false });
                    });
                };

                const initOverviewLiveTuner = () => {
                    const params = new URLSearchParams(window.location.search);
                    if (params.get('tuner') !== '1' || document.querySelector('.pulse-live-tuner')) return;

                    const groups = [
                        { title: '整体与外框', controls: [
                            ['--po-main-pad', '页面外边距', 8, 42, 1, 'px'],
                            ['--po-header-pad-x', '外框左右内边距', 12, 48, 1, 'px'],
                            ['--po-header-pad-y', '外框上边距', 8, 32, 1, 'px'],
                            ['--po-header-pad-bottom', '外框下边距', 4, 28, 1, 'px'],
                            ['--po-overview-width', '首页内容宽度', 980, 1500, 2, 'px'],
                            ['--po-overview-margin-top', '标题到卡片距离', 0, 40, 1, 'px'],
                            ['--po-overview-gap', '板块间距总控', 4, 32, 1, 'px'],
                            ['--po-stat-chart-gap', '数据卡到数据条', 0, 36, 1, 'px'],
                            ['--po-chart-topic-gap', '数据条到胶囊', 0, 36, 1, 'px'],
                            ['--po-panel-radius', '外层圆角', 8, 28, 1, 'px'],
                        ] },
                        { title: '四个数据卡', controls: [
                            ['--po-stat-height', '卡片高度', 82, 160, 1, 'px'],
                            ['--po-stat-gap', '卡片间距', 6, 26, 1, 'px'],
                            ['--po-stat-pad-x', '左右内边距', 10, 30, 1, 'px'],
                            ['--po-stat-pad-y', '上下内边距', 8, 24, 1, 'px'],
                            ['--po-stat-value-size', '数字字号', 26, 54, 1, 'px'],
                            ['--po-stat-radius', '卡片圆角', 8, 24, 1, 'px'],
                        ] },
                        { title: '数据条区域', controls: [
                            ['--po-chart-height', '数据区高度', 78, 190, 1, 'px'],
                            ['--po-chart-pad-x', '左右内边距', 8, 36, 1, 'px'],
                            ['--po-chart-pad-y', '上下内边距', 6, 28, 1, 'px'],
                            ['--po-chart-row-gap', '数据行距', 3, 20, 1, 'px'],
                            ['--po-chart-col-gap', '左右列间距', 16, 84, 1, 'px'],
                            ['--po-chart-bar-gap', '文字/条/数字间距', 8, 30, 1, 'px'],
                            ['--po-chart-bar-height', '数据条高度', 8, 20, 1, 'px'],
                        ] },
                        { title: '轮播胶囊与图标', controls: [
                            ['--po-topic-pad-y', '轨道上下内边距', 4, 20, 1, 'px'],
                            ['--po-topic-height', '胶囊高度', 32, 58, 1, 'px'],
                            ['--po-topic-width', '胶囊宽度', 126, 220, 1, 'px'],
                            ['--po-topic-gap', '胶囊间距', 6, 30, 1, 'px'],
                            ['--po-topic-track-pad-x', '轨道左右留白', 24, 130, 1, 'px'],
                            ['--po-topic-icon-size', '图标外圈', 24, 44, 1, 'px'],
                            ['--po-topic-glyph-size', '图标符号', 12, 28, 1, 'px'],
                            ['--po-topic-speed', '轮播速度', 30, 140, 1, 's'],
                        ] },
                    ];

                    const storageKey = 'pulse-live-overview-tuner-v1';
                    const positionKey = 'pulse-live-overview-tuner-position-v1';
                    const presets = [
                        { label: '紧凑', values: {
                            '--po-stat-height': '92px',
                            '--po-stat-gap': '10px',
                            '--po-stat-pad-x': '14px',
                            '--po-stat-pad-y': '10px',
                            '--po-stat-value-size': '34px',
                            '--po-stat-radius': '12px',
                        } },
                        { label: '均衡', values: {
                            '--po-stat-height': '112px',
                            '--po-stat-gap': '14px',
                            '--po-stat-pad-x': '18px',
                            '--po-stat-pad-y': '14px',
                            '--po-stat-value-size': '40px',
                            '--po-stat-radius': '16px',
                        } },
                        { label: '舒展', values: {
                            '--po-stat-height': '132px',
                            '--po-stat-gap': '18px',
                            '--po-stat-pad-x': '22px',
                            '--po-stat-pad-y': '18px',
                            '--po-stat-value-size': '46px',
                            '--po-stat-radius': '18px',
                        } },
                    ];
                    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
                    const bodyStyles = getComputedStyle(document.body);
                    const readVar = (name) => document.body.style.getPropertyValue(name).trim() || saved[name] || bodyStyles.getPropertyValue(name).trim();
                    const parseNumber = (value) => Number(String(value || '').replace(/[a-z%]+/gi, '')) || 0;

                    const panel = document.createElement('aside');
                    panel.className = 'pulse-live-tuner';
                    panel.innerHTML = `
                        <div class="pulse-live-tuner-toolbar">
                            <div class="pulse-live-tuner-head" data-tuner-drag>
                                <div>
                                    <h2>真实页面调参台</h2>
                                    <p>这里直接调当前正式首页 DOM。参数保存在本机浏览器，调满意后复制参数发我即可上线。</p>
                                </div>
                                <button class="pulse-live-tuner-handle" type="button" data-tuner-drag-button title="拖动调参台">拖动</button>
                            </div>
                            <div class="pulse-live-tuner-presets" aria-label="卡片参数套餐">
                                ${presets.map((preset, index) => `<button type="button" data-tuner-preset="${index}">${preset.label}</button>`).join('')}
                            </div>
                            <div class="pulse-live-tuner-status" data-tuner-status role="status" aria-live="polite"></div>
                        </div>
                        <div class="pulse-live-tuner-controls"></div>
                        <div class="pulse-live-tuner-actions">
                            <button type="button" data-tuner-reset>恢复默认</button>
                            <button type="button" data-tuner-copy>复制参数</button>
                        </div>
                        <pre data-tuner-export></pre>
                    `;
                    document.body.appendChild(panel);

                    const controlsEl = panel.querySelector('.pulse-live-tuner-controls');
                    const exportEl = panel.querySelector('[data-tuner-export]');
                    const statusEl = panel.querySelector('[data-tuner-status]');
                    const setVar = (name, value, unit) => document.body.style.setProperty(name, `${value}${unit}`);
                    const notify = (message) => {
                        statusEl.textContent = message;
                        window.clearTimeout(statusEl._timer);
                        statusEl._timer = window.setTimeout(() => {
                            statusEl.textContent = '';
                        }, 1600);
                    };

                    try {
                        const savedPosition = JSON.parse(localStorage.getItem(positionKey) || 'null');
                        if (savedPosition && Number.isFinite(savedPosition.left) && Number.isFinite(savedPosition.top)) {
                            panel.style.left = `${Math.max(8, Math.min(savedPosition.left, window.innerWidth - 80))}px`;
                            panel.style.top = `${Math.max(8, Math.min(savedPosition.top, window.innerHeight - 80))}px`;
                            panel.style.right = 'auto';
                        }
                    } catch (error) {
                        localStorage.removeItem(positionKey);
                    }

                    const renderExport = () => {
                        exportEl.textContent = groups
                            .flatMap((group) => group.controls.map(([name]) => `${name}: ${readVar(name)};`))
                            .join('\\n');
                    };

                    const saveState = () => {
                        const payload = {};
                        groups.forEach((group) => {
                            group.controls.forEach(([name]) => {
                                payload[name] = readVar(name);
                            });
                        });
                        localStorage.setItem(storageKey, JSON.stringify(payload));
                        renderExport();
                    };

                    controlsEl.innerHTML = '';
                    groups.forEach((group, groupIndex) => {
                        const section = document.createElement('section');
                        section.className = 'pulse-live-tuner-group';

                        const title = document.createElement('div');
                        title.className = 'pulse-live-tuner-title';
                        title.textContent = group.title;
                        section.appendChild(title);

                        group.controls.forEach(([name, label, min, max, step, unit]) => {
                            const value = parseNumber(readVar(name));
                            const control = document.createElement('div');
                            control.className = 'pulse-live-tuner-control';

                            const labelEl = document.createElement('label');
                            const inputId = `po-tuner-${groupIndex}-${name.replace(/[^a-z0-9-]/gi, '')}`;
                            labelEl.setAttribute('for', inputId);
                            labelEl.textContent = label;

                            const outputEl = document.createElement('output');
                            outputEl.textContent = `${value}${unit}`;

                            const input = document.createElement('input');
                            input.id = inputId;
                            input.type = 'range';
                            input.min = String(min);
                            input.max = String(max);
                            input.step = String(step);
                            input.value = String(value);
                            input.dataset.var = name;
                            input.dataset.unit = unit;

                            control.append(labelEl, outputEl, input);
                            section.appendChild(control);
                        });

                        controlsEl.appendChild(section);
                    });

                    controlsEl.querySelectorAll('input').forEach((input) => {
                        setVar(input.dataset.var, input.value, input.dataset.unit);
                        input.addEventListener('input', () => {
                            setVar(input.dataset.var, input.value, input.dataset.unit);
                            input.parentElement.querySelector('output').textContent = `${input.value}${input.dataset.unit}`;
                            saveState();
                        });
                    });

                    const syncControls = () => {
                        controlsEl.querySelectorAll('input').forEach((input) => {
                            const nextValue = parseNumber(readVar(input.dataset.var));
                            input.value = String(nextValue);
                            input.parentElement.querySelector('output').textContent = `${nextValue}${input.dataset.unit}`;
                        });
                    };

                    const highlightPreset = (activeIndex) => {
                        panel.querySelectorAll('[data-tuner-preset]').forEach((button) => {
                            button.classList.toggle('is-active', button.dataset.tunerPreset === String(activeIndex));
                        });
                    };

                    panel.querySelectorAll('[data-tuner-preset]').forEach((button) => {
                        button.addEventListener('click', () => {
                            const preset = presets[Number(button.dataset.tunerPreset)];
                            if (!preset) return;
                            Object.entries(preset.values).forEach(([name, value]) => {
                                document.body.style.setProperty(name, value);
                            });
                            syncControls();
                            saveState();
                            highlightPreset(button.dataset.tunerPreset);
                            notify(`已应用「${preset.label}」卡片套餐`);
                            button.textContent = `已应用`;
                            window.clearTimeout(button._labelTimer);
                            button._labelTimer = window.setTimeout(() => {
                                button.textContent = preset.label;
                            }, 1200);
                        });
                    });

                    const dragHandle = panel.querySelector('[data-tuner-drag]');
                    dragHandle.addEventListener('pointerdown', (event) => {
                        if (event.target.closest('button') && !event.target.closest('[data-tuner-drag-button]')) return;
                        const rect = panel.getBoundingClientRect();
                        const offsetX = event.clientX - rect.left;
                        const offsetY = event.clientY - rect.top;
                        panel.style.left = `${rect.left}px`;
                        panel.style.top = `${rect.top}px`;
                        panel.style.right = 'auto';
                        panel.style.bottom = 'auto';
                        dragHandle.setPointerCapture(event.pointerId);
                        const movePanel = (moveEvent) => {
                            const maxLeft = Math.max(8, window.innerWidth - panel.offsetWidth - 8);
                            const maxTop = Math.max(8, window.innerHeight - 80);
                            const nextLeft = Math.max(8, Math.min(moveEvent.clientX - offsetX, maxLeft));
                            const nextTop = Math.max(8, Math.min(moveEvent.clientY - offsetY, maxTop));
                            panel.style.left = `${nextLeft}px`;
                            panel.style.top = `${nextTop}px`;
                        };
                        const stopDrag = () => {
                            dragHandle.removeEventListener('pointermove', movePanel);
                            dragHandle.removeEventListener('pointerup', stopDrag);
                            dragHandle.removeEventListener('pointercancel', stopDrag);
                            localStorage.setItem(positionKey, JSON.stringify({
                                left: parseFloat(panel.style.left) || 18,
                                top: parseFloat(panel.style.top) || 18,
                            }));
                            notify('调参台位置已保存');
                        };
                        dragHandle.addEventListener('pointermove', movePanel);
                        dragHandle.addEventListener('pointerup', stopDrag);
                        dragHandle.addEventListener('pointercancel', stopDrag);
                    });

                    panel.querySelector('[data-tuner-reset]').addEventListener('click', () => {
                        localStorage.removeItem(storageKey);
                        localStorage.removeItem(positionKey);
                        groups.forEach((group) => {
                            group.controls.forEach(([name]) => document.body.style.removeProperty(name));
                        });
                        panel.remove();
                        initOverviewLiveTuner();
                    });

                    panel.querySelector('[data-tuner-copy]').addEventListener('click', async (event) => {
                        await navigator.clipboard.writeText(exportEl.textContent);
                        event.currentTarget.textContent = '已复制';
                        notify('参数已复制到剪贴板');
                        setTimeout(() => {
                            event.currentTarget.textContent = '复制参数';
                        }, 1200);
                    });

                    renderExport();
                };

                const wrapSection = (node, options) => {
                    if (!node || !content) return null;
                    const wrapper = document.createElement('section');
                    wrapper.id = options.id;
                    wrapper.className = 'pulse-panel';
                    wrapper.innerHTML = `
                        <div class="pulse-panel-head">
                            <div class="pulse-panel-copy">
                                <div class="pulse-panel-kicker">${options.kicker}</div>
                                <div class="pulse-panel-desc">${options.desc}</div>
                            </div>
                            <div class="pulse-panel-meta">${options.meta || ''}</div>
                        </div>
                        <div class="pulse-panel-body"></div>
                    `;
                    node.removeAttribute('id');
                    wrapper.querySelector('.pulse-panel-body').appendChild(node);
                    return wrapper;
                };

                buildOverview();
                initOverviewLiveTuner();
                addRssItemNumbers();
                bindSocialCommentRails();
                bindAiFlipCards();

                const panelStore = {};

                if (content) {
                    const sections = [
                        {
                            node: socialCard,
                            id: 'media',
                            kicker: 'Media Watch',
                            title: '媒体观测',
                            desc: '聚合 X 与 Reddit 观察名单，保留你真正关心的公开讨论切片。',
                            meta: socialCard?.querySelectorAll('.social-item').length ? `${socialCard.querySelectorAll('.social-item').length} 条` : '',
                        },
                        {
                            node: hotlistCard,
                            id: 'hotlist',
                            kicker: 'Hotlist Monitor',
                            title: '热榜监测',
                            desc: '追踪各平台热度变化，把高频争议和榜单位次放进同一视图。',
                            meta: hotlistCard?.querySelectorAll('.news-item').length ? `${hotlistCard.querySelectorAll('.news-item').length} 条` : '',
                        },
                        {
                            node: rssCard,
                            id: 'website',
                            kicker: 'Website Monitor',
                            title: '网站监测',
                            desc: '汇总重点媒体与观察站点的当日更新，用独立 section 呈现网站脉络。',
                            meta: rssCard?.querySelectorAll('.rss-item').length ? `${rssCard.querySelectorAll('.rss-item').length} 条` : '',
                        },
                        {
                            node: aiCard,
                            id: 'ai-insight',
                            kicker: 'AI Insight',
                            title: 'AI 洞察',
                            desc: '把热榜、网站监测和媒体观测纳入统一研判，输出主线议题与传播观察。',
                            meta: '',
                        },
                        {
                            node: sourceSection,
                            id: 'sources',
                            kicker: 'Source Directory',
                            title: '信源汇总',
                            desc: '按热榜监测、网站监测和媒体观测整理信源卡片，便于横向巡检。',
                            meta: sourceSection?.querySelectorAll('.pulse-static-source-card').length ? `${sourceSection.querySelectorAll('.pulse-static-source-card').length} 个` : '',
                        },
                        {
                            node: archiveSection,
                            id: 'archive',
                            kicker: 'Archive Center',
                            title: '查看归档',
                            desc: '按天查看历史产出，归档只保留每天最后一个时间点的快照。',
                            meta: '',
                        },
                    ].filter((section) => section.node);

                    if (sections.length) {
                        content.innerHTML = '';
                        sections.forEach((section) => {
                            const wrapped = wrapSection(section.node, section);
                            if (wrapped) {
                                panelStore[`#${section.id}`] = wrapped;
                            }
                        });
                    }
                }

                const navLinks = Array.from(document.querySelectorAll('.pulse-static-nav a'));
                const viewMap = { '#overview': header };
                Object.keys(panelStore).forEach((key) => {
                    viewMap[key] = panelStore[key];
                });

                const getCleanViewUrl = () => `${window.location.pathname}${window.location.search}`;

                const switchView = (hash) => {
                    const target = viewMap[hash];
                    if (!target) return;

                    if (header) {
                        header.classList.toggle('is-active', hash === '#overview');
                    }
                    document.body.classList.toggle('is-overview-active', hash === '#overview');

                    if (content) {
                        content.innerHTML = '';
                        if (hash === '#overview') {
                            Object.keys(panelStore).forEach((key) => {
                                const panel = panelStore[key];
                                if (panel) {
                                    panel.classList.remove('is-active');
                                    content.appendChild(panel);
                                }
                            });
                        } else if (panelStore[hash]) {
                            panelStore[hash].classList.add('is-active');
                            content.appendChild(panelStore[hash]);
                        }
                    }

                    navLinks.forEach((link) => {
                        link.classList.toggle('is-active', link.getAttribute('href') === hash);
                    });

                    window.scrollTo({ top: 0, behavior: 'auto' });
                };

                navLinks.forEach((link) => {
                    link.addEventListener('click', (event) => {
                        if (link.dataset.external === 'true') {
                            return;
                        }
                        event.preventDefault();
                        switchView(link.getAttribute('href'));
                    });
                });

                document.querySelectorAll('.pulse-overview-link').forEach((link) => {
                    link.addEventListener('click', (event) => {
                        if (link.dataset.external === 'true') {
                            return;
                        }
                        event.preventDefault();
                        switchView(link.getAttribute('href'));
                    });
                });

                const incomingHash = window.location.hash;
                const initialHash = viewMap[incomingHash] ? incomingHash : '#overview';
                switchView(initialHash);
                if (incomingHash && viewMap[incomingHash]) {
                    history.replaceState(null, '', getCleanViewUrl());
                }
                finishBoot();
            })();
        </script>
        </div>
    </body>
    </html>
    """

    return (
        html
        .replace("__PULSE_FAVICON_DATA__", favicon_svg)
        .replace("__SOURCE_CATALOG_JSON__", source_catalog_json)
    )
