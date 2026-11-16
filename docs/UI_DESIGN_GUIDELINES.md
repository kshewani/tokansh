# TokANSH — UI Design Guidelines

**Version:** 1.0
**Status:** Proposed MVP design specification
**Last updated:** 2026-11-16

---

## 1. Purpose

This document defines the user experience, visual design system, navigation,
screen structure and interaction standards for TokANSH.

The objective is to create a polished, institutional-grade real estate
tokenisation and investment management platform.

The product must feel like a credible digital financial platform used by
investors, property issuers and financial institutions.

Avoid generic hackathon dashboard aesthetics, excessive gradients,
unnecessary animations and decorative components that reduce clarity.

## 2. Design Direction

### 2.1 Visual identity

Design characteristics:

- Premium financial-services aesthetic
- Modern and restrained
- Strong information hierarchy
- Clean typography
- Consistent spacing
- Subtle borders and shadows
- Clear financial data presentation
- Professional charts and tables
- High information density without visual clutter

The experience should take inspiration from institutional wealth-management,
private banking and enterprise financial software.

Do not directly copy another financial product's branding or interface.

### 2.2 Colour system

Use a restrained colour palette.

Recommended direction:

| Purpose | Suggested treatment |
|---|---|
| Primary brand | Deep navy |
| Secondary brand | Slate blue |
| Primary background | Light neutral |
| Surface/card | White |
| Primary text | Dark navy/charcoal |
| Secondary text | Muted slate |
| Borders | Light grey |
| Success | Green |
| Warning | Amber |
| Error | Red |
| Information | Blue |

Colour must communicate meaning consistently.

Do not use green to imply financial success unless the operation has actually
succeeded.

### 2.3 Typography

Use a modern, highly readable sans-serif typeface.

Typography hierarchy:

- Page title: prominent but restrained
- Section heading: clear and consistent
- Card title: compact
- Body text: comfortable reading size
- Metadata: smaller and muted
- Financial values: tabular numerals where possible

Financial amounts, quantities and percentages must be easy to scan.

### 2.4 Spacing and layout

Use a consistent spacing scale.

- Maintain consistent page margins.
- Group related information visually.
- Avoid excessive empty space in data-heavy screens.
- Avoid overcrowded cards.
- Use consistent card padding and border radii.
- Keep important actions visually distinguishable.
- Use responsive grids where appropriate.

## 3. Technology and Component Standards

Use:

- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui
- Recharts
- React Router
- TanStack Query
- Lucide icons

Guidelines:

1. Reuse shadcn/ui components where appropriate.
2. Create shared components for repeated patterns.
3. Avoid unnecessary custom component implementations.
4. Keep page-level components separate from reusable UI components.
5. Keep business logic out of presentational components.
6. Use typed API response models.
7. Use TanStack Query for server-state management.
8. Provide loading, error, empty and success states.
9. Use accessible labels and keyboard-friendly controls.
10. Avoid unnecessary dependencies.

## 4. Application Layout

### 4.1 Main application shell

Use a professional dashboard layout.

Recommended structure:

- Left navigation sidebar
- Main content area
- Top header
- Page title and contextual actions
- Optional breadcrumb navigation
- User profile and active role
- System/integration status indicators

The sidebar should support collapse/expand behaviour where practical.

### 4.2 Top header

Include:

- TokANSH brand
- Current page context
- DRUNIX connectivity/operational indicator
- Notification area where useful
- Active demonstration role
- User/profile menu

DRUNIX status must be meaningful.

Distinguish:

- Connected
- Unavailable
- Submitting transaction
- Awaiting commitment
- Reconciliation required

Do not display a simple green "Connected" badge as proof that all
transactions are operational.

### 4.3 Navigation structure

Recommended navigation:

**Overview**
- Dashboard

**Real Estate**
- Property Registry
- ANSH Issuance
- Marketplace

**Portfolio**
- My Portfolio
- Transactions
- Asset Intelligence

**Financing**
- Collateral Management
- Loan Applications

