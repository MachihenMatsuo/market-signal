"""判定・照合・停止のしくみのテスト（ネットにはつながない）。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from market_signal import ai, anomaly
from market_signal.classify import classify
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
