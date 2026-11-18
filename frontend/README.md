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

Backend and Go/DRUNIX infrastructure are maintained separately inside the team repository. The frontend API boundary is in `src/api/`. Only read-only System Status is integrated; business data, authentication and ledger-status verification remain outstanding. The frontend does not have a runtime ledger simulation fallback.

Use `.env.example` to configure local `.env.local`, never commit secrets. A configured API URL alone does not make ledger operations complete.

- `VITE_API_MODE=preview` (default): retains scenario stages, illustrative holdings and preview forms; no API requests are sent.
- `VITE_API_MODE=real` with `VITE_API_BASE_URL`: selects Connected Mode. System Status requests `/api/v1/system/status`; other business screens show a not-integrated state without preview balances or history. A missing URL remains a Connected Mode configuration error, without falling back to preview.

System Status validates the existing frontend `SystemStatus` shape inside the documented `{data, meta}` envelope. It supports loading, explicit refresh/retry, HTTP/network/timeout errors and malformed-response feedback. Missing component observations remain unknown. Component availability comes from returned statuses; a returned last-operation reference is not proof of commitment. Cached observations are hidden during refresh and after failure.

The exact status component names, enum values and optional `last_ledger_operation` string in `src/api/contracts.ts` still require backend agreement: the shared API document describes the endpoint's responsibilities but does not prescribe this full JSON schema. Unsupported formats produce an explicit error rather than guessed readiness.

The shared request client preserves API error codes, details and correlation references, forwards caller-supplied `X-Correlation-ID`/`Idempotency-Key` headers and supports cancellation. Submission failures propagate to review dialogs, preserving form inputs and displaying recovery guidance. A synchronous guard blocks rapid duplicate submissions, and dialogs cannot be dismissed while awaiting their confirmation handler. No new financial mutation workflow is implemented.

Connected mutation retries are explicitly disabled. Timed-out, cancelled-after-dispatch, malformed, failed or nonterminal mutation results retain a reconciliation block for the current provider/dialog lifetime; HTTP success alone never confirms business success. Pre-dispatch cancellation sends nothing. Read-only status refresh/retry remains available.

These guards are not durable operation recovery: backend idempotency semantics, endpoint-specific result validation and persisted operation/status reconciliation must be integrated before enabling connected financial workflows. Reloading the application is not reconciliation. Business screens remain unavailable in Connected Mode.

Tests use Node.js 24, existing Node test facilities and TypeScript for server-rendered component assertions; no new dependencies are required. To run every test in the same process when a sandbox restricts test child processes:

```bash
node --test-isolation=none --experimental-strip-types --test tests/*.test.mjs
```

## Deployment

This directory is an independent Vite application and should be used as a frontend hosting project's root. This transfer does not alter the original GitHub Pages preview at https://mohinilahanukhare-star.github.io/tokansh/ or configure team hosting.
