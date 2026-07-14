# syntax=docker/dockerfile:1.7
# =============================================================================
# LeadMine AI — frontend image (Next.js standalone, multi-stage).
#
#   deps    — install node_modules from the lockfile (cache-friendly layer)
#   build   — `next build` producing .next/standalone + .next/static
#   runner  — minimal node:22-alpine running `node server.js` on :3000
#
# NEXT_PUBLIC_* values are inlined at build time; they default to empty so the
# image builds without secrets (Google Maps browser key can be supplied later
# via build args for a keyed build).
# =============================================================================

# --- deps ---------------------------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


# --- build --------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app

# Browser-safe public env, inlined into the client bundle at build time.
ARG NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY=""
ARG NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID=""
# Server-side rewrite target — defaults to localhost but must be overridden
# for production (e.g. the Render internal service URL).
ARG LEADMINE_BACKEND_ORIGIN="http://leadmine-backend:8000"
ENV NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY=$NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY \
    NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID=$NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID \
    LEADMINE_BACKEND_ORIGIN=http://leadmine-backend:8000 \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build


# --- runner -------------------------------------------------------------------
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# Standalone server + its trimmed node_modules, then the static/public assets
# that server.js expects to serve from disk.
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
