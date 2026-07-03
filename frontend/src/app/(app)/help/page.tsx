"use client";

import { useMemo, useState, type ReactNode } from "react";
import {
  Search,
  Rocket,
  Plug,
  Pickaxe,
  ShieldCheck,
  Send,
  LifeBuoy,
  ExternalLink,
  KeyRound,
} from "lucide-react";
import { Panel, PanelHeader, PanelSection } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { StatusChip } from "@/components/ui/StatusChip";
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from "@/components/ui/Accordion";
import { cn } from "@/lib/cn";

/* -------------------------------------------------------------------------- */
/* Content model                                                              */
/* -------------------------------------------------------------------------- */

interface FaqItem {
  id: string;
  q: string;
  /** Rendered answer. */
  a: ReactNode;
  /** Plain-text blob used for the client-side search filter. */
  text: string;
}

interface HelpSection {
  id: string;
  label: string;
  title: string;
  icon: typeof Rocket;
  blurb: string;
  items: FaqItem[];
}

/** A labeled external link that opens in a new tab. */
function Ext({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-accent underline-offset-2 hover:underline lm-focus"
    >
      {children}
      <ExternalLink className="size-3" aria-hidden />
    </a>
  );
}

/** Inline mono token for env vars, paths, commands. */
function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded-[4px] border border-border bg-panel-strong px-1 py-0.5 font-mono text-[12px] text-ink">
      {children}
    </code>
  );
}

/** In-app route pointer, e.g. Settings → Integrations. */
function Path({ children }: { children: ReactNode }) {
  return <span className="font-medium text-ink">{children}</span>;
}

/* --- Provider setup cards (mirror the real /integrations catalog) ---------- */

interface ProviderGuide {
  provider: string;
  label: string;
  powers: string;
  whereToGet: ReactNode;
  addSteps: ReactNode;
  /** Search blob. */
  text: string;
}

