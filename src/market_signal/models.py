"""配信する1件分の情報。

事実の欄（title / url / publisher / published / deadline / regions）は、
情報源のデータから機械的に取り出した値だけを入れる。AIは書き込まない。
AIが書くのは labels 内の ai_note（「AIによる見立て」）だけで、別欄に分ける。
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

# 配信での区分
KIND_SUBSIDY = "補助金・公募"
KIND_GOV = "行政の発表"
KIND_RECALL = "回収・注意喚起"
KINDS = (KIND_SUBSIDY, KIND_GOV, KIND_RECALL)


def make_id(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]


@dataclass
class Item:
    # --- 事実の欄（情報源からそのまま） ---
    source_id: str
    publisher: str
    kind: str
    title: str
    url: str
    published: str | None = None  # ISO 8601（日本時間）
    deadline: str | None = None  # ISO 8601。構造化された項目から取れたときだけ入れる
    regions: list[str] = field(default_factory=list)  # 例: ["全国"], ["大阪府"]
    industries_raw: str | None = None  # 情報源が持つ業種の値（そのまま）
    body_text: str = ""  # 分類のためだけに使う本文の抜粋。配信には載せない
    # --- 機械が付ける欄 ---
    id: str = ""
    first_seen: str | None = None
    business_types: list[str] = field(default_factory=list)
    importance: str = "低"
    relevant: bool = False
    # AIによる見立て（事実の欄とは分けて表示する）
    ai_note: str | None = None
    ai_used: bool = False
    # 機械照合の結果
    checks: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = make_id(self.url)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Item":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    # 表示用
    @property
    def published_dt(self) -> datetime | None:
        return datetime.fromisoformat(self.published) if self.published else None

    @property
    def deadline_dt(self) -> datetime | None:
        return datetime.fromisoformat(self.deadline) if self.deadline else None
