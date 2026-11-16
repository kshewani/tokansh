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
        # render_as_batch lets later migrations alter tables on SQLite.
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True, render_item=render_item, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
