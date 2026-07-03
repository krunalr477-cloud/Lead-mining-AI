"""Bounce/DSN parser unit tests (spec §14). Pure — no DB, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.constants import BounceType
from app.outreach.bounce_parser import BounceInfo, classify_bounce, parse_dsn

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "dsn"


def _load(name: str) -> BounceInfo:
    return parse_dsn((FIXTURES / name).read_bytes())


def test_hard_bounce_511():
    info = _load("hard_511.eml")
    assert info.final_recipient == "nonexistent@example.com"
    assert info.smtp_status == "5.1.1"
    assert info.bounce_type == BounceType.HARD
    assert info.original_message_id == "lm-11111111-1111-1111-1111-111111111111@leadmine.local"
    assert "does not exist" in (info.diagnostic_code or "")


def test_soft_bounce_422():
    info = _load("soft_422.eml")
    assert info.final_recipient == "delayed@example.net"
    assert info.smtp_status == "4.2.2"
    assert info.bounce_type == BounceType.SOFT
    assert info.original_message_id == "lm-22222222-2222-2222-2222-222222222222@leadmine.local"


def test_mailbox_full():
    info = _load("mailbox_full.eml")
    assert info.final_recipient == "fullbox@example.com"
    assert info.bounce_type == BounceType.MAILBOX_FULL
    assert info.original_message_id.startswith("lm-33333333")


def test_spam_block():
    info = _load("spam_block.eml")
    assert info.final_recipient == "someone@blocked-domain.com"
    assert info.bounce_type == BounceType.SPAM_REJECTED
    assert info.original_message_id.startswith("lm-44444444")


def test_gmail_html_notice_fallback():
    """No delivery-status part -> regex fallback still recovers everything."""
    info = _load("gmail_html_notice.eml")
    assert info.final_recipient == "ghost@example.org"
    assert info.smtp_status == "5.1.1"
    assert info.bounce_type == BounceType.HARD
    assert info.original_message_id == "lm-55555555-5555-5555-5555-555555555555@leadmine.local"


# ---- classifier unit table ------------------------------------------------- #


@pytest.mark.parametrize(
    "status,diagnostic,expected",
    [
        ("5.1.1", "no such user", BounceType.HARD),
        ("5.0.0", "", BounceType.HARD),
        ("4.3.0", "try again later", BounceType.RATE_LIMITED),
        ("4.2.1", "temporarily deferred", BounceType.SOFT),
        ("5.2.2", "over quota", BounceType.MAILBOX_FULL),
        ("5.1.2", "no such domain", BounceType.INVALID_DOMAIN),
        ("5.7.1", "message rejected as spam", BounceType.SPAM_REJECTED),
        ("5.7.1", "access denied, blocked", BounceType.BLOCKED),
        (None, None, BounceType.UNKNOWN),
        ("2.0.0", "delivered", BounceType.UNKNOWN),
    ],
)
def test_classify_bounce_table(status, diagnostic, expected):
    assert classify_bounce(status, diagnostic) == expected


def test_parse_handles_garbage_bytes():
    info = parse_dsn(b"not a real email at all")
    assert isinstance(info, BounceInfo)
    assert info.bounce_type == BounceType.UNKNOWN
