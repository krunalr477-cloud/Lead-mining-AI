/**
 * Hand-written mirror of the FastAPI /api/v1 contract — enough of the shape to
 * type the foundation. This will be REPLACED by generated types once the
 * backend publishes an OpenAPI document:
 *
 *   npm run gen:api   # openapi-typescript -> src/lib/api/schema.d.ts
 *
 * Keep this file's `paths` export compatible with openapi-fetch so swapping in
 * the generated file is a drop-in.
 */

export type ProviderStatus = "live" | "mock";
export type UserRole = "admin" | "sales_manager" | "sales_executive" | "viewer";

export interface User {
  id: string;
  name: string;
  email: string;
  role: UserRole;
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

export type JobStatus =
  | "draft"
  | "queued"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export interface JobTotals {
  companies: number;
  contacts: number;
  emails_found: number;
  verified: number;
  review: number;
  invalid: number;
  sales_ready: number;
}

export interface Job {
  id: string;
  name: string;
  status: JobStatus;
  company_type: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  created_by: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress_percent: number;
  totals: JobTotals;
  campaign_id: string | null;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

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
}

export interface FunnelStage {
  key: string;
  label: string;
  value: number;
}

/** SSE / job-event envelope (shared by /jobs/{id}/events and /events). */
export interface JobEvent {
  job_id: string;
  type: string;
  stage: string | null;
  progress_percent: number | null;
  message: string | null;
  totals: Partial<JobTotals> | null;
  status: JobStatus | null;
  at: string;
}

/**
 * openapi-fetch-compatible `paths` map. Only the endpoints the foundation
 * touches are typed precisely; everything else is intentionally loose until
 * the generated schema lands.
 */
export interface paths {
  "/api/v1/me": {
    get: {
      responses: { 200: { content: { "application/json": MeResponse } } };
    };
  };
  "/api/v1/auth/dev-login": {
    post: {
      responses: { 200: { content: { "application/json": MeResponse } } };
    };
  };
  "/api/v1/auth/logout": {
    post: { responses: { 204: { content: never } } };
  };
  "/api/v1/jobs": {
    get: {
      responses: { 200: { content: { "application/json": Paginated<Job> } } };
    };
  };
  "/api/v1/dashboard/summary": {
    get: {
      responses: {
        200: { content: { "application/json": DashboardSummary } };
      };
    };
  };
  "/api/v1/dashboard/funnel": {
    get: {
      responses: {
        200: { content: { "application/json": { stages: FunnelStage[] } } };
      };
    };
  };
}
