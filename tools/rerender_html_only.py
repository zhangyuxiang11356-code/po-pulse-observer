#!/usr/bin/env python3
# coding: utf-8
"""只基于已保存的渲染负载重新生成 HTML，不重新抓取、筛选、AI 或翻译。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trendradar.__main__ import _save_run_report
from trendradar.ai.analyzer import AIAnalysisResult
from trendradar.core import load_config
from trendradar.context import AppContext


def _override_time(target_date: str | None) -> None:
    if not target_date:
        return
    if os.environ.get("TRENDRADAR_NOW", "").strip():
        return
    os.environ["TRENDRADAR_NOW"] = f"{target_date}T12:00:00+08:00"


def _load_manifest(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _payload_path(date_str: str, mode: str) -> Path:
    return Path("output") / "meta" / "render_payloads" / date_str / f"{mode}.json"


def _restore_ai_result(payload: Dict[str, Any]) -> AIAnalysisResult | None:
    raw = payload.get("ai_analysis")
    if not isinstance(raw, dict):
        return None
    result = AIAnalysisResult()
    for key, value in raw.items():
        if hasattr(result, key):
            setattr(result, key, value)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="只重渲染 HTML")
    parser.add_argument("--date", help="目标日期，格式 YYYY-MM-DD；默认读取当前日期")
    parser.add_argument(
        "--mode",
        choices=["daily", "current", "incremental"],
        default="daily",
        help="报告模式，默认 daily",
    )
    args = parser.parse_args()

    _override_time(args.date)
    config = load_config()
    ctx = AppContext(config)

    target_date = args.date or ctx.format_date()
    payload_file = _payload_path(target_date, args.mode)
    if not payload_file.exists():
        print(f"[HTML-ONLY] 未找到渲染负载: {payload_file}")
        return 1

    payload = json.loads(payload_file.read_text(encoding="utf-8"))
    ai_result = _restore_ai_result(payload)
    standalone_data = dict(payload.get("standalone_data") or {})
    standalone_data["source_catalog"] = ctx.source_catalog_groups

    manifest_path = Path("output") / "meta" / "run_manifest.json"
    run_report = _load_manifest(manifest_path)
    if not run_report:
        run_report = {
            "status": "running",
            "summary": {},
            "publish": {},
            "artifacts": {},
            "steps": [],
        }

    run_report["started_at"] = datetime.now(timezone.utc).isoformat()
    run_report["finished_at"] = ""
    run_report["status"] = "running"
    run_report["error"] = ""
    run_report["steps"] = ["html_only_rerender"]
    run_report.setdefault("summary", {})["report_mode"] = args.mode

    try:
        html_file = ctx.generate_html(
            stats=payload.get("stats", []),
            total_titles=int(payload.get("total_titles", 0) or 0),
            failed_ids=payload.get("failed_ids", []),
            new_titles=payload.get("new_titles", {}),
            id_to_name=payload.get("id_to_name", {}),
            mode=args.mode,
            update_info=payload.get("update_info"),
            rss_items=payload.get("rss_items", []),
            rss_new_items=payload.get("rss_new_items", []),
            ai_analysis=ai_result,
            standalone_data=standalone_data,
            social_items=payload.get("social_items", []),
            frequency_file=(payload.get("frequency_file") or None),
            publish_latest=bool(payload.get("publish_latest", True)),
            publish_entry_index=bool(payload.get("publish_entry_index", args.mode == "daily")),
        )

        run_report["status"] = "success"
        run_report["finished_at"] = datetime.now(timezone.utc).isoformat()
        run_report.setdefault("artifacts", {})["html_file"] = html_file or ""
        run_report.setdefault("summary", {})["stats_count"] = len(payload.get("stats", []))
        run_report.setdefault("summary", {})["ai_analysis_success"] = bool(ai_result and ai_result.success)
        run_report.setdefault("publish", {})["latest"] = bool(payload.get("publish_latest", True))
        run_report.setdefault("publish", {})["entry_index"] = bool(payload.get("publish_entry_index", args.mode == "daily"))
        _save_run_report(run_report)
        print(f"[HTML-ONLY] 完成: {html_file}")
        return 0
    except Exception as exc:
        run_report["status"] = "error"
        run_report["error"] = str(exc)
        run_report["finished_at"] = datetime.now(timezone.utc).isoformat()
        _save_run_report(run_report)
        print(f"[HTML-ONLY] 失败: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
