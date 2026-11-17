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

## Connected to the TokANSH API

Every screen reads and writes through the Python API (`src/api/client.ts`); there are no scenario fixtures and no ledger simulation in the frontend.

Run the backend first (see `../backend/README.md`), then:

```bash
npm install
npm run dev        # http://localhost:5173; /api is proxied to http://localhost:8000
```

Set `VITE_API_PROXY_TARGET` to point the proxy elsewhere, or `VITE_API_BASE_URL` to call an API on another origin (the backend must allow it in `CORS_ORIGINS`).

- **Sign-in** picks a demo role and gets that user's id from `POST /api/v1/demo/active-role`. Not authentication.
- **Every consequential action** goes through a confirmation dialog and is sent with a fresh `Idempotency-Key`.
- **Ledger results** are reported from the operation the API returns: "committed on DRUNIX · tx …" only for `COMMITTED`; pending, reconciliation and failure states are shown as such.
- **Sources** are labelled on every event: DRUNIX, APPLICATION or SIMULATED.

Without a connected DRUNIX gateway, the off-chain steps work (onboarding, submission, approval record), and ledger steps show `LEDGER_UNAVAILABLE`.

## Deployment

This directory is an independent Vite application and should be used as a frontend hosting project's root. This transfer does not alter the original GitHub Pages preview at https://mohinilahanukhare-star.github.io/tokansh/ or configure team hosting.
