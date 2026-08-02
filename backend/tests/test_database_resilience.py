from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

from app.core import database as database_module
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


def test_init_db_repairs_partial_schema(tmp_path, monkeypatch):
    partial_engine = create_engine(
        f"sqlite:///{tmp_path / 'partial.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    Base.metadata.tables["sources"].create(bind=partial_engine)
    assert set(inspect(partial_engine).get_table_names()) == {"sources"}

    monkeypatch.setattr(database_module, "engine", partial_engine)
    database_module.init_db()

    expected = set(Base.metadata.tables)
    existing = set(inspect(partial_engine).get_table_names())
    assert expected <= existing
    partial_engine.dispose()


def test_sqlite_uses_configured_journal_mode():
    if engine.dialect.name != "sqlite":
        return
    init_db()
    with engine.connect() as connection:
        active = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
    assert str(active).upper() == settings.sqlite_journal_mode.strip().upper()