**Income**
- Rental Distributions

**Administration**
- Audit & Lifecycle
- System Status
- Settings

Navigation visibility may depend on the demonstration role.

Backend authorization remains mandatory. Hiding a navigation item is not
security enforcement.

## 5. Demonstration Roles

Support three demonstration roles.

### 5.1 Admin / Issuer

Primary responsibilities:

- Register property
- Submit property for approval
- Approve property
- Create ANSH issuance
- Review issuance status
- Manage marketplace listings
- View asset lifecycle
- Review audit information

### 5.2 Investor

Primary responsibilities:

- Explore available ANSH
- Purchase ANSH
- View portfolio
- View transaction history
- Pledge ANSH
- Apply for simulated financing
- View loan status
- Repay simulated loan
- View rental distributions

### 5.3 Lender

Primary responsibilities:

- View financing applications
- Review collateral details
- Perform simulated credit assessment
- Simulate approval or rejection
- View loan exposure
- Review pledge status

Role switching is a demonstration feature and must be visibly identified
as such. It is not production authentication.

## 6. Required Screens

### 6.1 Dashboard

Purpose:

Provide a consolidated view of TokANSH activity.

Recommended information:

- Total property value represented in the demonstration
- Total ANSH issued
- ANSH holders
- Marketplace activity
- Total pledged ANSH
- Simulated financing exposure
- Recent transactions
- Recent asset lifecycle events
- Portfolio distribution
- Asset performance overview

Use charts only where they communicate useful information.

Avoid presenting illustrative valuation as verified market value.

### 6.2 Property Registry

Purpose:

Manage property onboarding and approval.

Required information:

- Property name
- Property identifier
- Location
- Property category
- Illustrative valuation
- Total proposed ANSH supply
- Issue price
- Owner/issuer
- Property status
- Supporting documentation indicators

Actions:

- Register property
- View details
- Edit permitted information
- Submit for approval
- Approve or reject

Display approval and ledger state separately where they represent
different operations.

### 6.3 Property Details

Use a structured property details page.

Recommended sections:

- Property overview
- Location and property attributes
- Valuation information
- ANSH issuance information
- Ownership overview
- Marketplace activity
- Rental information
- Lifecycle history

Clearly identify illustrative property information.

### 6.4 ANSH Issuance

Purpose:

Create and monitor token issuance.

Display:

- Property
- Approved supply
- Requested issuance quantity
- Issue price
- Currency
- Total issuance value
- Issuance status
- DRUNIX transaction reference
- Commitment status

Actions:

- Initiate issuance
- Review transaction status
- View issuance history

Do not show issuance as completed before DRUNIX commitment is confirmed.

### 6.5 Marketplace

Purpose:

Allow investors to explore and purchase ANSH.

Display:

- Property
- Available listing quantity
- Price per ANSH
- Currency
- Illustrative property valuation
- Listing owner
- Listing status

Actions:

- View listing
- Select purchase quantity
- Review purchase summary
- Initiate simulated payment
- Track DRUNIX transfer

Show payment and ledger transfer as separate workflow stages.

### 6.6 Purchase Confirmation

Use a clear multi-stage transaction experience.

Recommended stages:

1. Order created
2. Business validation
3. Simulated payment
4. DRUNIX transfer submitted
5. Ledger commitment verified
6. Ownership projection updated

Each stage must show its actual state.

If payment succeeds but ledger transfer fails or becomes ambiguous, display
a reconciliation-required state.

Never show a misleading successful purchase confirmation.

### 6.7 Investor Portfolio

Purpose:

Provide a consolidated investor view.

Recommended metrics:

- Total illustrative portfolio value
- ANSH holdings
- Available ANSH
- Pledged ANSH
- Simulated financing outstanding
- Illustrative rental income

Display ANSH and REIT holdings separately.

ANSH holding details should include:

- Property
- Total owned units
- Available units
- Pledged units
- Illustrative acquisition value
- Illustrative current value
- Ownership transaction history

Identify the source and freshness of ledger-derived balances.

