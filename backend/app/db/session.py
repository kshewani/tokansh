"""Engine and session factory for the TokANSH application database."""
import os

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_URL = "sqlite:///./data/tokansh.db"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def make_engine(url: str | None = None) -> sa.Engine:
    url = url or database_url()
    engine = sa.create_engine(url, future=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")  # SQLite ignores foreign keys unless asked
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()
    return engine


engine = None
SessionLocal = None


def init_engine(url: str | None = None) -> sa.Engine:
    global engine, SessionLocal
    engine = make_engine(url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return engine


def get_session():
    """FastAPI dependency: one session per request, rolled back on error."""
    if SessionLocal is None:
        init_engine()
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
