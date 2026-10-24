"""Repair visibility for documents recorded as Admin shared uploads.

Revision ID: b7d8e2c1045f
Revises: a31b7d4e9c20
"""
from alembic import op
import sqlalchemy as sa


revision = "b7d8e2c1045f"
down_revision = "a31b7d4e9c20"
branch_labels = None
depends_on = None


def upgrade():
    # Only audit events emitted by the Admin shared-upload workflow are used as
    # evidence. Private uploads have no such event and remain private.
    op.execute(sa.text("""
        UPDATE documents
        SET is_shared = TRUE
        WHERE is_shared = FALSE
          AND EXISTS (
              SELECT 1
              FROM audit_events
              WHERE audit_events.action = 'shared_document.upload'
                AND audit_events.subject_type = 'document'
                AND audit_events.subject_id = CAST(documents.id AS VARCHAR)
          )
    """))


def downgrade():
    # A data repair cannot safely be reversed: records may have been updated
    # again after this migration, and the original visibility is not retained.
    pass
