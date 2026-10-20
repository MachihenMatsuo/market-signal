"""情報源へのアクセス。1回の実行で各情報源に数回だけアクセスし、間を空ける。"""
from __future__ import annotations

import requests

USER_AGENT = "MarketSignalJapanBot/1.0 (+weekly digest for food businesses)"


def get(url: str, params: dict | None = None, timeout: int = 30) -> requests.Response:
    r = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    return r