const PROVIDER_GUIDES: ProviderGuide[] = [
  {
    provider: "google_oauth",
    label: "Google OAuth",
    powers:
      "Sign-in with Google, plus the tenant's Sheets and Gmail authorization. Everything Google-facing rides on this consent.",
    whereToGet: (
      <>
        In the{" "}
        <Ext href="https://console.cloud.google.com/auth/clients">
          Google Cloud Console → Clients
        </Ext>
        , create a <strong>Web application</strong> OAuth client (see{" "}
        <Code>docs/GOOGLE_SETUP.md</Code>). Set the authorized redirect URI to{" "}
        <Code>http://localhost:8000/api/v1/auth/google/callback</Code>{" "}
        byte-for-byte, then copy the Client ID and Client Secret.
      </>
    ),
    addSteps: (
      <>
        Paste the Client ID and Secret under{" "}
        <Path>Settings → Integrations → Google OAuth → Add key</Path> (or set{" "}
        <Code>GOOGLE_CLIENT_ID</Code> / <Code>GOOGLE_CLIENT_SECRET</Code> in{" "}
        <Code>.env</Code>), then <Path>Test</Path>. Until this is set, the login
        page's &ldquo;Continue with Google&rdquo; button returns a{" "}
        <Code>503 Google OAuth not configured</Code>.
      </>
    ),
    text: "google oauth sign-in consent client id secret redirect uri callback 503 not configured",
  },
  {
    provider: "google_maps",
    label: "Google Maps",
    powers:
      "Company discovery via Places API (New) and Geocoding — turning a place + industry into candidate firms — plus the map render in the job UI.",
    whereToGet: (
      <>
        Two separate keys are mandatory (see <Code>docs/GOOGLE_SETUP.md</Code>).{" "}
        <strong>Server key:</strong> in{" "}
        <Ext href="https://console.cloud.google.com/apis/credentials">
          APIs &amp; Credentials
        </Ext>{" "}
        create an API key restricted to <strong>Places API (New)</strong> +{" "}
        <strong>Geocoding API</strong>, no application restriction.{" "}
        <strong>Browser key:</strong> a second key restricted by website to{" "}
        <Code>http://localhost:3000/*</Code> and to{" "}
        <strong>Maps JavaScript API</strong> only.
      </>
    ),
    addSteps: (
      <>
        Server key → <Code>GOOGLE_MAPS_API_KEY</Code> (in <Code>.env</Code>) or{" "}
        <Path>Settings → Integrations → Google Maps → Add key</Path>. Browser key
        → <Code>NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY</Code> in{" "}
        <Code>frontend/.env.local</Code> (it ships to the browser to render the
        map, so it must be the referrer-restricted one — never the server key).
      </>
    ),
    text: "google maps places geocoding server key browser key NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY maps javascript api two keys discovery",
  },
  {
    provider: "sheets",
    label: "Google Sheets",
    powers:
      "The sales-facing system of record. Every stage mirrors into a per-tenant 12-tab spreadsheet the sync engine keeps idempotent with Postgres.",
    whereToGet: (
      <>
        Enable the{" "}
        <Ext href="https://console.cloud.google.com/apis/library/sheets.googleapis.com">
          Google Sheets API
        </Ext>{" "}
        in the same project, and add the{" "}
        <Code>https://www.googleapis.com/auth/spreadsheets</Code> scope on the
        OAuth consent screen. Authorization flows through Google OAuth — there is
        no separate API key.
      </>
    ),
    addSteps: (
      <>
        No key to paste: once Google OAuth is connected and the spreadsheets
        scope is granted, Sheets goes <StatusChip status="live" label="Live" />{" "}
        automatically. Confirm the &ldquo;Sheets&rdquo; checkbox is ticked on the
        consent screen at first login.
      </>
    ),
    text: "google sheets system of record 12 tabs spreadsheets scope oauth mirror sync",
  },
  {
    provider: "gmail",
    label: "Gmail",
    powers:
      "Outreach sending and bounce/reply monitoring. Verified leads become campaign recipients; Gmail readonly polling closes the loop on bounces and replies.",
    whereToGet: (
      <>
        Enable the{" "}
        <Ext href="https://console.cloud.google.com/apis/library/gmail.googleapis.com">
          Gmail API
        </Ext>{" "}
        and add the <Code>gmail.send</Code> + <Code>gmail.readonly</Code> scopes
        on the consent screen. Also OAuth-based — no separate key.
      </>
    ),
    addSteps: (
      <>
        Connect Google OAuth with the Gmail scopes ticked; Gmail then reports{" "}
        <StatusChip status="live" label="Live" />. Consumer{" "}
        <Code>@gmail.com</Code> accounts cap at ~500 sends/day — for production
        use Google Workspace with an authenticated sending domain (see the
        troubleshooting section).
      </>
    ),
    text: "gmail send readonly bounce reply monitoring outreach 500 per day scopes workspace",
  },
  {
    provider: "rocketreach",
    label: "RocketReach",
    powers:
      "Contact enrichment — filling in missing emails and titles for the sparse contacts the crawler extracts.",
    whereToGet: (
      <>
        Sign up at <Ext href="https://rocketreach.co">rocketreach.co</Ext> and
        copy your API key from the account/API settings.
      </>
    ),
    addSteps: (
      <>
        <Path>Settings → Integrations → RocketReach → Add key</Path> →{" "}
        <Path>Test</Path>, or set <Code>ROCKETREACH_API_KEY</Code> in{" "}
        <Code>.env</Code>.
      </>
    ),
    text: "rocketreach enrichment emails titles api key rocketreach.co contact",
  },
  {
    provider: "millionverifier",
    label: "MillionVerifier",
    powers:
      "Provider-grade email deliverability checks — the external verification stage that decides whether an address is safe to email.",
    whereToGet: (
      <>
        Sign up at{" "}
        <Ext href="https://millionverifier.com">millionverifier.com</Ext> and
        copy the API key from your dashboard.
      </>
    ),
    addSteps: (
      <>
        <Path>Settings → Integrations → MillionVerifier → Add key</Path> →{" "}
        <Path>Test</Path>, or set <Code>MILLIONVERIFIER_API_KEY</Code> in{" "}
        <Code>.env</Code>.
      </>
    ),
    text: "millionverifier email verification deliverability api key millionverifier.com validation",
  },
  {
    provider: "groq",
    label: "Groq / LLM",
    powers:
      "LLM confidence scoring for the validation funnel — the model judgment that helps sort ambiguous, catch-all, and risky addresses.",
    whereToGet: (
      <>
        Create an API key at{" "}
        <Ext href="https://console.groq.com">console.groq.com</Ext>. The default
        model is <Code>llama-3.1-8b-instant</Code> (<Code>GROQ_MODEL</Code>).
      </>
    ),
    addSteps: (
      <>
        <Path>Settings → Integrations → Groq / LLM → Add key</Path> →{" "}
        <Path>Test</Path>, or set <Code>GROQ_API_KEY</Code> in <Code>.env</Code>.
        The scoring threshold is <Code>VALIDATION_LLM_THRESHOLD</Code> (default{" "}
        0.55).
      </>
    ),
    text: "groq llm confidence scoring validation console.groq.com llama model threshold",
  },
  {
    provider: "serp",
    label: "SERP / Jobs",
    powers:
      "Job discovery and hiring-signal mining — surfacing companies that are actively hiring for the target firm types.",
    whereToGet: (
      <>
        Pick a provider: <Ext href="https://serpapi.com">serpapi.com</Ext> or{" "}
        <Ext href="https://serper.dev">serper.dev</Ext>, and copy the API key.
        Set <Code>SERP_PROVIDER</Code> to <Code>serpapi</Code> or{" "}
        <Code>serper</Code> accordingly.
      </>
    ),
    addSteps: (
      <>
        <Path>Settings → Integrations → SERP / Jobs → Add key</Path> →{" "}
        <Path>Test</Path>, or set <Code>SERP_API_KEY</Code> +{" "}
        <Code>SERP_PROVIDER</Code> in <Code>.env</Code>.
      </>
    ),
    text: "serp jobs hiring signals serpapi serper api key provider discovery",
  },
  {
    provider: "approved_providers",
    label: "Approved data providers",
    powers:
      "Licensed third-party datasets that back the compliance-gated sources. These stay off until an admin signs off on the source.",
    whereToGet: (
      <>
        These are commercial data licenses, not self-serve signups. Provisioning
        is admin-controlled; the source stays gated (<Code>red</Code> posture)
        until an admin enables it with a signed-off provider.
      </>
    ),
    addSteps: (
      <>
        Enablement lives under <Path>Settings → Data Sources</Path> with the
        gated-source sign-off, and <Code>ENABLE_COMPLIANCE_GATED_SOURCES</Code>{" "}
        controls the master switch. No key is entered here in demo mode.
      </>
    ),
    text: "approved providers licensed datasets gated sources admin sign-off compliance red posture",
  },
];

