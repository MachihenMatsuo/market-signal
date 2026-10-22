"""検索から来る人のための、いつも最新のページ（毎日作り直す）。

- トップ（締切が近いもの・新しく始まったもの・毎週のまとめへの入口）
- 受付中の補助金・公募の一覧（全件、締切が近い順）
- 業態別（飲食店／食品製造・加工／食品卸・小売）
- 都道府県別（その都道府県が対象のものが一定数あるところだけ）と、都道府県の一覧

週ごとの号（issues/）とは別。号は週が変われば古くなるが、こちらは毎日中身が入れ替わる。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .classify import COMMON, PREFECTURES
from .config import SITE_DIR, Config
from .models import KIND_SUBSIDY, Item
from .render import TYPE_PAGES, _env, type_pages, days_left, fmt_date, write_sitemap

PREF_SLUGS = [
    "hokkaido", "aomori", "iwate", "miyagi", "akita", "yamagata", "fukushima",
    "ibaraki", "tochigi", "gunma", "saitama", "chiba", "tokyo", "kanagawa",
    "niigata", "toyama", "ishikawa", "fukui", "yamanashi", "nagano", "gifu",
    "shizuoka", "aichi", "mie", "shiga", "kyoto", "osaka", "hyogo",
    "nara", "wakayama", "tottori", "shimane", "okayama", "hiroshima", "yamaguchi",
    "tokushima", "kagawa", "ehime", "kochi", "fukuoka", "saga", "nagasaki",
    "kumamoto", "oita", "miyazaki", "kagoshima", "okinawa",
]
PREF_SLUG = dict(zip(PREFECTURES, PREF_SLUGS))
AREAS = [
    ("北海道・東北", PREFECTURES[0:7]), ("関東", PREFECTURES[7:14]), ("中部", PREFECTURES[14:23]),
    ("近畿", PREFECTURES[23:30]), ("中国", PREFECTURES[30:35]), ("四国", PREFECTURES[35:39]),
    ("九州・沖縄", PREFECTURES[39:47]),
]

# 都道府県別のページは、その都道府県だけ（または数県だけ）が対象のものがこの件数以上あるときに作る。
# 少ないページは中身の薄いページになり、検索の評価を下げるため作らない
MIN_LOCAL_ITEMS = 3
# これ以上の都道府県が並んでいる補助金は「広い地域が対象」とみなし、全国と同じ扱いにする
WIDE_REGION_MIN = 10
# トップの「受付が始まった」に載せる日数
NEW_DAYS = 14
# 情報源にこの日数載っていないものは、受付を終えた可能性があるので外す
STALE_DAYS = 3


def _is_wide(it: Item) -> bool:
    return "全国" in it.regions or len(it.regions) >= WIDE_REGION_MIN


def open_subsidies(items: dict[str, Item] | list[Item], now: datetime) -> list[Item]:
    """受付中（締切が過ぎておらず、情報源にまだ載っている）の補助金・公募を、締切が近い順に。"""
    vals = items.values() if isinstance(items, dict) else items
    out = []
    for it in vals:
        if it.kind != KIND_SUBSIDY or not it.relevant:
            continue
        dl = it.deadline_dt
        if not dl or dl < now:
            continue
        seen = it.checks.get("last_seen")
        if seen and datetime.fromisoformat(seen) < now - timedelta(days=STALE_DAYS):
            continue
        out.append(it)
    far = datetime.max.replace(tzinfo=now.tzinfo)
    out.sort(key=lambda i: (i.deadline_dt or far, i.title))
    return out


def local_items(items: list[Item], pref: str) -> list[Item]:
    return [it for it in items if pref in it.regions and not _is_wide(it)]


def wide_items(items: list[Item]) -> list[Item]:
    return [it for it in items if _is_wide(it)]


def _base(cfg: Config) -> str:
    url = str(cfg.s("site", "url", default="") or "")
    return url.rstrip("/") + "/" if url.startswith("http") else ""


def _common_ctx(cfg: Config, now: datetime) -> dict[str, Any]:
    return {
        "cfg": cfg.settings,
        "now": now,
        "edition": "free",
        "today": fmt_date(now),
        "updated_ym": f"{now.year}年{now.month}月",
        "days_left": lambda it: days_left(it.deadline_dt, now),
        "attr": {s["id"]: s.get("attribution", s.get("publisher", "")) for s in cfg.sources},
        "uses_jgrants": any(s.get("type") == "jgrants" and s.get("enabled", True) for s in cfg.sources),
        "type_pages": type_pages(),
        "base": _base(cfg),
    }


def _write(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def build(items: dict[str, Item], cfg: Config, now: datetime, archive: list[dict[str, Any]],
          out: Path = SITE_DIR) -> dict[str, Any]:
    """トップ・一覧・業態別・都道府県別・個人情報・サイトマップを作り直す。作ったページの数を返す。"""
    env = _env()
    base = _common_ctx(cfg, now)
    soon_days = int(cfg.s("issue", "deadline_soon_days", default=30))
    opened = open_subsidies(items, now)
    soon = [it for it in opened if it.deadline_dt - now <= timedelta(days=soon_days)]
    later = [it for it in opened if it.deadline_dt - now > timedelta(days=soon_days)]
    # 「受付が始まった」は、発表元の受付開始日で判断する（こちらが見つけた日ではなく）
    started_since = now - timedelta(days=NEW_DAYS)
    new = [it for it in opened if it.published_dt and started_since <= it.published_dt <= now]
    new.sort(key=lambda i: i.published_dt, reverse=True)
    made = {"top": 1, "list": 1, "gyotai": 0, "chiiki": 0}

    # 業態別
    type_counts = {}
    for name, slug, label, desc in TYPE_PAGES:
        own = [it for it in opened if name in it.business_types]
        common = [it for it in opened if COMMON in it.business_types and name not in it.business_types]
        type_counts[slug] = len(own) + len(common)
        _write(out / "gyotai" / f"{slug}.html", env.get_template("topic.html").render(
            **base, root="../", path=f"gyotai/{slug}.html",
            title=f"{label}が使える補助金・公募の一覧（受付中・{base['updated_ym']}更新）",
            h1=f"{label}が使える補助金・公募",
            crumbs=[("業態から探す", None), (label, None)],
            lead=(f"{base['today']}時点で受付中の補助金・公募のうち、{label}（{desc}）が使えるもの"
                  f"{len(own) + len(common)}件を、締切が近い順に並べています。"),
            sections=[(f"{label}向けの補助金・公募", own),
                      ("業種を問わず使える補助金・公募（中小企業・小規模事業者向けなど）", common)],
            description=(f"{label}が使える受付中の補助金・公募{len(own) + len(common)}件を締切が近い順に。"
                         "対象地域・締切・発表元の原文リンク付きで、毎朝更新。"),
        ))
        made["gyotai"] += 1

    # 都道府県別（基準を満たすところだけ）。基準を下回ったページは消す
    wide = wide_items(opened)
    pref_rows, keep = [], set()
    for pref in PREFECTURES:
        loc = local_items(opened, pref)
        slug = PREF_SLUG[pref]
        has_page = len(loc) >= MIN_LOCAL_ITEMS
        pref_rows.append({"pref": pref, "slug": slug, "local": len(loc), "page": has_page})
        if not has_page:
            continue
        keep.add(f"{slug}.html")
        _write(out / "chiiki" / f"{slug}.html", env.get_template("topic.html").render(
            **base, root="../", path=f"chiiki/{slug}.html",
            title=f"{pref}の飲食店・食品事業者が使える補助金・公募（受付中・{base['updated_ym']}更新）",
            h1=f"{pref}の飲食店・食品事業者が使える補助金・公募",
            crumbs=[("都道府県から探す", "index.html"), (pref, None)],
            lead=(f"{base['today']}時点で受付中の補助金・公募のうち、{pref}が対象のもの{len(loc)}件と、"
                  f"全国が対象のもの{len(wide)}件を、締切が近い順に並べています。"
                  "市区町村が独自に出している補助金は載っていないことがあります。"),
            sections=[(f"{pref}が対象の補助金・公募", loc), ("全国が対象の補助金・公募", wide)],
            description=(f"{pref}の飲食店・食品メーカー・食品卸が使える受付中の補助金・公募を締切が近い順に。"
                         f"{pref}が対象のもの{len(loc)}件、全国対象{len(wide)}件。毎朝更新。"),
        ))
        made["chiiki"] += 1
    for old in (out / "chiiki").glob("*.html") if (out / "chiiki").exists() else []:
        if old.name != "index.html" and old.name not in keep:
            old.unlink()
    areas = [(area, [r for r in pref_rows if r["pref"] in prefs]) for area, prefs in AREAS]
    _write(out / "chiiki" / "index.html", env.get_template("chiiki.html").render(
        **base, root="../", path="chiiki/", areas=areas, wide_count=len(wide), min_local=MIN_LOCAL_ITEMS,
        title=f"都道府県から探す 飲食店・食品事業者の補助金・公募（{base['updated_ym']}更新）",
    ))

    # 受付中の一覧（全件）
    _write(out / "list" / "index.html", env.get_template("topic.html").render(
        **base, root="../", path="list/",
        title=f"飲食店・食品事業者が使える補助金・公募の一覧（受付中{len(opened)}件・{base['updated_ym']}更新）",
        h1="飲食店・食品事業者が使える補助金・公募の一覧",
        crumbs=[("受付中の一覧", None)],
        lead=(f"{base['today']}時点で受付中の補助金・公募のうち、飲食・食品の事業者が使えるもの"
              f"{len(opened)}件を、締切が近い順に並べています。"),
        sections=[(f"締切が{soon_days}日以内", soon), (f"締切まで{soon_days}日より先", later)],
        description=(f"飲食店・食品メーカー・食品卸が使える受付中の補助金・公募{len(opened)}件を締切が近い順に。"
                     "業態別・都道府県別にも探せます。発表元の原文リンク付きで毎朝更新。"),
    ))

    # トップ
    _write(out / "index.html", env.get_template("index.html").render(
        **base, root="", path="", soon=soon[:10], soon_total=len(soon), new=new[:10], new_total=len(new),
        open_total=len(opened), soon_days=soon_days, new_days=NEW_DAYS, archive=archive, type_counts=type_counts,
        chiiki_pages=[r for r in pref_rows if r["page"]],
    ))
    _write(out / "privacy.html", env.get_template("privacy.html").render(**base, root="", path="privacy.html"))
    (out / ".nojekyll").write_text("", encoding="utf-8")
    write_sitemap(out, base["base"], today=now.strftime("%Y-%m-%d"))
    made.update({"open": len(opened), "soon": len(soon), "new": len(new)})
    return made
