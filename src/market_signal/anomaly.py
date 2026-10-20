"""異常を見つけたら配信を止める。

止まったときは、GitHub Actionsの実行が「失敗」になり、GitHubから松尾さんにメールが届く。
"""
from __future__ import annotations

from typing import Any

from .models import Item


class StopSending(Exception):
    """配信を止める理由。"""


def check_issue(
    items: list[Item],
    stats: dict[str, Any],
    previous_ids: list[str] | None,
    thresholds: dict[str, Any],
    missing_sender_info: list[str],
) -> None:
    reasons = []
    min_items = int(thresholds.get("min_items", 1))
    if len(items) < min_items:
        reasons.append(f"載せる項目が{len(items)}件（最低{min_items}件）")

    checked = stats.get("checked_links", 0)
    broken = stats.get("excluded_broken_link", 0)
    max_ratio = float(thresholds.get("max_broken_link_ratio", 0.3))
    if checked and broken / checked > max_ratio:
        reasons.append(f"リンク切れが多い（{broken}/{checked}件）")

    if previous_ids is not None and items and sorted(i.id for i in items) == sorted(previous_ids):
        reasons.append("前回の号と同じ内容")

    if missing_sender_info:
        reasons.append("送信者の表示が未記入: " + "、".join(missing_sender_info))

    if reasons:
        raise StopSending(" / ".join(reasons))


def check_sources(health: dict[str, Any], max_fail_days: int) -> list[str]:
    """何日も続けて取得に失敗している情報源（サイトの仕様変更の可能性）。"""
    return [sid for sid, h in health.items() if int(h.get("consecutive_failures", 0)) >= max_fail_days]
