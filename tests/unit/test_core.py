"""Unit tests for core infrastructure modules: clock, tokens, PII, and config."""

from datetime import date

from veltrix.core.clock import AppClock
from veltrix.core.config import Settings
from veltrix.core.pii import (
    mask_email,
    mask_emails_in_text,
    redact_phones_in_text,
    sanitize_text_for_user,
    scrub_pii_from_obj,
)
from veltrix.core.tokens import count_tokens


def test_clock_fixed_today() -> None:
    clock = AppClock(fixed_today="2026-09-15")
    assert clock.today() == date(2026, 9, 15)
    assert clock.now().year == 2026


def test_clock_system_today() -> None:
    clock = AppClock(fixed_today=None)
    assert clock.today() == date.today()


def test_token_counter() -> None:
    text = "Hello world from Veltrix assistant."
    count = count_tokens(text)
    assert count > 0
    assert count_tokens("") == 0


def test_pii_email_masking() -> None:
    assert mask_email("hr@veltrix.example") == "h***@veltrix.example"
    assert mask_email("robert.smith@company.org") == "r***@company.org"

    text = "Contact support at helpdesk@veltrix.example or hr@veltrix.example."
    masked = mask_emails_in_text(text)
    assert "h***@veltrix.example" in masked
    assert "helpdesk@veltrix.example" not in masked
    assert "hr@veltrix.example" not in masked


def test_pii_phone_redaction() -> None:
    text = "Call John at +1-555-123-4567 or 987-654-3210 for details."
    redacted = redact_phones_in_text(text)
    assert "555-123-4567" not in redacted
    assert "987-654-3210" not in redacted


def test_sanitize_text_for_user() -> None:
    text = "Email hr@veltrix.example or call 123-456-7890."
    sanitized = sanitize_text_for_user(text)
    assert "h***@veltrix.example" in sanitized
    assert "123-456-7890" not in sanitized


def test_scrub_pii_from_obj() -> None:
    data = {
        "user": "E1001",
        "email": "alice@veltrix.example",
        "contacts": ["bob@veltrix.example", "Call 555-019-2831"],
    }
    scrubbed = scrub_pii_from_obj(data)
    assert scrubbed["email"] == "a***@veltrix.example"
    assert scrubbed["contacts"][0] == "b***@veltrix.example"
    assert "555-019-2831" not in scrubbed["contacts"][1]


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.MAX_CORPUS_TOKENS == 3000
    assert settings.LLM_PROVIDER in ["gemini", "openai", "anthropic"]
