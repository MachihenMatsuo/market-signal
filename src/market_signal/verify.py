"""機械による照合（人の確認の代わり）と、その週に載せる項目の選定。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

import requests

from .models import KIND_GOV, KIND_RECALL, KIND_SUBSIDY, Item

USER_AGENT = "MarketSignalJapanBot/1.0 (+weekly digest; contact in site)"


def url_ok(url: str, timeout: int = 20) -> tuple[bool, int]:
    """出典URLが開けるか。HEADを断るサイトがあるのでGETで確かめる。"""
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, stream=True, allow_redirects=True)
        code = r.status_code
        r.close()
        return (200 <= code < 400), code
    except requests.RequestException:
        return False, 0


def select_for_issue(
    items: dict[str, Item],
    now: datetime,
    window_days: int,
    deadline_soon_days: int,
    published_before: set[str] | None = None,
    check_url: Callable[[str], tuple[bool, int]] = url_ok,
    new_subsidy_max_age_days: int = 60,
) -> tuple[list[Item], dict[str, Any]]:
    """その週の号に載せる項目を選び、機械照合で落ちた件数を返す。"""
    start = now - timedelta(days=window_days)
    published_before = published_before or set()
    stats = {"excluded_broken_link": 0, "excluded_out_of_period": 0, "excluded_deadline_passed": 0, "checked_links": 0}
    chosen: list[Item] = []

    for it in items.values():
        if not it.relevant:
            continue
        pub = it.published_dt
        seen = datetime.fromisoformat(it.first_seen) if it.first_seen else None
        dl = it.deadline_dt

        if it.kind == KIND_SUBSIDY:
            if dl and dl < now:
                stats["excluded_deadline_passed"] += 1
                continue
            if dl and pub and dl < pub:  # 締切が公表日より前＝データの誤りの可能性
                stats["excluded_out_of_period"] += 1
                continue
            # 「新しく見つかった」は、受付開始から60日以内のものだけ（前から受付中のものは締切が近づいたら載せる）
            recent_start = pub is None or pub >= now - timedelta(days=new_subsidy_max_age_days)
            is_new = bool(seen and seen >= start) and recent_start and it.id not in published_before
            soon = bool(dl and (dl - now) <= timedelta(days=deadline_soon_days))
            if not (is_new or soon):
                continue
            it.checks["new_this_week"] = is_new
            it.checks["deadline_soon"] = soon
        elif it.kind in (KIND_GOV, KIND_RECALL):
            ref = pub or seen
            if not ref or not (start <= ref <= now + timedelta(hours=1)):
                stats["excluded_out_of_period"] += 1
                continue
            if it.id in published_before:
                continue
        else:
            continue
        chosen.append(it)

    # 出典URLが開けるものだけ残す
    ok_items = []
    for it in chosen:
        ok, code = check_url(it.url)
        stats["checked_links"] += 1
        it.checks["url_status"] = code
        if ok:
            ok_items.append(it)
        else:
            stats["excluded_broken_link"] += 1
    return ok_items, stats
