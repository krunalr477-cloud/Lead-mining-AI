"""Pure DSN / bounce-notice parser (spec §14). NO I/O.

``parse_dsn(raw_bytes)`` accepts the raw RFC 822 bytes of a bounce message —
either a structured ``multipart/report; report-type=delivery-status`` DSN
(RFC 3464) or a Gmail-style HTML-ish "Delivery Status Notification (Failure)"
notice — and returns a :class:`BounceInfo` describing the failure.

Two extraction paths:

1. **Structured**: walk the ``message/delivery-status`` part for the
   per-recipient ``Final-Recipient`` / ``Action`` / ``Status`` /
   ``Diagnostic-Code`` fields, and recover the bounced message's own
   ``Message-ID`` from the attached ``message/rfc822`` (or its headers-only
   ``text/rfc822-headers``) part.
2. **Fallback**: when there is no delivery-status part (Gmail sometimes sends a
   human-readable HTML notice), scrape the recipient, an ``X.Y.Z`` enhanced
   status code, the SMTP reply, and the original Message-ID with regexes over
   the decoded text.

Classification maps the enhanced status class + diagnostic text to a
:class:`~app.constants.BounceType` bucket (see the module-level table).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import EmailMessage as _StdEmailMessage

from app.constants import BounceType

__all__ = ["BounceInfo", "classify_bounce", "parse_dsn"]


@dataclass(slots=True)
class BounceInfo:
    """Structured result of parsing one bounce message."""

    final_recipient: str | None = None
    smtp_status: str | None = None  # enhanced status, e.g. "5.1.1"
    diagnostic_code: str | None = None
    bounce_type: BounceType = BounceType.UNKNOWN
    original_message_id: str | None = None
    reason: str | None = None


# --------------------------------------------------------------------------- #
# Classification. Diagnostic-text keywords win over the raw status class so a
# 5.2.2 "mailbox full" is bucketed as MAILBOX_FULL, not a generic HARD.        #
# --------------------------------------------------------------------------- #

# Ordered (keyword-set -> bucket); first match wins.
_DIAGNOSTIC_RULES: tuple[tuple[tuple[str, ...], BounceType], ...] = (
    (
        ("mailbox full", "quota exceeded", "over quota", "user is over quota", "5.2.2"),
        BounceType.MAILBOX_FULL,
    ),
    (
        (
            "no such domain",
            "domain not found",
            "unable to resolve",
            "host unknown",
            "domain does not exist",
            "5.1.2",
        ),
        BounceType.INVALID_DOMAIN,
    ),
    (
        (
            "spam",
            "content rejected",
            "message rejected as spam",
            "policy violation",
            "listed on",
            "blocklist",
            "blacklist",
            "bulk mail",
        ),
        BounceType.SPAM_REJECTED,
    ),
    (
        ("blocked", "access denied", "not permitted", "rejected by", "connection refused"),
        BounceType.BLOCKED,
    ),
    (("rate limit", "too many", "try again later", "throttl", "4.7.28"), BounceType.RATE_LIMITED),
)


def _status_class(smtp_status: str | None) -> str | None:
    """First digit of an enhanced status like ``5.1.1`` (-> ``"5"``)."""
    if not smtp_status:
        return None
    smtp_status = smtp_status.strip()
    return smtp_status[0] if smtp_status and smtp_status[0].isdigit() else None


def classify_bounce(smtp_status: str | None, diagnostic: str | None) -> BounceType:
    """Map an enhanced status + diagnostic text to a :class:`BounceType`.

    Diagnostic keywords take precedence (a soft 4.2.2 "mailbox full" still buckets
    as MAILBOX_FULL). Otherwise the status class decides: ``5.x`` -> HARD,
    ``4.x`` -> SOFT, anything else -> UNKNOWN.
    """
    text = f"{diagnostic or ''} {smtp_status or ''}".lower()
    for keywords, bucket in _DIAGNOSTIC_RULES:
        if any(kw in text for kw in keywords):
            return bucket
    cls = _status_class(smtp_status)
    if cls == "5":
        return BounceType.HARD
    if cls == "4":
        return BounceType.SOFT
    return BounceType.UNKNOWN


# --------------------------------------------------------------------------- #
# Field extractors                                                            #
# --------------------------------------------------------------------------- #

_ANGLE_RE = re.compile(r"<([^>]+)>")
_RFC822_ADDR_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_STATUS_RE = re.compile(r"\b([245]\.\d{1,3}\.\d{1,3})\b")
_SMTP_REPLY_RE = re.compile(r"\b([245]\d\d)[ \-]")
_MSGID_RE = re.compile(r"Message-ID:\s*<([^>]+)>", re.IGNORECASE)


def _clean_addr(value: str | None) -> str | None:
    """Strip an RFC 822 address type prefix / angle brackets -> bare address."""
    if not value:
        return None
    value = value.strip()
    # DSN Final-Recipient is "rfc822; user@host"
    if ";" in value:
        value = value.split(";", 1)[1].strip()
    m = _ANGLE_RE.search(value)
    if m:
        value = m.group(1).strip()
    m = _RFC822_ADDR_RE.search(value)
    return m.group(0) if m else (value or None)


def _decode_text(part: _StdEmailMessage) -> str:
    """Best-effort decode of a text part to a str."""
    try:
        payload = part.get_content()
        if isinstance(payload, str):
            return payload
    except Exception:  # noqa: BLE001 - fall through to raw bytes
        pass
    raw = part.get_payload(decode=True)
    if raw is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def _walk(msg: _StdEmailMessage):
    yield msg
    if msg.is_multipart():
        for part in msg.iter_parts():
            yield from _walk(part)


def _find_original_message_id(msg: _StdEmailMessage) -> str | None:
    """Recover the bounced message's own Message-ID from the DSN payload.

    Prefer the ``message/rfc822`` (or ``text/rfc822-headers``) attachment's
    real ``Message-ID`` header; fall back to any ``Message-ID:`` line found in
    the decoded body.
    """
    for part in _walk(msg):
        ctype = part.get_content_type()
        if ctype == "message/rfc822":
            inner = part.get_payload()
            candidates = inner if isinstance(inner, list) else [inner]
            for cand in candidates:
                if isinstance(cand, _StdEmailMessage):
                    mid = cand.get("Message-ID")
                    if mid:
                        m = _ANGLE_RE.search(mid)
                        return m.group(1) if m else mid.strip()
        if ctype == "text/rfc822-headers":
            text = _decode_text(part)
            m = _MSGID_RE.search(text)
            if m:
                return m.group(1).strip()
    # Last resort: scan the whole decoded body.
    for part in _walk(msg):
        if part.get_content_maintype() == "text":
            m = _MSGID_RE.search(_decode_text(part))
            if m:
                return m.group(1).strip()
    return None


def _parse_delivery_status(part: _StdEmailMessage) -> dict[str, str]:
    """Parse a ``message/delivery-status`` part into a flat field dict.

    A delivery-status body is one per-message block then one-or-more
    per-recipient blocks, each a set of RFC 822-style header lines. We only need
    the (last, i.e. failed) recipient block's fields.
    """
    fields: dict[str, str] = {}
    payload = part.get_payload()
    blocks = payload if isinstance(payload, list) else [payload]
    for block in blocks:
        if not isinstance(block, _StdEmailMessage):
            # Some parsers hand back the raw text; split manually.
            text = block if isinstance(block, str) else _decode_text(part)
            for line in text.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fields[k.strip().lower()] = v.strip()
            continue
        for key in block:
            fields[key.strip().lower()] = str(block.get(key)).strip()
    return fields


def _parse_structured(msg: _StdEmailMessage) -> BounceInfo | None:
    """Extract a BounceInfo from a structured RFC 3464 DSN, or None if absent."""
    ds_part = next(
        (p for p in _walk(msg) if p.get_content_type() == "message/delivery-status"),
        None,
    )
    if ds_part is None:
        return None
    fields = _parse_delivery_status(ds_part)
    recipient = _clean_addr(fields.get("final-recipient") or fields.get("original-recipient"))
    status = fields.get("status")
    diagnostic = fields.get("diagnostic-code")
    action = fields.get("action", "").lower()

    # Recover an enhanced status from the diagnostic if Status header is absent.
    if not status and diagnostic:
        m = _STATUS_RE.search(diagnostic)
        if m:
            status = m.group(1)

    info = BounceInfo(
        final_recipient=recipient,
        smtp_status=status,
        diagnostic_code=diagnostic,
        original_message_id=_find_original_message_id(msg),
        reason=diagnostic or (f"action={action}" if action else None),
    )
    info.bounce_type = classify_bounce(status, diagnostic)
    # A "delayed" action with a 4.x status is a genuine soft bounce even absent
    # a keyword; the classifier already handles that via the status class.
    return info


def _parse_fallback(msg: _StdEmailMessage) -> BounceInfo:
    """Regex scrape a Gmail HTML-ish failure notice (no delivery-status part)."""
    # Collect all text/* bodies (html + plain) into one blob.
    blobs: list[str] = []
    for part in _walk(msg):
        if part.get_content_maintype() == "text":
            blobs.append(_decode_text(part))
    text = "\n".join(blobs)
    # Strip tags so "address not found" copy inside <div>s is searchable.
    stripped = re.sub(r"<[^>]+>", " ", text)
    stripped = re.sub(r"&[a-zA-Z]+;", " ", stripped)

    status_m = _STATUS_RE.search(stripped)
    status = status_m.group(1) if status_m else None

    original_id = _find_original_message_id(msg) or (
        _MSGID_RE.search(stripped).group(1) if _MSGID_RE.search(stripped) else None
    )

    # Recipient: the address the notice says wasn't found. Prefer one adjacent to
    # a "not found"/"failed" cue; else the first address that isn't the daemon.
    recipient = None
    cue = re.search(
        r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})[^@]{0,80}?"
        r"(?:not\s+found|does\s?n[o']?t\s+exist|couldn'?t\s+be\s+found|wasn'?t\s+found|"
        r"rejected|blocked|failed)",
        stripped,
        re.IGNORECASE,
    )
    if cue:
        recipient = cue.group(1)
    else:
        for addr in _RFC822_ADDR_RE.findall(stripped):
            low = addr.lower()
            if not low.startswith(("mailer-daemon@", "postmaster@")):
                recipient = addr
                break

    # SMTP reply text as the diagnostic (line containing the enhanced status).
    diagnostic = None
    for line in stripped.splitlines():
        if status and status in line:
            diagnostic = line.strip()
            break
    if diagnostic is None and status_m:
        diagnostic = stripped[max(0, status_m.start() - 40) : status_m.end() + 120].strip()

    info = BounceInfo(
        final_recipient=_clean_addr(recipient),
        smtp_status=status,
        diagnostic_code=diagnostic,
        original_message_id=original_id,
        reason=diagnostic,
    )
    info.bounce_type = classify_bounce(status, diagnostic or stripped)
    return info


def parse_dsn(raw_bytes: bytes) -> BounceInfo:
    """Parse raw bounce-message bytes into a :class:`BounceInfo` (pure, no I/O).

    Tries the structured RFC 3464 delivery-status path first, then falls back to
    a regex scrape of the human-readable notice. Always returns a BounceInfo;
    fields it cannot recover are left ``None`` / ``UNKNOWN``.
    """
    if isinstance(raw_bytes, str):
        raw_bytes = raw_bytes.encode("utf-8")
    msg = message_from_bytes(raw_bytes, policy=policy.default)
    structured = _parse_structured(msg)
    if structured is not None and structured.final_recipient:
        return structured
    fallback = _parse_fallback(msg)
    # If structured found a recipient-less status but fallback found nothing
    # better, keep whichever has the recipient.
    if structured is not None and not fallback.final_recipient:
        return structured
    return fallback
