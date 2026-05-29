# coding=utf-8
"""基于现有数据只重跑 AI 洞察并重渲染 HTML。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trendradar.__main__ import NewsAnalyzer, _save_run_report
from trendradar.core import load_config
from trendradar.core.scheduler import ResolvedSchedule
from trendradar.runtime.manifest import create_run_manifest
from trendradar.ai.analyzer import AIAnalysisResult


def _render_payload_path(date_str: str, mode: str) -> Path:
    return Path("output") / "meta" / "render_payloads" / date_str / f"{mode}.json"


def _save_render_payload(
    *,
    date_str: str,
    mode: str,
    stats: list[dict],
    total_titles: int,
    failed_ids: list[str],
    new_titles: dict,
    id_to_name: dict,
    update_info: dict | None,
    rss_items: list[dict] | None,
    rss_new_items: list[dict] | None,
    ai_result: AIAnalysisResult | None,
    standalone_data: dict | None,
    social_items: list[dict] | None,
    frequency_file: str | None,
    publish_latest: bool,
    publish_entry_index: bool,
) -> None:
    payload_file = _render_payload_path(date_str, mode)
    payload_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": date_str,
        "mode": mode,
        "stats": stats or [],
        "total_titles": total_titles,
        "failed_ids": failed_ids or [],
        "new_titles": new_titles or {},
        "id_to_name": id_to_name or {},
        "update_info": update_info or {},
        "rss_items": rss_items or [],
        "rss_new_items": rss_new_items or [],
        "ai_analysis": asdict(ai_result) if ai_result else None,
        "standalone_data": standalone_data or {},
        "social_items": social_items or [],
        "frequency_file": frequency_file or None,
        "publish_latest": bool(publish_latest),
        "publish_entry_index": bool(publish_entry_index),
    }
    payload_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_manual_schedule(base: ResolvedSchedule, mode: str) -> ResolvedSchedule:
    """构造只执行 AI + HTML 的手动调度结果。"""
    return ResolvedSchedule(
        period_key=base.period_key,
        period_name=base.period_name or "manual_ai_only",
        day_plan=base.day_plan,
        collect=False,
        analyze=True,
        push=False,
        report_mode=mode,
        ai_mode=base.ai_mode,
        once_analyze=False,
        once_push=False,
        frequency_file=base.frequency_file,
        filter_method=base.filter_method,
        interests_file=base.interests_file,
    )


def _load_existing_manifest() -> Optional[Dict[str, Any]]:
    manifest_path = Path("output") / "meta" / "run_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _seed_manifest(analyzer: NewsAnalyzer, mode: str) -> None:
    existing_manifest = _load_existing_manifest() or {}
    analyzer._run_report = create_run_manifest(
        version=existing_manifest.get("version", analyzer._run_report.get("version", "")),
        timezone_name=analyzer.ctx.timezone,
        prompt_versions=dict(existing_manifest.get("prompt_versions", {}) or analyzer._run_report.get("prompt_versions", {})),
        source_catalog_entries=analyzer.ctx.source_catalog_entries,
    )
    analyzer._run_report["started_at"] = datetime.now(timezone.utc).isoformat()
    analyzer._run_report["finished_at"] = ""
    analyzer._run_report["status"] = "running"
    analyzer._run_report["error"] = ""
    analyzer._run_report["steps"] = ["ai_only_rerun"]
    analyzer._run_report.setdefault("summary", {})["report_mode"] = mode


def _override_time(target_date: Optional[str]) -> None:
    if not target_date:
        return
    if os.environ.get("TRENDRADAR_NOW", "").strip():
        return
    os.environ["TRENDRADAR_NOW"] = f"{target_date}T12:00:00+08:00"


def _resolve_failed_ids(analyzer: NewsAnalyzer, mode: str, date: str) -> list[str]:
    if mode == "daily":
        news_data = analyzer.storage_manager.get_today_all_data(date)
    else:
        news_data = analyzer.storage_manager.get_latest_crawl_data(date)
    if not news_data:
        return []
    return list(news_data.failed_ids or [])


def main() -> int:
    parser = argparse.ArgumentParser(description="只重跑 AI 洞察并重渲染 HTML")
    parser.add_argument("--date", help="目标日期，格式 YYYY-MM-DD；默认取当前配置时区日期")
    parser.add_argument(
        "--mode",
        choices=["daily", "current", "incremental"],
        default="daily",
        help="报告模式，默认 daily",
    )
    parser.add_argument(
        "--skip-translation",
        action="store_true",
        help="跳过 RSS / 社交翻译，只重做 AI 洞察与 HTML",
    )
    args = parser.parse_args()

    _override_time(args.date)
    config = load_config()
    analyzer = NewsAnalyzer(config=config)

    if args.skip_translation:
        analyzer.ctx.config.setdefault("AI_TRANSLATION", {})["ENABLED"] = False

    analyzer.report_mode = args.mode
    _seed_manifest(analyzer, args.mode)

    try:
        scheduler = analyzer.ctx.create_scheduler()
        schedule = _build_manual_schedule(scheduler.resolve(), args.mode)
        analyzer.frequency_file = schedule.frequency_file
        analyzer.filter_method = schedule.filter_method or analyzer.ctx.filter_method
        analyzer.interests_file = schedule.interests_file

        target_date = analyzer.ctx.format_date()
        print(f"[AI-ONLY] 目标日期: {target_date}")
        print(f"[AI-ONLY] 报告模式: {args.mode}")

        analysis_data = analyzer._load_analysis_data()
        if not analysis_data:
            raise RuntimeError(f"未找到 {target_date} 的热榜历史数据，无法只重跑 AI")

        (
            all_results,
            id_to_name,
            title_info,
            new_titles,
            word_groups,
            filter_words,
            global_filters,
        ) = analysis_data

        failed_ids = _resolve_failed_ids(analyzer, args.mode, target_date)
        analyzer._run_report.setdefault("summary", {})["hotlist_failed_ids"] = failed_ids
        analyzer._sync_hotlist_source_status(all_results, failed_ids)

        rss_seed = analyzer.storage_manager.get_latest_rss_data(target_date)
        if rss_seed is None:
            rss_seed = analyzer.storage_manager.get_rss_data(target_date)

        rss_items = None
        rss_new_items = None
        raw_rss_items = None
        rss_new_urls = set()
        analyzer._last_rss_failed_ids = []

        if rss_seed:
            analyzer._last_rss_failed_ids = list(rss_seed.failed_ids or [])
            analyzer._run_report.setdefault("summary", {})["rss_failed_ids"] = analyzer._last_rss_failed_ids
            if rss_seed.source_status:
                analyzer._sync_rss_source_status(rss_seed.source_status)
            rss_items, rss_new_items, raw_rss_items, rss_new_urls = analyzer._process_rss_data_by_mode(rss_seed)
        else:
            print(f"[AI-ONLY] 未找到 {target_date} 的 RSS 数据，继续仅使用热榜/社交")

        social_items = analyzer._crawl_social_media_data()

        standalone_data = analyzer._prepare_standalone_data(
            all_results,
            id_to_name,
            title_info,
            raw_rss_items,
            hotlist_failed_ids=failed_ids,
            rss_failed_ids=analyzer._last_rss_failed_ids,
            social_source_status=getattr(analyzer, "_last_social_source_status", {}),
        )

        stats, html_file, ai_result, _ = analyzer._run_analysis_pipeline(
            all_results,
            args.mode,
            title_info,
            new_titles,
            word_groups,
            filter_words,
            id_to_name,
            failed_ids=failed_ids,
            global_filters=global_filters,
            rss_items=rss_items,
            rss_new_items=rss_new_items,
            standalone_data=standalone_data,
            social_items=social_items,
            schedule=schedule,
            rss_new_urls=rss_new_urls,
        )

        analyzer._run_report["status"] = "success"
        analyzer._run_report.setdefault("artifacts", {})["html_file"] = html_file or ""
        analyzer._run_report.setdefault("summary", {})["report_mode"] = args.mode
        analyzer._run_report.setdefault("summary", {})["stats_count"] = len(stats or [])
        analyzer._run_report.setdefault("summary", {})["ai_analysis_success"] = bool(ai_result and ai_result.success)
        analyzer._run_report["finished_at"] = datetime.now(timezone.utc).isoformat()

        _save_render_payload(
            date_str=target_date,
            mode=args.mode,
            stats=stats or [],
            total_titles=len(title_info or {}),
            failed_ids=failed_ids or [],
            new_titles=new_titles or {},
            id_to_name=id_to_name or {},
            update_info=analyzer.update_info if analyzer.ctx.config.get("SHOW_VERSION_UPDATE") else None,
            rss_items=rss_items or [],
            rss_new_items=rss_new_items or [],
            ai_result=ai_result,
            standalone_data=standalone_data or {},
            social_items=social_items or [],
            frequency_file=analyzer.frequency_file,
            publish_latest=bool(analyzer._last_publish_latest),
            publish_entry_index=bool(analyzer._last_publish_entry_index),
        )

        _save_run_report(analyzer._run_report)
        print(f"[AI-ONLY] 完成: {html_file or '未生成 HTML'}")
        return 0
    except Exception as exc:
        analyzer._run_report["status"] = "error"
        analyzer._run_report["error"] = str(exc)
        analyzer._run_report["finished_at"] = datetime.now(timezone.utc).isoformat()
        _save_run_report(analyzer._run_report)
        print(f"[AI-ONLY] 失败: {exc}")
        return 1
    finally:
        analyzer.ctx.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
