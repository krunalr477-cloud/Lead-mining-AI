"""Gmail send + inbox polling client (spec §13/§14).

Two backends behind one interface:

- :class:`GmailClient` — the real Gmail v1 API via ``google-api-python-client``
  ``build("gmail", "v1")`` with tenant OAuth credentials. ``send`` uses
  ``users.messages.send`` with a base64url raw RFC 822 message; polling uses
  ``users.messages.list``/``get``; label edits use ``users.messages.modify``.
- :class:`FakeGmailClient` — an in-memory demo backend. It stores every sent
  message, and — deterministically — synthesizes DSN bounce notices for ~3% of
  recipients and a few replies, so ``poll_bounces`` / ``poll_replies`` have real
  RFC 822 payloads to parse without any network.

:func:`get_gmail_client` picks the backend: Fake in DEMO_MODE or without a
usable tenant Google credential, else real.

The client speaks ``GmailMessage`` (id + threadId + raw bytes) so callers never
touch API dicts directly.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import EmailMessage as _StdEmailMessage
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.config import get_settings
from app.db import utcnow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

__all__ = [
    "FakeGmailClient",
    "GmailClient",
    "GmailMessage",
    "get_gmail_client",
]

GOOGLE_PROVIDER = "google"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"

# Demo bounce rate: ~1 in 33 recipients hard-bounces (spec §21 ≈ 3.1%).
_DEMO_BOUNCE_MODULUS = 33
# Demo reply rate: ~1 in 12 recipients replies.
_DEMO_REPLY_MODULUS = 12


@dataclass(slots=True)
class GmailMessage:
    """A Gmail message: its id, thread id, and (optionally) raw RFC 822 bytes."""

    id: str
    thread_id: str
    raw: bytes | None = None
    label_ids: list[str] = field(default_factory=list)
    snippet: str | None = None


def build_mime(
    *,
    to: str,
    sender: str,
    subject: str,
    body: str,
    headers: dict[str, str] | None = None,
) -> _StdEmailMessage:
    """Assemble a plain-text RFC 822 message with the given headers."""
    msg = _StdEmailMessage()
    msg["To"] = to
    msg["From"] = sender
    msg["Subject"] = subject
    for key, value in (headers or {}).items():
        # Message-ID / List-Unsubscribe / X-LeadMine-Id etc. Overwrite if preset.
        if key in msg:
            del msg[key]
        msg[key] = value
    msg.set_content(body)
    return msg


def _encode_raw(msg: _StdEmailMessage) -> str:
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


# --------------------------------------------------------------------------- #
# Real Gmail backend                                                          #
# --------------------------------------------------------------------------- #


class GmailClient:
    """Real Gmail v1 client for one authorized send account."""

    def __init__(
        self,
        credentials: Any = None,
        *,
        from_account: str,
        user_id: str = "me",
        service: Any = None,
    ) -> None:
        # ``credentials`` may be a Credentials object or a zero-arg callable.
        self._credentials = credentials
        self.from_account = from_account
        self.user_id = user_id
        self._service = service  # injectable for tests

    def _resolve_credentials(self) -> Any:
        creds = self._credentials
        if callable(creds):
            creds = creds()
        if creds is None:
            raise RuntimeError("GmailClient requires OAuth credentials")
        return creds

    @property
    def service(self) -> Any:
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build(
                "gmail",
                "v1",
                credentials=self._resolve_credentials(),
                cache_discovery=False,
            )
        return self._service

    def _execute(self, request: Any) -> Any:
        """Run a Gmail request; raise TransientError on 429/5xx for auto-retry.

        ``invalid_grant`` (revoked/expired refresh token) surfaces as a
        PermanentError so the caller can pause the campaign rather than retry.
        """
        from googleapiclient.errors import HttpError

        from app.workers.celery_app import PermanentError, TransientError

        try:
            return request.execute()
        except HttpError as exc:  # pragma: no cover - real network path
            status = getattr(getattr(exc, "resp", None), "status", None)
            detail = str(exc)
            if "invalid_grant" in detail:
                raise PermanentError("gmail invalid_grant") from exc
            if status in (429, 500, 502, 503):
                raise TransientError(f"gmail {status}") from exc
            raise
        except Exception as exc:  # pragma: no cover - refresh failures
            if "invalid_grant" in str(exc):
                from app.workers.celery_app import PermanentError as _PE

                raise _PE("gmail invalid_grant") from exc
            raise

    def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        headers: dict[str, str] | None = None,
    ) -> GmailMessage:
        mime = build_mime(
            to=to, sender=self.from_account, subject=subject, body=body, headers=headers
        )
        sent = self._execute(
            self.service.users()
            .messages()
            .send(userId=self.user_id, body={"raw": _encode_raw(mime)})
        )
        return GmailMessage(
            id=sent["id"],
            thread_id=sent.get("threadId", sent["id"]),
            label_ids=sent.get("labelIds", []),
        )

    def list_messages(self, q: str, *, max_results: int = 100) -> list[GmailMessage]:
        resp = self._execute(
            self.service.users().messages().list(userId=self.user_id, q=q, maxResults=max_results)
        )
        out: list[GmailMessage] = []
        for item in resp.get("messages", []):
            out.append(GmailMessage(id=item["id"], thread_id=item.get("threadId", item["id"])))
        return out

    def get_message(self, message_id: str, *, format: str = "raw") -> GmailMessage:
        resp = self._execute(
            self.service.users().messages().get(userId=self.user_id, id=message_id, format=format)
        )
        raw = None
        if format == "raw" and resp.get("raw"):
            raw = base64.urlsafe_b64decode(resp["raw"].encode("ascii"))
        return GmailMessage(
            id=resp["id"],
            thread_id=resp.get("threadId", resp["id"]),
            raw=raw,
            label_ids=resp.get("labelIds", []),
            snippet=resp.get("snippet"),
        )

    def list_thread_messages(self, thread_id: str) -> list[GmailMessage]:
        resp = self._execute(
            self.service.users().threads().get(userId=self.user_id, id=thread_id, format="metadata")
        )
        out: list[GmailMessage] = []
        for item in resp.get("messages", []):
            out.append(
                GmailMessage(
                    id=item["id"],
                    thread_id=item.get("threadId", thread_id),
                    label_ids=item.get("labelIds", []),
                    snippet=item.get("snippet"),
                )
            )
        return out

    def modify_labels(
        self, message_id: str, *, add: list[str] | None = None, remove: list[str] | None = None
    ) -> None:
        body = {"addLabelIds": add or [], "removeLabelIds": remove or []}
        self._execute(
            self.service.users().messages().modify(userId=self.user_id, id=message_id, body=body)
        )


# --------------------------------------------------------------------------- #
# Fake Gmail backend (demo)                                                   #
# --------------------------------------------------------------------------- #


@dataclass
class _StoredMessage:
    id: str
    thread_id: str
    to: str
    subject: str
    body: str
    headers: dict[str, str]
    raw: bytes
    sent_at: datetime
    is_dsn: bool = False
    is_reply: bool = False
    from_addr: str = ""
    label_ids: list[str] = field(default_factory=lambda: ["SENT"])
    snippet: str | None = None


def _stable_bucket(seed: str, modulus: int) -> int:
    """Deterministic 0..modulus-1 bucket for a recipient (no RNG state)."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulus


