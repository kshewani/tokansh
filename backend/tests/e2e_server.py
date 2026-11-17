"""TEST-ONLY API server for automated browser tests of the frontend wiring.

!!! Not a demo mode and not DRUNIX. !!! It injects the test fake ledger, whose
transaction ids all start with "TEST-ONLY-". It refuses to start unless
TOKANSH_E2E_TEST=1, and uses a throwaway database. Use it only for automated
UI tests; the demonstration must run against a real DRUNIX gateway.

    TOKANSH_E2E_TEST=1 python -m tests.e2e_server --port 8001
"""
import argparse
import os
import sys
import tempfile

import uvicorn
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import Base
from app.db.session import make_engine
from app.main import create_app
from scripts.seed_demo import seed
from tests.fakes.fake_ledger import FakeLedger


def main() -> None:
    if os.environ.get("TOKANSH_E2E_TEST") != "1":
        sys.exit("Refusing to start: this TEST-ONLY server needs TOKANSH_E2E_TEST=1 and is not a demo mode.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    url = f"sqlite:///{tempfile.mkdtemp(prefix='tokansh-e2e-')}/e2e.db"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        seed(s)
    settings = Settings(app_env="e2e-test", database_url=url, drunix_gateway_url="http://test-only.invalid",
                        commit_poll_attempts=1, commit_poll_interval_seconds=0)
    uvicorn.run(create_app(settings, ledger=FakeLedger()), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
