"""設定ファイル（config/*.yaml）の読み込み。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("MS_CONFIG_DIR", ROOT / "config"))
DATA_DIR = Path(os.environ.get("MS_DATA_DIR", ROOT / "data"))
SITE_DIR = Path(os.environ.get("MS_SITE_DIR", ROOT / "site"))
OUT_DIR = Path(os.environ.get("MS_OUT_DIR", ROOT / "out"))
TEMPLATE_DIR = ROOT / "templates"

# 未記入のまま配信しないための目印
PLACEHOLDER_MARK = "【要記入】"


def now_jst() -> datetime:
    fixed = os.environ.get("MS_NOW")  # テスト用に現在時刻を固定できる
    if fixed:
        return datetime.fromisoformat(fixed).astimezone(JST)
    return datetime.now(JST)


def _load(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Config:
    settings: dict[str, Any]
    rules: dict[str, Any]
    sources: list[dict[str, Any]]

    @classmethod
    def load(cls) -> "Config":
        return cls(
            settings=_load("settings.yaml"),
            rules=_load("rules.yaml"),
            sources=_load("sources.yaml").get("sources", []),
        )

    def s(self, *keys: str, default: Any = None) -> Any:
        cur: Any = self.settings
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def missing_sender_info(self) -> list[str]:
        """特定電子メール法の表示に必要な項目のうち、未記入のもの。"""
        missing = []
        op = self.s("operator", default={}) or {}
        for key, label in (
            ("name", "送信者の名称"),
            ("address", "送信者の住所"),
            ("contact_email", "問い合わせ先メールアドレス"),
        ):
            val = str(op.get(key) or "")
            if not val or PLACEHOLDER_MARK in val:
                missing.append(label)
        site = str(self.s("site", "url", default="") or "")
        if not site or PLACEHOLDER_MARK in site:
            missing.append("公開ページのURL")
        if self.s("email", "provider", default="dryrun") != "dryrun":
            sender = str(self.s("email", "sender_email", default="") or "")
            if not sender or PLACEHOLDER_MARK in sender:
                missing.append("送信元メールアドレス")
            reply = str(self.s("email", "reply_to", default="") or "")
            if not reply or PLACEHOLDER_MARK in reply:
                missing.append("返信を受け取るメールアドレス")
            if not int(self.s("email", "list_id", default=0) or 0):
                missing.append("配信サービスの登録者リスト番号")
        return missing