def _synthesize_dsn(original: _StoredMessage, from_account: str) -> bytes:
    """Build a realistic multipart/report DSN bouncing ``original``.

    Assembled as a raw RFC 822 string (rather than via MIMEBase, which cannot
    serialize a bare-text ``message/delivery-status`` sub-part) so it round-trips
    through :func:`~app.outreach.bounce_parser.parse_dsn`. The DSN quotes the
    original's own ``Message-ID`` so the poller can match it back.
    """
    original_message_id = original.headers.get("Message-ID") or f"<lm-{original.id}@leadmine>"
    original_message_id = original_message_id.strip("<>")
    daemon = f"mailer-daemon@{_domain_of(from_account)}"
    boundary = f"DSN-{original.id}"
    raw = (
        f"From: Mail Delivery Subsystem <{daemon}>\r\n"
        f"To: {from_account}\r\n"
        "Subject: Delivery Status Notification (Failure)\r\n"
        f"Message-ID: <dsn-{original.id}@mailer-daemon>\r\n"
        "Content-Type: multipart/report; report-type=delivery-status; "
        f'boundary="{boundary}"\r\n'
        "\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/plain; charset=UTF-8\r\n"
        "\r\n"
        f"Your message to {original.to} could not be delivered.\r\n"
        "The email account that you tried to reach does not exist.\r\n"
        "\r\n"
        f"--{boundary}\r\n"
        "Content-Type: message/delivery-status\r\n"
        "\r\n"
        "Reporting-MTA: dns; gmail.com\r\n"
        "\r\n"
        f"Final-Recipient: rfc822; {original.to}\r\n"
        "Action: failed\r\n"
        "Status: 5.1.1\r\n"
        "Diagnostic-Code: smtp; 550 5.1.1 The email account that you tried to "
        "reach does not exist.\r\n"
        "\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/rfc822-headers\r\n"
        "\r\n"
        f"To: {original.to}\r\n"
        f"From: {from_account}\r\n"
        f"Subject: {original.subject}\r\n"
        f"Message-ID: <{original_message_id}>\r\n"
        "\r\n"
        f"--{boundary}--\r\n"
    )
    return raw.encode("utf-8")


