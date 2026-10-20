"""Brevoへの送信のテスト（実際には送らず、送る内容を確かめる）。"""
from __future__ import annotations

import pytest

from market_signal import send
from market_signal.config import Config


class Resp:
    def __init__(self, code, data=None, text=""):
        self.status_code, self._d, self.text = code, data or {}, text

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    monkeypatch.setenv("EMAIL_API_KEY", "test-key")
    monkeypatch.setattr(send, "OUT_DIR", tmp_path)
    c = Config.load()
    c.settings["email"].update({"provider": "brevo", "list_id": 7, "sender_email": "news@example.jp",
                                "reply_to": "info@example.jp"})
    return c


def test_brevo_sends_campaign(cfg, monkeypatch):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(("GET", url, headers["api-key"]))
        return Resp(200, {"uniqueSubscribers": 12})

    def fake_post(url, headers, json=None, timeout=0):
        calls.append(("POST", url, json))
        return Resp(201, {"id": 99}) if url.endswith("/emailCampaigns") else Resp(204)

    monkeypatch.setattr(send.requests, "get", fake_get)
    monkeypatch.setattr(send.requests, "post", fake_post)
    r = send.send_issue(cfg, "件名", "<p>本文 <a href=\"{{ unsubscribe }}\">停止</a></p>", "本文", "2026-10-26 週刊号")
    assert r == {"provider": "brevo", "subscribers": 12, "sent": 12, "campaign_id": 99}
    create = calls[1][2]
    assert create["recipients"] == {"listIds": [7]} and create["sender"]["email"] == "news@example.jp"
    assert "{{ unsubscribe }}" in create["htmlContent"] and create["replyTo"] == "info@example.jp"
    assert calls[2][1].endswith("/emailCampaigns/99/sendNow")


def test_brevo_zero_subscribers_skips(cfg, monkeypatch):
    monkeypatch.setattr(send.requests, "get", lambda *a, **k: Resp(200, {"uniqueSubscribers": 0}))
    monkeypatch.setattr(send.requests, "post", lambda *a, **k: pytest.fail("送ってはいけない"))
    r = send.send_issue(cfg, "件名", "<p></p>", "")
    assert r["sent"] == 0


def test_brevo_warns_near_limit(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(send.requests, "get", lambda *a, **k: Resp(200, {"uniqueSubscribers": 280}))
    monkeypatch.setattr(send.requests, "post",
                        lambda url, **k: Resp(201, {"id": 1}) if url.endswith("/emailCampaigns") else Resp(204))
    send.send_issue(cfg, "件名", "<p></p>", "")
    assert (tmp_path / "warning.txt").exists()


def test_brevo_missing_settings_block_sending():
    c = Config.load()
    c.settings["email"].update({"provider": "brevo", "reply_to": "", "list_id": 0})
    missing = c.missing_sender_info()
    assert "返信を受け取るメールアドレス" in missing and "配信サービスの登録者リスト番号" in missing


def test_brevo_send_refused_raises_with_reason(cfg, monkeypatch):
    monkeypatch.setattr(send.requests, "get", lambda *a, **k: Resp(200, {"uniqueSubscribers": 1}))
    monkeypatch.setattr(send.requests, "post",
                        lambda url, **k: Resp(201, {"id": 5}) if url.endswith("/emailCampaigns")
                        else Resp(403, text="phone not verified"))
    with pytest.raises(RuntimeError, match="送信できませんでした"):
        send.send_issue(cfg, "件名", "<p></p>", "")


def test_check_connection_reads_list_without_sending(cfg, monkeypatch):
    monkeypatch.setattr(send.requests, "get", lambda *a, **k: Resp(200, {"uniqueSubscribers": 3}))
    monkeypatch.setattr(send.requests, "post", lambda *a, **k: pytest.fail("試し実行で送ってはいけない"))
    r = send.check_connection(cfg)
    assert r["subscribers"] == 3 and r["sent"] == 0


def test_check_connection_bad_key_stops_with_reason(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(send.requests, "get", lambda *a, **k: Resp(401, text="unauthorized"))
    with pytest.raises(RuntimeError):
        send.check_connection(cfg)
    assert "EMAIL_API_KEY" in (tmp_path / "stop_reason.txt").read_text(encoding="utf-8")


def test_brevo_without_api_key_skips_and_warns(cfg, monkeypatch, tmp_path):
    monkeypatch.delenv("EMAIL_API_KEY")
    monkeypatch.setattr(send.requests, "get", lambda *a, **k: pytest.fail("鍵が無いのに問い合わせてはいけない"))
    monkeypatch.setattr(send.requests, "post", lambda *a, **k: pytest.fail("送ってはいけない"))
    r = send.send_issue(cfg, "件名", "<p></p>", "")
    assert r["sent"] == 0 and "未登録" in r["provider"]
    assert "EMAIL_API_KEY" in (tmp_path / "warning.txt").read_text(encoding="utf-8")
