"""判定基準（config/rules.yaml）による振り分け。AIを使わなくても動く。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .models import KIND_GOV, KIND_RECALL, KIND_SUBSIDY, Item

PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]
COMMON = "共通"
IMPORTANCE_ORDER = {"高": 3, "中": 2, "低": 1}
# 業種欄にこれ以上の分類が並んでいたら「業種を問わない補助金」とみなす
ALL_INDUSTRIES_MIN = 10


def _hit(text: str, words: list[str] | None) -> bool:
    return any(w and w in text for w in (words or []))


def _types(text: str, rules: dict[str, Any]) -> list[str]:
    return [name for name, words in (rules.get("business_types") or {}).items() if _hit(text, words)]


def detect_regions(item: Item) -> list[str]:
    if item.regions:
        return item.regions
    found = [p for p in PREFECTURES if p in item.title]
    return found or ["全国"]


def classify(item: Item, rules: dict[str, Any], now: datetime, src: dict[str, Any] | None = None) -> Item:
    src = src or {}
    text = " ".join(filter(None, [item.title, item.body_text or ""]))
    industries = item.industries_raw or ""
    n_industries = len([p for p in re.split(r"\s*/\s*", industries) if p.strip()]) if industries else 0

    # 業態：題名・本文の言葉 ＋ 業種欄（業種を問わない補助金は「共通」）
    types = _types(text, rules)
    if industries and n_industries < ALL_INDUSTRIES_MIN:
        types += [t for t in _types(industries, rules) if t not in types]
    if not types and (n_industries >= ALL_INDUSTRIES_MIN or _hit(text, rules.get("common_keywords"))):
        types = [COMMON]

    # 載せるかどうか
    excluded = _hit(item.title, rules.get("exclude_keywords"))
    # 業種が絞られている補助金で、食に関わる業種（製造業・卸売業、小売業・飲食サービス業など）が
    # 1つも入っていないもの（例：建設業だけ、運輸業だけ）は、飲食・食品の事業者は使えないので載せない
    food_industries = rules.get("food_related_industries") or []
    if industries and n_industries < ALL_INDUSTRIES_MIN and food_industries and not _hit(industries, food_industries):
        excluded = True
    if item.kind == KIND_RECALL:
        relevant = not excluded
    elif item.kind == KIND_SUBSIDY:
        # 食の言葉（例：「飲食」）の検索で見つかった補助金は、業態が分からなくても載せる
        searched = set(item.checks.get("search_keywords") or [])
        food_search = searched & set(src.get("relevant_search_keywords") or [])
        if food_search and not types:
            types = [COMMON]
        relevant = bool(types) and not excluded
    else:  # 行政の発表
        hit = _hit(text, rules.get("food_keywords"))
        if src.get("match") == "all":
            hit = True
        elif src.get("match") == "food_or_common":
            hit = hit or bool(types)
        relevant = hit and not excluded
        if relevant and not types:
            types = [COMMON]

    # 重要度
    imp = "低"
    hi = (rules.get("importance") or {}).get("high") or {}
    md = (rules.get("importance") or {}).get("medium") or {}
    if item.kind in (md.get("kinds") or []) or _hit(item.title, md.get("title_keywords")):
        imp = "中"
    if item.kind in (hi.get("kinds") or []) or _hit(item.title, hi.get("title_keywords")):
        imp = "高"
    days = hi.get("subsidy_deadline_within_days")
    if item.kind == KIND_SUBSIDY and days and item.deadline_dt:
        left = (item.deadline_dt - now).total_seconds() / 86400
        if 0 <= left <= days:
            imp = "高"

    item.business_types = types
    item.relevant = relevant
    item.importance = imp
    item.regions = detect_regions(item)
    return item


def classify_all(
    items: list[Item], rules: dict[str, Any], now: datetime, sources: list[dict[str, Any]] | None = None
) -> list[Item]:
    by_id = {s["id"]: s for s in (sources or [])}
    return [classify(it, rules, now, by_id.get(it.source_id)) for it in items]


__all__ = ["classify", "classify_all", "IMPORTANCE_ORDER", "PREFECTURES", "COMMON", "KIND_GOV"]
