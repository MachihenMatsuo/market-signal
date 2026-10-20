"""jGrants（デジタル庁の補助金電子申請システム）の公開APIから、受付中の補助金を集める。

題名・締切・対象地域・業種は、APIが返す値をそのまま使う（AIは書かない）。
"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime
from typing import Any

from ..config import JST, Config
from ..models import KIND_SUBSIDY, Item
from ..store import load_items
from .http import get

TAG = re.compile(r"<[^>]+>")


def _dt(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(JST).isoformat(timespec="seconds")
    except ValueError:
        return None


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", s or ""))).strip()


def _regions(v: Any) -> list[str]:
    if not v:
        return []
    if isinstance(v, list):
        parts = v
    else:
        parts = re.split(r"\s*[/／、,，]\s*", str(v))
    return [p.strip() for p in parts if p and p.strip()]


def to_item(row: dict[str, Any], detail: dict[str, Any] | None, src: dict[str, Any],
            search_keywords: list[str] | None = None) -> Item:
    d = {**row, **(detail or {})}
    sid = str(d.get("id"))
    url = src["page_url"].format(id=sid)  # 毎回同じURLになるよう、決まった形で作る
    # 本文の抜粋は分類のためだけに使う（配信には載せない）
    body = " ".join(filter(None, [_clean(d.get("subsidy_catch_phrase")), _clean(d.get("subsidy_rate")),
                                  _clean(d.get("use_purpose")), _clean(d.get("detail"))]))
    industries = d.get("industry")
    if isinstance(industries, list):
        industries = " / ".join(map(str, industries))
    return Item(
        source_id=src["id"],
        publisher=src["publisher"],
        kind=KIND_SUBSIDY,
        title=_clean(d.get("title") or d.get("name")),
        url=url,
        published=_dt(d.get("acceptance_start_datetime")),
        deadline=_dt(d.get("acceptance_end_datetime")),
        regions=_regions(d.get("target_area_search")),
        industries_raw=str(industries) if industries else None,
        body_text=body[:800],
        checks={"search_keywords": sorted(set(search_keywords or []))},
    )


def collect(src: dict[str, Any], cfg: Config) -> list[Item]:
    base = src["url"].rstrip("/")
    pause = float(cfg.s("collect", "pause_seconds", default=2))
    seen: dict[str, dict[str, Any]] = {}
    hits: dict[str, list[str]] = {}
    for kw in src.get("keywords", []):
        params = {"keyword": kw, "sort": "created_date", "order": "DESC", "acceptance": 1}
        res = get(base, params=params).json()
        for row in res.get("result", []) or []:
            if row.get("id"):
                seen.setdefault(str(row["id"]), row)
                hits.setdefault(str(row["id"]), []).append(kw)
        time.sleep(pause)

    # 業種・本文は詳細APIにだけある。すでに詳細を持っている補助金は取りに行かない
    known = {it.url: it for it in load_items().values() if it.source_id == src["id"]}
    items = []
    detail_limit = int(src.get("detail_limit", 60))
    fetched = 0
    for sid, row in seen.items():
        page = src["page_url"].format(id=sid)
        old = known.get(page)
        detail = None
        if old is None or not old.industries_raw:
            if fetched < detail_limit:
                try:
                    res = get(f"{base}/id/{sid}").json()
                    lst = res.get("result") or []
                    detail = lst[0] if lst else None
                except Exception:
                    detail = None
                fetched += 1
                time.sleep(pause)
        it = to_item(row, detail, src, hits.get(sid))
        if detail is None and old is not None:  # 前回取った業種・本文を引き継ぐ
            it.industries_raw, it.body_text = old.industries_raw, old.body_text
        items.append(it)
    return [i for i in items if i.title]
