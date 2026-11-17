"""Alembic environment for the TokANSH application database."""
import os
from logging.config import fileConfig

from alembic import context

from app.db import Base
from app.db.session import database_url, make_engine
from app.db.types import UTCDateTime

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or database_url()


def render_item(type_, obj, autogen_context):
    # Keep migrations self-contained: render the custom type as its plain SQL type.
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite:///") and ":memory:" not in url:
        folder = os.path.dirname(url[len("sqlite:///"):])
        if folder:
            os.makedirs(folder, exist_ok=True)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True, render_item=render_item, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _url()
    _ensure_sqlite_dir(url)
    engine = make_engine(url)
    with engine.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            # Batch mode alters a SQLite table by copying it and dropping the original. With foreign
            # keys on, that drop fails as soon as another table references a row. Switch them off for
            # the migration (this pragma is ignored inside a transaction, so it runs first) and verify
            # every reference afterwards instead.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        # render_as_batch lets later migrations alter tables on SQLite.
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True, render_item=render_item, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
            if sqlite:
                broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise RuntimeError(f"migration left broken foreign keys: {broken[:5]}")
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
