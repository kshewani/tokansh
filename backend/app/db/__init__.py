"""TokANSH application database (ADR-009).

This is the application database only. It is not the DRUNIX ledger and never
touches DRUNIX's internal YugabyteDB (ADR-008). Ledger-backed data held here is
a projection that carries its ledger reference (ADR-007).
"""
from app.db.base import Base
from app.db import models  # noqa: F401  (registers every table on Base.metadata)

__all__ = ["Base", "models"]
