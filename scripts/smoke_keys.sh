#!/usr/bin/env bash
# Smoke-test every provider key in .env WITHOUT burning paid credits
# (except where noted). Run: make smoke-keys
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/.env" ] && set -a && source "$ROOT/.env" && set +a

pass=0; fail=0; skip=0
check() { # name, condition-command...
  local name="$1"; shift
  if [ -z "${!1:-}" ] 2>/dev/null; then :; fi
}
report() {
  local name="$1" ok="$2" detail="$3"
  if [ "$ok" = "skip" ]; then printf "  \033[33mSKIP\033[0m %-18s %s\n" "$name" "$detail"; skip=$((skip+1));
  elif [ "$ok" = "0" ]; then printf "  \033[32mPASS\033[0m %-18s %s\n" "$name" "$detail"; pass=$((pass+1));
  else printf "  \033[31mFAIL\033[0m %-18s %s\n" "$name" "$detail"; fail=$((fail+1)); fi
}

echo "LeadMine AI — provider key smoke tests"
echo "--------------------------------------"

# RocketReach: free /account endpoint (no lookup credits consumed)
if [ -n "${ROCKETREACH_API_KEY:-}" ]; then
  body=$(curl -sS --max-time 20 -H "Api-Key: $ROCKETREACH_API_KEY" https://api.rocketreach.co/api/v2/account/ || true)
  echo "$body" | grep -q '"error"' && report rocketreach 1 "$(echo "$body" | head -c 120)" || report rocketreach 0 "account OK"
else report rocketreach skip "ROCKETREACH_API_KEY empty"; fi

# MillionVerifier: free /credits endpoint
if [ -n "${MILLIONVERIFIER_API_KEY:-}" ]; then
  body=$(curl -sS --max-time 20 "https://api.millionverifier.com/api/v3/credits?api=$MILLIONVERIFIER_API_KEY" || true)
  echo "$body" | grep -qi '"credits"' && report millionverifier 0 "$(echo "$body" | head -c 80)" || report millionverifier 1 "$(echo "$body" | head -c 120)"
else report millionverifier skip "MILLIONVERIFIER_API_KEY empty"; fi

# Groq: free /models endpoint
if [ -n "${GROQ_API_KEY:-}" ]; then
  code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 20 -H "Authorization: Bearer $GROQ_API_KEY" https://api.groq.com/openai/v1/models || true)
  [ "$code" = "200" ] && report groq 0 "models list OK" || report groq 1 "HTTP $code"
else report groq skip "GROQ_API_KEY empty"; fi

# SERP provider: free account endpoint (serpapi) / cheap search (serper)
if [ -n "${SERP_API_KEY:-}" ]; then
  case "${SERP_PROVIDER:-serpapi}" in
    serpapi)
      body=$(curl -sS --max-time 20 "https://serpapi.com/account?api_key=$SERP_API_KEY" || true)
      echo "$body" | grep -q 'searches_per_month\|plan_id' && report serpapi 0 "account OK" || report serpapi 1 "$(echo "$body" | head -c 120)";;
    serper)
      code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 20 -X POST https://google.serper.dev/search -H "X-API-KEY: $SERP_API_KEY" -H "Content-Type: application/json" -d '{"q":"test"}' || true)
      [ "$code" = "200" ] && report serper 0 "search OK (1 credit)" || report serper 1 "HTTP $code";;
    *) report serp skip "unknown SERP_PROVIDER=${SERP_PROVIDER}";;
  esac
else report serp skip "SERP_API_KEY empty"; fi

# Google Maps server key: 1 cheap Geocoding call
if [ -n "${GOOGLE_MAPS_API_KEY:-}" ]; then
  body=$(curl -sS --max-time 20 "https://maps.googleapis.com/maps/api/geocode/json?address=Ahmedabad&key=$GOOGLE_MAPS_API_KEY" || true)
  echo "$body" | grep -q '"status" : "OK"\|"status": "OK"' && report google_maps 0 "geocode OK" || report google_maps 1 "$(echo "$body" | grep -o '"status"[^,]*' | head -1)"
else report google_maps skip "GOOGLE_MAPS_API_KEY empty"; fi

# Google OAuth client: config presence only (flow needs a browser)
if [ -n "${GOOGLE_CLIENT_ID:-}" ] && [ -n "${GOOGLE_CLIENT_SECRET:-}" ]; then
  report google_oauth 0 "client configured (full flow tested via app login)"
else report google_oauth skip "GOOGLE_CLIENT_ID/SECRET empty"; fi

echo "--------------------------------------"
echo "pass=$pass fail=$fail skip=$skip"
[ "$fail" -eq 0 ]
