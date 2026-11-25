# TokANSH — Free Test Hosting (Vercel + Render)

**Purpose:** a public test URL at no cost. **Not** the hackathon deployment (ADR-017: AWS VM with
Docker Compose, including DRUNIX).

| Part | Host | Plan |
|---|---|---|
| Website (`frontend/`) | Vercel | Hobby (free) |
| API (`backend/`) | Render | Free web service |

## What works on this setup

- Sign-in, property onboarding, submission and approval (application records).
- Every ledger step (registration, issuance, purchase transfer, pledge, release) **fails safely with
  `LEDGER_UNAVAILABLE`**, because no DRUNIX network runs here. That is the intended behaviour: there
  is no simulator fallback. The full demo needs DRUNIX + the Go adapter (AWS VM later).

## Limits of the free plans

- Render free instances **sleep after ~15 minutes idle**; the first request then takes up to ~1 minute.
- Render's free disk is **not persistent**: the SQLite demo database is recreated (empty, with the demo
  users) after every restart, sleep or redeploy. Sign-in sessions are in memory too, so after the API
  sleeps the website asks you to sign in again.
- Free plans and their limits change; check Render's and Vercel's current pricing pages.

## 1. API on Render

1. Sign in at https://render.com with GitHub and allow access to `kshewani/tokansh`.
2. **New → Blueprint**, pick the repository and branch `feature/db_schema`. Render reads `render.yaml`.
3. When asked for `CORS_ORIGINS`, enter your Vercel URL (you can fill it in after step 2 of the
   Vercel part; `CORS_ORIGIN_REGEX` already allows `*.vercel.app`).
4. Deploy. When it is live, open `https://<service>.onrender.com/health` → `{"status":"ok"}` and
   `https://<service>.onrender.com/docs` for the API.

## 2. Website on Vercel

1. Sign in at https://vercel.com with GitHub. **Add New → Project**, import `kshewani/tokansh`.
2. **Root Directory:** `frontend`. Framework preset: Vite (detected). Build command `npm run build`,
   output `dist` (defaults).
3. **Environment variable:** `VITE_API_BASE_URL` = `https://<service>.onrender.com` (no trailing slash,
   no `/api/v1`).
4. In **Settings → Git**, set the production branch to `feature/db_schema` (or deploy that branch).
5. Deploy and open the Vercel URL. `VITE_*` values are baked in at build time: redeploy after changing them.

## 3. Check it

- System Status page: API **CONNECTED**, DRUNIX gateway **UNAVAILABLE**.
- Sign in as Admin / Issuer (any password) → Property Registry → onboard and submit TechPark One → approve:
  the approval is saved and the registration shows `FAILED · LEDGER_UNAVAILABLE` with no transaction id.

## 4. Remove

Render: service → Settings → Delete. Vercel: project → Settings → Delete. Nothing else is created.
