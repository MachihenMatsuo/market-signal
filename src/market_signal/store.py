"""集めた情報と記録の保存（リポジトリ内の data/ にJSONで置き、GitHub Actionsがコミットする）。"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .config import DATA_DIR, now_jst
from .models import Item

ITEMS_FILE = "items.json"
ISSUES_FILE = "issues.json"
METRICS_FILE = "metrics.csv"
AI_USAGE_FILE = "ai_usage.json"
SOURCE_HEALTH_FILE = "source_health.json"


def _path(name: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / name


def _read_json(name: str, default: Any) -> Any:
    p = _path(name)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _write_json(name: str, data: Any) -> None:
    p = _path(name)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    tmp.replace(p)


# --- 集めた情報 ---
def load_items() -> dict[str, Item]:
    raw = _read_json(ITEMS_FILE, {})
    return {k: Item.from_dict(v) for k, v in raw.items()}


def save_items(items: dict[str, Item]) -> None:
    _write_json(ITEMS_FILE, {k: v.to_dict() for k, v in items.items()})


def merge_items(existing: dict[str, Item], new: Iterable[Item]) -> tuple[dict[str, Item], int]:
    """新しく見つかった件数を返す。既にある件は、締切など情報源側の更新だけ反映する。"""
    added = 0
    stamp = now_jst().isoformat(timespec="seconds")
    for it in new:
        if it.id in existing:
            old = existing[it.id]
            old.title = it.title
            old.deadline = it.deadline
            old.regions = it.regions or old.regions
            old.industries_raw = it.industries_raw or old.industries_raw
            old.body_text = it.body_text or old.body_text
            if it.checks.get("search_keywords"):
                old.checks["search_keywords"] = it.checks["search_keywords"]
            continue
        it.first_seen = stamp
        existing[it.id] = it
        added += 1
    return existing, added


# --- 発行した号の記録 ---
def load_issues() -> list[dict[str, Any]]:
    return _read_json(ISSUES_FILE, [])


def save_issues(issues: list[dict[str, Any]]) -> None:
    _write_json(ISSUES_FILE, issues)


# --- AIの利用額 ---
def load_ai_usage() -> dict[str, Any]:
    return _read_json(AI_USAGE_FILE, {})


def save_ai_usage(data: dict[str, Any]) -> None:
    _write_json(AI_USAGE_FILE, data)


# --- 情報源ごとの取得状況 ---
def load_source_health() -> dict[str, Any]:
    return _read_json(SOURCE_HEALTH_FILE, {})


def save_source_health(data: dict[str, Any]) -> None:
    _write_json(SOURCE_HEALTH_FILE, data)


# --- 数字の記録（続けるか止めるかの判断に使う） ---
METRIC_FIELDS = [
    "date",
    "event",
    "collected_new",
    "issue_items",
    "excluded_broken_link",
    "excluded_out_of_period",
    "excluded_deadline_passed",
    "ai_notes_dropped",
    "ai_input_tokens",
    "ai_output_tokens",
    "ai_cost_jpy_month_to_date",
    "subscribers",
    "sent",
    "note",
]


def append_metric(row: dict[str, Any]) -> None:
    p = _path(METRICS_FILE)
    new_file = not p.exists()
    with open(p, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=METRIC_FIELDS)
        if new_file:
            w.writeheader()
        row = {k: row.get(k, "") for k in METRIC_FIELDS}
        row["date"] = row["date"] or now_jst().isoformat(timespec="seconds")
        w.writerow(row)
