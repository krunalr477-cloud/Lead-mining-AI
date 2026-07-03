# LeadMine AI

AI-driven B2B lead mining: discover companies, crawl their sites, extract and
enrich contacts, validate emails, and mirror the pipeline into a 12-tab Google
Sheet — with a fully deterministic demo mode that runs end-to-end without any
third-party keys.

## Quick start

```bash
# Infra (Postgres + Redis)
docker compose up -d

# Backend (Python 3.12, uv)
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# Demo pipeline self-check (mocks only, no keys, no network)
uv run python -m scripts.verify_demo   # expect 8/8

# Tests
uv run pytest -q
```

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
