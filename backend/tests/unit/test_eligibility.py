"""Per-recipient eligibility unit tests (spec §25 HARD rule).

Runs against the live Postgres schema via ``sync_session_factory`` (same pattern
as ``test_sheet_sync``); each test builds an isolated tenant and rolls back.

Asserts only VERIFIED, non-suppressed, non-bounced, role-passing contacts are
targeted — the product must never send to (or surface) invalid emails.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.constants import CampaignStatus, FinalEmailStatus, MessageStatus
from app.db import sync_session_factory
from app.models import (
    Campaign,
    Company,
    Contact,
    EmailMessage,
    MiningJob,
    Suppression,
    Tenant,
    User,
)
from app.outreach.scheduler import EligibilityReason, plan_recipients

pytestmark = pytest.mark.integration


@pytest.fixture
def session() -> Iterator[Session]:
    s = sync_session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def tenant(session: Session) -> Tenant:
    t = Tenant(name=f"elig-{uuid.uuid4().hex[:8]}")
    session.add(t)
    session.flush()
    session.add(User(tenant_id=t.id, name="A", email=f"a-{t.id}@x.local", role="admin"))
    session.flush()
    return t


def _company(session: Session, tenant: Tenant) -> Company:
    c = Company(
        tenant_id=tenant.id,
        canonical_name="Acme",
        city="Ahmedabad",
        country="India",
        services=["Audit"],
    )
    session.add(c)
    session.flush()
    return c


def _contact(session, tenant, company, *, email, final, designation="Partner", job_id=None):
    ct = Contact(
        tenant_id=tenant.id,
        company_id=company.id,
        job_id=job_id,
        full_name="Asha Patel",
        first_name="Asha",
        last_name="Patel",
        designation=designation,
        role_category=designation,
        email=email,
        final_email_status=final,
        confidence_score=Decimal("0.9"),
    )
    session.add(ct)
    session.flush()
    return ct


def _campaign(session, tenant, *, job_id=None) -> Campaign:
    camp = Campaign(
        tenant_id=tenant.id,
        job_id=job_id,
        name="C",
        subject_template="Hi {{FirstName}}",
        body_template="Hello {{Company}}",
        from_account="sender@leadmine.local",
        status=CampaignStatus.DRAFT.value,
    )
    session.add(camp)
    session.flush()
    return camp


def _decisions_by_email(session, campaign):
    return {d.email: d for d in plan_recipients(session, campaign)}


def test_only_verified_targeted(session, tenant):
    company = _company(session, tenant)
    _contact(session, tenant, company, email="ok@acme.example", final=FinalEmailStatus.VERIFIED)
    _contact(
        session, tenant, company, email="bad@acme.example", final=FinalEmailStatus.INVALID_SYNTAX
    )
    _contact(
        session,
        tenant,
        company,
        email="review@acme.example",
        final=FinalEmailStatus.CATCH_ALL_REVIEW,
    )
    campaign = _campaign(session, tenant)

    decisions = _decisions_by_email(session, campaign)
    assert decisions["ok@acme.example"].eligible is True
    assert decisions["bad@acme.example"].eligible is False
    assert decisions["bad@acme.example"].reason == EligibilityReason.NOT_VERIFIED
    assert decisions["review@acme.example"].reason == EligibilityReason.NOT_VERIFIED
    eligible = [d for d in decisions.values() if d.eligible]
    assert [d.email for d in eligible] == ["ok@acme.example"]


def test_suppressed_email_excluded(session, tenant):
    company = _company(session, tenant)
    _contact(session, tenant, company, email="supp@acme.example", final=FinalEmailStatus.VERIFIED)
    session.add(
        Suppression(
            tenant_id=tenant.id,
            email="supp@acme.example",
            reason="prior bounce",
            source="bounce_parser",
            permanent=True,
        )
    )
    session.flush()
    campaign = _campaign(session, tenant)
    d = _decisions_by_email(session, campaign)["supp@acme.example"]
    assert d.eligible is False
    assert d.reason == EligibilityReason.SUPPRESSED


def test_suppressed_domain_excluded(session, tenant):
    company = _company(session, tenant)
    _contact(
        session, tenant, company, email="anyone@blocked.example", final=FinalEmailStatus.VERIFIED
    )
    session.add(
        Suppression(
            tenant_id=tenant.id,
            domain="blocked.example",
            reason="domain block",
            source="manual",
            permanent=True,
        )
    )
    session.flush()
    campaign = _campaign(session, tenant)
    d = _decisions_by_email(session, campaign)["anyone@blocked.example"]
    assert d.eligible is False
    assert d.reason == EligibilityReason.SUPPRESSED


def test_prior_hard_bounce_excluded(session, tenant):
    company = _company(session, tenant)
    _contact(
        session, tenant, company, email="bounced@acme.example", final=FinalEmailStatus.VERIFIED
    )
    prior = _campaign(session, tenant)
    session.add(
        EmailMessage(
            campaign_id=prior.id,
            to_email="bounced@acme.example",
            subject="x",
            body="y",
            status=MessageStatus.HARD_BOUNCE.value,
        )
    )
    session.flush()
    campaign = _campaign(session, tenant)
    d = _decisions_by_email(session, campaign)["bounced@acme.example"]
    assert d.eligible is False
    assert d.reason == EligibilityReason.ALREADY_BOUNCED


def test_prior_reply_excluded(session, tenant):
    company = _company(session, tenant)
    _contact(
        session, tenant, company, email="replied@acme.example", final=FinalEmailStatus.VERIFIED
    )
    prior = _campaign(session, tenant)
    session.add(
        EmailMessage(
            campaign_id=prior.id,
            to_email="replied@acme.example",
            subject="x",
            body="y",
            status=MessageStatus.REPLIED.value,
        )
    )
    session.flush()
    campaign = _campaign(session, tenant)
    d = _decisions_by_email(session, campaign)["replied@acme.example"]
    assert d.eligible is False
    assert d.reason == EligibilityReason.ALREADY_REPLIED


def test_role_include_and_exclude_filters(session, tenant):
    job = MiningJob(
        tenant_id=tenant.id,
        name="J",
        contact_roles=["Partner", "Founder"],
        exclude_keywords=["Intern", "HR"],
    )
    session.add(job)
    session.flush()
    company = _company(session, tenant)
    _contact(
        session,
        tenant,
        company,
        email="partner@acme.example",
        final=FinalEmailStatus.VERIFIED,
        designation="Managing Partner",
        job_id=job.id,
    )
    _contact(
        session,
        tenant,
        company,
        email="intern@acme.example",
        final=FinalEmailStatus.VERIFIED,
        designation="Summer Intern",
        job_id=job.id,
    )
    _contact(
        session,
        tenant,
        company,
        email="clerk@acme.example",
        final=FinalEmailStatus.VERIFIED,
        designation="Data Clerk",
        job_id=job.id,
    )
    campaign = _campaign(session, tenant, job_id=job.id)

    d = _decisions_by_email(session, campaign)
    assert d["partner@acme.example"].eligible is True
    assert d["intern@acme.example"].reason == EligibilityReason.EXCLUDED_KEYWORD
    assert d["clerk@acme.example"].reason == EligibilityReason.ROLE_FILTERED


def test_missing_email_not_eligible(session, tenant):
    company = _company(session, tenant)
    _contact(session, tenant, company, email="", final=FinalEmailStatus.VERIFIED)
    campaign = _campaign(session, tenant)
    decisions = plan_recipients(session, campaign)
    noemail = [d for d in decisions if d.reason == EligibilityReason.NO_EMAIL]
    assert len(noemail) == 1
