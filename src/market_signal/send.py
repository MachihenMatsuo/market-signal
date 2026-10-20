"""メール配信。配信サービスは config/settings.yaml の email.provider で切り替える。

- dryrun：送らずに out/ に保存するだけ（配信サービスの登録前）
- brevo ：Brevo のAPIで、登録者リストに一斉配信する
  （配信停止リンクは Brevo の差し込み記号 {{ unsubscribe }} で入れる）
"""
from __future__ import annotations

import os
from typing import Any

import requests

from .config import OUT_DIR, Config

BREVO = "https://api.brevo.com/v3"


def _brevo_headers() -> dict[str, str]:
    key = os.environ.get("EMAIL_API_KEY")
    if not key:
        raise RuntimeError("EMAIL_API_KEY（BrevoのAPIキー）が登録されていません")
    return {"api-key": key, "accept": "application/json", "content-type": "application/json"}


def brevo_subscribers(list_id: int) -> int:
    r = requests.get(f"{BREVO}/contacts/lists/{list_id}", headers=_brevo_headers(), timeout=30)
    r.raise_for_status()
    d = r.json()
    return int(d.get("uniqueSubscribers", d.get("totalSubscribers", 0)) or 0)


def send_brevo(cfg: Config, subject: str, html: str, campaign_name: str) -> dict[str, Any]:
    list_id = int(cfg.s("email", "list_id"))
    subs = brevo_subscribers(list_id)
    result: dict[str, Any] = {"provider": "brevo", "subscribers": subs, "sent": 0}
    limit = int(cfg.s("email", "daily_limit", default=300))
    if subs >= int(limit * 0.9):
        # 無料プランは1日300通まで。上限に近づいたら知らせる（上位プランに移るかの判断材料）
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "warning.txt").write_text(
            f"登録者が{subs}人になりました。配信サービスの無料プランは1日{limit}通までのため、"
            f"超えた分はその日に届きません。上位プランへの切り替えを検討する時期です。",
            encoding="utf-8",
        )
    if subs == 0:
        result["note"] = "登録者0人のため送信なし"
        return result
    body = {
        "name": campaign_name,
        "subject": subject,
        "sender": {"name": cfg.s("email", "sender_name"), "email": cfg.s("email", "sender_email")},
        "htmlContent": html,
        "recipients": {"listIds": [list_id]},
    }
    reply_to = cfg.s("email", "reply_to")
    if reply_to and "【要記入】" not in str(reply_to):
        body["replyTo"] = reply_to  # 返信は、受け取れるアドレスに届くようにする
    r = requests.post(f"{BREVO}/emailCampaigns", headers=_brevo_headers(), json=body, timeout=60)
    r.raise_for_status()
    cid = r.json()["id"]
    s = requests.post(f"{BREVO}/emailCampaigns/{cid}/sendNow", headers=_brevo_headers(), timeout=60)
    if s.status_code != 204:
        raise RuntimeError(f"Brevoで送信できませんでした（{s.status_code}）：{s.text[:300]}")
    result.update({"sent": min(subs, limit), "campaign_id": cid})
    return result


def check_connection(cfg: Config) -> dict[str, Any]:
    """試し実行用：送らずに、配信サービスにつながるか（APIキーが有効で、登録者リストを読めるか）だけ確かめる。"""
    if cfg.s("email", "provider", default="dryrun") != "brevo":
        return {"sent": 0, "subscribers": "", "provider": "dryrun（配信サービス未設定）"}
    if not os.environ.get("EMAIL_API_KEY"):
        return {"sent": 0, "subscribers": "", "provider": "brevo（APIキー未登録のため接続確認なし）"}
    list_id = int(cfg.s("email", "list_id", default=0) or 0)
    try:
        subs = brevo_subscribers(list_id)
    except Exception as e:  # キーの誤り・権限不足・リスト番号の誤りなど
        reason = (f"Brevoの登録者リスト（番号{list_id}）を読めませんでした。APIキー（EMAIL_API_KEY）の値と、"
                  f"キーの権限（Contacts：Read、Email campaigns：All）を確認してください。詳細：{str(e)[:200]}")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "stop_reason.txt").write_text(reason, encoding="utf-8")
        raise RuntimeError(reason) from e
    return {"sent": 0, "subscribers": subs, "provider": "brevo（接続確認のみ。送信なし）"}


def send_issue(cfg: Config, subject: str, html: str, text: str, campaign_name: str = "") -> dict[str, Any]:
    provider = cfg.s("email", "provider", default="dryrun")
    if provider == "dryrun":
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "sent_dryrun.txt").write_text(subject, encoding="utf-8")
        return {"sent": 0, "subscribers": "", "provider": "dryrun（配信サービス未設定）"}
    if provider == "brevo":
        if not os.environ.get("EMAIL_API_KEY"):
            # 鍵の登録前でも公開ページは更新し、メールだけ送らずに知らせる
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            (OUT_DIR / "warning.txt").write_text(
                "配信サービス（Brevo）のAPIキーが、GitHubの Secrets に EMAIL_API_KEY として登録されていないため、"
                "今週はメールを送っていません（公開ページは更新済みです）。登録すると、次の号から送ります。",
                encoding="utf-8",
            )
            return {"sent": 0, "subscribers": "", "provider": "brevo（APIキー未登録のため送信なし）"}
        return send_brevo(cfg, subject, html, campaign_name or subject)
    raise ValueError(f"未対応の配信サービス: {provider}")