### 6.8 Collateral Management

Purpose:

Manage ANSH collateral.

Display:

- Property and ANSH asset
- Owned quantity
- Available quantity
- Pledged quantity
- Proposed pledge quantity
- Illustrative collateral value
- Loan-to-value ratio
- Pledge status

Actions:

- Initiate pledge
- View pledge status
- View associated loan
- Initiate full collateral release after repayment

Clearly distinguish the DRUNIX pledge state from the simulated loan state.

### 6.9 Lending

Purpose:

Demonstrate financing backed by ANSH collateral.

Display:

- Applicant
- Pledged property
- Pledged ANSH quantity
- Illustrative collateral value
- Requested loan
- Simulated LTV
- Simulated assessment result
- Loan status
- Outstanding amount
- Repayment history

Clearly display:

**SIMULATED LENDING WORKFLOW**

Do not imply that an actual bank has approved or disbursed a loan.

Partial collateral release is not supported in the MVP.

### 6.10 Rental Distributions

Purpose:

Demonstrate income distribution based on eligible ANSH holdings.

Display:

- Property
- Distribution period
- Record date
- Total distributable amount
- Investor entitlement
- ANSH quantity used for calculation
- Calculation status
- Simulated payment status

Show that the calculation uses record-date ownership rather than current
ownership.

Clearly label payment execution as simulated.

### 6.11 Asset Intelligence

Purpose:

Provide illustrative property and portfolio analytics.

Recommended information:

- Property valuation trend
- Rental yield
- Occupancy information
- Portfolio allocation
- Property performance
- Transaction activity

Identify simulated data and assumptions.

Do not present forecasts or estimates as guaranteed returns.

### 6.12 Audit and Lifecycle

Purpose:

Provide traceability.

Display:

- Event type
- Asset
- Operation identifier
- Actor
- Timestamp
- Application status
- DRUNIX transaction reference where applicable
- Commitment status

Clearly distinguish application audit records from actual ledger events.

### 6.13 System Status

Purpose:

Make the underlying demonstration infrastructure visible.

Display separate statuses for:

- FastAPI
- Application database
- Go gateway
- DRUNIX peers
- Ordering service
- Validation service
- DRUNIX state database
- Last successful ledger operation

Do not expose credentials, private network details or secrets.

## 7. Core Demo Scenario

The UI must support the complete TokANSH demonstration.

1. Meera registers TechPark One.
2. Property is approved.
3. 100,000 ANSH are issued through DRUNIX.
4. Aarav purchases 500 ANSH.
5. Simulated payment succeeds.
6. DRUNIX transfer commits.
7. Aarav's portfolio reflects 500 ANSH.
8. Aarav pledges 200 ANSH through DRUNIX.
9. Portfolio reflects 300 available and 200 pledged.
10. Attempt to transfer pledged units is rejected.
11. Rental entitlement is calculated using record-date ownership.
12. Rental payment is simulated.
13. Aarav repays the simulated loan.
14. Collateral release commits through DRUNIX.
15. Portfolio reflects the released units as available.

All core ANSH state transitions in this journey must be backed by actual
DRUNIX operations.

## 8. Financial Data Presentation

Use consistent formatting.

For INR:

- Display Indian digit grouping.
- Display currency symbol or ISO currency code consistently.
- Display appropriate decimal precision.
- Distinguish unit price from total value.
- Avoid ambiguous abbreviations for important transaction values.

Examples:

- ₹10,000 per ANSH
- ₹50,00,000 purchase value
- 500 ANSH
- 200 ANSH pledged

Use tabular numerals for financial values where possible.

Do not confuse:

- Property valuation
- ANSH issuance value
- Investor acquisition value
- Illustrative market value
- Outstanding loan amount
- Simulated rental income

## 9. Transaction and Status Visual Language

Use consistent status indicators.

Recommended statuses:

