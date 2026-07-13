/**
 * Hand-written mirror of the LeadMine FastAPI /api/v1 contract, matched field-
 * for-field against the LIVE seeded backend (verified 2026-07-03) and the
 * published OpenAPI document at http://localhost:8000/openapi.json.
 *
 * The `gen:api` npm script points at /api/v1/openapi.json which currently 404s
 * (the doc is served at the root /openapi.json), and several dashboard/queue
 * routes are not modelled in OpenAPI at all — so these types are hand-written
 * to stay authoritative. The `paths` export at the bottom stays openapi-fetch
 * compatible so screens keep type-checked GET/POST/PATCH calls.
 *
 * FIELD-NAME NOTES for screen agents (real API != naive expectations):
 *  - Job totals live under `totals_json` (NOT `totals`) with keys
 *    total_companies / total_contacts / emails_found / verified_emails /
 *    invalid_emails / review_emails / sales_ready_count.
 *  - GET /jobs, /companies, /contacts, /validation/{id} all return BARE ARRAYS
 *    (no pagination envelope, no total-count header). Paginate via limit/offset.
 *  - Decimal-ish fields arrive as STRINGS from the API: company.latitude,
 *    company.longitude, company.google_rating, company.company_size,
 *    contact.confidence_score, validation.llm_score, hiring.confidence_score.
 *    Parse with Number(...) at the display layer. Numbers are typed `string`
 *    here on purpose so nobody does arithmetic on them by accident.
 *  - final_email_status / final_status are UPPERCASE ("VERIFIED" | "INVALID" |
 *    "REVIEW" | "PENDING") and nullable.
 *  - Estimate returns estimated_companies_min/max, estimated_cost_usd,
 *    estimated_runtime_seconds (NOT the flat spec names).
 *  - The job event stream is a single flat LOG-ROW shape (seq/stage/level/
 *    message/payload) — NOT a per-type discriminated union. `level` +
 *    `stage` + `payload` carry the semantics. SSE uses `id:` = seq for
 *    Last-Event-ID resume.
 */

/* ── Providers / identity ────────────────────────────────────────────── */

export type ProviderStatus = "live" | "mock";
export type UserRole = "admin" | "sales_manager" | "sales_executive" | "viewer";

export interface User {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  created_at?: string;
}

export interface Tenant {
  id: string;
  name: string;
}

export type ProviderKey =
  | "google_maps"
  | "rocketreach"
  | "millionverifier"
  | "groq"
  | "serp"
  | "gmail"
  | "sheets";

export type ProviderMap = Record<ProviderKey, ProviderStatus>;

export interface MeResponse {
  user: User;
  tenant: Tenant;
  demo_mode: boolean;
  providers: ProviderMap;
}

/* ── Jobs ────────────────────────────────────────────────────────────── */

export type JobStatus =
  | "draft"
  | "queued"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

/** Raw totals object as returned under Job.totals_json. */
export interface JobTotals {
  total_companies: number;
  total_contacts: number;
  emails_found: number;
  verified_emails: number;
  invalid_emails: number;
  review_emails: number;
  sales_ready_count: number;
}

/** GET /jobs list item (lean). */
export interface JobListItem {
  id: string;
  name: string;
  status: JobStatus;
  company_type: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  selected_sources: string[];
  progress_percent: number;
  totals_json: JobTotals;
  created_by: string | null;
  created_at: string;
}

/** GET /jobs/{id} full record. */
export interface Job {
  id: string;
  name: string;
  status: JobStatus;
  company_type: string | null;
  services: string[];
  country: string | null;
  state: string | null;
  city: string | null;
  zipcode: string | null;
  latitude: number | null;
  longitude: number | null;
  radius_km: number | null;
  company_size_min: number | null;
  company_size_max: number | null;
  contact_roles: string[];
  exclude_keywords: string[];
  selected_sources: string[];
  progress_percent: number;
  totals_json: JobTotals;
  created_by: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  notes: string | null;
}

