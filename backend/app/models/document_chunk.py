from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import ARRAY

from app import db


class DocumentChunk(db.Model):
    __tablename__ = "document_chunks"
    __table_args__ = (
        db.UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_document_index"
        ),
        db.CheckConstraint("chunk_index >= 0", name="ck_document_chunks_index_nonnegative"),
        db.CheckConstraint("start_char >= 0", name="ck_document_chunks_start_nonnegative"),
        db.CheckConstraint("end_char > start_char", name="ck_document_chunks_valid_offsets"),
        db.Index("ix_document_chunks_document_id", "document_id"),
        db.CheckConstraint(
            "embedding IS NULL OR (array_ndims(embedding) = 1 AND cardinality(embedding) = 384)",
            name="ck_document_chunks_embedding_dimension",
        ),
        db.CheckConstraint(
            "embedding_status <> 'PROCESSED' OR (embedding IS NOT NULL AND embedding_model IS NOT NULL AND embedding_content_hash IS NOT NULL)",
            name="ck_document_chunks_processed_embedding_complete",
        ),
        db.CheckConstraint(
            "embedding_status IN ('PENDING', 'PROCESSING', 'PROCESSED', 'FAILED')",
            name="ck_document_chunks_embedding_status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(
        db.Integer,
        db.ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, nullable=False)
    start_char = db.Column(db.Integer, nullable=False)
    end_char = db.Column(db.Integer, nullable=False)
    embedding = db.Column(ARRAY(db.Float), nullable=True)
    embedding_model = db.Column(db.String(255), nullable=True)
    embedding_content_hash = db.Column(db.String(64), nullable=True)
    embedding_status = db.Column(
        db.String(20), nullable=False, default="PENDING", server_default="PENDING"
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    document = db.relationship("Document", backref=db.backref("chunks", lazy="select"))
