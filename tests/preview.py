"""見本データでの通しテスト（ネットにつながない環境用）。

tests/fixtures/ に置いた各情報源の見本（RSSのXML、jGrantsのJSON）を、本番と同じ読み取り処理に通し、
振り分け→照合→ページとメールの作成まで動かす。出力は MS_SITE_DIR / MS_OUT_DIR。

  MS_NOW=2026-10-26T07:00:00+09:00 PYTHONPATH=src python tests/preview.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
tmp = Path(tempfile.mkdtemp(prefix="ms-preview-"))
os.environ.setdefault("MS_DATA_DIR", str(tmp / "data"))
os.environ.setdefault("MS_SITE_DIR", str(tmp / "site"))
os.environ.setdefault("MS_OUT_DIR", str(tmp / "out"))
sys.path.insert(0, str(ROOT / "src"))

from market_signal import store  # noqa: E402
from market_signal.classify import classify_all  # noqa: E402
from market_signal.cli import cmd_weekly  # noqa: E402
from market_signal.collect import jgrants, rss  # noqa: E402
from market_signal.config import Config, now_jst  # noqa: E402


def main() -> int:
    cfg = Config.load()
    # 見本では送信者の表示を仮に埋める（本番の設定ファイルは変えない）
    cfg.settings["operator"] = {"name": "まちへん合同会社", "address": "（見本）住所", "contact_email": "（見本）info@example.jp"}
    cfg.settings.setdefault("site", {})["url"] = "https://example.github.io/market-signal/"
    cfg.settings.setdefault("signup", {})["url"] = "https://example.com/signup"
    items = []
    for src in cfg.sources:
        if src["type"] == "rss":
            f = FIX / f"{src['id']}.xml"
            if f.exists():
                items += rss.parse(f.read_bytes(), src)
        elif src["type"] == "jgrants":
            f = FIX / f"{src['id']}.json"
            if f.exists():
                data = json.loads(f.read_text(encoding="utf-8"))
                for row in data["list"]["result"]:
                    detail = {**row, **data.get("details", {}).get(row["id"], {})}
                    items.append(jgrants.to_item(row, detail, src, [data.get("search_keyword", "")]))
    now = now_jst()
    classify_all(items, cfg.rules, now, cfg.sources)
    merged, added = store.merge_items({}, items)
    store.save_items(merged)
    print(f"見本の件数: {len(items)}（新規 {added}）")
    code = cmd_weekly(cfg, dry_run=True, skip_collect=True, check_url=lambda u: (True, 200))
    print("出力先:", os.environ["MS_SITE_DIR"], os.environ["MS_OUT_DIR"])
    return code


if __name__ == "__main__":
    sys.exit(main())
