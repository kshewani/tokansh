from pathlib import Path

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


SCHEMA_REVISION = "0001_m2"


class Database:
    def __init__(self, url: str):
        self.engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 10})

        @event.listens_for(self.engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def ready(self) -> bool:
        from app.properties.models import ApplicationOperation, Property, PropertyEvent
        from sqlalchemy.exc import SQLAlchemyError

        try:
            with self.engine.connect() as connection:
                revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                for model in (Property, ApplicationOperation, PropertyEvent):
                    connection.execute(select(model).limit(0))
                return revision == SCHEMA_REVISION
        except SQLAlchemyError:
            return False


def prepare_database_directory(url: str) -> None:
    """Only migration/bootstrap code prepares the local database directory."""
    from sqlalchemy.engine import make_url
    database = make_url(url).database
    if database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
