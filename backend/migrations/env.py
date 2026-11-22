from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.database import Base, prepare_database_directory
from app.wallet import DemoCashAccount, DemoCashEntry  # noqa: F401
from app.registration import LedgerOperation  # noqa: F401
from app.properties import models  # noqa: F401 -- register migration metadata

config = context.config
url = config.attributes.get("database_url") or Settings().database_url
target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    prepare_database_directory(url)
    engine = create_engine(url, poolclass=NullPool)
    with engine.connect() as connection:
        # SQLite DDL must participate in the migration transaction as well as version stamping.
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()
    engine.dispose()
