"""add chunk embedding storage and processing status

Revision ID: d5b2c4e819a7
Revises: c41a9e72b6d3
Create Date: 2026-10-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d5b2c4e819a7"
down_revision = "c41a9e72b6d3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "document_chunks",
        sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("embedding_content_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column(
            "embedding_status",
            sa.String(length=20),
            server_default="PENDING",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_document_chunks_embedding_dimension",
        "document_chunks",
        "embedding IS NULL OR (array_ndims(embedding) = 1 AND cardinality(embedding) = 384)",
    )
    op.create_check_constraint(
        "ck_document_chunks_processed_embedding_complete",
        "document_chunks",
        "embedding_status <> 'PROCESSED' OR (embedding IS NOT NULL AND embedding_model IS NOT NULL AND embedding_content_hash IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_document_chunks_embedding_status",
        "document_chunks",
        "embedding_status IN ('PENDING', 'PROCESSING', 'PROCESSED', 'FAILED')",
    )


def downgrade():
    op.drop_constraint(
        "ck_document_chunks_embedding_status", "document_chunks", type_="check"
    )
    op.drop_constraint(
        "ck_document_chunks_processed_embedding_complete",
        "document_chunks",
        type_="check",
    )
    op.drop_constraint(
        "ck_document_chunks_embedding_dimension", "document_chunks", type_="check"
    )
    op.drop_column("document_chunks", "embedding_status")
    op.drop_column("document_chunks", "embedding_content_hash")
    op.drop_column("document_chunks", "embedding_model")
    op.drop_column("document_chunks", "embedding")
