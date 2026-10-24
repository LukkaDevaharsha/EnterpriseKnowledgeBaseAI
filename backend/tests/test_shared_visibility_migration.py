import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = (
    Path(__file__).parents[1] / "migrations" / "versions"
    / "b7d8e2c1045f_repair_audited_shared_visibility.py"
)


def test_visibility_migration_repairs_only_audited_shared_uploads(monkeypatch):
    spec = importlib.util.spec_from_file_location("shared_visibility_migration", MIGRATION_PATH)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE documents (id INTEGER PRIMARY KEY, is_shared BOOLEAN NOT NULL)"
        ))
        connection.execute(sa.text("""
            CREATE TABLE audit_events (
                action VARCHAR(80), subject_type VARCHAR(40), subject_id VARCHAR(80)
            )
        """))
        connection.execute(sa.text(
            "INSERT INTO documents (id, is_shared) VALUES (1, FALSE), (2, FALSE)"
        ))
        connection.execute(sa.text("""
            INSERT INTO audit_events (action, subject_type, subject_id)
            VALUES ('shared_document.upload', 'document', '1')
        """))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))

        migration.upgrade()

        rows = connection.execute(sa.text(
            "SELECT id, is_shared FROM documents ORDER BY id"
        )).all()
    assert rows == [(1, True), (2, False)]
