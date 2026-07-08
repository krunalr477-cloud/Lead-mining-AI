"""Synchronous per-stage worker logic (spec §4 pipeline).

Each ``run_*`` function performs one stage's DB work for a job and is pure w.r.t.
the transport: it is called both by the inline runner (no broker) and by the
Celery task wrappers. Functions take an open ``Session`` + Redis client, mutate
rows, publish events, and return small summary dicts. They never commit — the
caller owns the transaction boundary (the inline runner commits per stage; a
Celery task commits at the end of its unit of work).

Determinism: all synthesized data is seeded from job_id / company_id / email via
the mock adapters, and every mock row is marked ``is_demo=True``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import String, func, select
from sqlalchemy import inspect as sa_inspect

from app.adapters.base import CompanyRef, DiscoveredCompany, ExtractionResult
from app.adapters.registry import get_registry
from app.constants import (
    EnrichmentStatus,
    FinalEmailStatus,
    JobStage,
    SourceName,
    SourceRunStatus,
    StageStatus,
)
from app.db import utcnow
from app.models import (
    Company,
    CompanySource,
    Contact,
    DataSourceConfig,
    EmailCandidate,
    HiringSignal,
    MiningJob,
    SalesReadyLead,
    Suppression,
    ValidationCheck,
)
from app.pipeline.dedupe import (
    SourceEvidence,
    company_dedupe_key,
    contact_dedupe_key,
    merge_company_evidence,
)
from app.pipeline.runtime import build_job_spec, drain_async_iter, load_rules, run_async
from app.pipeline.sales_ready import is_sales_ready, rank_key
from app.pipeline.validation import (
    check_disposable,
    check_syntax,
    decide,
    is_role_based,
)
from app.services.events import publish_event

if TYPE_CHECKING:
    import redis
    from sqlalchemy.orm import Session

__all__ = [
    "recompute_sales_ready_for_job",
    "run_discovery",
    "run_enrichment",
    "run_extraction",
    "run_sync",
    "run_validation_for_candidate",
    "sync_company_row",
    "sync_contact_row",
    "validate_all_pending",
]

# Sources that DISCOVER companies (yield rows). Others only deep-dive/extract.
_DISCOVERY_SOURCES = {
    SourceName.GOOGLE_MAPS,
    SourceName.DIRECTORIES,
    SourceName.YELLOW_PAGES,
    SourceName.CLUTCH,
    SourceName.INDEED,
    SourceName.LINKEDIN,
}


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _clamp_str_columns(obj) -> None:
    """Truncate over-length string fields to their VARCHAR limits before flush.

    Real crawled/enriched data is messy — a marketing paragraph mis-parsed as a
    job title, a very long address, a tracking-laden URL — and a single value that
    exceeds its column length aborts the whole task and stalls the job. Clamp
    defensively so one bad record never blocks the pipeline.
    """
    for col in sa_inspect(type(obj)).columns:
        length = getattr(col.type, "length", None)
        if isinstance(col.type, String) and length:
            val = getattr(obj, col.key, None)
            if isinstance(val, str) and len(val) > length:
                setattr(obj, col.key, val[:length])


def _source_configs(session: Session, tenant_id: uuid.UUID) -> dict[str, DataSourceConfig]:
    rows = session.scalars(
        select(DataSourceConfig).where(DataSourceConfig.tenant_id == tenant_id)
    ).all()
    return {r.source_name: r for r in rows}


# --------------------------------------------------------------------------- #
# Discovery + dedupe (RESOLVING_LOCATION -> DISCOVERING -> DEDUPING)
# --------------------------------------------------------------------------- #


def run_discovery(session: Session, redis_client: redis.Redis, job: MiningJob) -> dict:
    """Run every selected discovery source, normalize + dedupe into Company rows.

    Gated sources that cannot run log a SKIPPED SourceRun and are skipped (the job
    continues). Overlapping sightings merge into one Company + CompanySource
    evidence via the pure dedupe keys.
    """
    registry = get_registry()
    configs = _source_configs(session, job.tenant_id)
    spec = build_job_spec(job)

    selected = [s for s in (job.selected_sources or []) if s]
    # Company_websites/facebook/serp are extract-only; skip them in discovery.
    discovery_selected = [s for s in selected if _safe_source(s) in _DISCOVERY_SOURCES]
    if not discovery_selected:
        discovery_selected = [SourceName.GOOGLE_MAPS.value]

    # dedupe_key -> Company (in-memory index for this run, backed by DB lookups).
    index: dict[str, Company] = {}
    total_found = 0
    total_inserted = 0
    skipped_sources: list[str] = []

    for source_str in discovery_selected:
        name = _safe_source(source_str)
        if name is None:
            continue
        cfg = configs.get(source_str)
        resolved = registry.resolve_source(
            name,
            enabled=bool(cfg.enabled) if cfg else False,
            signed_off=bool(cfg and cfg.signoff_at is not None),
        )
        if not resolved.ok:
            # Log a SKIPPED SourceRun; the job continues (graceful degradation).
            session.add(
                _skipped_run(
                    job.id,
                    name.value,
                    resolved.unavailable.reason if resolved.unavailable else "unavailable",
                )
            )
            skipped_sources.append(name.value)
            publish_event(
                session,
                tenant_id=job.tenant_id,
                job_id=job.id,
                stage=JobStage.DISCOVERING,
                level="warning",
                message=f"Source {name.value} skipped: "
                f"{resolved.unavailable.reason if resolved.unavailable else 'unavailable'}",
            )
            continue

        adapter = resolved.adapter
        assert adapter is not None
        ctx = registry.build_context(
            session=session,
            redis_client=redis_client,
            tenant_id=job.tenant_id,
            job_id=job.id,
            adapter=adapter,
        )
        ctx.open()
        found = 0
        imported = 0
        for discovered in drain_async_iter(adapter.discover(spec, ctx)):
            found += 1
            total_found += 1
            company, created = _upsert_company(session, job, discovered, index)
            if created:
                imported += 1
                total_inserted += 1
        ctx.finalize(SourceRunStatus.COMPLETED, records_found=found, records_imported=imported)

    session.flush()
    publish_event(
        session,
        tenant_id=job.tenant_id,
        job_id=job.id,
        stage=JobStage.DEDUPING,
        message=f"Discovery complete: {total_found} sightings -> {total_inserted} unique companies"
        + (f" ({len(skipped_sources)} sources skipped)" if skipped_sources else ""),
        payload={"found": total_found, "unique": total_inserted, "skipped": skipped_sources},
    )
    return {"found": total_found, "unique": total_inserted, "skipped_sources": skipped_sources}


def _safe_source(source_str: str) -> SourceName | None:
    try:
        return SourceName(source_str)
    except ValueError:
        return None


def _skipped_run(job_id: uuid.UUID, source_name: str, reason: str):
    from app.models import SourceRun

    return SourceRun(
        job_id=job_id,
        source_name=source_name,
        access_method="mock",
        compliance_posture="red",
        status=SourceRunStatus.SKIPPED,
        error_message=reason,
        started_at=utcnow(),
        completed_at=utcnow(),
    )


def _upsert_company(
    session: Session,
    job: MiningJob,
    discovered: DiscoveredCompany,
    index: dict[str, Company],
) -> tuple[Company, bool]:
    """Insert or merge a discovered company. Returns (company, created?)."""
    key = company_dedupe_key(
        discovered.name, discovered.domain, discovered.phone, discovered.address
    )
    evidence = SourceEvidence(
        source_name=discovered.source_name,
        source_url=discovered.source_url,
        access_method="mock",
        compliance_posture=_posture_for(discovered.source_name),
    )

    existing = index.get(key) if key else None
    if existing is None and key:
        existing = session.scalar(
            select(Company).where(Company.tenant_id == job.tenant_id, Company.dedupe_key == key)
        )

    if existing is not None:
        # Merge evidence (fill-only); mark deduped.
        merge = merge_company_evidence(
            {"source_urls": list(existing.source_urls or [])},
            {"source_urls": [discovered.source_url] if discovered.source_url else []},
            evidence,
        )
        existing.source_urls = merge.merged_source_urls
        existing.dedupe_status = "merged"
        _add_company_source(session, existing, evidence, discovered)
        existing.compliance_posture = _worst_posture(
            existing.compliance_posture, evidence.compliance_posture
        )
        if key:
            index[key] = existing
        return existing, False

    company = Company(
        tenant_id=job.tenant_id,
        job_id=job.id,
        canonical_name=discovered.name,
        website=discovered.website,
        domain=discovered.domain,
        phone=discovered.phone,
        address=discovered.address,
        city=discovered.city,
        state=discovered.state,
        country=discovered.country,
        postal_code=discovered.postal_code,
        latitude=_dec(discovered.latitude),
        longitude=_dec(discovered.longitude),
        industry=discovered.industry,
        services=list(discovered.services or []),
        description=discovered.description,
        company_size=discovered.company_size,
        google_place_id=discovered.google_place_id,
        google_rating=_dec(discovered.google_rating),
        google_reviews=discovered.google_reviews,
        facebook_page_url=discovered.facebook_page_url,
        source_urls=[discovered.source_url] if discovered.source_url else [],
        dedupe_key=key,
        dedupe_status="unique",
        compliance_posture=evidence.compliance_posture,
        last_refreshed_at=utcnow(),
    )
    _clamp_str_columns(company)
    session.add(company)
    session.flush()
    _add_company_source(session, company, evidence, discovered)
    if key:
        index[key] = company
    return company, True


def _add_company_source(
    session: Session, company: Company, evidence: SourceEvidence, discovered: DiscoveredCompany
) -> None:
    session.add(
        CompanySource(
            company_id=company.id,
            source_name=evidence.source_name,
            source_url=evidence.source_url,
            access_method=evidence.access_method or "mock",
            compliance_posture=evidence.compliance_posture or "green",
            raw_payload=discovered.raw_payload or None,
        )
    )


_POSTURE_BY_SOURCE = {
    SourceName.GOOGLE_MAPS.value: "green",
    SourceName.COMPANY_WEBSITES.value: "green",
    SourceName.DIRECTORIES.value: "green",
    SourceName.YELLOW_PAGES.value: "amber",
    SourceName.CLUTCH.value: "amber",
    SourceName.FACEBOOK_SIGNALS.value: "amber",
    SourceName.SERP_JOBS.value: "amber",
    SourceName.INDEED.value: "red",
    SourceName.LINKEDIN.value: "red",
}
_POSTURE_RANK = {"green": 0, "amber": 1, "red": 2}


def _posture_for(source_name: str) -> str:
    return _POSTURE_BY_SOURCE.get(source_name, "green")


def _worst_posture(a: str | None, b: str | None) -> str:
    ra = _POSTURE_RANK.get(a or "green", 0)
    rb = _POSTURE_RANK.get(b or "green", 0)
    return a if ra >= rb else b  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Extraction (CRAWLING + EXTRACTING) — one company at a time
# --------------------------------------------------------------------------- #


def run_extraction(
    session: Session, redis_client: redis.Redis, job: MiningJob, company: Company
) -> dict:
    """Deep-dive one company: crawl website + hiring-signal sources, insert
    Contacts/EmailCandidates/HiringSignals with contact dedupe."""
    registry = get_registry()
    configs = _source_configs(session, job.tenant_id)
    ref = CompanyRef(
        company_id=company.id,
        name=company.canonical_name,
        website=company.website,
        domain=company.domain,
        city=company.city,
        country=company.country,
    )

    # company_websites always runs (GREEN). Optional signal sources run if enabled.
    extract_sources = [SourceName.COMPANY_WEBSITES]
    for opt in (SourceName.FACEBOOK_SIGNALS, SourceName.SERP_JOBS):
        if opt.value in (job.selected_sources or []):
            extract_sources.append(opt)

    contacts_added = 0
    emails_added = 0
    signals_added = 0

    for name in extract_sources:
        cfg = configs.get(name.value)
        resolved = registry.resolve_source(
            name,
            enabled=bool(cfg.enabled) if cfg else False,
            signed_off=bool(cfg and cfg.signoff_at is not None),
        )
        if not resolved.ok:
            continue
        adapter = resolved.adapter
        assert adapter is not None
        ctx = registry.build_context(
            session=session,
            redis_client=redis_client,
            tenant_id=job.tenant_id,
            job_id=job.id,
            adapter=adapter,
        )
        ctx.open()
        result: ExtractionResult = run_async(adapter.extract(ref, ctx))
        c_add, e_add = _apply_contacts(session, job, company, result, adapter.name.value)
        contacts_added += c_add
        emails_added += e_add
        signals_added += _apply_signals(session, company, result)
        if result.website_status and name == SourceName.COMPANY_WEBSITES:
            company.website_status = result.website_status
        ctx.finalize(
            SourceRunStatus.COMPLETED, records_found=c_add + signals_added, records_imported=c_add
        )

    if signals_added:
        company.hiring_signal_status = "signals_found"
    company.last_refreshed_at = utcnow()
    session.flush()
    return {"contacts": contacts_added, "emails": emails_added, "signals": signals_added}


def _apply_contacts(
    session: Session, job: MiningJob, company: Company, result: ExtractionResult, source: str
) -> tuple[int, int]:
    contacts_added = 0
    emails_added = 0
    # In-memory dedupe of contacts within this company for this extraction.
    existing_contacts = session.scalars(
        select(Contact).where(Contact.company_id == company.id)
    ).all()
    by_key: dict[str, Contact] = {}
    for ct in existing_contacts:
        ckey = contact_dedupe_key(ct.email, ct.full_name, str(company.id))
        if ckey:
            by_key[ckey] = ct

    for ec in result.contacts:
        ckey = contact_dedupe_key(ec.email, ec.full_name, str(company.id))
        contact = by_key.get(ckey) if ckey else None
        if contact is None:
            contact = Contact(
                tenant_id=job.tenant_id,
                job_id=job.id,
                company_id=company.id,
                full_name=ec.full_name,
                first_name=ec.first_name,
                last_name=ec.last_name,
                designation=ec.designation,
                department=ec.department,
                seniority=ec.seniority,
                role_category=ec.role_category,
                email=ec.email,
                phone=ec.phone,
                linkedin_url=ec.linkedin_url,
                facebook_url=ec.facebook_url,
                source_page=ec.source_page,
                source_type=ec.source_type or source,
                confidence_score=_dec(ec.confidence_score),
                primary_contact=False,
                enrichment_status=(
                    EnrichmentStatus.NOT_NEEDED if ec.email else EnrichmentStatus.PENDING
                ),
            )
            _clamp_str_columns(contact)
            session.add(contact)
            session.flush()
            contacts_added += 1
            if ckey:
                by_key[ckey] = contact
        else:
            # Fill-only merge of scalar fields.
            for attr in (
                "designation",
                "department",
                "seniority",
                "role_category",
                "linkedin_url",
                "phone",
            ):
                if getattr(contact, attr) in (None, "") and getattr(ec, attr):
                    setattr(contact, attr, getattr(ec, attr))
            _clamp_str_columns(contact)

        if ec.email:
            emails_added += _add_email_candidate(session, contact, ec.email, source)

    # Mark the highest-confidence contact as the company's primary contact.
    _designate_primary(session, company)
    return contacts_added, emails_added


def _add_email_candidate(session: Session, contact: Contact, email: str, source: str) -> int:
    email = email.strip().lower()
    existing = session.scalar(
        select(EmailCandidate).where(
            EmailCandidate.contact_id == contact.id,
            func.lower(EmailCandidate.email) == email,
        )
    )
    if existing is not None:
        return 0
    session.add(EmailCandidate(contact_id=contact.id, email=email, source=source, status="pending"))
    if not contact.email:
        contact.email = email
    session.flush()
    return 1


def _designate_primary(session: Session, company: Company) -> None:
    contacts = session.scalars(select(Contact).where(Contact.company_id == company.id)).all()
    if not contacts:
        return
    ranked = sorted(
        contacts,
        key=lambda c: rank_key(
            {
                "primary_contact": c.primary_contact,
                "confidence_score": c.confidence_score,
                "role_category": c.role_category,
                "seniority": c.seniority,
                "designation": c.designation,
                "last_verified_at": c.last_verified_at,
            }
        ),
        reverse=True,
    )
    for i, c in enumerate(ranked):
        c.primary_contact = i == 0


def _apply_signals(session: Session, company: Company, result: ExtractionResult) -> int:
    added = 0
    for sig in result.hiring_signals:
        exists = session.scalar(
            select(HiringSignal).where(
                HiringSignal.company_id == company.id,
                HiringSignal.source == sig.source,
                HiringSignal.job_title == sig.job_title,
            )
        )
        if exists is not None:
            continue
        session.add(
            HiringSignal(
                company_id=company.id,
                source=sig.source,
                source_url=sig.source_url,
                job_title=sig.job_title,
                location=sig.location,
                posted_at=sig.posted_at,
                description_excerpt=sig.description_excerpt,
                signal_type=sig.signal_type,
                confidence_score=_dec(sig.confidence_score),
            )
        )
        added += 1
    session.flush()
    return added


# --------------------------------------------------------------------------- #
# Enrichment (ENRICHING) — one contact at a time
# --------------------------------------------------------------------------- #


def run_enrichment(
    session: Session, redis_client: redis.Redis, job: MiningJob, contact: Contact
) -> dict:
    """Enrich a contact missing an email via the enrichment provider. Never
    overwrites a higher-confidence value."""
    registry = get_registry()
    if contact.email:
        contact.enrichment_status = EnrichmentStatus.NOT_NEEDED
        return {"enriched": 0}

    adapter = registry.enrichment_adapter()
    # Build a context bound to the google_maps card slot for audit/usage. Use a
    # synthetic adapter card via the company_websites adapter posture (GREEN).
    from app.adapters.mock.company_websites import MockCompanyWebsitesAdapter

    ctx = registry.build_context(
        session=session,
        redis_client=redis_client,
        tenant_id=job.tenant_id,
        job_id=job.id,
        adapter=MockCompanyWebsitesAdapter(),
    )
    ctx.open()
    company = session.get(Company, contact.company_id)
    results = run_async(
        adapter.enrich(
            company_name=company.canonical_name if company else "",
            domain=company.domain if company else None,
            website=company.website if company else None,
            person_name=contact.full_name,
            designation=contact.designation,
            location=contact.city
            if hasattr(contact, "city")
            else (company.city if company else None),
            ctx=ctx,
        )
    )
    enriched = 0
    for ec in results:
        if ec.email:
            contact.email = ec.email
            contact.enrichment_status = EnrichmentStatus.ENRICHED
            contact.enrichment_provider = adapter.provider
            new_conf = ec.confidence_score
            if (
                contact.confidence_score is None
                or Decimal(str(new_conf)) > contact.confidence_score
            ):
                contact.confidence_score = _dec(new_conf)
            _add_email_candidate(session, contact, ec.email, adapter.provider)
            enriched += 1
            break
    if enriched == 0:
        contact.enrichment_status = EnrichmentStatus.NO_RESULT
    ctx.finalize(SourceRunStatus.COMPLETED, records_found=len(results), records_imported=enriched)
    session.flush()
    return {"enriched": enriched}


# --------------------------------------------------------------------------- #
# Validation (VALIDATING) — one email candidate at a time
# --------------------------------------------------------------------------- #


def validate_all_pending(session: Session, redis_client: redis.Redis, job: MiningJob) -> dict:
    """Validate every email candidate for the job (inline path)."""
    candidates = session.scalars(
        select(EmailCandidate)
        .join(Contact, EmailCandidate.contact_id == Contact.id)
        .where(Contact.job_id == job.id)
    ).all()
    validated = 0
    for cand in candidates:
        run_validation_for_candidate(session, redis_client, job, cand)
        validated += 1
    return {"validated": validated}


def run_validation_for_candidate(
    session: Session, redis_client: redis.Redis, job: MiningJob, candidate: EmailCandidate
) -> ValidationCheck:
    """Run all six stages for one email candidate, write ValidationCheck, and set
    the owning Contact.final_email_status."""
    registry = get_registry()
    rules = load_rules(session, job.tenant_id)
    contact = session.get(Contact, candidate.contact_id)
    email = candidate.email.strip().lower()
    domain = email.rsplit("@", 1)[1] if "@" in email else ""

    # Stage 1-3 (pure).
    syntax_ok = check_syntax(email)
    disposable_hit = check_disposable(email)
    role_hit = is_role_based(email, rules.role_keywords)

    # Stage 4 MX — mock mode never hits the network for a demo domain; treat as
    # PASS when syntax is ok (real DNS lands with the real adapter). A retryable
    # DNS failure would raise ValidationTransient in the real path.
    if not syntax_ok:
        mx_status = StageStatus.SKIPPED
        mx_detail = "skipped (syntax failed)"
    else:
        mx_status, mx_detail = _mx_for(domain)

    # Stage 5 LLM + Stage 6 verifier via the mock providers (skip on hard fail).
    llm_score: float | None = None
    llm_reason: str | None = None
    mv_status = None
    mv_payload: dict = {}
    hard_failed = (
        (not syntax_ok)
        or disposable_hit
        or (role_hit and not rules.allow_role_based)
        or (mx_status == StageStatus.FAIL)
    )
    ctx = registry.build_context(
        session=session,
        redis_client=redis_client,
        tenant_id=job.tenant_id,
        job_id=job.id,
        adapter=registry.adapter_card(SourceName.COMPANY_WEBSITES),
    )
    ctx.open()
    if not hard_failed:
        scored = run_async(registry.scorer_adapter().score([email], ctx))
        if scored:
            _, llm_score, llm_reason = scored[0]
        raw_status, mv_payload = run_async(registry.verifier_adapter().verify(email, ctx))
        from app.constants import MillionVerifierStatus

        mv_status = MillionVerifierStatus(raw_status)
    ctx.finalize(SourceRunStatus.COMPLETED, records_found=1, records_imported=1)

    suppressed = _is_suppressed(session, job.tenant_id, email, domain)

    from app.constants import MillionVerifierStatus as _MV

    final_status, final_reason = decide(
        syntax_ok=syntax_ok,
        disposable_ok=not disposable_hit,
        role_based=role_hit,
        mx_status=mx_status,
        llm_score=llm_score,
        mv_status=mv_status,
        suppressed=suppressed,
        rules=rules,
    )

    check = ValidationCheck(
        email_candidate_id=candidate.id,
        contact_id=candidate.contact_id,
        company_id=contact.company_id if contact else None,
        syntax_status=StageStatus.PASS if syntax_ok else StageStatus.FAIL,
        disposable_status=StageStatus.FAIL if disposable_hit else StageStatus.PASS,
        role_based_status=StageStatus.FAIL if role_hit else StageStatus.PASS,
        mx_status=mx_status,
        llm_score=_dec(llm_score),
        llm_reason=llm_reason,
        millionverifier_status=(mv_status.value if isinstance(mv_status, _MV) else None),
        final_status=final_status,
        final_reason=final_reason,
        raw_result_json=mv_payload or None,
        verified_at=utcnow() if final_status == FinalEmailStatus.VERIFIED else None,
    )
    session.add(check)

    candidate.status = final_status.value
    if contact is not None:
        contact.final_email_status = final_status
        if final_status == FinalEmailStatus.VERIFIED:
            contact.last_verified_at = utcnow()
            if not contact.email:
                contact.email = email
    session.flush()
    return check


def _mx_for(domain: str) -> tuple[StageStatus, str]:
    """MX result for the demo. Disposable/obviously-dead domains fail; everything
    else passes (real DNS lookups happen only with the real adapter)."""
    dead = {"tempmail.com", "yopmail.com", "guerrillamail.com", "mailinator.com"}
    if not domain:
        return StageStatus.FAIL, "empty domain"
    if domain in dead:
        return StageStatus.FAIL, "no MX (disposable)"
    return StageStatus.PASS, "MX present (demo)"


def _is_suppressed(session: Session, tenant_id: uuid.UUID, email: str, domain: str) -> bool:
    row = session.scalar(
        select(Suppression.id).where(
            Suppression.tenant_id == tenant_id,
            (func.lower(Suppression.email) == email) | (func.lower(Suppression.domain) == domain),
        )
    )
    return row is not None


# --------------------------------------------------------------------------- #
# Sales-ready (SALES_READY)
# --------------------------------------------------------------------------- #


def recompute_sales_ready_for_job(session: Session, job: MiningJob) -> dict:
    """Materialize/tombstone SalesReadyLead rows for a job and rank them."""
    contacts = session.scalars(select(Contact).where(Contact.job_id == job.id)).all()
    existing = {
        lead.contact_id: lead
        for lead in session.scalars(
            select(SalesReadyLead).where(SalesReadyLead.job_id == job.id)
        ).all()
    }

    ready: list[tuple[Contact, Company | None]] = []
    for ct in contacts:
        eligible = is_sales_ready(ct.final_email_status)
        lead = existing.get(ct.id)
        if not eligible:
            ct.sales_ready = False
            if lead is not None and not lead.tombstoned:
                lead.tombstoned = True
            continue
        ct.sales_ready = True
        company = session.get(Company, ct.company_id)
        ready.append((ct, company))

    # Rank the eligible set (best leads first) for a stable ``rank`` column.
    ready.sort(
        key=lambda pair: rank_key(
            {
                "primary_contact": pair[0].primary_contact,
                "confidence_score": pair[0].confidence_score,
                "role_category": pair[0].role_category,
                "seniority": pair[0].seniority,
                "designation": pair[0].designation,
                "last_verified_at": pair[0].last_verified_at,
            }
        ),
        reverse=True,
    )

    materialized = 0
    for rank, (ct, company) in enumerate(ready, start=1):
        lead = existing.get(ct.id)
        source_summary = (
            ", ".join(sorted({s.source_name for s in company.sources})) if company else ""
        )
        fields = {
            "tenant_id": job.tenant_id,
            "job_id": job.id,
            "contact_id": ct.id,
            "company_id": ct.company_id,
            "company_name": company.canonical_name if company else "",
            "website": company.website if company else None,
            "city": company.city if company else None,
            "state": company.state if company else None,
            "country": company.country if company else None,
            "contact_name": ct.full_name,
            "designation": ct.designation,
            "email": ct.email or "",
            "phone": ct.phone or (company.phone if company else None),
            "services": list(company.services or []) if company else [],
            "source_summary": source_summary,
            "validation_status": ct.final_email_status,
            "confidence_score": ct.confidence_score,
            "last_verified_at": ct.last_verified_at,
            "rank": rank,
            "tombstoned": False,
        }
        if lead is None:
            lead = SalesReadyLead(**fields)
            session.add(lead)
            materialized += 1
        else:
            for k, v in fields.items():
                setattr(lead, k, v)
    session.flush()
    return {"sales_ready": len(ready), "materialized": materialized}


# --------------------------------------------------------------------------- #
# Sheet-sync helpers (SYNCING) — enqueue upserts for a row
# --------------------------------------------------------------------------- #


def sync_company_row(session: Session, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
    _enqueue(session, tenant_id, "Companies", str(company_id))


def sync_contact_row(session: Session, tenant_id: uuid.UUID, contact_id: uuid.UUID) -> None:
    _enqueue(session, tenant_id, "Contacts", str(contact_id))


def _enqueue(session: Session, tenant_id: uuid.UUID, tab: str, row_key: str) -> None:
    # enqueue_upsert is DB-only (no client I/O), so any client works; use the
    # non-persisting Fake to avoid disk writes and credential lookups.
    from app.sheetsync.client import FakeSheetsClient
    from app.sheetsync.engine import SheetSyncEngine

    engine = SheetSyncEngine(session, FakeSheetsClient(tenant_id, persist=False))
    engine.enqueue_upsert(session, tenant_id, tab, row_key)


def run_sync(session: Session, tenant_id: uuid.UUID) -> dict:
    """Set up the spreadsheet (idempotent) and flush every DB-backed tab."""
    from app.sheetsync.engine import SheetSyncEngine
    from app.sheetsync.factory import get_sheets_client

    client = get_sheets_client(tenant_id, session)
    engine = SheetSyncEngine(session, client)
    engine.setup_spreadsheet(tenant_id)
    results = engine.flush_all(tenant_id)

    tenant = session.get(_tenant_model(), tenant_id)
    if tenant is not None and client.spreadsheet_id:
        tenant.google_spreadsheet_id = client.spreadsheet_id
    session.flush()
    return {
        "tabs": len(results),
        "appended": sum(r.appended for r in results),
        "updated": sum(r.updated for r in results),
    }


def _tenant_model():
    from app.models import Tenant

    return Tenant
