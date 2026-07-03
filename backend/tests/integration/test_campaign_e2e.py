"""Campaign end-to-end integration test (spec §13/§14).

Launches a small campaign against :class:`FakeGmailClient`, sends every message,
injects a DSN + a reply, polls bounces/replies, and asserts the full side-effect
set: Suppression + EmailMessage HARD_BOUNCE + tombstoned lead + sheet mirror
updates, and a REPLIED message.

Marker: ``integration`` (needs Postgres + Redis).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.google.gmail_client import FakeGmailClient
from app.constants import (
    CampaignStatus,
    FinalEmailStatus,
    MessageStatus,
)
from app.db import sync_session_factory
from app.models import (
    Campaign,
    Company,
    Contact,
    EmailMessage,
    SalesReadyLead,
    Suppression,
    Tenant,
    User,
)
from app.outreach.sender import send_email_message

pytestmark = pytest.mark.integration


@pytest.fixture
def session() -> Iterator[Session]:
    s = sync_session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture(autouse=True)
def _clear_fake_registry() -> Iterator[None]:
    FakeGmailClient.reset_registry()
    yield
    FakeGmailClient.reset_registry()


FROM_ACCOUNT = "sender@leadmine.local"


def _build_campaign(session: Session) -> tuple[Tenant, Campaign, list[Contact]]:
    tenant = Tenant(name=f"camp-e2e-{uuid.uuid4().hex[:8]}")
    session.add(tenant)
    session.flush()
    session.add(
        User(tenant_id=tenant.id, name="Admin", email=f"a-{tenant.id}@x.local", role="admin")
    )
    company = Company(
        tenant_id=tenant.id,
        canonical_name="Acme CA",
        city="Ahmedabad",
        country="India",
        services=["Audit"],
    )
    session.add(company)
    session.flush()

    contacts: list[Contact] = []
    for i in range(4):
        ct = Contact(
            tenant_id=tenant.id,
            company_id=company.id,
            full_name=f"Person {i}",
            first_name=f"Person{i}",
            last_name="X",
            designation="Partner",
            role_category="Partner",
            email=f"person{i}@acme.example",
            final_email_status=FinalEmailStatus.VERIFIED.value,
            confidence_score=Decimal("0.9"),
            sales_ready=True,
        )
        session.add(ct)
        session.flush()
        contacts.append(ct)
        # Matching sales-ready lead so the bounce can tombstone it.
        session.add(
            SalesReadyLead(
                tenant_id=tenant.id,
                contact_id=ct.id,
                company_id=company.id,
                company_name="Acme CA",
                contact_name=ct.full_name,
                email=ct.email,
                validation_status=FinalEmailStatus.VERIFIED.value,
            )
        )
    campaign = Campaign(
        tenant_id=tenant.id,
        name="E2E Campaign",
        subject_template="Audit help for {{Company}}",
        body_template="Hi {{FirstName}}, about {{Company}} in {{City}}.",
        from_account=FROM_ACCOUNT,
        rate_limit_per_hour=1000,
        rate_limit_per_day=1000,
        status=CampaignStatus.DRAFT.value,
    )
    session.add(campaign)
    session.flush()
    return tenant, campaign, contacts


def test_campaign_send_bounce_reply_e2e(session: Session) -> None:
    tenant, campaign, contacts = _build_campaign(session)
    session.commit()

    # 1. Schedule + eligibility re-check.
    from app.outreach.scheduler import schedule_campaign

    summary = schedule_campaign(session, campaign)
    campaign.status = CampaignStatus.SENDING.value
    session.commit()
    assert summary["recipient_count"] == 4

    messages = session.scalars(
        select(EmailMessage)
        .where(EmailMessage.campaign_id == campaign.id)
        .order_by(EmailMessage.to_email)
    ).all()
    assert len(messages) == 4
    # Strict render: subject/body carry no literal placeholders.
    for m in messages:
        assert "{{" not in m.subject and "{{" not in m.body

    # 2. Send them all through the Fake Gmail client.
    client = FakeGmailClient.for_account(FROM_ACCOUNT, tenant.id)
    for m in messages:
        send_email_message(session, m, client=client, enforce_rate_limit=False)
    session.commit()
    for m in messages:
        session.refresh(m)
        assert m.status == MessageStatus.SENT.value
        assert m.gmail_message_id is not None

    # 3. Deterministically inject a DSN for the first recipient and a reply for
    #    the second (independent of the Fake's hash-based auto injection).
    bounced_msg = messages[0]
    replied_msg = messages[1]
    client.inject_bounce_for(bounced_msg.gmail_message_id)
    client.inject_reply_for(replied_msg.gmail_message_id)

    # 4. Poll bounces -> parse, match by Message-ID, apply actions.
    from app.workers.tasks.bounce import poll_bounces, poll_replies

    bounce_result = poll_bounces.apply(
        kwargs={"tenant_id": str(tenant.id), "from_account": FROM_ACCOUNT}
    ).get()
    assert bounce_result["matched"] >= 1

    reply_result = poll_replies.apply(kwargs={"tenant_id": str(tenant.id)}).get()
    assert reply_result["replies"] >= 1

    session.expire_all()

    # 5. Bounced message -> HARD_BOUNCE + suppression + tombstone.
    bounced = session.get(EmailMessage, bounced_msg.id)
    assert bounced.status == MessageStatus.HARD_BOUNCE.value
    assert bounced.bounced_at is not None

    supp = session.scalar(
        select(Suppression).where(
            Suppression.tenant_id == tenant.id,
            func.lower(Suppression.email) == bounced.to_email.lower(),
        )
    )
    assert supp is not None and supp.permanent is True

    lead = session.scalar(
        select(SalesReadyLead).where(
            SalesReadyLead.tenant_id == tenant.id,
            func.lower(SalesReadyLead.email) == bounced.to_email.lower(),
        )
    )
    assert lead is not None and lead.tombstoned is True

    contact = session.get(Contact, bounced.contact_id)
    assert contact.final_email_status == FinalEmailStatus.SUPPRESSED.value
    assert contact.sales_ready is False

    # 6. Replied message -> REPLIED + ReplyEvent.
    replied = session.get(EmailMessage, replied_msg.id)
    assert replied.status == MessageStatus.REPLIED.value
    assert replied.replied_at is not None

    # 7. Sheets mirror reflects the bounce + suppression.
    from app.sheetsync.client import FakeSheetsClient

    mirror = FakeSheetsClient.load(tenant.id)
    supp_rows = mirror.tabs.get("Suppression_List", {}).get("rows", [])
    assert any(r.get("email", "").lower() == bounced.to_email.lower() for r in supp_rows)
    bounce_rows = mirror.tabs.get("Bounce_Log", {}).get("rows", [])
    assert any(r.get("email", "").lower() == bounced.to_email.lower() for r in bounce_rows)

    # Cleanup.
    session.delete(session.get(Tenant, tenant.id))
    session.commit()


def test_launch_refuses_without_verified(session: Session) -> None:
    """§25 guard: a campaign with no VERIFIED recipient schedules zero and the
    launch path must refuse."""
    tenant = Tenant(name=f"camp-empty-{uuid.uuid4().hex[:8]}")
    session.add(tenant)
    session.flush()
    company = Company(tenant_id=tenant.id, canonical_name="NoVerify", city="X", country="Y")
    session.add(company)
    session.flush()
    session.add(
        Contact(
            tenant_id=tenant.id,
            company_id=company.id,
            first_name="A",
            email="unverified@x.example",
            final_email_status=FinalEmailStatus.RISK_REVIEW.value,
        )
    )
    campaign = Campaign(
        tenant_id=tenant.id,
        name="Empty",
        subject_template="Hi {{FirstName}}",
        body_template="Hello",
        from_account=FROM_ACCOUNT,
        status=CampaignStatus.DRAFT.value,
    )
    session.add(campaign)
    session.commit()

    from app.outreach.scheduler import schedule_campaign

    summary = schedule_campaign(session, campaign)
    assert summary["recipient_count"] == 0
    assert (
        session.scalar(
            select(func.count())
            .select_from(EmailMessage)
            .where(EmailMessage.campaign_id == campaign.id)
        )
        == 0
    )

    session.rollback()
    session.delete(session.get(Tenant, tenant.id))
    session.commit()
