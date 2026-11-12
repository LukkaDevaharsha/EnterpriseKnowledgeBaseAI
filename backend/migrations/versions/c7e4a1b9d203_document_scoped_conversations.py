"""Associate conversations with an optional Study document."""
from alembic import op
import sqlalchemy as sa

revision = "c7e4a1b9d203"
down_revision = "f6b8a2c14d90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("conversations", sa.Column("document_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_conversations_document_id_documents", "conversations", "documents", ["document_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_conversations_document_id", "conversations", ["document_id"])


def downgrade():
    op.drop_index("ix_conversations_document_id", table_name="conversations")
    op.drop_constraint("fk_conversations_document_id_documents", "conversations", type_="foreignkey")
    op.drop_column("conversations", "document_id")
