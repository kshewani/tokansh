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

Backend and Go/DRUNIX infrastructure are maintained separately inside the team repository. The frontend API boundary is in `src/api/` but live API integration, authentication and ledger-status verification remain outstanding. The frontend does not have a runtime ledger simulation fallback.

Use `.env.example` to configure local `.env.local`, never commit secrets. A configured API URL alone does not make ledger operations complete.

## Deployment

This directory is an independent Vite application and should be used as a frontend hosting project's root. This transfer does not alter the original GitHub Pages preview at https://mohinilahanukhare-star.github.io/tokansh/ or configure team hosting.
