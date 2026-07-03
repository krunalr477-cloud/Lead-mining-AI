# LeadMine AI — Production Deployment

This covers taking LeadMine AI from the demo/dev setup (see the root
[`README.md`](../README.md)) to a real deployment: a Google **Workspace** identity
with proper email authentication, real object storage, managed secrets, and scaled
workers. Local dev commands assume paths are quoted (the repo path contains a
space).

---

## 1. Deployment topology (full container profile)

Day-to-day dev runs `api` / `worker` / `beat` / `web` natively. Production uses the
**`full`** docker-compose profile, which builds and runs every service against the
same Postgres + Redis:

```bash
docker compose --profile full up -d --build     # or: make full
```

Services in the profile (`docker-compose.yml`):

| Service | Build target | Notes |
| --- | --- | --- |
| `postgres` | `postgres:16-alpine` | volume `pgdata`; healthchecked |
| `redis` | `redis:7-alpine` | volume `redisdata`; healthchecked |
| `api` | `backend` → `api` | binds `127.0.0.1:8000`; **runs migrations** (`RUN_MIGRATIONS=1`) on start |
| `worker` | `backend` → `worker` | Celery across all 12 queues, `--concurrency=8` |
| `beat` | `backend` → `api` image | Celery Beat (bounce polling, audit flush) |
| `web` | `frontend` | binds `127.0.0.1:3000`; proxies `/api/*` to `api` via `LEADMINE_BACKEND_ORIGIN` |

**Migrations run in exactly one place.** Only `api` sets `RUN_MIGRATIONS=1` so its
entrypoint runs `alembic upgrade head`; `worker` and `beat` leave it unset so they
never race the schema. Keep this invariant if you split services onto separate
hosts — run migrations as a one-shot before rolling workers.

