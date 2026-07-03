# LeadMine AI

**Mine → Enrich → Validate → Sync to Sheets → Send → Monitor.**

LeadMine AI is an AI-driven B2B lead-mining platform. You point it at a place and
an industry; it **mines** companies from compliant data sources, **crawls** their
sites and **extracts** contacts, **enriches** the sparse ones, runs a multi-stage
email **validation** funnel, **syncs** everything into a 12-tab Google Sheet that
acts as the system of record, **sends** personalized outreach through Gmail, and
**monitors** bounces, opens, clicks and replies — closing the loop back into the
same sheet and database. Every source ships with a compliance posture, and gated
sources stay off until an admin signs off. The whole pipeline also runs in a fully
deterministic **demo mode** that needs no third-party keys and never touches the
network.

The frontend is a **premium dark UI** (Next.js App Router, 21 routes) tuned for a
near-black control-room aesthetic — deep `#050607 / #080A0D / #0B0F14` backgrounds,
posture-colored source chips, and live job/pipeline event streaming.

---

## Table of contents

1. [What it is](#1-what-it-is)
2. [Architecture](#2-architecture)
3. [Data sources & compliance postures](#3-data-sources--compliance-postures)
4. [Prerequisites & quick start](#4-prerequisites--quick-start)
5. [Configuration](#5-configuration)
6. [Testing](#6-testing)
7. [Compliance posture](#7-compliance-posture)
8. [Project structure](#8-project-structure)
9. [Implementation summary](#9-implementation-summary)
10. [Real vs demo adapters](#real-vs-demo-adapters)

---

## 1. What it is

A single tenant workspace runs mining **jobs**. A job walks a fixed pipeline of
stages (`app/constants.py::JobStage`):

```
resolving_location → discovering → deduping → crawling → extracting
   → enriching → validating → syncing → sales_ready → done
```

Each stage emits **Server-Sent Events** consumed live by the UI, and mirrors its
output into both PostgreSQL and a per-tenant **Google Sheet** (12 tabs). Verified,
non-suppressed contacts land in the `Sales_Ready_Leads` projection, which feeds
Gmail outreach **campaigns**; bounce/reply monitoring writes back status changes.

---

## 2. Architecture

**Backend** — FastAPI (async SQLAlchemy 2.x over Postgres) + Celery with **12
dedicated queues** on Redis + Celery Beat for periodic work (bounce polling,
audit flush). **Frontend** — Next.js (App Router, React Query, SSE). **System of
record** — Google Sheets v4, mirrored idempotently from Postgres by the sheet-sync
engine. **Adapter framework** — every external capability is an adapter with a
matched real + mock pair, resolved per-request by `app/adapters/registry.py`
(see [Real vs demo adapters](#real-vs-demo-adapters)).

```
                         ┌─────────────────────────────────────────────┐
   Next.js (dark UI)     │  FastAPI  /api/v1                            │
   21 routes ───SSE────► │  auth · jobs · companies · contacts ·        │
        │  REST          │  validation · sheets · campaigns · bounces · │
        ▼                │  templates · suppressions · exports ·        │
   React Query           │  dashboard · users · events(SSE)             │
                         └───────────────┬─────────────────────────────┘
                                         │ enqueue
                     ┌───────────────────▼───────────────────┐
                     │   Redis  ── 12 Celery queues ──────────│
                     │   google_maps · website_scrape ·       │
                     │   directory · facebook_signal ·        │
                     │   job_signal · enrichment · validation │
                     │   · spreadsheet_sync · campaign ·      │
                     │   bounce_check · export · audit        │
                     └───┬───────────────────────────────┬────┘
                         │ workers                        │ beat
      ┌──────────────────▼───────────┐         ┌──────────▼─────────┐
      │  Adapter registry (real|mock)│         │  PostgreSQL        │
      │  14 sources/providers        │◄───────►│  (source of truth) │
      └──────────────┬───────────────┘         └──────────┬─────────┘
                     │ official APIs / licensed / crawl               │ mirror
   Google Places ─ Website crawl ─ RocketReach ─ MillionVerifier      ▼
   ─ Groq ─ SERP ─ Gmail send/read      ┌──────────────────────────────┐
                                        │ Google Sheet — 12 tabs        │
                                        │ README · Mining_Jobs ·        │
                                        │ Companies · Contacts ·        │
                                        │ Email_Validation ·            │
                                        │ Sales_Ready_Leads ·           │
                                        │ Outreach_Queue · Campaigns ·  │
                                        │ Bounce_Log · Suppression_List │
                                        │ · Data_Source_Audit ·         │
                                        │ Audit_Log                     │
                                        └──────────────────────────────┘
```

**Pipeline (one job):**

```
   place + industry
        │
        ▼
  ┌───────────┐   ┌──────────┐   ┌──────────┐   ┌────────────┐
  │ DISCOVER  │─► │  DEDUPE  │─► │  CRAWL   │─► │  EXTRACT   │
  │ (sources) │   │ domain/  │   │ public   │   │ contacts + │
  └───────────┘   │ name/tel │   │ pages    │   │ evidence   │
                  └──────────┘   └──────────┘   └─────┬──────┘
                                                      ▼
  ┌───────────┐   ┌──────────────────────────┐   ┌──────────┐
  │  SEND +   │◄─ │        VALIDATE          │◄─ │  ENRICH  │
  │  MONITOR  │   │ syntax → disposable →     │   │ (fill    │
  │ (Gmail)   │   │ role → MX → LLM →         │   │ gaps)    │
  └─────┬─────┘   │ MillionVerifier          │   └──────────┘
        │         └────────────┬─────────────┘
        │                      ▼
        │              ┌───────────────┐
        └─────────────►│  SYNC → Sheet │  (Postgres = truth, Sheet = mirror)
                       └───────────────┘
```

---

## 3. Data sources & compliance postures

Eight mining sources + one directory source + three providers + Google Sheets sync
make up the **14 real-vs-mock adapters** wired into the registry. Postures and
gating come straight from the adapter cards (`app/adapters/mock/*`,
`app/adapters/sources/*`) and the gate flags in `app/adapters/registry.py`.

### Mining & signal sources

| Source | Posture | Access method | Default | What activates the real adapter |
| --- | --- | --- | --- | --- |
| **Google Maps** | 🟢 green | Official API (Places New + Geocoding) | **on** | `GOOGLE_MAPS_API_KEY` + `DEMO_MODE=false` |
| **Company Websites** | 🟢 green | Polite public HTTP crawl (2-tier) | **on** | no key — just `DEMO_MODE=false` |
| **Public Directories** | 🟢 green | Provider API | **on** | mock-only (open/licensed directory placeholder) |
| **Yellow Pages** | 🟠 amber | Licensed provider only | off | enable + sign-off + `ENABLE_COMPLIANCE_GATED_SOURCES` + tenant provider connection |
| **Clutch** | 🟠 amber | Licensed provider only | off | enable + sign-off + `ENABLE_COMPLIANCE_GATED_SOURCES` + tenant provider connection |
| **Facebook Pages & Hiring Signals** | 🟠 amber | Licensed provider (Graph Page token **or** SERP public-page/careers) | off | enable + sign-off + `ENABLE_FACEBOOK_SIGNALS` + a compliant access mode |
| **Google Jobs / SERP Jobs** | 🟠 amber* | SERP (approved provider) | off | `SERP_API_KEY` + enable + sign-off + `ENABLE_COMPLIANCE_GATED_SOURCES` |
| **Indeed** | 🔴 red | Approved hiring-signal provider only | off | enable + sign-off + `ENABLE_COMPLIANCE_GATED_SOURCES` + provider connection |
| **LinkedIn** | 🔴 red | Official/authorized connector only (**stub**) | off | official access — **never scrapes**; unavailable until configured |

\* The SERP-jobs **card** that supplies the gate posture (the mock) is **AMBER and
requires sign-off**, so this source is gated exactly like the other
compliance-gated sources. The real `SerpJobsAdapter` class is itself tagged green,
but it is only reached once the AMBER card's enable + sign-off +
`ENABLE_COMPLIANCE_GATED_SOURCES` gate passes and `SERP_API_KEY` resolves.

### Providers

| Provider | Purpose | What activates the real adapter |
| --- | --- | --- |
| **RocketReach** | Contact enrichment (fill missing email/title) | `ROCKETREACH_API_KEY` + `DEMO_MODE=false` |
| **MillionVerifier** | Deliverability verification | `MILLIONVERIFIER_API_KEY` + `DEMO_MODE=false` |
| **Groq** | LLM suspicious-email confidence scoring | `GROQ_API_KEY` + `DEMO_MODE=false` |

### System of record

| Integration | Purpose | What activates the real adapter |
| --- | --- | --- |
| **Google Sheets v4** | 12-tab mirror of the pipeline | `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` + per-tenant OAuth credential |

When any activation condition fails, the registry serves the deterministic **mock**
for that source — the job runs fully and never hits the network. Gated (amber/red)
sources that aren't enabled + signed-off + flagged-on resolve to `SourceUnavailable`;
the worker logs a **skipped** `SourceRun` and continues (graceful degradation).

---

## 4. Prerequisites & quick start

### Prerequisites (macOS)

- **Colima + Docker** — the container runtime for Postgres + Redis
  (`brew install colima docker docker-compose && colima start`)
- **uv** — Python 3.12 toolchain/runner (`brew install uv`)
- **Node.js 20+** — for the Next.js frontend (`brew install node`)

> All commands below are run from the repo root. Paths contain a space, so quote
> them in the shell: `cd "/Users/you/…/leadmine-ai"`.

### Quick start

```bash
# 0. Infra: Postgres + Redis (Colima/Docker)
make infra

# 1. Backend: install, migrate, seed the demo workspace
cd backend
uv sync
uv run alembic upgrade head
make seed            # or, from repo root: make migrate && make seed

# 2. Run the dev processes (each in its own terminal)
make api             # FastAPI on :8000
make worker          # Celery worker across all 12 queues
make beat            # Celery beat (periodic jobs)
make web             # Next.js on :3000
```

Or bring up the whole stack containerized (production parity):

```bash
make full            # docker compose --profile full up -d --build
```

Then open **http://localhost:3000** and click **"Dev Login (Demo)"**. This calls
`POST /api/v1/auth/dev-login`, which upserts the canonical demo tenant/admin
(`Demo Workspace` / `demo@leadmine.local`) so dev-login and the seed converge on a
single workspace. You land in the seeded Ahmedabad chartered-accountancy dataset
with a completed demo job, sales-ready leads, and a mirrored sheet.

---

## 5. Configuration

Copy the example env and fill it in — **never commit `.env`**:

```bash
cp .env.example .env
```

See **[`.env.example`](.env.example)** for the full annotated list. Key groups:

- **Core** — `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`
  (`openssl rand -hex 32`), `ENCRYPTION_KEY` (Fernet key — see the inline
  `.env.example` command), and `DEMO_MODE`.
- **Google** — `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI`
  for OAuth (Sheets + Gmail), and a **separate server** `GOOGLE_MAPS_API_KEY`
  restricted to Places API (New) + Geocoding. Full console runbook:
  **[`docs/GOOGLE_SETUP.md`](docs/GOOGLE_SETUP.md)**.
- **Providers** — `ROCKETREACH_API_KEY`, `MILLIONVERIFIER_API_KEY`, `GROQ_API_KEY`
  (+ `GROQ_MODEL`), and `SERP_PROVIDER` / `SERP_API_KEY`.
- **Object storage** (optional) — `S3_*`; exports fall back to local disk when empty.
- **Policy & gates** — send limits, LLM threshold, and the three compliance gate
  flags `ENABLE_FACEBOOK_SIGNALS` / `ENABLE_LINKEDIN_CONNECTOR` /
  `ENABLE_COMPLIANCE_GATED_SOURCES`.
- **Adapter mode** — `ADAPTER_MODE=auto|real|mock` plus per-source overrides
  (`SOURCE_GOOGLE_MAPS_MODE=real`, etc.).

**`DEMO_MODE`** is the master switch. `DEMO_MODE=true` (the default) forces **every**
adapter to its mock regardless of which keys are present — so the demo and
`verify-demo` are deterministic and offline. Set `DEMO_MODE=false` (and provide
keys) to activate real adapters.

**Verify provider keys** without running a job:

```bash
make smoke-keys      # bash scripts/smoke_keys.sh — pings each configured provider
```

**Crawler (optional Playwright tier):** the website crawler's Tier 1 uses `httpx`
and handles most static firm sites. Tier 2 (Playwright Chromium) is an optional
JS-rendered fallback and degrades gracefully when absent. To enable it:

```bash
cd backend && uv run playwright install chromium
```

---

## 6. Testing

```bash
make test              # full suite (unit + integration) — 418 tests
make test-unit         # unit only
make test-integration  # integration only
make verify-demo       # the 10 end-to-end acceptance checks (expect 10/10)
make lint              # ruff check + format --check
```

**`make verify-demo`** runs 10 acceptance checks against the seeded demo dataset
(all **offline**, mocks only):

1. pipeline ran to completion, 2. companies deduped, 3. contacts carry evidence
snippets, 4. every contact has a complete validation-stage chain, 5. sales-ready
projection is clean (verified, non-suppressed, non-tombstoned), 6. the sheet
mirror matches the DB, 7. funnel counts are internally consistent, 8. campaign
metrics reconcile, 9. **a gated source with no sign-off is skipped, not crashed**,
10. an export materializes real non-empty file rows.

**Offline vs live keys.** The entire test suite and `verify-demo` run **offline** —
real adapters are exercised by unit tests using `respx` / recorded JSON fixtures
(`tests/fixtures/*`, `tests/unit/test_*_real.py`), never a live network. Only an
actual end-to-end run against Google/RocketReach/MillionVerifier/Groq/SERP/Gmail
needs live keys and `DEMO_MODE=false`; use `make smoke-keys` to confirm those.

---

## 7. Compliance posture

Official APIs and licensed sources are preferred; scraping is allowed **only where
legal, permitted, and explicitly configured by an admin**.

- **Official-APIs-first.** Google Maps uses the Places API; enrichment/verification
  go through RocketReach/MillionVerifier; jobs signals go through an approved SERP
  provider; Facebook uses an authorized Graph Page token or public-page SERP.
- **Gated sources need admin sign-off.** Amber/red sources stay off until a tenant
  admin enables them **and** records a compliance sign-off on the `DataSourceConfig`
  row, **and** the corresponding global env flag is on. Any missing gate →
  `SourceUnavailable` → skipped, never a crash.
- **No LinkedIn / Facebook scraping — enforced by tests.** The `LinkedInAdapter` is
  a deliberate official-connector stub with **no HTTP client and no URL**;
  `FacebookSignalsAdapter` only touches Graph-Page or SERP hosts. This is proven by
  **`backend/tests/unit/test_adapter_compliance_guard.py`**
  (`test_no_real_adapter_targets_forbidden_social_endpoint`,
  `test_linkedin_adapter_has_no_http_client_and_no_url`,
  `test_facebook_only_uses_graph_page_and_serp_hosts`,
  `test_facebook_page_normaliser_rejects_non_public_page_urls`) with a non-vacuous
  negative-control test.
- **robots.txt** — the website crawler respects robots directives and applies
  per-domain rate limits and a page cap (`CRAWLER_MAX_PAGES_PER_DOMAIN`,
  `CRAWLER_PER_DOMAIN_DELAY_SECONDS`).
- **Suppression / opt-out** — a per-tenant `Suppression_List` (tab + API) removes
  contacts from sales-ready output and outreach; unsubscribes and spam complaints
  feed it automatically.
- **Data retention** — Google Places data is not cached beyond allowed retention;
  audit trails (`AuditLog`, `Data_Source_Audit`) and per-source raw event logging
  keep every source run accountable.

---

## 8. Project structure

```
leadmine-ai/
├── README.md                 · this file
├── Makefile                  · infra / dev / test / verify targets
├── docker-compose.yml        · postgres + redis (+ "full" app profile)
├── .env.example              · annotated configuration template
├── docs/
│   ├── GOOGLE_SETUP.md       · Google Cloud console runbook (OAuth + Maps)
│   └── DEPLOYMENT.md         · production deployment notes
├── backend/                  · FastAPI + Celery (uv, Python 3.12)
│   ├── app/
│   │   ├── main.py           · FastAPI app factory
│   │   ├── config.py         · Settings (env), adapter modes, gate flags
│   │   ├── constants.py      · enums, 12 queue names, demo identity, sheet vars
│   │   ├── deps.py           · get_async_session · get_current_user ·
│   │   │                       get_tenant_id · require(perm)
│   │   ├── db.py             · async engine/session
│   │   ├── models/           · SQLAlchemy: DataSourceConfig, ValidationRuleSet,
│   │   │                       CampaignSettings, IntegrationCredential,
│   │   │                       AuditLog, APIUsage, jobs, companies, contacts…
│   │   ├── schemas/          · Pydantic v2 request/response models
│   │   ├── api/              · routers aggregated at /api/v1 (router.py):
│   │   │                       auth · users · events(SSE) · jobs · companies ·
│   │   │                       contacts · validation · sheets · exports ·
│   │   │                       dashboard · campaigns · bounces · templates ·
│   │   │                       suppressions · health
│   │   ├── security/         · rbac.py (has_permission) · crypto.py
│   │   │                       (get_cipher, mask_secret)
│   │   ├── adapters/         · registry.py + base/ · sources/ (real) ·
│   │   │                       mock/ · enrichment/ · validation/ · llm/
│   │   ├── crawler/          · 2-tier website crawler (httpx + optional Playwright)
│   │   ├── pipeline/         · stage orchestration (discover→…→sales_ready)
│   │   ├── outreach/         · Gmail send + bounce/reply monitoring
│   │   ├── sheetsync/        · 12-tab Google Sheet engine (tabs.py, engine.py, client.py)
│   │   ├── services/         · domain services
│   │   ├── seeds/            · demo corpus (Ahmedabad CA firms)
│   │   └── workers/          · celery_app + 12-queue task modules
│   ├── scripts/              · seed_demo.py · verify_demo.py · smoke_keys.sh
│   ├── tests/                · unit/ + integration/ + fixtures/  (418 tests)
│   └── alembic/              · migrations
└── frontend/                 · Next.js App Router (premium dark UI, 21 routes)
    └── src/app/
        ├── (auth)/login      · dev-login + OAuth entry
        └── (app)/            · dashboard · jobs · results · companies ·
                                validation · sheets · campaigns · outreach ·
                                bounces · exports · settings (sources /
                                integrations / validation / users / audit)
```

---

## 9. Implementation summary

**What's built.** A complete Mine → Enrich → Validate → Sync → Send → Monitor
platform: 16 API router groups under `/api/v1`, a 12-queue Celery pipeline, a
14-adapter registry with matched real+mock pairs and key-driven activation, a
2-tier compliant website crawler, a 6-stage email validation funnel, a 12-tab
Google Sheets mirror as system of record, Gmail outreach with bounce/reply
monitoring, RBAC + encrypted integration credentials, and a premium dark Next.js
UI across 21 routes.

**Test status.** **418 backend tests green**; **`verify-demo` 10/10**; the frontend
builds (22 route entries). Real adapters are covered offline by `respx`/fixture
unit tests.

**25 acceptance criteria.**

- **Automated-verified (offline):** the demo pipeline running end-to-end, dedupe,
  contact evidence, the full validation-stage chain, the clean sales-ready
  projection, sheet-mirror consistency, funnel/campaign reconciliation, gated-source
  skip-without-sign-off (AC23), and export file materialization (AC17) — all proven
  by `verify-demo`'s 10 checks plus the 418-test suite (compliance guard, registry
  resolution, gated sources, per-adapter real tests).
- **Need live keys (structure/unit-tested; require keys for a live run):**
  real Google Places discovery, live website crawl, RocketReach enrichment,
  MillionVerifier verification, Groq scoring, SERP jobs, real Google Sheets writes,
  and Gmail send + bounce/reply polling. Confirm with `make smoke-keys` +
  `DEMO_MODE=false`.
- **Deferred:** the LinkedIn official connector is a compliant stub (no scraping) —
  live only once official/authorized access is configured; the additional
  enrichment provider is an interface placeholder.

**Known limitations.**

- **Consumer Gmail send limits** — a personal `@gmail.com` account caps at ~500
  sends/day; production outreach needs a Google **Workspace** account (see
  [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)).
- **OAuth testing-mode tokens** — while the Google OAuth consent screen is in
  "Testing", refresh tokens **expire after 7 days**; publish the app (or use an
  internal Workspace app) for durable tokens.
- **Opens / clicks need a public URL** — the tracking pixel and click redirects
  require a publicly reachable `APP_BASE_URL`; on `localhost` sends and bounces
  work but open/click tracking won't register.

---

## Real vs demo adapters

Every data source and provider ships as a matched pair: a **real** implementation
(live HTTP against Google, RocketReach, MillionVerifier, Groq, or a polite website
crawl) and a deterministic **mock**. The registry
(`backend/app/adapters/registry.py`) picks between them per request — you never
choose in code.

**Activation is key-driven.** A real adapter runs only when **all** of these hold:

1. `DEMO_MODE=false` (in demo mode every adapter is forced to its mock), and
2. `ADAPTER_MODE` is `auto` or `real` (not `mock`), and
3. the adapter's required credential resolves to a non-empty value in settings.

If any condition fails, the registry serves the mock. This means:

- **No key present** → mock. The pipeline still runs fully, deterministically,
  and **never touches the network**.
- **`DEMO_MODE=true`** → mock, always — regardless of which keys are set. The
  demo (`verify_demo`, seeded Ahmedabad dataset) is unaffected by real keys.
- **Key present + `DEMO_MODE=false`** → real adapter, activated for that call.

Credential mapping (env var → what it activates):

| Env var | Activates real | Falls back to |
| --- | --- | --- |
| `GOOGLE_MAPS_API_KEY` | Google Places (New) + Geocoding discovery | Mock Google Maps |
| `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` (+ tenant OAuth credential) | Google Sheets v4 sync | Fake in-memory sheet mirror |
| _(none)_ | Website crawler (polite public HTTP — no credential) | Mock company websites |
| `ROCKETREACH_API_KEY` | RocketReach contact enrichment | Mock enrichment |
| `MILLIONVERIFIER_API_KEY` | MillionVerifier email verification | Mock verifier |
| `GROQ_API_KEY` | Groq suspicious-email LLM scoring | Heuristic mock scorer |
| `SERP_API_KEY` | SERP jobs / Facebook public-page discovery | Mock signals |

The website crawler needs no credential; it goes real whenever `DEMO_MODE=false`
and `ADAPTER_MODE` allows. Gated (AMBER/RED) sources — LinkedIn, Indeed, Clutch,
Yellow Pages, SERP jobs, Facebook signals — additionally require per-tenant
enablement, compliance sign-off, and their global env flag; otherwise the
registry returns `SourceUnavailable` and the job logs a skipped source and
continues.

Per-source override for testing: `SOURCE_GOOGLE_MAPS_MODE=real` (etc.) forces one
source's mode independent of the global setting.

Resolution is proven end-to-end by
`backend/tests/unit/test_registry_resolution.py`, and every real adapter has
offline unit tests (respx / recorded JSON fixtures) that never hit a live
network.

### Website crawler: optional Playwright tier

The crawler's Tier 1 uses `httpx` and handles the static HTML that most firm
sites serve. **Tier 2 (Playwright Chromium)** is an *optional* fallback used only
when Tier-1 output looks empty or client-rendered. It degrades gracefully when
Playwright or its browser binary is absent. To enable JS-rendered fallback,
install the Chromium binary:

```bash
uv run playwright install chromium
```

Without it, the crawler still works — it simply skips Tier 2 and returns the
Tier-1 result.