def _synthesize_reply(original: _StoredMessage) -> bytes:
    in_reply_to = original.headers.get("Message-ID", f"<lm-{original.id}@leadmine>")
    raw = (
        f"From: {original.to}\r\n"
        f"To: {original.from_addr}\r\n"
        f"Subject: Re: {original.subject}\r\n"
        f"In-Reply-To: {in_reply_to}\r\n"
        f"Message-ID: <reply-{original.id}@{_domain_of(original.to)}>\r\n"
        "Content-Type: text/plain; charset=UTF-8\r\n"
        "\r\n"
        "Thanks for reaching out — please send more details.\r\n"
    )
    return raw.encode("utf-8")


def _domain_of(addr: str) -> str:
    return addr.split("@", 1)[1] if "@" in addr else "example.com"


class FakeGmailClient:
    """In-memory demo Gmail backend. Instances are keyed per tenant+account.

    A class-level registry keeps store state stable across ``get_gmail_client``
    calls within a process, so a send in one task and a poll in another (same
    process, e.g. the integration test / inline demo) see the same mailbox.
    """

    _registry: dict[tuple[str, str], FakeGmailClient] = {}

    def __init__(self, from_account: str, tenant_id: UUID | None = None) -> None:
        self.from_account = from_account
        self.tenant_id = tenant_id
        self.messages: dict[str, _StoredMessage] = {}
        self.threads: dict[str, list[str]] = {}
        self._counter = 0

    @classmethod
    def for_account(cls, from_account: str, tenant_id: UUID | None = None) -> FakeGmailClient:
        key = (str(tenant_id), from_account)
        inst = cls._registry.get(key)
        if inst is None:
            inst = cls(from_account, tenant_id)
            cls._registry[key] = inst
        return inst

    @classmethod
    def reset_registry(cls) -> None:
        cls._registry.clear()

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:06d}"

    def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        headers: dict[str, str] | None = None,
    ) -> GmailMessage:
        headers = dict(headers or {})
        mime = build_mime(
            to=to, sender=self.from_account, subject=subject, body=body, headers=headers
        )
        mid = self._next_id("fakemsg")
        thread_id = self._next_id("fakethread")
        stored = _StoredMessage(
            id=mid,
            thread_id=thread_id,
            to=to,
            subject=subject,
            body=body,
            headers=headers,
            raw=mime.as_bytes(),
            sent_at=utcnow(),
            from_addr=self.from_account,
            snippet=body[:100],
        )
        self.messages[mid] = stored
        self.threads[thread_id] = [mid]

        # Deterministically inject a bounce or reply for a slice of recipients.
        if _stable_bucket(to, _DEMO_BOUNCE_MODULUS) == 0:
            self._inject_dsn(stored)
        elif _stable_bucket(to, _DEMO_REPLY_MODULUS) == 0:
            self._inject_reply(stored)

        return GmailMessage(id=mid, thread_id=thread_id, label_ids=["SENT"])

    def _inject_dsn(self, original: _StoredMessage) -> None:
        raw = _synthesize_dsn(original, self.from_account)
        dsn_id = self._next_id("fakedsn")
        dsn_thread = self._next_id("fakethread")
        self.messages[dsn_id] = _StoredMessage(
            id=dsn_id,
            thread_id=dsn_thread,
            to=self.from_account,
            subject="Delivery Status Notification (Failure)",
            body="",
            headers={},
            raw=raw,
            sent_at=original.sent_at + timedelta(seconds=30),
            is_dsn=True,
            from_addr=f"mailer-daemon@{_domain_of(self.from_account)}",
            label_ids=["INBOX"],
            snippet="Delivery Status Notification (Failure)",
        )
        self.threads[dsn_thread] = [dsn_id]

    def _inject_reply(self, original: _StoredMessage) -> None:
        raw = _synthesize_reply(original)
        reply_id = self._next_id("fakereply")
        # A reply lands in the SAME thread as the original message.
        self.messages[reply_id] = _StoredMessage(
            id=reply_id,
            thread_id=original.thread_id,
            to=self.from_account,
            subject=f"Re: {original.subject}",
            body="Thanks for reaching out — please send more details.",
            headers={},
            raw=raw,
            sent_at=original.sent_at + timedelta(hours=6),
            is_reply=True,
            from_addr=original.to,
            label_ids=["INBOX"],
            snippet="Thanks for reaching out — please send more details.",
        )
        self.threads[original.thread_id].append(reply_id)

    # ---- polling (mimics the real client's query semantics) -------------- #

    def list_messages(self, q: str, *, max_results: int = 100) -> list[GmailMessage]:
        """Support the daemon query used by ``poll_bounces``.

        Recognizes ``from:(mailer-daemon OR postmaster)`` (returns DSNs) as the
        one query the poller issues; any other query returns inbox messages.
        """
        want_daemon = "mailer-daemon" in q or "postmaster" in q
        out: list[GmailMessage] = []
        for m in self.messages.values():
            if want_daemon and not m.is_dsn:
                continue
            if not want_daemon and m.is_dsn:
                continue
            out.append(GmailMessage(id=m.id, thread_id=m.thread_id, snippet=m.snippet))
            if len(out) >= max_results:
                break
        return out

    def get_message(self, message_id: str, *, format: str = "raw") -> GmailMessage:
        m = self.messages[message_id]
        return GmailMessage(
            id=m.id,
            thread_id=m.thread_id,
            raw=m.raw if format == "raw" else None,
            label_ids=list(m.label_ids),
            snippet=m.snippet,
        )

    def list_thread_messages(self, thread_id: str) -> list[GmailMessage]:
        ids = self.threads.get(thread_id, [])
        out: list[GmailMessage] = []
        for mid in ids:
            m = self.messages[mid]
            out.append(
                GmailMessage(
                    id=m.id,
                    thread_id=thread_id,
                    label_ids=list(m.label_ids),
                    snippet=m.snippet,
                )
            )
        return out

    def modify_labels(
        self, message_id: str, *, add: list[str] | None = None, remove: list[str] | None = None
    ) -> None:
        m = self.messages.get(message_id)
        if m is None:
            return
        labels = set(m.label_ids)
        labels.update(add or [])
        labels.difference_update(remove or [])
        m.label_ids = sorted(labels)

    # ---- test / demo helpers --------------------------------------------- #

    def inject_bounce_for(self, message_id: str) -> None:
        """Force a DSN for a specific already-sent message (tests)."""
        original = self.messages.get(message_id)
        if original is not None and not original.is_dsn:
            self._inject_dsn(original)

    def inject_reply_for(self, message_id: str) -> None:
        original = self.messages.get(message_id)
        if original is not None:
            self._inject_reply(original)


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #


