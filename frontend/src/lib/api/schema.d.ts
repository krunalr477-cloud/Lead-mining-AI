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
}