/** POST /jobs body (also POST /jobs/estimate body). */
export interface JobCreate {
  name: string;
  company_type?: string | null;
  services?: string[];
  country?: string | null;
  state?: string | null;
  city?: string | null;
  zipcode?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  radius_km?: number | null;
  company_size_min?: number | null;
  company_size_max?: number | null;
  contact_roles?: string[];
  exclude_keywords?: string[];
  selected_sources?: string[];
  deep_discovery?: boolean;
  enrichment_providers?: string[];
  validation_stages?: string[];
  output_options?: string[];
  notes?: string | null;
}

export interface ComplianceWarning {
  source: string;
  posture: string;
  message: string;
}

/** POST /jobs/estimate response. */
export interface JobEstimate {
  estimated_companies_min: number;
  estimated_companies_max: number;
  estimated_cost_usd: number;
  estimated_runtime_seconds: number;
  compliance_warnings: ComplianceWarning[];
  sheet_target: string;
  selected_sources: string[];
}

/** POST /jobs/{id}/start body. */
export interface JobStartRequest {
  inline?: boolean;
}

/** GET /jobs/{id}/results envelope. */
export interface JobResults {
  job_id: string;
  status: JobStatus;
  totals: JobTotals;
  companies: Company[];
}

/* ── Job event stream (SSE + ?format=json polling) ───────────────────── */

export type JobEventLevel = "info" | "success" | "warning" | "error" | "debug";

/**
 * A single job-log/event row. The backend emits one flat shape for every
 * event; consumers branch on `level` and `stage` rather than a `type` tag.
 * `payload` is stage-specific (e.g. deduping -> {found, unique, skipped}).
 * `seq` is the monotonic id used for SSE Last-Event-ID resume.
 */
export interface JobEvent {
  seq: number;
  job_id: string;
  stage: string | null;
  level: JobEventLevel;
  message: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
}

/* ── Companies ───────────────────────────────────────────────────────── */

export interface Company {
  id: string;
  job_id: string | null;
  canonical_name: string;
  website: string | null;
  domain: string | null;
  phone: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  postal_code: string | null;
  /** DECIMAL AS STRING — Number() before use. */
  latitude: string | null;
  /** DECIMAL AS STRING — Number() before use. */
  longitude: string | null;
  industry: string | null;
  services: string[];
  /** e.g. "150-200" — a free-text band, not a number. */
  company_size: string | null;
  /** DECIMAL AS STRING, e.g. "3.90". */
  google_rating: string | null;
  google_reviews: number | null;
  facebook_page_url: string | null;
  source_urls: string[];
  dedupe_status: string;
  website_status: string | null;
  hiring_signal_status: string | null;
  compliance_posture: string | null;
  last_refreshed_at: string | null;
  created_at: string;
}

export interface CompanySource {
  id: string;
  source_name: string;
  source_url: string | null;
  access_method: string;
  compliance_posture: string;
  first_seen_at: string;
}

export interface HiringSignal {
  id: string;
  source: string;
  source_url: string | null;
  job_title: string | null;
  location: string | null;
  posted_at: string | null;
  signal_type: string;
  /** DECIMAL AS STRING. */
  confidence_score: string | null;
}

/** Lean contact embedded in CompanyDetail.contacts. */
export interface ContactBrief {
  id: string;
  full_name: string | null;
  designation: string | null;
  role_category: string | null;
  email: string | null;
  final_email_status: EmailStatus | null;
  primary_contact: boolean;
  sales_ready: boolean;
}

/** GET /companies/{id}. */
export interface CompanyDetail extends Company {
  contacts: ContactBrief[];
  sources: CompanySource[];
  hiring_signals: HiringSignal[];
}

/** PATCH /companies/{id} body. */
export interface CompanyPatch {
  canonical_name?: string | null;
  website?: string | null;
  phone?: string | null;
  industry?: string | null;
  company_size?: string | null;
  notes?: string | null;
}

