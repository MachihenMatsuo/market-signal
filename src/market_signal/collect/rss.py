"""RSS / RDF / Atom の情報源。題名・リンク・日付は、フィードの値をそのまま使う。"""
from __future__ import annotations

import calendar
import html
import re
from datetime import datetime, timezone
from typing import Any

import feedparser

from ..config import JST, Config
from ..models import Item
from .http import get

TAG = re.compile(r"<[^>]+>")


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", s or ""))).strip()


def _date(entry: Any) -> str | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(key)
        if t:
            dt = datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc).astimezone(JST)
            return dt.isoformat(timespec="seconds")
    return None


def parse(raw: bytes, src: dict[str, Any]) -> list[Item]:
    feed = feedparser.parse(raw)
    if feed.bozo and not feed.entries:
        raise ValueError(f"フィードを読めません: {feed.bozo_exception}")
    items = []
    for e in feed.entries:
        title = _clean(e.get("title"))
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        items.append(
            Item(
                source_id=src["id"],
                publisher=src["publisher"],
                kind=src["kind"],
                title=title,
                url=link,
                published=_date(e),
                regions=list(src.get("regions") or []),
                body_text=_clean(e.get("summary") or e.get("description"))[:800],
            )
        )
    return items


def collect(src: dict[str, Any], cfg: Config) -> list[Item]:
    r = get(src["url"])
    return parse(r.content, src)
