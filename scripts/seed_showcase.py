#!/usr/bin/env python3
"""Guarded provisioning plan for the fixed TokANSH showcase catalogue.

Dry-run is the default.  ``--apply --allow-live-writes`` is intentionally
explicit because the registration, issuance and transfer calls create real
application and DRUNIX state.  The script uses existing HTTP/operator
workflows; it never writes ledger-shaped records directly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sqlite3
import tempfile
from datetime import datetime, timezone
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


ROOT = Path(__file__).resolve().parents[1]
BACKEND_PYTHON = ROOT / "backend" / ".venv" / "bin" / "python"
SHOWCASE_NAMESPACE = uuid5(NAMESPACE_URL, "https://tokansh.example/showcase/2026")


@dataclass(frozen=True)
class ShowcaseProperty:
    name: str
    symbol: str
    location: str
    category: str
    size: str
    valuation: str
    supply: int
    description: str
    risk_profile: str


CATALOGUE = (
    ShowcaseProperty("Silver Oak Residential Plot", "OAK", "Wagholi, Pune", "Residential plot", "2,400 sq. ft.", "6000000", 6000, "A compact residential land parcel for owner-led tokenization.", "Vacant land; no rental income assumption."),
    ShowcaseProperty("Green Acres Farmland", "GREEN", "Nashik", "Agricultural land", "5 acres", "8500000", 8500, "A productive agricultural parcel illustrating a non-urban property owner journey.", "Agricultural use and weather exposure; no rental income assumption."),
    ShowcaseProperty("Urban Nest Residences", "NEST", "Kharadi, Pune", "Residential apartment", "1,450 sq. ft.", "12000000", 12000, "A residential unit positioned near a growing employment corridor.", "Residential vacancy and local market liquidity risk."),
    ShowcaseProperty("Cornerstone Retail", "CORNER", "Indore", "Commercial retail", "1,800 sq. ft.", "15000000", 15000, "A neighbourhood retail asset with a visible commercial use case.", "Tenant concentration and commercial vacancy risk."),
    ShowcaseProperty("Hillcrest Boutique Retreat", "HILL", "Lonavala", "Boutique hotel", "12 rooms", "35000000", 35000, "A small hospitality asset demonstrating diversified property access.", "Seasonality and hospitality operating risk."),
    ShowcaseProperty("Metro Logistics Hub", "METRO", "Chakan, Pune", "Warehouse", "8,000 sq. ft.", "24000000", 24000, "A logistics-oriented warehouse close to a major industrial corridor.", "Industrial tenant and logistics-cycle risk."),
    ShowcaseProperty("Palm Haven Villa", "PALM", "North Goa", "Holiday villa", "3,200 sq. ft.", "27500000", 27500, "A leisure property illustrating an owner-led hospitality opportunity.", "Seasonality and holiday-demand risk."),
    ShowcaseProperty("Summit Business Centre", "SUMMIT", "Bhopal", "Commercial property", "6,000 sq. ft.", "45000000", 45000, "A larger commercial asset for demonstrating institutional-style property data.", "Commercial leasing and valuation uncertainty."),
)

INVESTOR_IDS = {
    "Rohan": "00000000-0000-4000-8000-000000000007", "Priya": "00000000-0000-4000-8000-000000000008",
    "Vikram": "00000000-0000-4000-8000-000000000009", "Ananya": "00000000-0000-4000-8000-000000000010",
    "Neha": "00000000-0000-4000-8000-000000000011", "Arjun": "00000000-0000-4000-8000-000000000012",
}
MEERA_ID = "00000000-0000-4000-8000-000000000006"
ALLOCATIONS = {
    "OAK": {"Aarav": 150, "Priya": 100}, "GREEN": {"Rohan": 1000, "Priya": 500},
    "NEST": {"Aarav": 250, "Rohan": 750}, "CORNER": {"Priya": 550},
    "HILL": {"Aarav": 100, "Vikram": 300}, "METRO": {"Aarav": 200, "Rohan": 800},
    "PALM": {"Neha": 350}, "SUMMIT": {"Aarav": 100, "Arjun": 900},
}
OFFERINGS = {item.symbol: max(1000, item.supply // 10) for item in CATALOGUE}
BORROWER_POSITIONS = (
    ("Rohan", "GREEN"), ("Priya", "CORNER"), ("Vikram", "HILL"),
    ("Neha", "PALM"), ("Arjun", "SUMMIT"),
)
LENDER_STATES = {
    "axim-bank": {"APPLIED": 3, "APPROVED": 2, "REJECTED": 2, "DISBURSED": 3, "RELEASED": 2},
    "real-finance": {"APPLIED": 2, "APPROVED": 3, "REJECTED": 2, "DISBURSED": 2, "RELEASED": 1},
    "horizon-credit": {"APPLIED": 3, "APPROVED": 2, "REJECTED": 1, "DISBURSED": 3, "RELEASED": 2},
}
LENDER_OFFERS = {"axim-bank": ("axim-standard", 1000, 60, 12), "real-finance": ("real-flex", 900, 55, 12), "horizon-credit": ("horizon-liquidity", 1200, 70, 12)}
# Maximum repayment for the fixed showcase payload: principal 60,000 plus
# Horizon Credit's 7,200 interest. This also covers a loan already disbursed
# before a resumed run adds the cash buffer.
REPAYMENT_BUFFER_MINOR = 67_200
LOAN_STATES = ("APPLIED", "ASSESSED", "APPROVED", "DISBURSED", "REPAID", "RELEASED")


def api(base: str, token: str | None, path: str, method: str = "GET", payload: dict | None = None, key: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if key:
        headers["Idempotency-Key"] = key
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(base.rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read(16_385).decode())
            error = detail.get("error", {}) if isinstance(detail, dict) else {}
            code = error.get("code", "HTTP_ERROR")
            message = error.get("message", "The API rejected the request.")
            detail_text = f" code={code} message={message}" if isinstance(code, str) and isinstance(message, str) else ""
        except (ValueError, UnicodeDecodeError):
            detail_text = ""
        raise RuntimeError(f"API request failed: HTTP {exc.code} {exc.reason} {method} {path}.{detail_text}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"API request failed: {method} {path}: {exc.reason}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("data"), (dict, list)):
        raise RuntimeError(f"Unexpected API response for {method} {path}")
    return value["data"]


def login(base: str, username: str) -> tuple[str, dict]:
    data = api(base, None, "/api/v1/auth/login", "POST", {"username": username, "password": "TokANSH@123"})
    return data["access_token"], data


def registration_command(item: ShowcaseProperty, property_id: str) -> tuple[dict, str]:
    operation_id = str(uuid5(SHOWCASE_NAMESPACE, f"registration:{item.symbol}"))
    approval_reference = str(uuid5(SHOWCASE_NAMESPACE, f"approval:{item.symbol}"))
    approval_digest = hashlib.sha256(json.dumps(asdict(item), sort_keys=True).encode()).hexdigest()
    command = {
        "command_version": 1, "operation_id": operation_id, "property_id": property_id,
        "issuer_id": "00000000-0000-4000-8000-000000000006", "approval_reference": approval_reference,
        "approval_digest": approval_digest, "approved_supply": item.supply,
        "issue_price_minor": "100000", "currency": "INR",
    }
    return command, operation_id


def operator_step(action: str, reference: str) -> None:
    if not BACKEND_PYTHON.exists():
        raise RuntimeError(f"Missing backend interpreter: {BACKEND_PYTHON}")
    subprocess.run([str(BACKEND_PYTHON), "-m", "app.registration_operator", action, reference], cwd=ROOT / "backend", check=True)


def reconcile_if_unresolved(base: str, token: str, result: dict, endpoint: str) -> dict:
    """Resolve a persisted operation without ever creating a replacement."""
    state = result.get("state")
    if state in {"PREPARING", "PREPARED", "SUBMISSION_PENDING", "SUBMITTED", "UNKNOWN"}:
        operation_id = result.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            raise RuntimeError(f"Unresolved {endpoint} operation has no operation_id; reconcile manually before retrying")
        result = api(base, token, f"{endpoint}/{operation_id}/reconcile", "POST")
    return result


def database_path() -> Path:
    url = os.environ.get("DATABASE_URL", "sqlite:///" + str(Path.home() / ".local/share/tokansh/tokansh.db"))
    if not url.startswith("sqlite:///"):
        raise RuntimeError("DATABASE_URL must be a local SQLite URL")
    return Path(url.removeprefix("sqlite:///"))


def backup_database() -> Path:
    source = database_path().expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"Persistent database is unavailable: {source}")
    with sqlite3.connect(source) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        if revision != ("0005_showcase_metadata",):
            raise RuntimeError(f"Expected migration 0005_showcase_metadata, found {revision!r}")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise RuntimeError(f"Persistent database integrity check failed: {integrity!r}")
        backup_dir = source.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"tokansh_pre_showcase_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
        with sqlite3.connect(target) as backup:
            connection.backup(backup)
    return target


def fund_investor_to_target(base: str, username: str, target_minor: int) -> None:
    token, _ = login(base, username)
    wallet = api(base, token, "/api/v1/demo-wallet")
    try:
        available = int(wallet["available_minor"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Wallet response for {username} has no valid available_minor") from exc
    if available >= target_minor:
        print(f"wallet borrower={username} available={available} target={target_minor} action=none")
        return
    amount = target_minor - available
    api(base, token, "/api/v1/demo-wallet/fund", "POST", {"amount_minor": str(amount)},
        "showcase-wallet-" + username.lower())
    print(f"wallet borrower={username} available_before={available} funded={amount} target={target_minor}")


def transition_actions(current: str, target: str) -> list[str]:
    if current not in (*LOAN_STATES, "REJECTED") or target not in (*LOAN_STATES, "REJECTED"):
        raise RuntimeError(f"Unsupported lender state transition: current={current!r} target={target!r}")
    if current == target:
        return []
    if current == "REJECTED" or target == "REJECTED":
        if target == "REJECTED" and current in {"APPLIED", "ASSESSED"}:
            return (["assess"] if current == "APPLIED" else []) + ["reject"]
        raise RuntimeError(f"Incompatible lender state transition: current={current} target={target}")
    states = list(LOAN_STATES)
    current_index, target_index = states.index(current), states.index(target)
    if current_index > target_index:
        raise RuntimeError(f"Loan already passed target state: current={current} target={target}")
    return ["assess", "approve", "disburse", "repay", "release"][current_index:target_index]


def advance_loan(base: str, lender_id: str, borrower: str, loan: dict,
                 borrower_token: str, lender_token: str, target: str) -> dict:
    loan_id, current = loan.get("id"), loan.get("state")
    if not isinstance(loan_id, str):
        raise RuntimeError(f"Lender {lender_id} returned an application without an id")
    actions = transition_actions(current, target)
    print(f"loan lender={lender_id} borrower={borrower} loan={loan_id} current={current} target={target}")
    for action in actions:
        token = borrower_token if action in {"repay", "release"} else lender_token
        result = api(base, token, f"/api/v1/financing/applications/{loan_id}/{action}", "POST")
        next_state = result.get("state")
        if not isinstance(next_state, str):
            raise RuntimeError(f"Loan {loan_id} action={action} returned no state")
        current = next_state
        print(f"loan lender={lender_id} borrower={borrower} loan={loan_id} action={action} state={current} target={target}")
    if current != target:
        raise RuntimeError(f"Loan {loan_id} stopped at {current}; target was {target}")
    return {**loan, "state": current}


def plan() -> None:
    print(json.dumps({"catalogue": [asdict(item) for item in CATALOGUE], "initial_issue_price_minor": "100000", "properties": len(CATALOGUE), "lender_state_targets": LENDER_STATES, "note": "REIT positions remain illustrative frontend representations and are not ledger records."}, indent=2))


def provision_lenders(base: str, property_rows: dict[str, dict]) -> dict[str, dict[str, str]]:
    showcase_loans: dict[str, dict[str, str]] = {lender_id: {} for lender_id in LENDER_STATES}
    for lender_id, targets in LENDER_STATES.items():
        lender_token, _ = login(base, lender_id)
        offer_id, rate, ltv, term = LENDER_OFFERS[lender_id]
        index = 0
        for state, count in targets.items():
            for ordinal in range(count):
                borrower, symbol = BORROWER_POSITIONS[index % len(BORROWER_POSITIONS)]
                index += 1
                borrower_token, _ = login(base, borrower)
                property_id = property_rows[symbol]["id"]
                key = f"showcase-loan-{lender_id}-{state.lower()}-{ordinal + 1}"
                loan = api(base, borrower_token, "/api/v1/financing/applications", "POST", {
                    "property_id": property_id, "asset_class": "ANSH", "lender_id": lender_id,
                    "offer_id": offer_id, "quantity": 1, "unit_value_minor": "100000",
                    "ltv_percent": ltv, "annual_rate_bps": rate, "term_months": term,
                }, key)
                advance_loan(base, lender_id, borrower, loan, borrower_token, lender_token, state)
                showcase_loans[lender_id][loan["id"]] = state
    print_showcase_summary(base, showcase_loans)
    return showcase_loans


def print_showcase_summary(base: str, showcase_loans: dict[str, dict[str, str]]) -> None:
    print("showcase loan summary:")
    for lender_id, expected in showcase_loans.items():
        token, _ = login(base, lender_id)
        rows = api(base, token, "/api/v1/financing/applications")
        by_id = {row.get("id"): row for row in rows if isinstance(row, dict)}
        counts = {state: 0 for state in ("APPLIED", "APPROVED", "REJECTED", "DISBURSED", "RELEASED")}
        missing = []
        for loan_id in expected:
            row = by_id.get(loan_id)
            if row is None:
                missing.append(loan_id)
            elif row.get("state") in counts:
                counts[row["state"]] += 1
        if missing:
            raise RuntimeError(f"Lender {lender_id} cannot read {len(missing)} provisioned applications")
        print(f"  {lender_id}: {counts}")
        target_counts = {state: LENDER_STATES[lender_id][state] for state in counts}
        if counts != target_counts:
            raise RuntimeError(f"Lender {lender_id} showcase counts do not match target: actual={counts} target={target_counts}")


def existing_showcase_properties(base: str) -> dict[str, dict]:
    token, _ = login(base, "Meera")
    properties = api(base, token, "/api/v1/properties")
    by_symbol = {value.get("ansh_symbol"): value for value in properties.get("items", []) if isinstance(value, dict)}
    missing = ["ANSH-" + item.symbol for item in CATALOGUE if "ANSH-" + item.symbol not in by_symbol]
    if missing:
        raise RuntimeError("Lender-only provisioning requires existing showcase properties: missing " + ", ".join(missing))
    return {item.symbol: by_symbol["ANSH-" + item.symbol] for item in CATALOGUE}


def provision_lenders_only(base: str) -> None:
    backup = backup_database()
    print(f"Created SQLite backup: {backup}")
    property_rows = existing_showcase_properties(base)
    for borrower in dict.fromkeys(name for name, _ in BORROWER_POSITIONS):
        fund_investor_to_target(base, borrower, REPAYMENT_BUFFER_MINOR)
    provision_lenders(base, property_rows)
    print("Lender-only provisioning completed using existing properties and deterministic loan keys.")


def apply(base: str) -> None:
    backup = backup_database()
    print(f"Created SQLite backup: {backup}")
    token, _ = login(base, "Meera")
    properties = api(base, token, "/api/v1/properties")
    by_symbol = {value.get("ansh_symbol"): value for value in properties.get("items", []) if isinstance(value, dict)}
    showcase_rows: dict[str, dict] = {}
    for item in CATALOGUE:
        payload = {
            "name": item.name, "friendly_symbol": item.symbol, "location": item.location,
            "category": item.category, "size": item.size, "description": item.description,
            "risk_profile": item.risk_profile, "valuation": item.valuation,
            "proposed_supply": item.supply, "issue_price": "1000", "currency": "INR",
        }
        existing = by_symbol.get("ANSH-" + item.symbol)
        if existing is None:
            existing = api(base, token, "/api/v1/properties", "POST", payload, "showcase-property-" + item.symbol)
            by_symbol["ANSH-" + item.symbol] = existing
        if existing.get("ansh_symbol") != "ANSH-" + item.symbol or existing.get("proposed_supply") != item.supply:
            raise RuntimeError(f"Existing {item.symbol} property does not match the approved showcase catalogue")
        showcase_rows[item.symbol] = existing
        with tempfile.NamedTemporaryFile("w", prefix=f"tokansh-{item.symbol}-", suffix=".json", delete=False) as command_file:
            command, operation_id = registration_command(item, existing["id"])
            json.dump(command, command_file, indent=2)
            command_path = command_file.name
        try:
            operator_step("prepare", command_path)
            operator_step("submit", operation_id)
            operator_step("reconcile", operation_id)
        finally:
            Path(command_path).unlink(missing_ok=True)
        issuance = api(base, token, "/api/v1/ansh/issuances", "POST", {
            "property_id": existing["id"], "quantity": item.supply,
            "issue_price_minor": "100000", "currency": "INR",
        }, "showcase-issuance-" + item.symbol)
        issuance = reconcile_if_unresolved(base, token, issuance, "/api/v1/ansh/issuances")
        if issuance.get("state") != "COMMITTED_VALID":
            raise RuntimeError(f"Issuance {item.symbol} did not commit: {issuance.get('state')}")
        for name, quantity in ALLOCATIONS[item.symbol].items():
            recipient = "00000000-0000-4000-8000-000000000003" if name == "Aarav" else INVESTOR_IDS[name]
            transfer = api(base, token, "/api/v1/ansh/transfers", "POST", {
                "asset_id": existing["id"], "from_user_id": MEERA_ID, "to_user_id": recipient,
                "quantity": quantity, "kind": "TRANSFER", "payment_outcome": "SUCCESS",
            }, "showcase-transfer-" + item.symbol + "-" + name.lower())
            transfer = reconcile_if_unresolved(base, token, transfer, "/api/v1/ansh/transfers")
            if transfer.get("state") != "COMMITTED_VALID":
                raise RuntimeError(f"Transfer {item.symbol}/{name} did not commit: {transfer.get('state')}")
        offerings = api(base, token, "/api/v1/marketplace/offerings")
        if not any(value.get("property_id") == existing["id"] and value.get("status") == "ACTIVE" for value in offerings):
            api(base, token, "/api/v1/marketplace/offerings", "POST", {
                "property_id": existing["id"], "quantity": OFFERINGS[item.symbol],
            })
    for username, target_minor in (("Meera", 45_000_000), ("Aarav", 20_000_000)):
        fund_investor_to_target(base, username, target_minor)
    for borrower in dict.fromkeys(name for name, _ in BORROWER_POSITIONS):
        fund_investor_to_target(base, borrower, REPAYMENT_BUFFER_MINOR)
    provision_lenders(base, showcase_rows)
    print("Showcase properties, ownership allocations, offerings, wallets and lender applications completed through existing workflows.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=os.environ.get("TOKANSH_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--apply", action="store_true", help="perform authenticated application and ledger workflows")
    parser.add_argument("--allow-live-writes", action="store_true", help="required with --apply")
    parser.add_argument("--lenders-only", action="store_true", help="resume only supporting-investor funding and lender applications")
    args = parser.parse_args()
    if args.lenders_only and not args.apply:
        raise SystemExit("Refusing lender-only provisioning without --apply.")
    if not args.apply:
        plan()
        return 0
    if not args.allow_live_writes:
        raise SystemExit("Refusing live provisioning: pass --apply --allow-live-writes explicitly.")
    if args.lenders_only:
        provision_lenders_only(args.api)
    else:
        apply(args.api)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
