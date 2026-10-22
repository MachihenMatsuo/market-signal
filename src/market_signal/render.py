"""週ごとの号（公開ページとメール）を作る。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .classify import IMPORTANCE_ORDER
from .config import SITE_DIR, TEMPLATE_DIR, Config
from .models import KIND_GOV, KIND_RECALL, KIND_SUBSIDY, Item

WEEKDAYS = "月火水木金土日"


def fmt_date(dt: datetime | None, with_time: bool = False) -> str:
    if not dt:
        return ""
    s = f"{dt.year}年{dt.month}月{dt.day}日（{WEEKDAYS[dt.weekday()]}）"
    if with_time and (dt.hour or dt.minute):
        s += f" {dt.hour}:{dt.minute:02d}"
    return s


def days_left(dt: datetime | None, now: datetime) -> int | None:
    if not dt:
        return None
    # 残り日数は少ない側に丸める（切り捨て）
    return int((dt - now).total_seconds() // 86400)


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["jdate"] = fmt_date
    env.filters["jdatetime"] = lambda d: fmt_date(d, True)
    return env


def group(items: list[Item], now: datetime, deadline_soon_days: int) -> dict[str, list[Item]]:
    soon, new, recall, gov = [], [], [], []
    for it in items:
        if it.kind == KIND_SUBSIDY:
            dl = it.deadline_dt
            if dl and dl - now <= timedelta(days=deadline_soon_days):
                soon.append(it)
            else:
                new.append(it)
        elif it.kind == KIND_RECALL:
            recall.append(it)
        elif it.kind == KIND_GOV:
            gov.append(it)
    far = datetime.max.replace(tzinfo=now.tzinfo)
    soon.sort(key=lambda i: i.deadline_dt or far)
    new.sort(key=lambda i: (i.deadline_dt or far, i.title))
    key_pub = lambda i: (-IMPORTANCE_ORDER.get(i.importance, 1), -(i.published_dt or now).timestamp())
    recall.sort(key=key_pub)
    gov.sort(key=key_pub)
    return {"soon": soon, "new": new, "recall": recall, "gov": gov}


def cap(groups: dict[str, list[Item]], max_per_section: int) -> tuple[dict[str, list[Item]], dict[str, int]]:
    """1つの欄に載せすぎないよう、並び順の上から決まった件数までにする。"""
    over = {k: max(0, len(v) - max_per_section) for k, v in groups.items()}
    return {k: v[:max_per_section] for k, v in groups.items()}, over


def issue_context(items: list[Item], cfg: Config, now: datetime, edition: str,
                  max_per_section: int | None = None) -> dict[str, Any]:
    """max_per_section を渡すと、各欄をその件数までに絞る（メール用。ウェブ版は全件）。"""
    soon_days = int(cfg.s("issue", "deadline_soon_days", default=30))
    window = int(cfg.s("issue", "window_days", default=7))
    full = group(items, now, soon_days)
    g, over = cap(full, max_per_section) if max_per_section else (full, {k: 0 for k in full})
    return {
        "overflow": over,
        "cfg": cfg.settings,
        "edition": edition,
        "now": now,
        "issue_date": fmt_date(now),
        "issue_slug": now.strftime("%Y-%m-%d"),
        "period": f"{fmt_date(now - timedelta(days=window))}〜{fmt_date(now)}",
        "groups": g,
        "counts": {k: len(v) for k, v in full.items()},
        "total": len(items),
        "soon_days": soon_days,
        "days_left": lambda it: days_left(it.deadline_dt, now),
        # 出典の書き方（例：「出典：農林水産省ウェブサイト」）
        "attr": {s["id"]: s.get("attribution", s.get("publisher", "")) for s in cfg.sources},
        # 回収・注意喚起の情報源（許可が必要）が無い間は、その欄を出さない
        "show_recall": any(s.get("kind") == KIND_RECALL and s.get("enabled", True) for s in cfg.sources),
        "uses_jgrants": any(s.get("type") == "jgrants" and s.get("enabled", True) for s in cfg.sources),
    }


def render_issue_page(ctx: dict[str, Any]) -> str:
    return _env().get_template("issue.html").render(**ctx)


def render_email(ctx: dict[str, Any]) -> tuple[str, str, str]:
    env = _env()
    subject = env.from_string(
        "【{{ cfg.service.short_name }}】{{ issue_date }}号："
        "{% if counts.soon %}締切が近い補助金・公募{{ counts.soon }}件、{% endif %}"
        "補助金・公募{{ counts.soon + counts.new }}件・行政の発表{{ counts.gov }}件"
    ).render(**ctx)
    return subject, env.get_template("email.html").render(**ctx), env.get_template("email.txt").render(**ctx)


def write_site(ctx: dict[str, Any], archive: list[dict[str, Any]], out: Path = SITE_DIR) -> Path:
    env = _env()
    (out / "issues").mkdir(parents=True, exist_ok=True)
    page = out / "issues" / f"{ctx['issue_slug']}.html"
    page.write_text(render_issue_page(ctx), encoding="utf-8")
    (out / "index.html").write_text(
        env.get_template("index.html").render(**ctx, archive=archive), encoding="utf-8"
    )
    (out / "privacy.html").write_text(env.get_template("privacy.html").render(**ctx), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    write_sitemap(out, str((ctx.get("cfg") or {}).get("site", {}).get("url") or ""))
    return page


def write_sitemap(out: Path, base_url: str) -> Path | None:
    """検索エンジンに渡すページの一覧（sitemap.xml）。公開URLが未記入なら作らない。"""
    if not base_url.startswith("http"):
        return None
    base = base_url.rstrip("/") + "/"
    urls = [(base, None), (base + "privacy.html", None)]
    for p in sorted((out / "issues").glob("*.html"), reverse=True):
        urls.append((base + "issues/" + p.name, p.stem if len(p.stem) == 10 else None))
    newest = next((d for _, d in urls if d), None)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, day in urls:
        day = day or (newest if loc == base else None)  # トップは最新号の日付で更新
        lines.append(f"  <url><loc>{loc}</loc>" + (f"<lastmod>{day}</lastmod>" if day else "") + "</url>")
    lines.append("</urlset>")
    path = out / "sitemap.xml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
