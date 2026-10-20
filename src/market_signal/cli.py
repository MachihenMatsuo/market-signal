"""実行の入口。

  python -m market_signal collect      毎日：情報源から集めて保存
  python -m market_signal weekly       毎週：集める→選ぶ→照合→AIの見立て→ページとメールを作る→配信
  python -m market_signal weekly --dry-run   配信だけしない（作ったメールは out/ に保存）
  python -m market_signal audit        月1回：点検用に3件を選ぶ
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import timedelta

from . import ai, anomaly, render, send, store
from .classify import classify_all
from .collect import collect_all
from .config import OUT_DIR, Config, now_jst
from .verify import select_for_issue, url_ok


def cmd_collect(cfg: Config) -> dict:
    now = now_jst()
    new, report = collect_all(cfg)
    classify_all(new, cfg.rules, now, cfg.sources)
    items, added = store.merge_items(store.load_items(), new)
    # 古くなったものを整理（締切済みで90日以上たったもの、公表から180日以上たったもの）
    cutoff_pub = now - timedelta(days=180)
    for k in [k for k, v in items.items() if (v.published_dt and v.published_dt < cutoff_pub)
              or (v.deadline_dt and v.deadline_dt < now - timedelta(days=90))]:
        items.pop(k)
    store.save_items(items)
    failing = anomaly.check_sources(store.load_source_health(), int(cfg.s("thresholds", "source_fail_days", default=3)))
    store.append_metric({"event": "collect", "collected_new": added,
                         "note": ("取得失敗が続く情報源: " + ",".join(failing)) if failing else ""})
    print(json.dumps({"新規": added, "情報源ごと": report, "失敗が続く情報源": failing}, ensure_ascii=False, indent=1))
    return {"added": added, "failing": failing}


def cmd_weekly(cfg: Config, dry_run: bool, skip_collect: bool, check_url=url_ok) -> int:
    now = now_jst()
    if not skip_collect:
        cmd_collect(cfg)
    items = store.load_items()
    # 判定基準が変わっても反映されるよう、毎回振り分け直す（AIの見立ては残す）
    for it in items.values():
        keep_note, keep_used = it.ai_note, it.ai_used
        classify_all([it], cfg.rules, now, cfg.sources)
        it.ai_note, it.ai_used = keep_note, keep_used

    issues = store.load_issues()
    published_before = {i for iss in issues for i in iss.get("ids", [])}
    chosen, stats = select_for_issue(
        items, now,
        window_days=int(cfg.s("issue", "window_days", default=7)),
        deadline_soon_days=int(cfg.s("issue", "deadline_soon_days", default=30)),
        published_before=published_before,
        check_url=check_url,
    )
    ai_stats = ai.annotate(chosen, cfg)
    chosen = [it for it in chosen if it.relevant]
    store.save_items(items)

    edition = "free"
    ctx = render.issue_context(chosen, cfg, now, edition)  # ウェブ版は全件
    mail_ctx = render.issue_context(chosen, cfg, now, edition,
                                    max_per_section=int(cfg.s("issue", "max_per_section", default=40)))
    subject, html, text = render.render_email(mail_ctx)
    # メールの見本は、止まった場合も確認できるよう out/ に必ず残す（リポジトリには入れない）
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "email.html").write_text(html, encoding="utf-8")
    (OUT_DIR / "email.txt").write_text(f"件名：{subject}\n\n{text}", encoding="utf-8")

    row = {"event": "weekly", "issue_items": len(chosen), **{k: stats[k] for k in stats if k.startswith("excluded")},
           "ai_notes_dropped": ai_stats["ai_notes_dropped"], "ai_input_tokens": ai_stats["ai_input_tokens"],
           "ai_output_tokens": ai_stats["ai_output_tokens"],
           "ai_cost_jpy_month_to_date": math.ceil(ai.month_cost_jpy(cfg)),  # 費用は切り上げ
           "note": ai_stats.get("ai_skipped", "")}

    previous_ids = issues[-1]["ids"] if issues else None
    try:
        anomaly.check_issue(chosen, stats, previous_ids, cfg.s("thresholds", default={}) or {},
                            cfg.missing_sender_info())
    except anomaly.StopSending as e:
        row["note"] = f"配信停止: {e}"
        store.append_metric(row)
        (OUT_DIR / "stop_reason.txt").write_text(str(e), encoding="utf-8")
        print(f"配信を止めました：{e}", file=sys.stderr)
        return 2

    # 照合と異常の確認を通ったときだけ、公開ページを更新する
    archive = [{"slug": i["slug"], "label": i["label"], "total": i["total"]} for i in reversed(issues)]
    page = render.write_site(ctx, archive)

    if dry_run:
        result = send.check_connection(cfg)  # 試し実行では送らず、配信サービスにつながるかだけ確かめる
    else:
        try:
            result = send.send_issue(cfg, subject, html, text, campaign_name=f"{ctx['issue_slug']} 週刊号")
        except Exception as e:
            # 公開ページはこの後のGitHubの手順で出す。メールが送れなかった理由だけ知らせに残す
            row["note"] = f"送信失敗: {str(e)[:200]}"
            store.append_metric(row)
            (OUT_DIR / "stop_reason.txt").write_text(
                f"公開ページは更新しましたが、メールを送れませんでした。{e}", encoding="utf-8")
            raise
    row.update({"sent": result.get("sent", 0), "subscribers": result.get("subscribers", "")})
    if dry_run:
        row["event"] = "weekly_dry_run"
    store.append_metric(row)
    if not dry_run:  # 試し実行は号として記録しない（翌日の本番で項目が抜けないように）
        issues.append({"slug": ctx["issue_slug"], "label": ctx["issue_date"], "total": len(chosen),
                       "ids": [it.id for it in chosen], "sent": True,
                       "created": now.isoformat(timespec="seconds")})
        store.save_issues(issues)
    print(json.dumps({"件名": subject, "掲載": len(chosen), "照合で除外": stats, "AI": ai_stats,
                      "ページ": str(page), "配信": result, "試し実行": dry_run}, ensure_ascii=False, indent=1))
    return 0


def cmd_audit(cfg: Config) -> int:
    """月1回の点検：先月の号から3件を選び、原文と見比べる一覧を作る。"""
    now = now_jst()
    items = store.load_items()
    since = now - timedelta(days=35)
    ids = [i for iss in store.load_issues() if iss.get("created", "") >= since.isoformat() for i in iss.get("ids", [])]
    pick = random.sample([i for i in set(ids) if i in items], k=min(3, len(set(ids) & set(items))))
    lines = ["月1回の点検（15分）です。次の3件を原文と見比べ、題名・日付・締切・地域に食い違いがないか見てください。",
             "食い違いがあれば、このページにコメントで書いてください。判定ルールを直します。", ""]
    for i in pick:
        it = items[i]
        lines += [f"- [{it.title}]({it.url})", f"  - 発表元：{it.publisher}／公表：{it.published or 'なし'}／締切：{it.deadline or 'なし'}／地域：{'・'.join(it.regions)}"]
    if not pick:
        lines.append("先月の号がまだありません。")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "audit.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="market_signal")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("collect")
    w = sub.add_parser("weekly")
    w.add_argument("--dry-run", action="store_true")
    w.add_argument("--skip-collect", action="store_true")
    sub.add_parser("audit")
    a = p.parse_args(argv)
    cfg = Config.load()
    if a.cmd == "collect":
        cmd_collect(cfg)
        return 0
    if a.cmd == "weekly":
        return cmd_weekly(cfg, a.dry_run, a.skip_collect)
    if a.cmd == "audit":
        return cmd_audit(cfg)
    return 1