/* ── Contacts ────────────────────────────────────────────────────────── */

export type EmailStatus = "VERIFIED" | "INVALID" | "REVIEW" | "PENDING";

export interface Contact {
  id: string;
  company_id: string;
  job_id: string | null;
  full_name: string | null;
  first_name: string | null;
  last_name: string | null;
  designation: string | null;
  department: string | null;
  seniority: string | null;
  role_category: string | null;
  email: string | null;
  phone: string | null;
  linkedin_url: string | null;
  facebook_url: string | null;
  source_type: string | null;
  /** DECIMAL AS STRING, e.g. "0.904". */
  confidence_score: string | null;
  primary_contact: boolean;
  enrichment_status: string;
  enrichment_provider: string | null;
  final_email_status: EmailStatus | null;
  last_verified_at: string | null;
  sales_ready: boolean;
  owner_user_id: string | null;
  notes: string | null;
  created_at: string;
}

/** GET /contacts/{id}. */
export interface ContactDetail extends Contact {
  validation_checks: ValidationRow[];
}

/**
 * PATCH /contacts/{id} body (backend accepts a free-form object; these are the
 * fields the UI actually writes — owner/notes/next_action). sales_executive
 * role may only patch contacts they own.
 */
export interface ContactPatch {
  owner_user_id?: string | null;
  notes?: string | null;
  next_action?: string | null;
  sales_ready?: boolean;
  primary_contact?: boolean;
}

/* ── Validation ──────────────────────────────────────────────────────── */

export type ValidationStageStatus = "pass" | "fail" | "skip" | "unknown";
export type ValidationFinalStatus = "VERIFIED" | "INVALID" | "REVIEW" | "PENDING";

/**
 * One row per email candidate; the columns are the pipeline stages. Returned
 * by GET /validation/{job_id}, GET /validation/{contact_id}/history, and
 * embedded in ContactDetail.validation_checks.
 */
export interface ValidationRow {
  id: string;
  email_candidate_id: string;
  contact_id: string;
  company_id: string | null;
  syntax_status: ValidationStageStatus;
  disposable_status: ValidationStageStatus;
  role_based_status: ValidationStageStatus;
  mx_status: ValidationStageStatus;
  /** DECIMAL AS STRING, e.g. "0.507". */
  llm_score: string | null;
  llm_reason: string | null;
  millionverifier_status: string | null;
  final_status: ValidationFinalStatus | null;
  final_reason: string | null;
  retry_count: number;
  verified_at: string | null;
  created_at: string;
}

/** Alias for the per-contact history feed (same row shape). */
export type ValidationHistory = ValidationRow[];

/** POST /validation/run body. */
export interface ValidationRunRequest {
  contact_ids?: string[];
  email_candidate_ids?: string[];
}

/* ── Dashboard (routes NOT in OpenAPI — typed from live responses) ────── */

export interface DashboardSummary {
  companies_mined: number;
  contacts_found: number;
  emails_found: number;
  verified_emails: number;
  invalid_emails: number;
  review_emails: number;
  sales_ready_leads: number;
  emails_sent: number;
  delivered: number;
  open_rate: number;
  click_rate: number;
  reply_rate: number;
  bounce_rate: number;
  active_jobs: number;
  failed_jobs: number;
  api_requests: number;
  estimated_api_cost_usd: number;
  validation_rejection_reasons: {
    syntax: number;
    disposable: number;
    role_based: number;
    mx: number;
    llm: number;
    provider: number;
  };
}

export interface FunnelStage {
  stage: string;
  count: number;
}

export interface Funnel {
  stages: FunnelStage[];
}

export interface SourcePerformance {
  source_name: string;
  compliance_posture: string;
  runs: number;
  records_found: number;
  records_imported: number;
  skipped_runs: number;
  failed_runs: number;
}

export interface CampaignPerformance {
  campaign_id: string;
  name: string;
  status: string;
  recipients: number;
  sent: number;
  delivered: number;
  opened: number;
  clicked: number;
  replied: number;
  bounced: number;
}