| Status | Meaning |
|---|---|
| Draft | Not submitted |
| Pending | Awaiting next workflow stage |
| Processing | Operation in progress |
| Submitted | Sent to DRUNIX |
| Committed | Ledger commitment confirmed |
| Failed | Definitive failure |
| Unknown | Outcome cannot be established |
| Reconciliation required | Further investigation required |
| Simulated | Supporting workflow is simulated |

Use colour and text together. Never rely on colour alone.

A transaction in Submitted, Unknown or Reconciliation required state
must not be shown as successful.

## 10. Forms and User Interaction

Forms must:

- Use clear labels and contextual help.
- Validate input before submission.
- Display validation errors near relevant fields.
- Confirm consequential operations.
- Prevent accidental duplicate submissions.
- Show loading states.
- Preserve user input when recoverable errors occur.
- Explain business-rule rejection clearly.

Before ANSH issuance, transfer or pledge, display a transaction review
containing the important parameters.

For irreversible or consequential actions, provide an explicit confirmation.

## 11. Tables and Data Visualisation

Tables should support:

- Clear column headings
- Right-aligned financial values
- Consistent date formatting
- Appropriate sorting
- Pagination for large datasets
- Empty states
- Loading states
- Error states

Charts should:

- Have clear titles
- Show units and periods
- Use appropriate scales
- Include useful tooltips
- Avoid misleading axes
- Identify illustrative or simulated data

Do not use charts merely for decoration.

## 12. Responsive Design

Desktop is the primary demonstration target.

The interface must also remain usable on tablets and mobile screens.

- Sidebar may collapse on smaller screens.
- Tables should support horizontal scrolling or responsive alternatives.
- Important transaction actions must remain accessible.
- Cards should reflow cleanly.
- Avoid fixed-width layouts that overflow.

## 13. Accessibility

- Use semantic HTML.
- Maintain readable colour contrast.
- Provide keyboard navigation.
- Associate form labels with controls.
- Provide visible focus indicators.
- Use accessible status messages.
- Do not communicate critical information through colour alone.

## 14. Loading, Empty, Error and Success States

Every data-driven screen must define:

### Loading

Use skeletons or appropriate progress indicators.

### Empty

Explain why no records are displayed and provide a relevant next action.

### Error

Show a clear message and an appropriate recovery action.

### Success

Confirm only what actually succeeded.

For DRUNIX operations, distinguish submission from confirmed commitment.

### Unknown outcome

Provide a reconciliation status and prevent unsafe duplicate retries.

## 15. Demo Data and Labels

Use the agreed illustrative scenario:

- Property: TechPark One
- Illustrative valuation: ₹100 crore
- Total ANSH: 100,000
- Issue price: ₹10,000 per ANSH
- Investor: Aarav
- Purchase: 500 ANSH
- Purchase value: ₹50 lakh
- Pledge: 200 ANSH
- Available after pledge: 300 ANSH

Other supporting values must be clearly identified as illustrative.

Use consistent names and figures across the application.

## 16. Performance and Engineering Standards

- Avoid unnecessary frontend re-rendering.
- Paginate large tables.
- Use query caching appropriately.
- Avoid repeated polling without a defined purpose.
- Refresh ledger-derived data after confirmed operations.
- Handle slow ledger responses without freezing the UI.
- Keep UI components independent of DRUNIX-specific SDKs.
- Use typed frontend API contracts.
- Do not place private keys or gateway credentials in frontend code.

## 17. AI Coding Agent Instructions

When implementing the UI:

1. Read this document and `PRODUCT_VISION.md`, `MVP_SCOPE.md`,
   `DOMAIN_MODEL.md`, `BUSINESS_RULES.md` and `API_CONTRACTS.md`.
2. Build a consistent application shell before implementing individual pages.
3. Create reusable components and design tokens.
4. Implement the complete demonstration journey.
5. Use actual backend APIs rather than hardcoded UI-only outcomes.
6. Never fake a successful core ANSH ledger operation.
7. Clearly label simulated supporting workflows.
8. Maintain consistent financial data and terminology.
9. Test loading, error, empty and success states.
10. Do not introduce new design libraries without justification.

---

**End of UI Design Guidelines**
