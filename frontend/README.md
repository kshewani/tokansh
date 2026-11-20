# TokANSH — React Frontend

This directory contains the latest React + TypeScript + Vite frontend transferred from [mohinilahanukhare-star/tokansh](https://github.com/mohinilahanukhare-star/tokansh) at source commit `f5fe56dc6a4c27ef1da577db6e711757e9ebf32d`.

The team's source of truth is [../docs](../docs), particularly `UI_DESIGN_GUIDELINES.md`, `MVP_SCOPE.md`, `API_CONTRACTS.md` and `DEMO_SCRIPT.md`.

## Run from the frontend directory

```bash
cd frontend
npm install
npm run dev
```

Visit http://localhost:5173. Test and build with:

```bash
npm test
npm run build
```

## Implemented preview

React UI with a demo-only sign-in gate, logout/switch-account, Admin/Issuer, Investor and Lender navigation, property registry and issuance, marketplace, portfolio, collateral, lending, rental distribution, audit, analytics and system status.

The illustrative baseline data uses TechPark One at ₹100 crore, 100,000 authorized ANSH at ₹10,000 each, a 500-ANSH investor purchase, a 200-ANSH pledge and 300 remaining available. **No real DRUNIX ledger operations or banking services are claimed.** Scenario stages are UI previews, not committed transactions.

## Backend integration

Backend and Go/DRUNIX infrastructure are maintained separately inside the team repository. The frontend API boundary is in `src/api/`. System Status and the M4.3 investor Marketplace/Portfolio are integrated; other business screens remain unavailable in Connected Mode. Browser identity selection is the local X-Demo-Role mechanism, not production authentication. The frontend does not have a runtime ledger simulation fallback.

Use `.env.example` to configure local `.env.local`, never commit secrets. A configured API URL alone does not make ledger operations complete.

- `VITE_API_MODE=preview` (default): retains scenario stages, illustrative holdings and preview forms; no API requests are sent.
- `VITE_API_MODE=real` with `VITE_API_BASE_URL`: selects Connected Mode. System Status requests `/api/v1/system/status`; Marketplace, Portfolio and the investor dashboard use the transfer/balance APIs described below. Other business screens remain unavailable without preview balances or history. A missing URL remains a Connected Mode configuration error, without falling back to preview.

System Status validates the existing frontend `SystemStatus` shape inside the documented `{data, meta}` envelope. It supports loading, explicit refresh/retry, HTTP/network/timeout errors and malformed-response feedback. Missing component observations remain unknown. Component availability comes from returned statuses; a returned last-operation reference is not proof of commitment. Cached observations are hidden during refresh and after failure.

The M2 FastAPI backend in [../backend](../backend/README.md) implements the existing frontend status shape. Its API tests pass the actual response through this TypeScript parser. The database status reflects connectivity and the current migration; gateway integration remains unavailable and unqueried DRUNIX components remain unknown. No last ledger operation is fabricated. Property onboarding and the other unconnected screens remain outside this frontend integration milestone.

The shared request client preserves API error codes, details and correlation references, forwards caller-supplied `X-Correlation-ID`/`Idempotency-Key` headers and supports cancellation. Submission failures propagate to review dialogs, preserving form inputs and displaying recovery guidance. A synchronous guard blocks rapid duplicate submissions, and dialogs cannot be dismissed while awaiting their confirmation handler. The M4.3 investor flow uses its own typed result validation and persisted request keys, described below.

Connected mutation retries are explicitly disabled. Timed-out, cancelled-after-dispatch, malformed, failed or nonterminal mutation results retain a reconciliation block for the current provider/dialog lifetime; HTTP success alone never confirms business success. Pre-dispatch cancellation sends nothing. Read-only status refresh/retry remains available.

Generic preview-form guards are not durable operation recovery. The M4.3 investor flow separately retains request keys and backend operation references; reloading is never treated as reconciliation. All unconnected workflows remain unavailable.

Tests use Node.js 24, existing Node test facilities and TypeScript for server-rendered component assertions; no new dependencies are required. To run every test in the same process when a sandbox restricts test child processes:

```bash
node --test-isolation=none --experimental-strip-types --test tests/*.test.mjs
```

## Deployment

This directory is an independent Vite application and should be used as a frontend hosting project's root. This transfer does not alter the original GitHub Pages preview at https://mohinilahanukhare-star.github.io/tokansh/ or configure team hosting.

## M4.3 — connected investor journey

Select the existing **Investor** demo identity in Connected Mode. Marketplace
acquisition defaults to 4 ANSH from the registered issuer; My Portfolio defaults
to a 1-ANSH secondary transfer. Both require an explicit review/confirmation.
Suggested quantities do not imply these transactions have occurred. The target
6/3/1 balances must be observed through actual API reads after separately authorized
live execution; this implementation/test checkpoint performs no real transfers.

The UI uses property `f6169750-4676-4e99-887f-2bc5471bd518`, existing issuer `…0002`,
Investor A `…0003`, and existing recipient `00000000-0000-4000-8000-000000000005`
from the backend's transfer fixture/runbook. No new user ID or role is created.
Investor B is a recipient/holder account, not a second selectable login; holdings
can be inspected from Investor A's session. These are platform-mediated transfers
using Org1 User1 authority, not investor wallet signatures.

- `POST /api/v1/ansh/transfers` sends the backend's `asset_id`, `from_user_id`,
  `to_user_id`, integer `quantity`, `kind` and simulated `payment_outcome`.
- Reads use `GET /api/v1/ansh/balances/{property_id}/{holder_id}`. Three fresh
  observations display issuer, Investor A and Investor B balances. Missing/failed
  reads show unavailable values; no scenario quantities substitute for ledger data.
- Each reviewed request persists a UUID `Idempotency-Key` and frozen body in
  sessionStorage **before dispatch**. Rapid clicks, navigation or reload cannot
  silently create a second attempt in that session. No automatic mutation retries.
- The response's matching request, operation ID, transaction ID, simulated payment
  and commit evidence are validated. Only `COMMITTED_VALID` with matching successful
  commit evidence shows success. Balance queries refresh on that confirmed result.
- Pending/submitted/UNKNOWN states stay unresolved. “Check saved status” uses
  `GET /api/v1/ansh/transfers/{operation_id}/status`; “Reconcile” uses only
  `POST /api/v1/ansh/transfers/{operation_id}/reconcile`. Neither resubmits the
  financial request. Cached terminal evidence is distinguished from fresh holdings.
- If a lost response contains no operation ID, retain the displayed request key
  and ask the operator to recover it. There is no backend key-lookup API.
  PREPARING/PREPARED after interruption needs operator review; no resume-submit UI.
- Only an explicitly completed/known failed attempt permits “New request”. Preserve
  recovery references until resolved; do not clear browser storage to bypass UNKNOWN.

React sends **X-Demo-Role only**, plus correlation/idempotency headers where needed.
There are no bearer secrets, transfer capabilities or signing credentials in the
frontend. Use existing `VITE_API_MODE=real` / `VITE_API_BASE_URL` configuration;
frontend code never contacts port 8001 directly. Local identity headers are spoofable
and accepted only for the controlled hackathon demo. Use one operator and one tab;
sessionStorage is not cross-tab coordination and does not survive closing the tab.
The backend's durable operation records and chaincode invariants remain authoritative.

Payments, imagery, property labels, indicative analytics and external REIT examples
are explicitly illustrative/simulated. No fake price, valuation, rental entitlement
or transaction history is presented as ledger data. Preview Mode keeps all existing
scenario features unchanged. No new dependencies, application restarts, live writes
or deployment are part of this frontend implementation.