/* ── Queues ──────────────────────────────────────────────────────────── */

export interface QueueHealth {
  queues: Record<string, number>;
  total_pending: number;
}

export interface WorkersHealth {
  status: "ok" | "down";
  up: boolean;
  workers: string[];
}

/** Aggregated per-source activity for one job (GET /jobs/{id}/sources). */
export interface SourceRunSummary {
  source_name: string;
  runs: number;
  completed: number;
  failed: number;
  skipped: number;
  in_progress: number;
  records_found: number;
  records_imported: number;
  retries: number;
  last_error: string | null;
  first_started_at: string | null;
  last_completed_at: string | null;
}

/* ── Google Sheets sync ──────────────────────────────────────────────── */

export interface SheetsStatus {
  connected: boolean;
  spreadsheet_id?: string | null;
  /** Tab name -> row count. */
  tabs: Record<string, number>;
  row_count?: number;
  last_synced_at: string | null;
  pending_rows: number;
  failed_rows: number;
}

export interface SheetsEvent {
  id?: string;
  tab?: string | null;
  action?: string | null;
  status?: string | null;
  rows?: number | null;
  message?: string | null;
  created_at?: string | null;
}

/* ── Exports ─────────────────────────────────────────────────────────── */

export type ExportFormat = "csv" | "xlsx" | "json" | "sheets";
export type ExportScope = "raw" | "sales_ready";
export type ExportStatus =
  | "pending"
  | "queued"
  | "running"
  | "processing"
  | "completed"
  | "failed";

export interface ExportRecord {
  id: string;
  format: ExportFormat | string;
  scope: ExportScope | string;
  status: ExportStatus | string;
  row_count?: number | null;
  file_size?: number | null;
  download_url?: string | null;
  error?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
}

export interface ExportCreate {
  format: ExportFormat;
  scope: ExportScope;
  job_id?: string | null;
}

/* ── Settings ────────────────────────────────────────────────────────── */

export interface Settings {
  /** Free-form settings blob; extended as backend fields land. */
  [key: string]: unknown;
}

/* ── Data source compliance ──────────────────────────────────────────── */

export type SourcePosture = "green" | "amber" | "red";

export interface DataSource {
  name: string;
  display_name?: string | null;
  source_type?: string | null;
  access_method?: string | null;
  posture: SourcePosture | string;
  enabled: boolean;
  legal_note?: string | null;
  requires_signoff?: boolean | null;
  signed_off?: boolean | null;
  signed_off_by?: string | null;
  signed_off_at?: string | null;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  quota_used?: number | null;
  quota_limit?: number | null;
  rate_limit?: string | null;
}

export interface SourcePatch {
  enabled?: boolean;
}

/* ── Integrations ────────────────────────────────────────────────────── */

export type IntegrationStatus = "live" | "mock" | "not_configured";

export interface Integration {
  provider: string;
  display_name?: string | null;
  status: IntegrationStatus | string;
  /** Server-provided masked key, e.g. "****ab12". Never a full secret. */
  masked_key?: string | null;
  last_verified_at?: string | null;
  note?: string | null;
  scopes?: string[] | null;
}

export interface IntegrationTestResult {
  ok: boolean;
  provider?: string;
  status?: string;
  message?: string | null;
  latency_ms?: number | null;
}

/**
 * Body for PUT /integrations/{provider}. The backend accepts a per-provider
 * shape: a single {api_key} for most providers, {client_id, client_secret} for
 * google_oauth, and {base_url, api_key} for approved_providers. All fields are
 * optional here so one client type covers every card.
 */
export interface IntegrationSecretInput {
  api_key?: string;
  client_id?: string;
  client_secret?: string;
  base_url?: string;
}

/* ── Environment keys (.env) ─────────────────────────────────────────── */

