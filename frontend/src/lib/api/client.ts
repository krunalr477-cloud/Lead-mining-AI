import createClient from "openapi-fetch";
import type { paths } from "./schema";

/**
 * Typed API client. Points at the SAME ORIGIN /api prefix; next.config.ts
 * rewrites /api/:path* -> http://localhost:8000/api/:path* so the httpOnly
 * `lm_session` cookie flows to FastAPI without a cross-origin request.
 *
 * `credentials: "include"` ensures the cookie rides along even if the app is
 * later served from a different origin than the API in production.
 */
export const api = createClient<paths>({
  baseUrl: "/",
  credentials: "include",
});

/** Base path for hand-rolled fetches (SSE, EventSource) that bypass openapi-fetch. */
export const API_BASE = "/api/v1";