def _load_credentials(tenant_id: UUID, session: Session):
    """Build a lazy Google Credentials callable from the tenant's stored token."""
    from sqlalchemy import select

    from app.models import IntegrationCredential
    from app.security.crypto import get_cipher

    settings = get_settings()
    credential = session.scalars(
        select(IntegrationCredential).where(
            IntegrationCredential.tenant_id == tenant_id,
            IntegrationCredential.provider == GOOGLE_PROVIDER,
            IntegrationCredential.status == "active",
        )
    ).first()
    if credential is None:
        return None
    refresh_token = get_cipher().decrypt(credential.encrypted_secret_reference)
    scopes = list(credential.scopes) or settings.gmail_scopes.split()

    def _make():
        from google.oauth2.credentials import Credentials

        return Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=scopes,
        )

    return _make


def get_gmail_client(
    tenant_id: UUID,
    session: Session,
    from_account: str,
) -> GmailClient | FakeGmailClient:
    """Return the real or fake Gmail client for ``(tenant, from_account)``.

    Falls back to :class:`FakeGmailClient` in DEMO_MODE, without OAuth app
    config, or when the tenant has no active Google credential — mirroring the
    Sheets factory's real-vs-mock decision.
    """
    settings = get_settings()
    if settings.demo_mode:
        return FakeGmailClient.for_account(from_account, tenant_id)
    if not (settings.google_client_id and settings.google_client_secret):
        return FakeGmailClient.for_account(from_account, tenant_id)
    creds = _load_credentials(tenant_id, session)
    if creds is None:
        return FakeGmailClient.for_account(from_account, tenant_id)
    return GmailClient(creds, from_account=from_account)


def message_id_header(email_message_id: UUID | str) -> str:
    """Deterministic RFC 822 Message-ID for one EmailMessage (bounce matching)."""
    domain = _own_domain()
    return f"<lm-{email_message_id}@{domain}>"


def _own_domain() -> str:
    """The domain we stamp into our Message-IDs (from app_base_url)."""
    base = get_settings().app_base_url
    m = re.sub(r"^https?://", "", base).split("/")[0].split(":")[0]
    return m or "leadmine.local"
