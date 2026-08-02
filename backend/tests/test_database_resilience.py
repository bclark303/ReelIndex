from sqlalchemy import inspect
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import engine, init_db
from app.models import Base


def test_sqlite_uses_fresh_connections():
    if engine.dialect.name == "sqlite":
        assert isinstance(engine.pool, NullPool)


def test_init_db_creates_complete_registered_schema():
    init_db()
    expected = set(Base.metadata.tables)
    existing = set(inspect(engine).get_table_names())
    assert expected <= existing


def test_sqlite_uses_configured_journal_mode():
    if engine.dialect.name != "sqlite":
        return
    init_db()
    with engine.connect() as connection:
        active = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
    assert str(active).upper() == settings.sqlite_journal_mode.strip().upper()
