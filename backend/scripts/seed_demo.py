"""Seed synthetic demonstration data into the TokANSH application database.

    python -m scripts.seed_demo                  # users + simulated REIT holdings
    python -m scripts.seed_demo --with-property  # also TechPark One as a DRAFT property

Safe to run repeatedly: rows have fixed identifiers and are skipped when present.

Deliberately NOT seeded: issuances, ownership positions, pledges, listings and
anything else that is ledger-backed. Those rows may only appear after a genuine
DRUNIX commit (ADR-005, ADR-007); seeding them would fabricate ledger state.
"""
import argparse
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import models as m
from app.db.enums import DocumentType, PropertyStatus, UserRole, ValuationPurpose
from app.db.session import init_engine

NS = uuid.UUID("6f1c2a54-0d7e-4a55-9a53-70b1c0a5e001")
INR = 100  # paise per rupee
CRORE = 10_000_000 * INR
OBSERVED = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)

# Illustrative figures from AGENTS.md section 8 and BUSINESS_RULES section 14.
TECHPARK_VALUATION = 100 * CRORE   # INR 100 crore
TECHPARK_SUPPLY = 100_000          # ANSH
TECHPARK_UNIT_VALUE = 10_000 * INR  # INR 10,000 per ANSH


def sid(name: str) -> str:
    return str(uuid.uuid5(NS, name))


# (seed key, display name, email, role, demo login username). Lenders are fictional institutions.
USERS = [
    ("meera", "Meera", "meera@demo.tokansh.example", UserRole.ISSUER, "meera"),
    ("admin", "Platform Admin", "admin@demo.tokansh.example", UserRole.ADMIN, "admin"),
    ("aarav", "Aarav", "aarav@demo.tokansh.example", UserRole.INVESTOR, "aarav"),
    ("lender", "Axim Bank", "axim-bank@demo.tokansh.example", UserRole.LENDER, "axim-bank"),
    ("real-finance", "Real Finance", "real-finance@demo.tokansh.example", UserRole.LENDER, "real-finance"),
    ("horizon-credit", "Horizon Credit", "horizon-credit@demo.tokansh.example", UserRole.LENDER, "horizon-credit"),
]

# Synthetic REIT rows: invented names and values, labelled simulated (ADR-019).
REITS = [
    ("DEMO-REIT-A", "Demo Office REIT A", 400, 120_000 * INR, 131_200 * INR),
    ("DEMO-REIT-B", "Demo Retail REIT B", 250, 87_500 * INR, 84_750 * INR),
]


def _add(session: Session, model, pk: str, **values) -> bool:
    if session.get(model, pk) is not None:
        return False
    session.add(model(id=pk, **values))
    return True


def seed(session: Session, with_property: bool = False) -> dict:
    created = {"users": 0, "reit_holdings": 0, "properties": 0}
    for key, name, email, role, username in USERS:
        created["users"] += _add(session, m.User, sid(f"user:{key}"), full_name=name, email=email,
                                 role=role, ledger_identity_ref=username)
    session.flush()
    for ident, name, qty, cost, value in REITS:
        created["reit_holdings"] += _add(
            session, m.ReitHolding, sid(f"reit:aarav:{ident}"), investor_id=sid("user:aarav"),
            reit_identifier=ident, reit_name=name, quantity=qty, purchase_value_minor=cost,
            illustrative_market_value_minor=value, data_source="TokANSH REIT simulator",
            is_simulated=True, observed_at=OBSERVED)
    if with_property:
        pid = sid("property:techpark-one")
        if _add(session, m.Property, pid, property_name="TechPark One", property_type="COMMERCIAL_OFFICE",
                description="Synthetic demonstration property.", address="Demo Address, Whitefield",
                city="Bengaluru", country="India", illustrative_valuation_minor=TECHPARK_VALUATION,
                proposed_supply=TECHPARK_SUPPLY, proposed_issue_price_minor=TECHPARK_UNIT_VALUE,
                issuer_id=sid("user:meera"), approval_status=PropertyStatus.DRAFT, is_synthetic=True):
            created["properties"] += 1
            session.flush()
            for dtype, name in [(DocumentType.TITLE_DEED, "Title deed (synthetic)"),
                                (DocumentType.VALUATION_REPORT, "Valuation report (synthetic)"),
                                (DocumentType.LEASE_AGREEMENT, "Lease agreement (synthetic)")]:
                session.add(m.PropertyDocument(property_id=pid, document_type=dtype, document_name=name,
                                               document_reference=f"demo://techpark-one/{dtype.value.lower()}"))
            for purpose in (ValuationPurpose.ILLUSTRATIVE_MARKET, ValuationPurpose.COLLATERAL):
                session.add(m.PropertyValuation(
                    property_id=pid, purpose=purpose, property_value_minor=TECHPARK_VALUATION,
                    unit_value_minor=TECHPARK_UNIT_VALUE, valuation_source="TokANSH valuation simulator",
                    is_simulated=True, observed_at=OBSERVED))
    session.commit()
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with-property", action="store_true", help="also create TechPark One as a DRAFT property")
    args = parser.parse_args()
    engine = init_engine()
    with Session(engine) as session:
        print("seeded:", seed(session, with_property=args.with_property))


if __name__ == "__main__":
    main()