/* --- FAQ sections ---------------------------------------------------------- */

const SECTIONS: HelpSection[] = [
  {
    id: "getting-started",
    label: "Start here",
    title: "Getting started",
    icon: Rocket,
    blurb: "What LeadMine does, how to sign in, and demo vs live mode.",
    items: [
      {
        id: "what-is",
        q: "What does LeadMine AI do?",
        a: (
          <p>
            LeadMine runs the pipeline{" "}
            <Path>Mine → Enrich → Validate → Sync to Sheets → Send → Monitor</Path>
            . You point a job at a place and an industry; it{" "}
            <strong>mines</strong> companies from compliant sources, crawls their
            sites and extracts contacts, <strong>enriches</strong> the sparse
            ones, runs a multi-stage email <strong>validation</strong> funnel,{" "}
            <strong>syncs</strong> everything into a 12-tab Google Sheet that acts
            as the system of record, <strong>sends</strong> personalized Gmail
            outreach, and <strong>monitors</strong> bounces, opens, clicks, and
            replies — writing every result back into the same sheet and database.
          </p>
        ),
        text: "what does leadmine do mine enrich validate sync sheets send monitor pipeline overview companies contacts",
      },
      {
        id: "dev-vs-google",
        q: "Dev Login vs Continue with Google — which do I use?",
        a: (
          <>
            <p>
              <strong>Dev Login</strong> signs you straight into the demo tenant
              with a seeded account — no Google project needed. It is the fastest
              way to explore and is what powers the deterministic demo.
            </p>
            <p className="mt-2">
              <strong>Continue with Google</strong> is the real OAuth path used to
              authorize Sheets and Gmail for your own Google account. It requires
              a configured OAuth client (Client ID + Secret). Until those are set,
              use Dev Login.
            </p>
          </>
        ),
        text: "dev login google sign in oauth demo tenant seeded account which to use",
      },
      {
        id: "demo-vs-live",
        q: "Demo mode vs live mode — how do I switch?",
        a: (
          <>
            <p>
              <Code>DEMO_MODE=true</Code> (the default in <Code>.env</Code>){" "}
              forces <strong>every adapter to its mock</strong>: mining,
              enrichment, validation, Sheets, and Gmail all run deterministically
              and never touch the network. That is why cards across the app show a{" "}
              <StatusChip status="review" label="Mock" /> badge.
            </p>
            <p className="mt-2">
              To go live: add the real provider keys (below), set{" "}
              <Code>DEMO_MODE=false</Code> and{" "}
              <Code>ENVIRONMENT=production</Code>, and restart. Any provider whose
              key is still empty falls back to mock; the rest go{" "}
              <StatusChip status="live" label="Live" />. Validate with{" "}
              <Code>make smoke-keys</Code>.
            </p>
          </>
        ),
        text: "demo mode live mode DEMO_MODE flag switch mock adapters keys smoke-keys environment production",
      },
    ],
  },
  {
    id: "validation",
    label: "Quality",
    title: "Validation & sales-ready",
    icon: ShieldCheck,
    blurb: "The 6-stage funnel and why only verified emails ship.",
    items: [
      {
        id: "six-stages",
        q: "What are the validation stages?",
        a: (
          <>
            <p>
              An email walks a six-stage funnel, cheapest checks first, so the
              paid provider check only runs on addresses that survive:
            </p>
            <ol className="mt-2 list-decimal space-y-1 pl-5">
              <li>
                <strong>Syntax</strong> — RFC-shape and obvious garbage.
              </li>
              <li>
                <strong>Domain / MX</strong> — the domain exists and accepts mail.
              </li>
              <li>
                <strong>Role &amp; disposable</strong> — flag{" "}
                <Code>info@</Code>-style role boxes and throwaway domains.
              </li>
              <li>
                <strong>SMTP / catch-all</strong> — probe deliverability and detect
                accept-all domains.
              </li>
              <li>
                <strong>Provider check</strong> — MillionVerifier's verdict.
              </li>
              <li>
                <strong>LLM confidence</strong> — Groq scoring on the ambiguous
                remainder (threshold <Code>0.55</Code>).
              </li>
            </ol>
          </>
        ),
        text: "validation six stages syntax domain mx role disposable smtp catch-all provider millionverifier llm groq funnel",
      },
      {
        id: "why-verified",
        q: "Why do only VERIFIED emails become sales-ready?",
        a: (
          <p>
            Sales-ready is the projection that feeds Gmail outreach, and outreach
            reputation is fragile. Only <strong>VERIFIED</strong>,
            non-suppressed contacts land in <Code>Sales_Ready_Leads</Code> so you
            never send to an address that is likely to bounce. Sending to
            unverified addresses tanks deliverability for the whole domain, so the
            gate is deliberate.
          </p>
        ),
        text: "why only verified emails sales-ready sales_ready_leads suppressed deliverability gate outreach",
      },
      {
        id: "catch-all",
        q: "How are catch-all, risky, and unknown addresses handled?",
        a: (
          <p>
            They are kept but <strong>not promoted</strong> to sales-ready.
            Catch-all domains accept anything, so a &ldquo;valid&rdquo; result is
            not trustworthy; risky and unknown verdicts likewise fall short of
            VERIFIED. They remain in the sheet/database for reference and can be
            re-checked, but they never enter a campaign automatically.
          </p>
        ),
        text: "catch-all risky unknown addresses handling not promoted verified re-check reference",
      },
    ],
  },
  {
    id: "campaigns",
    label: "Reach",
    title: "Campaigns & Google Sheets",
    icon: Send,
    blurb: "Sending rules, monitoring, and the 12-tab sheet.",
    items: [
      {
        id: "eligibility",
        q: "Who is eligible for a campaign, and what are the send limits?",
        a: (
          <p>
            Only <strong>verified, non-suppressed</strong> leads are eligible.
            Sending is rate-limited (<Code>DEFAULT_SEND_LIMIT_PER_HOUR</Code> /{" "}
            <Code>DEFAULT_SEND_LIMIT_PER_DAY</Code>), every message carries an{" "}
            <strong>unsubscribe</strong> path, and the suppression list is honored
            before each send. Bounce and reply monitoring polls Gmail and writes
            status changes back so a hard bounce suppresses the address.
          </p>
        ),
        text: "campaign eligibility verified send limits per hour per day unsubscribe suppression bounce reply monitoring",
      },
      {
        id: "sheet-tabs",
        q: "Why is Google Sheets the system of record, and what are the 12 tabs?",
        a: (
          <>
            <p>
              The per-tenant spreadsheet is the sales-facing source of truth: the
              sync engine mirrors Postgres into it idempotently, so your team
              works in a familiar sheet while the platform keeps it consistent.
            </p>
            <p className="mt-2">
              The tabs cover the full lifecycle — companies, contacts, the
              enrichment and validation working sets, the{" "}
              <Code>Sales_Ready_Leads</Code> projection, campaigns and sends,
              bounces/replies, hiring signals, sources, and an audit/run log —
              twelve in total, each mirrored from the database.
            </p>
          </>
        ),
        text: "google sheets system of record 12 tabs companies contacts sales_ready_leads campaigns bounces replies audit mirror idempotent",
      },
    ],
  },
  {
    id: "troubleshooting",
    label: "Fixes",
    title: "Troubleshooting / FAQ",
    icon: LifeBuoy,
    blurb: "Common issues and how to resolve them.",
    items: [
      {
        id: "google-not-working",
        q: "\"Continue with Google\" isn't working",
        a: (
          <>
            <p>
              This needs a configured Google OAuth client. Add a{" "}
              <strong>Client ID</strong> and <strong>Client Secret</strong> under{" "}
              <Path>Settings → Integrations → Google OAuth</Path> (or set{" "}
              <Code>GOOGLE_CLIENT_ID</Code> / <Code>GOOGLE_CLIENT_SECRET</Code> in{" "}
              <Code>.env</Code>). While they are empty the backend returns{" "}
              <Code>503 Google OAuth not configured</Code>.
            </p>
            <p className="mt-2">
              Also note: in consumer-Gmail{" "}
              <strong>Testing</strong> mode the OAuth consent screen shows
              &ldquo;Google hasn't verified this app&rdquo; (expected — click
              Continue), and refresh tokens <strong>expire after 7 days</strong>.
              LeadMine detects the <Code>invalid_grant</Code> and shows a
              &ldquo;Reconnect Google&rdquo; banner — one click plus consent
              restores Sheets/Gmail. In the meantime, Dev Login always works.
            </p>
          </>
        ),
        text: "continue with google not working 503 not configured client id secret refresh token expire 7 days invalid_grant reconnect testing mode",
      },
      {
        id: "localhost",
        q: "localhost isn't loading",
        a: (
          <p>
            The web app has to be running. From the repo root start the frontend
            with <Code>make web</Code> (or <Code>npm run dev</Code> in{" "}
            <Code>frontend/</Code>); it serves on{" "}
            <Code>http://localhost:3000</Code> and same-origin-proxies{" "}
            <Code>/api/*</Code> to the backend on <Code>:8000</Code>. Make sure
            Postgres and Redis are up (they run in Docker).
          </p>
        ),
        text: "localhost not loading make web npm run dev frontend 3000 8000 proxy postgres redis docker",
      },
      {
        id: "everything-mock",
        q: "Everything says MOCK",
        a: (
          <p>
            Demo mode is on. <Code>DEMO_MODE=true</Code> forces all adapters to
            mock regardless of keys. To go live, add the real provider keys, set{" "}
            <Code>DEMO_MODE=false</Code> (and{" "}
            <Code>ENVIRONMENT=production</Code>), and restart. Any provider still
            missing a key stays on its mock; the rest flip to{" "}
            <StatusChip status="live" label="Live" />.
          </p>
        ),
        text: "everything says mock demo mode DEMO_MODE false keys go live restart provider",
      },
      {
        id: "gmail-limits",
        q: "Gmail send limits / production email deliverability",
        a: (
          <p>
            Consumer <Code>@gmail.com</Code> accounts cap at{" "}
            <strong>~500 sends/day</strong> with weaker sender reputation. For
            production use a <strong>Google Workspace</strong> account (~2,000/day)
            with a custom sending domain authenticated by{" "}
            <strong>SPF, DKIM, and DMARC</strong>, and publish the OAuth app (or
            make it Internal) so refresh tokens don't expire every 7 days. Open/
            click tracking also needs a public <Code>APP_BASE_URL</Code> — it
            never registers on localhost. See <Code>docs/DEPLOYMENT.md</Code>.
          </p>
        ),
        text: "gmail send limits 500 per day workspace 2000 spf dkim dmarc sending domain publish oauth app_base_url tracking deployment",
      },
      {
        id: "docker-stack",
        q: "How do I run the full Docker stack?",
        a: (
          <p>
            Use the compose <Code>full</Code> profile:{" "}
            <Code>docker compose --profile full up -d --build</Code> (or{" "}
            <Code>make full</Code>). It runs Postgres, Redis, the{" "}
            <Code>api</Code> (which runs migrations via{" "}
            <Code>RUN_MIGRATIONS=1</Code>), a Celery <Code>worker</Code> across
            all 12 queues, a single Celery <Code>beat</Code>, and the{" "}
            <Code>web</Code> frontend. Migrations run in exactly one place —{" "}
            <Code>api</Code> only — so workers never race the schema.
          </p>
        ),
        text: "run full docker stack compose profile full make full postgres redis api worker beat web migrations run_migrations queues",
      },
      {
        id: "demo-data",
        q: "Where does the demo data come from?",
        a: (
          <p>
            Demo mode is fully deterministic: the mock adapters return seeded,
            fixed fixtures instead of calling any third-party service, and no
            network requests are made. That is what keeps{" "}
            <Code>make verify-demo</Code> reproducible (10/10) and lets the whole
            pipeline run with zero keys.
          </p>
        ),
        text: "where does demo data come from deterministic mock adapters seeded fixtures no network verify-demo reproducible",
      },
    ],
  },
];

/* -------------------------------------------------------------------------- */
/* Search helpers                                                             */
/* -------------------------------------------------------------------------- */

function matches(query: string, haystack: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return q
    .split(/\s+/)
    .every((term) => haystack.toLowerCase().includes(term));
}

/* -------------------------------------------------------------------------- */
/* Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function HelpPage() {
  const [query, setQuery] = useState("");

  const filteredSections = useMemo(
    () =>
      SECTIONS.map((s) => ({
        ...s,
        items: s.items.filter((it) => matches(query, `${it.q} ${it.text}`)),
      })).filter((s) => s.items.length > 0),
    [query],
  );

  const filteredProviders = useMemo(
    () =>
      PROVIDER_GUIDES.filter((p) =>
        matches(query, `${p.label} ${p.powers} ${p.text}`),
      ),
    [query],
  );

  const hasResults =
    filteredSections.length > 0 || filteredProviders.length > 0;

  return (
    <div className="flex flex-col gap-5">
      <Panel>
        <PanelHeader
          actions={<StatusChip status="review" label="In-app help center" />}
        >
          <MicroLabel className="text-accent/70">Info &amp; Help</MicroLabel>
          <h1 className="text-base font-semibold text-ink">
            Everything you need to run LeadMine AI
          </h1>
        </PanelHeader>

        <PanelSection>
          <p className="max-w-3xl text-sm leading-relaxed text-muted">
            LeadMine turns a place and an industry into verified, sales-ready
            leads and monitored outreach. This guide walks you from first login
            through connecting your own accounts, how mining and validation
            actually work, and the fixes for the questions we hear most. Search
            below or expand any topic.
          </p>

          {/* Search box */}
          <div className="relative mt-4 max-w-xl">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted"
              aria-hidden
            />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search help — e.g. google login, mock, send limits"
              aria-label="Search help topics"
              className={cn(
                "w-full rounded-[10px] border border-border bg-panel-strong py-2.5 pl-9 pr-3",
                "text-sm text-ink placeholder:text-muted lm-focus",
              )}
            />
          </div>

          {query.trim() && (
            <p className="mt-3">
              <MicroLabel>
                {hasResults
                  ? `Filtering by "${query.trim()}"`
                  : `No results for "${query.trim()}"`}
              </MicroLabel>
            </p>
          )}
        </PanelSection>
      </Panel>

      {!hasResults && query.trim() ? (
        <Panel>
          <PanelSection className="py-8 text-center">
            <p className="text-sm text-muted">
              Nothing matched. Try a shorter term, or clear the search to browse
              all topics.
            </p>
          </PanelSection>
        </Panel>
      ) : null}

      {/* Connecting your accounts — provider setup cards */}
      {filteredProviders.length > 0 && (
        <Panel>
          <PanelHeader>
            <div className="flex items-center gap-2">
              <Plug className="size-4 text-accent" aria-hidden />
              <MicroLabel className="text-accent/70">Connect</MicroLabel>
            </div>
            <h2 className="text-base font-semibold text-ink">
              Connecting your accounts
            </h2>
            <p className="mt-1 text-xs text-muted">
              One card per provider in the catalog. Add keys under{" "}
              <Path>Settings → Integrations → Add key → Test</Path>. Secrets are
              stored server-side and only ever shown masked.
            </p>
          </PanelHeader>

          <PanelSection>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {filteredProviders.map((p) => (
                <div
                  key={p.provider}
                  className="flex flex-col gap-3 rounded-[12px] border border-border bg-panel-strong p-4"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-ink">{p.label}</p>
                      <p className="mt-0.5 font-mono text-[11px] text-muted">
                        {p.provider}
                      </p>
                    </div>
                    <KeyRound className="size-4 shrink-0 text-muted" aria-hidden />
                  </div>
                  <p className="text-xs leading-relaxed text-muted">{p.powers}</p>
                  <div>
                    <MicroLabel>Where to get it</MicroLabel>
                    <p className="mt-1 text-xs leading-relaxed text-muted">
                      {p.whereToGet}
                    </p>
                  </div>
                  <div>
                    <MicroLabel>How to add it</MicroLabel>
                    <p className="mt-1 text-xs leading-relaxed text-muted">
                      {p.addSteps}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </PanelSection>
        </Panel>
      )}

      {/* Mining & data sources — non-collapsible reference block */}
      {matches(query, MINING_SEARCH_BLOB) && (
        <Panel>
          <PanelHeader>
            <div className="flex items-center gap-2">
              <Pickaxe className="size-4 text-accent" aria-hidden />
              <MicroLabel className="text-accent/70">Mine</MicroLabel>
            </div>
            <h2 className="text-base font-semibold text-ink">
              Mining &amp; data sources
            </h2>
          </PanelHeader>

          <PanelSection className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <MicroLabel>How a job runs</MicroLabel>
              <p className="mt-1.5 text-sm leading-relaxed text-muted">
                A job walks a fixed pipeline of stages —{" "}
                <Code>
                  resolving_location → discovering → deduping → crawling →
                  extracting → enriching → validating → syncing → sales_ready →
                  done
                </Code>{" "}
                — emitting live Server-Sent Events the UI streams. Each stage
                mirrors its output into both Postgres and the Google Sheet.
              </p>
            </div>

            <div>
              <MicroLabel>Compliance postures</MicroLabel>
              <p className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-muted">
                <StatusChip variant="accent" label="Green — open" />
                <StatusChip variant="warn" label="Amber — caution" />
                <StatusChip variant="danger" label="Red — gated" />
              </p>
              <p className="mt-1.5 text-sm leading-relaxed text-muted">
                Every source ships with a posture. <strong>Green</strong> sources
                are used freely; <strong>amber</strong> ones with care; and{" "}
                <strong>red</strong> sources stay off until an admin signs off.
              </p>
            </div>

            <div>
              <MicroLabel>Gated sources</MicroLabel>
              <p className="mt-1.5 text-sm leading-relaxed text-muted">
                Yellow Pages, Clutch, Indeed, and Facebook are{" "}
                <strong>gated</strong> — they require admin sign-off (and{" "}
                <Code>ENABLE_COMPLIANCE_GATED_SOURCES</Code> /{" "}
                <Code>ENABLE_FACEBOOK_SIGNALS</Code>) before a job may use them.{" "}
                <strong>LinkedIn is disabled</strong> — there is no LinkedIn
                scraping (<Code>ENABLE_LINKEDIN_CONNECTOR=false</Code>).
              </p>
            </div>

            <div>
              <MicroLabel>Politeness &amp; limits</MicroLabel>
              <p className="mt-1.5 text-sm leading-relaxed text-muted">
                The crawler honors <Code>robots.txt</Code> and is deliberately
                polite — capped at{" "}
                <Code>CRAWLER_MAX_PAGES_PER_DOMAIN</Code> pages with a{" "}
                <Code>CRAWLER_PER_DOMAIN_DELAY_SECONDS</Code> delay between
                requests per domain, so it never hammers a site.
              </p>
            </div>

            <div className="md:col-span-2">
              <MicroLabel>Global firm-type targeting</MicroLabel>
              <p className="mt-1.5 text-sm leading-relaxed text-muted">
                Jobs can target professional-services firm types worldwide —{" "}
                <strong>CA / CPA</strong> (chartered / certified accountants),{" "}
                <strong>IT</strong>, <strong>KPO</strong>, <strong>BPO</strong>,{" "}
                <strong>LPO</strong>, <strong>RPO</strong>, <strong>ITES</strong>,{" "}
                <strong>MSP</strong>, and similar — so you can mine, for example,
                CPA firms in one region and BPO/ITES providers in another from the
                same targeting model.
              </p>
            </div>
          </PanelSection>
        </Panel>
      )}

      {/* FAQ accordion sections */}
      {filteredSections.map((section) => {
        const Icon = section.icon;
        return (
          <Panel key={section.id}>
            <PanelHeader>
              <div className="flex items-center gap-2">
                <Icon className="size-4 text-accent" aria-hidden />
                <MicroLabel className="text-accent/70">
                  {section.label}
                </MicroLabel>
              </div>
              <h2 className="text-base font-semibold text-ink">
                {section.title}
              </h2>
              <p className="mt-1 text-xs text-muted">{section.blurb}</p>
            </PanelHeader>

            <PanelSection>
              <Accordion
                type="multiple"
                defaultValue={query.trim() ? section.items.map((i) => i.id) : []}
              >
                {section.items.map((item) => (
                  <AccordionItem key={item.id} value={item.id}>
                    <AccordionTrigger>{item.q}</AccordionTrigger>
                    <AccordionContent>{item.a}</AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </PanelSection>
          </Panel>
        );
      })}
    </div>
  );
}

/** Search blob for the non-accordion mining block. */
const MINING_SEARCH_BLOB =
  "mining data sources how a job runs pipeline stages sse compliance posture green amber red gated yellow pages clutch indeed facebook linkedin disabled no scraping robots.txt rate limits crawler firm type targeting ca cpa it kpo bpo lpo rpo ites msp global professional services";