/**
 * A single `.env` key row from GET /settings/env-keys. Secret rows carry only a
 * masked hint in `value`; the full value is fetched on demand via
 * POST /settings/env-keys/reveal. Non-secret rows carry plaintext in `value`.
 */
export interface EnvKey {
  key: string;
  label: string;
  group: string;
  is_secret: boolean;
  is_set: boolean;
  /** Masked hint for secrets (e.g. "****ab12"), plaintext for non-secrets. */
  masked?: string | null;
  /** Plaintext for non-secret rows; masked/omitted for secrets. */
  value?: string | null;
  /** Where the value came from, e.g. "env" or "default". */
  source?: string | null;
}

/** Response of POST /settings/env-keys/reveal — the full plaintext secret. */
export interface EnvKeyReveal {
  key: string;
  value: string;
}

/* ── Validation rules ────────────────────────────────────────────────── */

export type CatchAllHandling = "review" | "reject" | "accept";
export type RiskHandling = "review" | "reject" | "accept";
export type UnknownRetryPolicy = "retry" | "review" | "reject";

export interface ValidationRules {
  disposable_domains: string[];
  role_based_keywords: string[];
  llm_threshold: number;
  catch_all_handling: CatchAllHandling | string;
  risk_handling: RiskHandling | string;
  unknown_retry_policy: UnknownRetryPolicy | string;
}

export interface ValidationRulesPatch {
  disposable_domains?: string[];
  role_based_keywords?: string[];
  llm_threshold?: number;
  catch_all_handling?: string;
  risk_handling?: string;
  unknown_retry_policy?: string;
}

/* ── Users & invites ─────────────────────────────────────────────────── */

export interface UserInvite {
  email: string;
  name?: string;
  role: UserRole;
}

export interface UserPatch {
  role?: UserRole;
  name?: string;
}

/* ── Audit ───────────────────────────────────────────────────────────── */

export interface AuditEntry {
  id: string;
  actor?: string | null;
  actor_name?: string | null;
  action: string;
  entity_type?: string | null;
  entity_id?: string | null;
  before?: unknown;
  after?: unknown;
  summary?: string | null;
  created_at?: string | null;
}

export interface AuditFilters extends Record<string, unknown> {
  q?: string;
  action?: string;
  entity_type?: string;
  limit?: number;
  offset?: number;
}

/* ── Query filter shapes ─────────────────────────────────────────────── */

