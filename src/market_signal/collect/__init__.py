"""情報源からの収集。情報源の一覧は config/sources.yaml。"""
from __future__ import annotations

import time
from typing import Any

from .. import store
from ..config import Config, now_jst
from ..models import Item
from . import jgrants, rss

COLLECTORS = {"rss": rss.collect, "jgrants": jgrants.collect}


def collect_all(cfg: Config) -> tuple[list[Item], dict[str, Any]]:
    health = store.load_source_health()
    items: list[Item] = []
    report: dict[str, Any] = {}
    for src in cfg.sources:
        if not src.get("enabled", True):
            continue
        sid = src["id"]
        fn = COLLECTORS.get(src["type"])
        h = health.setdefault(sid, {"consecutive_failures": 0})
        if not fn:
            report[sid] = "未対応の種類"
            continue
        try:
            got = fn(src, cfg)
            items.extend(got)
            h["consecutive_failures"] = 0
            h["last_success"] = now_jst().isoformat(timespec="seconds")
            h["last_count"] = len(got)
            report[sid] = len(got)
        except Exception as e:  # 1つの情報源が壊れても、他は続ける
            h["consecutive_failures"] = int(h.get("consecutive_failures", 0)) + 1
            h["last_error"] = f"{type(e).__name__}: {e}"[:300]
            report[sid] = f"失敗: {h['last_error']}"
        time.sleep(float(cfg.s("collect", "pause_seconds", default=1)))
    store.save_source_health(health)
    return items, report
