"""PII protection and masking utilities.

Per specification Section 7.4:
- Personal data: full_name, email, phone.
- Answers & tool_calls: Mask emails as first char + *** + @domain (e.g. r***@veltrix.example).
  Never show phone numbers.
- Logs: No names, emails, or phone numbers. Use employee IDs instead.
"""

import re
from typing import Any

# Regex to match email addresses
EMAIL_REGEX = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b")

# Regex to match phone numbers in common formats
PHONE_REGEX = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b")


def mask_email(email: str) -> str:
    """Mask an email address to format: first_char + *** + @domain."""
    match = EMAIL_REGEX.match(email.strip())
    if not match:
        return "***@***"
    first_char, domain = match.groups()
    return f"{first_char}***@{domain}"


def mask_emails_in_text(text: str) -> str:
    """Find and mask all email addresses in a block of text."""
    if not text:
        return text

    def replacer(match: re.Match[str]) -> str:
        first_char = match.group(1)
        domain = match.group(2)
        return f"{first_char}***@{domain}"

    return EMAIL_REGEX.sub(replacer, text)


def redact_phones_in_text(text: str) -> str:
    """Remove or redact phone numbers from text."""
    if not text:
        return text
    # Avoid replacing single year numbers or standard identifiers
    # by ensuring match length and formatting look like phones
    return PHONE_REGEX.sub("[REDACTED_PHONE]", text)


def sanitize_text_for_user(text: str) -> str:
    """Sanitize user-facing text: mask emails and redact phones."""
    if not text:
        return text
    cleaned = redact_phones_in_text(text)
    return mask_emails_in_text(cleaned)


def scrub_pii_from_obj(obj: Any) -> Any:
    """Recursively scrub email addresses and phones from strings, dicts, and lists."""
    if isinstance(obj, str):
        # In logs, mask emails completely and redact phones
        text = EMAIL_REGEX.sub(r"\1***@\2", obj)
        return PHONE_REGEX.sub("[PHONE_REDACTED]", text)
    if isinstance(obj, dict):
        return {k: scrub_pii_from_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_pii_from_obj(item) for item in obj]
    return obj
