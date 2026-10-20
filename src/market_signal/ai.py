"""AIによる見立て（任意）。

- AIに事実は書かせない。題名・日付・締切・URLは情報源の値をそのまま使う。
- AIが返すのは「載せるか」「業態」「重要度」「一言の見立て」だけ。
- 見立てに、原文にない数字が入っていたら捨てる（機械による照合）。
- 月の利用額が上限に達したら、その月はAIを使わず判定基準だけで動く。
APIキー（ANTHROPIC_API_KEY）が無ければ、何もしない。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

from . import store
from .config import Config, now_jst
from .models import Item

API_URL = "https://api.anthropic.com/v1/messages"
DIGITS = re.compile(r"[0-9０-９]+")
ALLOWED_TYPES = {"飲食店", "食品製造", "食品卸・小売", "共通"}

SYSTEM_PROMPT = """あなたは、飲食・食品の事業者（飲食店、食品メーカー、食品卸・小売）向けに、行政の発表と補助金・公募を毎週届けるサービスの編集担当です。
渡された各項目について、次をJSONで返してください。
- relevant: 飲食・食品の事業者が知っておく価値があれば true
- business_types: 次から当てはまるものすべて（飲食店 / 食品製造 / 食品卸・小売 / 共通）。業態を問わず関係するなら 共通
- importance: 高 / 中 / 低（高＝営業・安全・法令対応に直接影響、または締切が近い。中＝使える可能性が高い。低＝参考）
- note: 事業者がどう活かせるか、何に気をつけるかを、40字以内の一文で。

厳守すること:
- note に、数字・金額・日付・締切・固有名詞を新しく書かない（それらは別欄に原文の値を載せるため）。
- 原文に書かれていないことを事実のように書かない。「〜の可能性」「〜を確認」のように見立てとして書く。
- 出力はJSON配列だけ。各要素は {"id": "...", "relevant": true, "business_types": [...], "importance": "中", "note": "..."}。"""


def _month_key() -> str:
    return now_jst().strftime("%Y-%m")


def month_cost_jpy(cfg: Config) -> float:
    u = store.load_ai_usage().get(_month_key(), {})
    return _cost(cfg, u.get("input_tokens", 0), u.get("output_tokens", 0))


def _cost(cfg: Config, tin: int, tout: int) -> float:
    pin = float(cfg.s("ai", "price_input_usd_per_mtok", default=0) or 0)
    pout = float(cfg.s("ai", "price_output_usd_per_mtok", default=0) or 0)
    fx = float(cfg.s("ai", "usd_jpy", default=170) or 170)
    tax = float(cfg.s("ai", "tax_rate", default=0.10) or 0)
    return (tin / 1e6 * pin + tout / 1e6 * pout) * fx * (1 + tax)


def _record(tin: int, tout: int) -> None:
    usage = store.load_ai_usage()
    m = usage.setdefault(_month_key(), {"input_tokens": 0, "output_tokens": 0, "calls": 0})
    m["input_tokens"] += tin
    m["output_tokens"] += tout
    m["calls"] += 1
    store.save_ai_usage(usage)


def note_is_safe(note: str, item: Item, max_len: int = 60) -> bool:
    """見立ての機械照合。原文にない数字、長すぎる文、URLを含むものは捨てる。"""
    if not note or len(note) > max_len or "http" in note:
        return False
    source = f"{item.title} {item.body_text or ''}"
    for d in DIGITS.findall(note):
        if d not in source:
            return False
    return True


def enabled(cfg: Config) -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and bool(cfg.s("ai", "enabled", default=True))


def annotate(items: list[Item], cfg: Config) -> dict[str, Any]:
    """載せる候補の項目にだけAIをかける。結果の集計を返す。"""
    stats = {"ai_input_tokens": 0, "ai_output_tokens": 0, "ai_notes_dropped": 0, "ai_skipped": ""}
    if not enabled(cfg):
        stats["ai_skipped"] = "APIキーなし"
        return stats
    budget = float(cfg.s("ai", "monthly_budget_jpy", default=2000))
    max_items = int(cfg.s("ai", "max_items_per_run", default=150))
    batch = int(cfg.s("ai", "batch_size", default=10))
    model = cfg.s("ai", "model")
    targets = [it for it in items if it.relevant and not it.ai_used][:max_items]

    for i in range(0, len(targets), batch):
        if month_cost_jpy(cfg) >= budget:
            stats["ai_skipped"] = "今月の上限に到達"
            break
        chunk = targets[i : i + batch]
        payload = [
            {
                "id": it.id,
                "区分": it.kind,
                "発表元": it.publisher,
                "題名": it.title,
                "業種欄": it.industries_raw or "",
                "本文の抜粋": (it.body_text or "")[:500],
            }
            for it in chunk
        ]
        try:
            res = requests.post(
                API_URL,
                headers={
                    "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": int(cfg.s("ai", "max_tokens", default=1500)),
                    # 思考機能は使わない（思考の分も出力として課金されるため）
                    "thinking": {"type": "disabled"},
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                },
                timeout=60,
            )
            res.raise_for_status()
            body = res.json()
        except Exception as e:  # AIが失敗しても配信は判定基準だけで続ける
            stats["ai_skipped"] = f"AI呼び出し失敗: {type(e).__name__}"
            break
        tin = int(body.get("usage", {}).get("input_tokens", 0))
        tout = int(body.get("usage", {}).get("output_tokens", 0))
        _record(tin, tout)
        stats["ai_input_tokens"] += tin
        stats["ai_output_tokens"] += tout
        text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
        results = _parse(text)
        by_id = {it.id: it for it in chunk}
        for r in results:
            it = by_id.get(str(r.get("id")))
            if not it:
                continue
            it.ai_used = True
            if r.get("relevant") is False:
                it.relevant = False
                continue
            types = [t for t in (r.get("business_types") or []) if t in ALLOWED_TYPES]
            if types:
                it.business_types = types
            imp = r.get("importance")
            # 回収・注意喚起は、AIの判断で重要度を下げない
            if imp in ("高", "中", "低") and not (it.importance == "高" and it.kind == "回収・注意喚起"):
                it.importance = imp
            note = str(r.get("note") or "").strip()
            if note_is_safe(note, it):
                it.ai_note = note
            else:
                it.ai_note = None
                stats["ai_notes_dropped"] += 1
    return stats


def _parse(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []
