from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import Base

_is_sqlite = settings.db_url.startswith("sqlite")
engine_options: dict = {"pool_pre_ping": True}
if _is_sqlite:
    # Unraid user shares can move or replace the underlying SQLite file while a
    # container is running. Avoid retaining pooled handles to an old inode and
    # wait briefly for ordinary concurrent writes instead of failing at once.
    engine_options["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine_options["poolclass"] = NullPool

engine = create_engine(settings.db_url, **engine_options)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _upgrade_library_identity() -> None:
    # Imported lazily to avoid a database/session import cycle while models are
    # being registered. The upgrade is idempotent and also consolidates legacy
    # cross-source duplicates before the API starts serving requests.
    from app.services.library_identity import upgrade_library_identity

    with SessionLocal() as db:
        upgrade_library_identity(db)


def init_db() -> None:
    if not _is_sqlite:
        Base.metadata.create_all(bind=engine)
        _upgrade_library_identity()
        return

    journal_mode = settings.sqlite_journal_mode.strip().upper()
    supported_modes = {"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"}
    if journal_mode not in supported_modes:
        raise RuntimeError(
            "REELINDEX_SQLITE_JOURNAL_MODE must be one of "
            + ", ".join(sorted(supported_modes))
        )

    # Set the persistent journal mode before creating or validating tables.
    # DELETE is the safe default for bind-mounted Unraid appdata paths; WAL can
    # still be selected explicitly for a local filesystem that supports it.
    with engine.connect() as connection:
        active_mode = connection.exec_driver_sql(f"PRAGMA journal_mode={journal_mode}").scalar_one()
        if str(active_mode).upper() != journal_mode:
            raise RuntimeError(
                f"SQLite refused journal mode {journal_mode}; active mode is {active_mode}"
            )
        Base.metadata.create_all(bind=connection)
        connection.commit()

        expected_tables = set(Base.metadata.tables)
        existing_tables = set(inspect(connection).get_table_names())
        missing_tables = sorted(expected_tables - existing_tables)
        if missing_tables:
            raise RuntimeError(
                "SQLite schema initialization is incomplete; missing tables: "
                + ", ".join(missing_tables)
            )

    _upgrade_library_identity()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
