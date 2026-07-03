# Google Cloud Setup Runbook (do these in your browser, ~30 minutes)

LeadMine AI needs a Google Cloud project with five APIs enabled, an OAuth client,
and two Maps API keys. Follow in order. Everything goes into `.env` at the repo root.

## 1. Create the project
1. Go to https://console.cloud.google.com/projectcreate
2. Name: `leadmine-dev` → **Create**.
3. For every later step, confirm `leadmine-dev` is selected in the top project picker.

## 2. Link billing + budget alert
1. https://console.cloud.google.com/billing → link a billing account to `leadmine-dev`
   (required by Places API (New); there is a monthly free usage tier, but a card must be on file).
2. Billing → **Budgets & alerts** → Create budget → **$10**, alerts at 50/90/100%.

## 3. Enable the five APIs
Visit each link and click **Enable**:
- Places API (New): https://console.cloud.google.com/apis/library/places.googleapis.com
- Maps JavaScript API: https://console.cloud.google.com/apis/library/maps-backend.googleapis.com
- Geocoding API: https://console.cloud.google.com/apis/library/geocoding-backend.googleapis.com
- Google Sheets API: https://console.cloud.google.com/apis/library/sheets.googleapis.com
- Gmail API: https://console.cloud.google.com/apis/library/gmail.googleapis.com

## 4. OAuth consent screen
1. https://console.cloud.google.com/auth/overview → **Get started**.
2. App name: `LeadMine AI (dev)`. Support email: `krunalr477@gmail.com`.
3. Audience: **External**. Publishing status: **leave in Testing**
   (do NOT publish — the Gmail scopes are "restricted" and publishing triggers a paid security assessment).
4. Test users (https://console.cloud.google.com/auth/audience): add `krunalr477@gmail.com`.

## 5. Scopes
https://console.cloud.google.com/auth/scopes → **Add or remove scopes** → add:
- `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` (login)
- `https://www.googleapis.com/auth/spreadsheets` (create + write the LeadMine spreadsheet)
- `https://www.googleapis.com/auth/gmail.send` (campaign sending)
- `https://www.googleapis.com/auth/gmail.readonly` (bounce/reply polling)

## 6. OAuth client
1. https://console.cloud.google.com/auth/clients → **Create client** → type **Web application**, name `leadmine-web`.
2. Authorized JavaScript origins: `http://localhost:3000`
3. Authorized redirect URIs: `http://localhost:8000/api/v1/auth/google/callback`
   (must match `GOOGLE_REDIRECT_URI` in `.env` byte-for-byte)
4. Copy **Client ID** → `GOOGLE_CLIENT_ID`, **Client Secret** → `GOOGLE_CLIENT_SECRET`.
   Do not download/commit the JSON.

## 7. API key #1 — server key (Places/Geocoding, used by the backend)
1. https://console.cloud.google.com/apis/credentials → Create credentials → **API key** → rename `leadmine-server`.
2. API restrictions: restrict to **Places API (New)** and **Geocoding API** only.
3. Application restrictions: **None** (home machine has no stable IP; the API restriction is the guard).
4. → `GOOGLE_MAPS_API_KEY` in `.env`.

## 8. API key #2 — browser key (map rendering in the web app)
1. Create another API key → rename `leadmine-browser`.
2. Application restrictions: **Websites** → add `http://localhost:3000/*`
3. API restrictions: **Maps JavaScript API** only.
4. → `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY` in `frontend/.env.local`.

Two separate keys are mandatory: referrer-restricted keys are rejected on server-side
calls, and an unrestricted key must never ship to the browser.

## 9. Quota caps (runaway-cost protection)
1. https://console.cloud.google.com/apis/api/places.googleapis.com/quotas
   → edit "requests per day" down to **500**.
2. Repeat for Geocoding API (500/day).

## 10. First login
When you first log into LeadMine with Google, the consent screen will say
"Google hasn't verified this app" — expected in Testing mode; click **Continue**.
Make sure the Sheets and Gmail checkboxes are ticked on the consent screen.

## Known limitation while in Testing mode
Refresh tokens **expire after 7 days**. LeadMine detects the resulting
`invalid_grant`, shows a "Reconnect Google" banner, and pauses Sheets/Gmail work
until you reconnect (one click + consent). This is a Google policy for unpublished
apps, not a bug. Production deployments should use a Google Workspace account,
a custom sending domain with SPF/DKIM/DMARC, and a verified OAuth app.
