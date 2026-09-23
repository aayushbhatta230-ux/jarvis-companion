"""Reliability tests 4/4 — email diagnostics, drafting, honest send success/failure."""

from __future__ import annotations

import json
import os
import smtplib
from pathlib import Path

import pytest

import core.capabilities as capabilities
from core.capabilities import get_capability
from core.permissions import get_permission_manager


@pytest.fixture(autouse=True)
def _setup_email_env(monkeypatch):
    """Set up a test email password via environment variable."""
    monkeypatch.setenv("JARVIS_GMAIL_ADDRESS", "aayushbhatta230@gmail.com")
    monkeypatch.setenv("JARVIS_GMAIL_APP_PASSWORD", "test_app_password_123")
    yield


def test_email_diagnostics_reports_configuration_without_secret():
    from tools.email import diagnostics, diagnostics_dict
    d = diagnostics_dict()
    assert d["configured"] is True
    assert d["provider"] == "Gmail"
    assert d["authentication_available"] is True
    text = diagnostics()
    assert "aayushbhatta230@gmail.com" in text
    assert "smtp.gmail.com" in text
    config = json.loads(Path("memory/email_config.json").read_text(encoding="utf-8"))
    # Password should never be in the config file
    assert "password" not in config
    # Password should never be in diagnostics output
    assert "test_app_password_123" not in text


def test_email_draft_persists(tmp_path, monkeypatch):
    from tools import email as email_tools
    monkeypatch.setattr(email_tools, "DRAFTS_FILE", tmp_path / "drafts.json")
    out = email_tools.draft_email(to="aayushbhatta230@gmail.com", subject="JARVIS test", body="hi")
    assert "aayushbhatta230@gmail.com" in out
    assert "JARVIS test" in out
    saved = (tmp_path / "drafts.json").read_text(encoding="utf-8")
    assert "JARVIS test" in saved


def test_email_send_without_config_is_honest(monkeypatch):
    from tools import email as email_tools
    monkeypatch.setattr(email_tools, "_get_email_config", lambda: None)
    result = email_tools.send_email_direct(to="x@y.com", subject="s", body="b")
    assert result.success is False
    assert result.status == "UNCONFIGURED"
    assert "isn't configured" in str(result)


def test_email_send_failure_is_reported_not_faked(monkeypatch):
    from tools import email as email_tools

    class FailingSMTP:
        def __init__(self, *a, **k):
            pass

        def starttls(self, context=None):
            pass

        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

        def sendmail(self, *a, **k):
            raise AssertionError("should not be reached")

        def quit(self):
            pass

    monkeypatch.setattr(smtplib, "SMTP", FailingSMTP)
    result = email_tools.send_email_direct(to="x@y.com", subject="s", body="b")
    assert result.success is False
    assert result.status == "FAILED"
    assert result.message_id is None
    assert "fail" in str(result).lower()


def test_email_send_success_reports_real_message_id(monkeypatch):
    from tools import email as email_tools
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port):
            sent["host"], sent["port"] = host, port

        def starttls(self, context=None):
            sent["tls"] = True

        def login(self, user, password):
            sent["user"] = user

        def sendmail(self, sender, recipients, payload):
            sent["sender"], sent["recipients"], sent["payload"] = sender, recipients, payload
            return {}

        def quit(self):
            sent["quit"] = True

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    result = email_tools.send_email_direct(to="x@y.com", subject="hello", body="world")
    assert result.success is True
    assert result.status == "SENT"
    assert result.message_id, "a real Message-ID header must have been generated"
    assert sent["recipients"] == "x@y.com"
    assert result.message_id in sent["payload"]
    assert "hello" in sent["payload"]


def test_email_send_requires_confirmation_by_policy():
    assert get_capability("email.send").confirmation_required is True
    assert get_permission_manager().requires_confirmation("email.send") is True


def test_email_result_maps_to_honest_tool_result():
    from tools.email import EmailActionResult
    ok = EmailActionResult(True, "SENT", "x@y.com", "s", provider="Gmail", message_id="<1@x>")
    assert capabilities._resolve_result("email.send_direct", ok).success is True
    bad = EmailActionResult(False, "FAILED", "x@y.com", "s", error="boom")
    tool_bad = capabilities._resolve_result("email.send_direct", bad)
    assert tool_bad.success is False
    assert tool_bad.error == "boom"


def test_email_diagnostics_capability_registered():
    cap = get_capability("email.diagnostics")
    assert cap is not None and callable(cap.handler)
    result = capabilities.execute_capability("email.diagnostics")
    assert result.success is True
    assert "configured" in result.result
