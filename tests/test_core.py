"""判定・照合・停止のしくみのテスト（ネットにはつながない）。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from market_signal import ai, anomaly
from market_signal.classify import classify, classify_all
from market_signal.config import JST, Config
from market_signal.models import KIND_GOV, KIND_RECALL, KIND_SUBSIDY, Item
from market_signal.verify import select_for_issue

NOW = datetime(2026, 10, 26, 7, 0, tzinfo=JST)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config.load()


def mk(kind, title, **kw) -> Item:
    return Item(source_id="t", publisher="テスト省", kind=kind, title=title,
                url=kw.pop("url", f"https://example.go.jp/{abs(hash(title))}"), **kw)


def test_gov_food_relevant(cfg):
    it = classify(mk(KIND_GOV, "食品表示基準の一部改正について"), cfg.rules, NOW)
    assert it.relevant and it.importance == "高" and it.business_types


def test_gov_excluded(cfg):
    it = classify(mk(KIND_GOV, "森林・林業に関する食品の話題"), cfg.rules, NOW)
    assert not it.relevant


def test_gov_unrelated(cfg):
    it = classify(mk(KIND_GOV, "漁港の整備計画を公表します"), cfg.rules, NOW)
    assert not it.relevant


def test_subsidy_types_and_deadline(cfg):
    it = mk(KIND_SUBSIDY, "飲食店の省力化設備導入支援", deadline=(NOW + timedelta(days=10)).isoformat(),
            industries_raw="宿泊業、飲食サービス業")
    classify(it, cfg.rules, NOW)
    assert it.relevant and "飲食店" in it.business_types and it.importance == "高"


def test_subsidy_unrelated_dropped(cfg):
    it = classify(mk(KIND_SUBSIDY, "宇宙機器の研究開発", industries_raw="学術研究"), cfg.rules, NOW)
    assert not it.relevant


def test_region_from_title(cfg):
    it = classify(mk(KIND_GOV, "大阪府の食品衛生講習会"), cfg.rules, NOW)
    assert it.regions == ["大阪府"]


def test_recall_always_high(cfg):
    it = classify(mk(KIND_RECALL, "菓子の自主回収について"), cfg.rules, NOW)
    assert it.relevant and it.importance == "高"


def test_note_digit_check():
    it = mk(KIND_SUBSIDY, "補助率2分の1の支援", body_text="上限500万円")
    assert ai.note_is_safe("設備更新を考えている店は対象か確認を", it)
    assert ai.note_is_safe("上限500万円の範囲で使える可能性", it)          # 原文にある数字はよい
    assert not ai.note_is_safe("上限300万円なので早めに申請を", it)        # 原文にない数字は捨てる
    assert not ai.note_is_safe("詳しくは https://example.com を参照", it)  # URLは捨てる
    assert not ai.note_is_safe("あ" * 61, it)                              # 長すぎる


def _stored(*items: Item) -> dict[str, Item]:
    for it in items:
        it.relevant = True
        it.first_seen = (NOW - timedelta(days=1)).isoformat()
    return {it.id: it for it in items}


def test_select_rules():
    ok = lambda u: (True, 200)
    past = mk(KIND_SUBSIDY, "締切済み", deadline=(NOW - timedelta(days=1)).isoformat())
    new = mk(KIND_SUBSIDY, "新しい公募", deadline=(NOW + timedelta(days=60)).isoformat())
    soon_old = mk(KIND_SUBSIDY, "前からある公募", deadline=(NOW + timedelta(days=5)).isoformat())
    old_gov = mk(KIND_GOV, "古い発表", published=(NOW - timedelta(days=20)).isoformat())
    gov = mk(KIND_GOV, "今週の発表", published=(NOW - timedelta(days=2)).isoformat())
    items = _stored(past, new, soon_old, old_gov, gov)
    soon_old.first_seen = (NOW - timedelta(days=40)).isoformat()
    chosen, stats = select_for_issue(items, NOW, 7, 30, check_url=ok)
    titles = {c.title for c in chosen}
    assert titles == {"新しい公募", "前からある公募", "今週の発表"}
    assert stats["excluded_deadline_passed"] == 1 and stats["excluded_out_of_period"] == 1


def test_broken_links_removed_and_stop():
    a = mk(KIND_GOV, "発表A", published=(NOW - timedelta(days=1)).isoformat())
    b = mk(KIND_GOV, "発表B", published=(NOW - timedelta(days=1)).isoformat())
    items = _stored(a, b)
    chosen, stats = select_for_issue(items, NOW, 7, 30, check_url=lambda u: (u == a.url, 200 if u == a.url else 404))
    assert [c.title for c in chosen] == ["発表A"] and stats["excluded_broken_link"] == 1
    with pytest.raises(anomaly.StopSending):  # 2件中1件がリンク切れ＝50%なので止まる
        anomaly.check_issue(chosen, stats, None, {"max_broken_link_ratio": 0.3}, [])


def test_stop_when_empty_or_same_or_missing_sender():
    it = mk(KIND_GOV, "x")
    with pytest.raises(anomaly.StopSending):
        anomaly.check_issue([], {}, None, {}, [])
    with pytest.raises(anomaly.StopSending):
        anomaly.check_issue([it], {}, [it.id], {}, [])
    with pytest.raises(anomaly.StopSending):
        anomaly.check_issue([it], {}, None, {}, ["送信者の住所"])
    anomaly.check_issue([it], {}, None, {}, [])  # 問題なければ止まらない


def test_placeholders_block_sending(cfg):
    cfg.settings["operator"]["address"] = "【要記入】住所"
    cfg.settings["site"]["url"] = "【要記入】公開ページのURL"
    missing = cfg.missing_sender_info()
    assert "送信者の住所" in missing and "公開ページのURL" in missing


def test_old_open_subsidy_not_new_until_deadline_near():
    ok = lambda u: (True, 200)
    old_open = mk(KIND_SUBSIDY, "春から受付中", published=(NOW - timedelta(days=200)).isoformat(),
                  deadline=(NOW + timedelta(days=90)).isoformat())
    old_soon = mk(KIND_SUBSIDY, "春から受付中で締切間近", published=(NOW - timedelta(days=200)).isoformat(),
                  deadline=(NOW + timedelta(days=10)).isoformat())
    fresh = mk(KIND_SUBSIDY, "今月受付開始", published=(NOW - timedelta(days=5)).isoformat(),
               deadline=(NOW + timedelta(days=90)).isoformat())
    chosen, _ = select_for_issue(_stored(old_open, old_soon, fresh), NOW, 7, 30, check_url=ok)
    assert {c.title for c in chosen} == {"春から受付中で締切間近", "今月受付開始"}


def test_all_industry_subsidy_is_common(cfg):
    inds = " / ".join(f"業種{i}" for i in range(19)) + " / 宿泊業、飲食サービス業"
    it = classify(mk(KIND_SUBSIDY, "太陽光設備の導入補助", industries_raw=inds), cfg.rules, NOW)
    assert it.business_types == ["共通"] and it.relevant


def test_food_search_hit_makes_relevant(cfg):
    it = mk(KIND_SUBSIDY, "消費喚起イベントの補助")
    it.checks["search_keywords"] = ["飲食"]
    classify(it, cfg.rules, NOW, {"relevant_search_keywords": ["飲食", "食品"]})
    assert it.relevant


def test_award_excluded(cfg):
    it = classify(mk(KIND_GOV, "食料システムの女性ヒーローに選出"), cfg.rules, NOW)
    assert not it.relevant


def test_sitemap_lists_pages(tmp_path):
    from market_signal.render import write_sitemap
    (tmp_path / "issues").mkdir()
    for d in ("2026-10-20", "2026-10-26"):
        (tmp_path / "issues" / f"{d}.html").write_text("x", encoding="utf-8")
    p = write_sitemap(tmp_path, "https://example.github.io/market-signal")
    s = p.read_text(encoding="utf-8")
    assert "<loc>https://example.github.io/market-signal/</loc><lastmod>2026-10-26</lastmod>" in s
    assert "issues/2026-10-20.html</loc><lastmod>2026-10-20</lastmod>" in s
    assert write_sitemap(tmp_path, "【要記入】") is None


# --- 検索から来る人のためのページ（毎日作り直す） ---
def _sub(id_, title, deadline, regions, types, last_seen=None, published=None):
    it = Item(source_id="jgrants", publisher="jGrants（デジタル庁）", kind=KIND_SUBSIDY, title=title,
              url=f"https://www.jgrants-portal.go.jp/subsidy/{id_}", published=published, deadline=deadline)
    it.regions, it.business_types, it.relevant = regions, types, True
    if last_seen:
        it.checks["last_seen"] = last_seen
    return it


def test_open_subsidies_excludes_closed_and_stale():
    from market_signal import pages
    now = datetime(2026, 10, 22, 7, 0, tzinfo=JST)
    a = _sub("a", "受付中", "2026-11-01T17:00:00+09:00", ["全国"], ["共通"], last_seen="2026-10-22T06:20:00+09:00")
    b = _sub("b", "締切済み", "2026-10-20T17:00:00+09:00", ["全国"], ["共通"])
    c = _sub("c", "情報源から消えた", "2026-11-05T17:00:00+09:00", ["全国"], ["共通"], last_seen="2026-10-15T06:20:00+09:00")
    assert [i.title for i in pages.open_subsidies([a, b, c], now)] == ["受付中"]


def test_local_and_wide_regions():
    from market_signal import pages
    tokyo = _sub("t", "東京だけ", "2026-11-01T17:00:00+09:00", ["東京都"], ["共通"])
    many = _sub("m", "多くの県", "2026-11-01T17:00:00+09:00", list(pages.PREF_SLUG)[:12], ["共通"])
    zen = _sub("z", "全国", "2026-11-01T17:00:00+09:00", ["全国"], ["共通"])
    assert pages.local_items([tokyo, many, zen], "東京都") == [tokyo]
    assert pages.wide_items([tokyo, many, zen]) == [many, zen]


def test_build_writes_pages_and_drops_thin_prefecture_pages(tmp_path):
    from market_signal import pages
    cfg = Config.load()
    now = datetime(2026, 10, 22, 7, 0, tzinfo=JST)
    items = {f"t{n}": _sub(f"t{n}", f"東京の補助金{n}", "2026-11-01T17:00:00+09:00", ["東京都"], ["飲食店"]) for n in range(3)}
    items["o"] = _sub("o", "大阪の補助金", "2026-11-01T17:00:00+09:00", ["大阪府"], ["共通"])
    (tmp_path / "chiiki").mkdir()
    (tmp_path / "chiiki" / "osaka.html").write_text("old", encoding="utf-8")  # 基準を下回った古いページ
    made = pages.build({k: v for k, v in items.items()}, cfg, now, [], out=tmp_path)
    assert made["chiiki"] == 1 and (tmp_path / "chiiki" / "tokyo.html").exists()
    assert not (tmp_path / "chiiki" / "osaka.html").exists()
    for p in ("index.html", "list/index.html", "gyotai/inshokuten.html", "chiiki/index.html", "privacy.html"):
        assert (tmp_path / p).exists(), p
    html = (tmp_path / "gyotai" / "inshokuten.html").read_text(encoding="utf-8")
    assert "飲食店が使える補助金・公募の一覧（受付中・2026年10月更新）" in html and "東京の補助金0" in html
    sm = (tmp_path / "sitemap.xml").read_text(encoding="utf-8")
    assert "chiiki/tokyo.html</loc><lastmod>2026-10-22</lastmod>" in sm and "osaka" not in sm


def test_industry_limited_to_other_trades_is_excluded():
    cfg = Config.load()
    now = datetime(2026, 10, 22, 7, 0, tzinfo=JST)
    bus = Item(source_id="jgrants", publisher="jGrants（デジタル庁）", kind=KIND_SUBSIDY,
               title="バス事業者人材開発支援奨励金", url="https://example.jp/bus", deadline="2026-11-30T17:00:00+09:00")
    bus.industries_raw, bus.body_text = "運輸業、郵便業", "中小企業の人材育成"
    food = Item(source_id="jgrants", publisher="jGrants（デジタル庁）", kind=KIND_SUBSIDY,
                title="食のまち推進補助金", url="https://example.jp/food", deadline="2026-11-30T17:00:00+09:00")
    food.industries_raw, food.body_text = "製造業 / 卸売業、小売業 / 宿泊業、飲食サービス業", "中小企業"
    classify_all([bus, food], cfg.rules, now, cfg.sources)
    assert not bus.relevant and food.relevant