export interface JobsFilters extends Record<string, unknown> {
  status?: JobStatus | string;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface CompaniesFilters extends Record<string, unknown> {
  job_id?: string;
  source?: string;
  status?: string;
  city?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface ContactsFilters extends Record<string, unknown> {
  job_id?: string;
  company_id?: string;
  status?: EmailStatus | string;
  role?: string;
  owner?: string;
  sales_ready?: boolean;
  q?: string;
  limit?: number;
  offset?: number;
}

/* ── Campaigns / Outreach (§13 — routes typed from documented shapes) ── */

/** Draft → Scheduled → Queued → Sending → Paused → Completed/Failed/Cancelled. */
export type CampaignStatus =
  | "draft"
  | "scheduled"
  | "queued"
  | "sending"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

/** Per-message lifecycle for the outreach queue. */
export type MessageStatus =
  | "queued"
  | "sent"
  | "delivered"
  | "opened"
  | "clicked"
  | "replied"
  | "hard_bounce"
  | "soft_bounce"
  | "blocked"
  | "spam_complaint"
  | "unsubscribed";

/** The 12 supported template variables (§13). */
export type TemplateVariable =
  | "FirstName"
  | "LastName"
  | "FullName"
  | "Company"
  | "Industry"
  | "City"
  | "State"
  | "Country"
  | "Services"
  | "Designation"
  | "Website"
  | "HiringSignal";

export interface TrackingSettings {
  opens: boolean;
  clicks: boolean;
  replies: boolean;
  bounces: boolean;
}

export interface RateLimitSettings {
  per_hour: number;
  per_day: number;
  /** "HH:mm" 24h. */
  window_start?: string | null;
  window_end?: string | null;
  timezone?: string | null;
}

/** Aggregate counts on a campaign row/detail. */
export interface CampaignStats {
  recipients: number;
  sent: number;
  delivered: number;
  opened: number;
  clicked: number;
  replied: number;
  bounced: number;
  suppressed?: number;
  open_rate?: number;
  click_rate?: number;
  reply_rate?: number;
  bounce_rate?: number;
}

/** GET /campaigns row. */
export interface Campaign {
  id: string;
  name: string;
  status: CampaignStatus | string;
  job_id: string | null;
  job_name?: string | null;
  from_account: string | null;
  subject: string;
  body: string;
  ai_opener_enabled: boolean;
  tracking: TrackingSettings;
  rate_limit: RateLimitSettings;
  stats: CampaignStats;
  created_at: string;
  updated_at?: string | null;
  launched_at?: string | null;
  completed_at?: string | null;
  /** Estimated completion in seconds for the remaining queue. */
  estimated_completion_seconds?: number | null;
}

/** Eligibility breakdown returned by campaign detail / create-preview. */
export interface EligibilitySummary {
  eligible: number;
  /** Excluded counts keyed by reason. */
  excluded: {
    not_verified: number;
    suppressed: number;
    bounced: number;
    unsubscribed: number;
    role_based: number;
  };
  total: number;
}

/** GET /campaigns/{id} — detail. */
export interface CampaignDetail extends Campaign {
  eligibility?: EligibilitySummary;
}

/** POST /campaigns body. */
export interface CampaignCreate {
  name: string;
  job_id?: string | null;
  from_account?: string | null;
  subject: string;
  body: string;
  ai_opener_enabled?: boolean;
  tracking?: Partial<TrackingSettings>;
  rate_limit?: Partial<RateLimitSettings>;
}

/** POST /campaigns/{id}/test body. */
export interface CampaignTestRequest {
  to?: string;
  contact_id?: string;
}

/** Reusable subject/body template. */
export interface Template {
  id: string;
  name: string;
  subject: string;
  body: string;
  ai_opener_enabled?: boolean;
  created_at?: string;
}

export interface TemplateCreate {
  name: string;
  subject: string;
  body: string;
  ai_opener_enabled?: boolean;
}

/** A single outreach-queue row (per email message). */
export interface OutreachQueueRow {
  queue_id: string;
  campaign_id: string;
  contact_id: string | null;
  contact_name: string | null;
  email: string;
  company: string | null;
  subject: string;
  send_status: MessageStatus | string;
  scheduled_at: string | null;
  sent_at: string | null;
  gmail_message_id: string | null;
  opened: boolean;
  replied: boolean;
  bounced: boolean;
  suppressed: boolean;
}

export interface OutreachQueueFilters extends Record<string, unknown> {
  campaign_id?: string;
  status?: MessageStatus | string;
  q?: string;
  limit?: number;
  offset?: number;
}

/* ── Bounces / Replies / Suppressions (§14) ──────────────────────────── */

export type BounceType =
  | "hard_bounce"
  | "soft_bounce"
  | "mailbox_full"
  | "invalid_domain"
  | "blocked"
  | "spam_rejected"
  | "rate_limited"
  | "spam_complaint"
  | "unsubscribe"
  | "reply"
  | "unknown";

export interface BounceRow {
  id: string;
  email: string;
  contact_id: string | null;
  campaign_id: string | null;
  campaign_name: string | null;
  /** "reply" vs a bounce class — drives the row's action set. */
  event_type: "bounce" | "reply";
  smtp_status_code: string | null;
  bounce_type: BounceType | string | null;
  reason: string | null;
  diagnostic_code?: string | null;
  gmail_message_id?: string | null;
  detected_at: string;
  suppressed: boolean;
}

export interface BouncesFilters extends Record<string, unknown> {
  campaign_id?: string;
  event_type?: "bounce" | "reply";
  bounce_type?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface Suppression {
  id: string;
  email: string;
  reason: string | null;
  source?: string | null;
  created_at: string;
}

export interface SuppressionCreate {
  email: string;
  reason?: string | null;
}

/* ── openapi-fetch `paths` map ───────────────────────────────────────── */

type Json<T> = { content: { "application/json": T } };

export interface paths {
  "/api/v1/me": {
    get: { responses: { 200: Json<MeResponse> } };
  };
  "/api/v1/auth/dev-login": {
    post: { responses: { 200: Json<MeResponse> } };
  };
  "/api/v1/auth/logout": {
    post: { responses: { 204: { content: never } } };
  };

  "/api/v1/jobs": {
    get: {
      parameters: { query?: JobsFilters };
      responses: { 200: Json<JobListItem[]> };
    };
    post: {
      requestBody: Json<JobCreate>;
      responses: { 200: Json<Job>; 201: Json<Job> };
    };
  };
  "/api/v1/jobs/estimate": {
    post: {
      requestBody: Json<JobCreate>;
      responses: { 200: Json<JobEstimate> };
    };
  };
  "/api/v1/jobs/{job_id}": {
    get: {
      parameters: { path: { job_id: string } };
      responses: { 200: Json<Job> };
    };
  };
  "/api/v1/jobs/{job_id}/results": {
    get: {
      parameters: { path: { job_id: string } };
      responses: { 200: Json<JobResults> };
    };
  };
  "/api/v1/jobs/{job_id}/start": {
    post: {
      parameters: { path: { job_id: string } };
      requestBody?: Json<JobStartRequest>;
      responses: { 200: Json<Job> };
    };
  };
  "/api/v1/jobs/{job_id}/pause": {
    post: {
      parameters: { path: { job_id: string } };
      responses: { 200: Json<Job> };
    };
  };
  "/api/v1/jobs/{job_id}/cancel": {
    post: {
      parameters: { path: { job_id: string } };
      responses: { 200: Json<Job> };
    };
  };

  "/api/v1/companies": {
    get: {
      parameters: { query?: CompaniesFilters };
      responses: { 200: Json<Company[]> };
    };
  };
  "/api/v1/companies/{company_id}": {
    get: {
      parameters: { path: { company_id: string } };
      responses: { 200: Json<CompanyDetail> };
    };
    patch: {
      parameters: { path: { company_id: string } };
      requestBody: Json<CompanyPatch>;
      responses: { 200: Json<CompanyDetail> };
    };
  };

  "/api/v1/contacts": {
    get: {
      parameters: { query?: ContactsFilters };
      responses: { 200: Json<Contact[]> };
    };
  };
  "/api/v1/contacts/{contact_id}": {
    get: {
      parameters: { path: { contact_id: string } };
      responses: { 200: Json<ContactDetail> };
    };
    patch: {
      parameters: { path: { contact_id: string } };
      requestBody: Json<ContactPatch>;
      responses: { 200: Json<Contact> };
    };
  };
  "/api/v1/contacts/{contact_id}/verify": {
    post: {
      parameters: { path: { contact_id: string } };
      responses: { 200: Json<Contact> };
    };
  };

  "/api/v1/validation/run": {
    post: {
      requestBody: Json<ValidationRunRequest>;
      responses: { 200: Json<ValidationRow[]> };
    };
  };
  "/api/v1/validation/{job_id}": {
    get: {
      parameters: { path: { job_id: string }; query?: { limit?: number; offset?: number } };
      responses: { 200: Json<ValidationRow[]> };
    };
  };
  "/api/v1/validation/{contact_id}/history": {
    get: {
      parameters: { path: { contact_id: string } };
      responses: { 200: Json<ValidationRow[]> };
    };
  };

  "/api/v1/dashboard/summary": {
    get: { responses: { 200: Json<DashboardSummary> } };
  };
  "/api/v1/dashboard/funnel": {
    get: { responses: { 200: Json<Funnel> } };
  };
  "/api/v1/dashboard/source-performance": {
    get: { responses: { 200: Json<SourcePerformance[]> } };
  };
  "/api/v1/dashboard/campaign-performance": {
    get: { responses: { 200: Json<CampaignPerformance[]> } };
  };
  "/api/v1/queues/health": {
    get: { responses: { 200: Json<QueueHealth> } };
  };
  "/api/v1/workers/health": {
    get: { responses: { 200: Json<WorkersHealth> } };
  };
  "/api/v1/jobs/{job_id}/sources": {
    get: {
      parameters: { path: { job_id: string } };
      responses: { 200: Json<SourceRunSummary[]> };
    };
  };
  "/api/v1/sheets/status": {
    get: { responses: { 200: Json<SheetsStatus> } };
  };

  "/api/v1/campaigns": {
    get: { responses: { 200: Json<Campaign[]> } };
    post: {
      requestBody: Json<CampaignCreate>;
      responses: { 200: Json<CampaignDetail>; 201: Json<CampaignDetail> };
    };
  };
  "/api/v1/campaigns/{campaign_id}": {
    get: {
      parameters: { path: { campaign_id: string } };
      responses: { 200: Json<CampaignDetail> };
    };
  };
  "/api/v1/campaigns/{campaign_id}/test": {
    post: {
      parameters: { path: { campaign_id: string } };
      requestBody?: Json<CampaignTestRequest>;
      responses: { 200: Json<{ ok: boolean; message?: string }> };
    };
  };
  "/api/v1/campaigns/{campaign_id}/launch": {
    post: {
      parameters: { path: { campaign_id: string } };
      responses: { 200: Json<CampaignDetail> };
    };
  };
  "/api/v1/campaigns/{campaign_id}/pause": {
    post: {
      parameters: { path: { campaign_id: string } };
      responses: { 200: Json<CampaignDetail> };
    };
  };
  "/api/v1/campaigns/{campaign_id}/resume": {
    post: {
      parameters: { path: { campaign_id: string } };
      responses: { 200: Json<CampaignDetail> };
    };
  };
  "/api/v1/campaigns/{campaign_id}/cancel": {
    post: {
      parameters: { path: { campaign_id: string } };
      responses: { 200: Json<CampaignDetail> };
    };
  };
  "/api/v1/campaigns/{campaign_id}/queue": {
    get: {
      parameters: { path: { campaign_id: string }; query?: OutreachQueueFilters };
      responses: { 200: Json<OutreachQueueRow[]> };
    };
  };

  "/api/v1/outreach": {
    get: {
      parameters: { query?: OutreachQueueFilters };
      responses: { 200: Json<OutreachQueueRow[]> };
    };
  };

  "/api/v1/templates": {
    get: { responses: { 200: Json<Template[]> } };
    post: {
      requestBody: Json<TemplateCreate>;
      responses: { 200: Json<Template>; 201: Json<Template> };
    };
  };
  "/api/v1/templates/{template_id}": {
    patch: {
      parameters: { path: { template_id: string } };
      requestBody: Json<Partial<TemplateCreate>>;
      responses: { 200: Json<Template> };
    };
  };

  "/api/v1/bounces": {
    get: {
      parameters: { query?: BouncesFilters };
      responses: { 200: Json<BounceRow[]> };
    };
  };
  "/api/v1/bounces/poll": {
    post: {
      responses: { 200: Json<{ detected: number; bounces: number; replies: number }> };
    };
  };

  "/api/v1/suppressions": {
    get: { responses: { 200: Json<Suppression[]> } };
    post: {
      requestBody: Json<SuppressionCreate>;
      responses: { 200: Json<Suppression>; 201: Json<Suppression> };
    };
  };
  "/api/v1/suppressions/{suppression_id}": {
    delete: {
      parameters: { path: { suppression_id: string } };
      responses: { 200: Json<{ ok: boolean }>; 204: { content: never } };
    };
  };
}