**Reverse proxy / TLS.** The `api` and `web` ports bind to loopback. Put a TLS
terminator (nginx, Caddy, or your platform's LB) in front of `web` on your public
domain, and set `APP_BASE_URL` / `FRONTEND_URL` to the public HTTPS URLs. The
browser talks only to `web`, which same-origin-proxies `/api/*` to `api` — so
auth cookies stay first-party.

---

## 2. Google Workspace + email authentication

The consumer-Gmail path is fine for the demo but not for production outreach.

- **Use a Google Workspace account**, not personal `@gmail.com`. Personal accounts
  cap at ~500 sends/day and have weaker sender reputation. Workspace raises limits
  (~2,000/day) and lets you authenticate the domain.
- **Publish the OAuth app** (or make it an **Internal** Workspace app). While the
  OAuth consent screen is in "Testing", refresh tokens **expire after 7 days** —
  outreach silently stops when they lapse. Publishing (or Internal) gives durable
  refresh tokens. Follow [`GOOGLE_SETUP.md`](GOOGLE_SETUP.md) for the console steps;
  in production set the redirect URI to your public `GOOGLE_REDIRECT_URI`.
- **Custom sending domain + SPF/DKIM/DMARC.** Send from a domain you control and
  authenticate it so mailbox providers trust you:
  - **SPF** — a TXT record authorizing Google to send for your domain, e.g.
    `v=spf1 include:_spf.google.com ~all`.
  - **DKIM** — generate the DKIM key in the Google Workspace Admin console
    (Apps → Gmail → Authenticate email), publish the provided `google._domainkey`
    TXT record, then turn on signing.
  - **DMARC** — publish a `_dmarc` TXT record, starting at
    `v=DMARC1; p=none; rua=mailto:dmarc@yourdomain` to monitor, then tightening to
    `quarantine`/`reject` once SPF+DKIM pass cleanly.
  Warm up the domain gradually and keep bounce/complaint rates low — the platform's
  suppression list and bounce monitoring exist to protect this reputation.
- **Opens / clicks need a public URL.** The tracking pixel and click redirects are
  served off `APP_BASE_URL`; on localhost they never register. In production set
  `APP_BASE_URL` to your public HTTPS origin so open/click tracking works.

---

## 3. Object storage (real S3)

Exports (`ExportTarget.FILE`) and any generated artifacts fall back to **local
disk** when the `S3_*` env is empty — fine for a single box, wrong for a scaled or
ephemeral deployment. Point them at real object storage:

```
S3_ENDPOINT=https://s3.<region>.amazonaws.com   # or a MinIO/R2 endpoint
S3_BUCKET=leadmine-exports
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
```

Use a dedicated bucket with least-privilege credentials (put/get/list on that
bucket only), enable server-side encryption, and set a lifecycle policy matching
your data-retention rules. With multiple API/worker replicas you **must** use
shared object storage — local-disk exports on one replica aren't visible to
another.

---

## 4. Secrets management

- **Never commit `.env`.** Generate secrets fresh per environment:
  - `JWT_SECRET` — `openssl rand -hex 32`
  - `ENCRYPTION_KEY` — a Fernet key (see the command in `.env.example`). This
    encrypts `IntegrationCredential.encrypted_secret_reference` at rest via
    `app/security/crypto.py` (`get_cipher`, `mask_secret`). **Rotating it
    invalidates existing stored credentials** — re-connect integrations after a
    rotation.
- Inject secrets from your platform's secret manager (AWS Secrets Manager, GCP
  Secret Manager, Vault, or the orchestrator's secret store) as env vars rather
  than baking them into images.
- Provider keys (`GOOGLE_MAPS_API_KEY`, `ROCKETREACH_API_KEY`,
  `MILLIONVERIFIER_API_KEY`, `GROQ_API_KEY`, `SERP_API_KEY`) belong in the secret
  store too. Restrict the Maps key to Places API (New) + Geocoding and to your
  server IPs.
- **Set `DEMO_MODE=false` and `ENVIRONMENT=production`** in production, otherwise
  every adapter is forced to its mock. Validate keys after deploy with
  `make smoke-keys`.

---

## 5. Scaling workers

The 12 Celery queues let you scale by workload rather than as one monolith.

- **Vertical:** raise `--concurrency` on the `worker` service (default 8 in the
  full profile). Match it to CPU and to provider rate limits — enrichment and
  validation are I/O-bound and tolerate higher concurrency; the crawler is
  deliberately polite (`CRAWLER_PER_DOMAIN_DELAY_SECONDS`) and should not be
  over-provisioned per domain.
- **Horizontal / dedicated pools:** run multiple `worker` replicas, and for hot
  paths give a queue its own worker with a targeted `-Q`. Example — a dedicated
  crawl pool and a dedicated validation pool:

  ```bash
  celery -A app.workers.celery_app worker -Q website_scrape_jobs --concurrency=4
  celery -A app.workers.celery_app worker -Q validation_jobs,enrichment_jobs --concurrency=12
  ```

  Keep at least one worker subscribed to **every** queue name (see
  `app/constants.py::QUEUES`) or those tasks will never drain.
- **Exactly one `beat`.** Run a single Celery Beat instance — multiple beats
  double-schedule periodic jobs (bounce polling, audit flush).
- **Redis** is the broker + result/SSE backend; give it enough memory and enable
  persistence (the compose `redisdata` volume). For HA use a managed Redis.
- **Postgres** is the source of truth; use a managed instance with automated
  backups and PITR. Scale API/worker replicas behind it, but run
  `alembic upgrade head` as a single migration step before rolling new workers.

---

## 6. Pre-flight checklist

- [ ] `DEMO_MODE=false`, `ENVIRONMENT=production`
- [ ] `JWT_SECRET` and `ENCRYPTION_KEY` generated and injected from a secret store
- [ ] Google OAuth app **published** (or Internal), production `GOOGLE_REDIRECT_URI` set
- [ ] Workspace sending domain with **SPF + DKIM + DMARC** verified
- [ ] `APP_BASE_URL` / `FRONTEND_URL` = public HTTPS origins (open/click tracking works)
- [ ] Real `S3_*` object storage configured
- [ ] Provider keys set and validated with `make smoke-keys`
- [ ] Migrations run once (`api` with `RUN_MIGRATIONS=1`, or a one-shot job)
- [ ] TLS terminator in front of `web`; `api`/`web` bound to loopback behind it
- [ ] Single `beat`; every queue in `QUEUES` covered by at least one worker
- [ ] `make test` green and `make verify-demo` 10/10 in CI before promotion
