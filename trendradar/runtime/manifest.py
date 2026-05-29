# coding=utf-8
"""统一运行清单。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from trendradar.sources import group_source_catalog


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_run_manifest(
    *,
    version: str,
    timezone_name: str,
    prompt_versions: Dict[str, str],
    source_catalog_entries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """初始化统一运行清单。"""
    return {
        "schema_version": "1.0",
        "version": version,
        "timezone": timezone_name,
        "started_at": _iso_now(),
        "finished_at": "",
        "status": "running",
        "steps": [],
        "error": "",
        "prompt_versions": dict(prompt_versions or {}),
        "publish": {
            "latest": False,
            "entry_index": False,
            "healthy": False,
            "reasons": [],
        },
        "artifacts": {
            "html_file": "",
            "latest_html": "",
            "entry_index": "",
            "manifest_latest": "",
            "manifest_snapshot": "",
            "run_report_latest": "",
            "run_report_snapshot": "",
        },
        "summary": {
            "report_mode": "",
            "hotlist_failed_ids": [],
            "rss_failed_ids": [],
            "social_failed_ids": [],
        },
        "source_catalog": {
            "entries": [deepcopy(entry) for entry in source_catalog_entries],
            "groups": group_source_catalog(source_catalog_entries),
        },
        "source_status": {
            str(entry.get("id")): {
                "status": "pending",
                "healthy": False,
                "count": 0,
                "last_synced": "",
                "error": "",
                "fetch_mode": "",
                "fresh_today": False,
            }
            for entry in source_catalog_entries
        },
    }


def merge_source_runtime(manifest: Dict[str, Any], source_id: str, **runtime: Any) -> None:
    """更新单个信源运行状态。"""
    source_status = manifest.setdefault("source_status", {})
    current = dict(source_status.get(source_id, {}))
    current.update({key: value for key, value in runtime.items() if value is not None})
    source_status[source_id] = current


def get_grouped_source_catalog(manifest: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """合并信源目录与运行状态，得到页面可直接消费的结构。"""
    entries = manifest.get("source_catalog", {}).get("entries", []) or []
    source_status = manifest.get("source_status", {}) or {}
    groups = {
        "hotlist": [],
        "website": [],
        "media": [],
    }
    for entry in entries:
        source_id = str(entry.get("id", "") or "")
        runtime = source_status.get(source_id, {})
        merged = {
            **deepcopy(entry),
            "healthy": bool(runtime.get("healthy", False)),
            "status": str(runtime.get("status", "pending") or "pending"),
            "count": int(runtime.get("count", 0) or 0),
            "last_synced": str(runtime.get("last_synced", "") or ""),
            "error": str(runtime.get("error", "") or ""),
            "fetch_mode": str(runtime.get("fetch_mode", "") or ""),
            "fresh_today": bool(runtime.get("fresh_today", False)),
        }
        group = str(entry.get("group", "") or "").strip().lower()
        if group in groups:
            groups[group].append(merged)
    return groups


def build_legacy_run_report(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """兼容旧版 latest_run_report.json。"""
    source_status = manifest.get("source_status", {}) or {}
    social_status = {
        entry.get("name", source_id): {
            "platform": entry.get("platform", ""),
            "healthy": bool(runtime.get("healthy", False)),
            "count": int(runtime.get("count", 0) or 0),
            "error": str(runtime.get("error", "") or ""),
            "last_synced": str(runtime.get("last_synced", "") or ""),
            "fresh_today": bool(runtime.get("fresh_today", False)),
            "strategy": str(entry.get("strategy", "") or ""),
            "status": str(runtime.get("status", "pending") or "pending"),
            "fetch_mode": str(runtime.get("fetch_mode", "") or ""),
        }
        for entry in manifest.get("source_catalog", {}).get("entries", []) or []
        if entry.get("group") == "media"
        for source_id, runtime in [(str(entry.get("id", "") or ""), source_status.get(str(entry.get("id", "") or ""), {}))]
    }
    return {
        "version": manifest.get("version", ""),
        "started_at": manifest.get("started_at", ""),
        "finished_at": manifest.get("finished_at", ""),
        "status": manifest.get("status", ""),
        "steps": list(manifest.get("steps", []) or []),
        "prompt_versions": dict(manifest.get("prompt_versions", {}) or {}),
        "html_file": manifest.get("artifacts", {}).get("html_file", ""),
        "report_mode": manifest.get("summary", {}).get("report_mode", ""),
        "publish_latest": bool(manifest.get("publish", {}).get("latest", False)),
        "publish_entry_index": bool(manifest.get("publish", {}).get("entry_index", False)),
        "hotlist_failed_ids": list(manifest.get("summary", {}).get("hotlist_failed_ids", []) or []),
        "rss_failed_ids": list(manifest.get("summary", {}).get("rss_failed_ids", []) or []),
        "social_source_status": social_status,
        "error": manifest.get("error", ""),
    }


def write_run_manifest(output_dir: str | Path, manifest: Dict[str, Any]) -> Dict[str, str]:
    """落盘统一运行清单，并同步生成兼容旧版的 run report。"""
    output_root = Path(output_dir)
    meta_dir = output_root / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    manifest_snapshot = meta_dir / f"run_manifest_{timestamp}.json"
    manifest_latest = meta_dir / "run_manifest.json"
    report_snapshot = meta_dir / f"run_report_{timestamp}.json"
    report_latest = meta_dir / "latest_run_report.json"

    manifest_payload = json.dumps(manifest, ensure_ascii=False, indent=2)
    manifest_snapshot.write_text(manifest_payload, encoding="utf-8")
    manifest_latest.write_text(manifest_payload, encoding="utf-8")

    legacy_report = build_legacy_run_report(manifest)
    legacy_payload = json.dumps(legacy_report, ensure_ascii=False, indent=2)
    report_snapshot.write_text(legacy_payload, encoding="utf-8")
    report_latest.write_text(legacy_payload, encoding="utf-8")

    artifacts = manifest.setdefault("artifacts", {})
    artifacts["manifest_snapshot"] = str(manifest_snapshot)
    artifacts["manifest_latest"] = str(manifest_latest)
    artifacts["run_report_snapshot"] = str(report_snapshot)
    artifacts["run_report_latest"] = str(report_latest)

    manifest_latest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "manifest_snapshot": str(manifest_snapshot),
        "manifest_latest": str(manifest_latest),
        "run_report_snapshot": str(report_snapshot),
        "run_report_latest": str(report_latest),
    }
