"""Add verified registration, shared docs, admin audit, employee ID sequence.

Revision ID: a31b7d4e9c20
Revises: d5b2c4e819a7
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a31b7d4e9c20"
down_revision = "d5b2c4e819a7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("is_verified", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "documents",
        sa.Column("is_shared", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("documents", sa.Column("processing_error", sa.String(255), nullable=True))
    op.add_column("document_chunks", sa.Column("page_number", sa.Integer(), nullable=True))

    op.create_table(
        "registration_challenges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("department", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resend_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_registration_challenges_email", "registration_challenges", ["email"], unique=True
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("subject_type", sa.String(40), nullable=False),
        sa.Column("subject_id", sa.String(80), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"], unique=False)


def downgrade():
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_registration_challenges_email", table_name="registration_challenges")
    op.drop_table("registration_challenges")
    op.drop_column("document_chunks", "page_number")
    op.drop_column("documents", "processing_error")
    op.drop_column("documents", "is_shared")
    op.drop_column("users", "is_verified")
