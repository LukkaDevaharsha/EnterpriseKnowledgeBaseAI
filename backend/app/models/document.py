from datetime import datetime, timezone

from app import db


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(36), unique=True, nullable=False)
    file_type = db.Column(db.String(10), nullable=False)
    file_size = db.Column(db.BigInteger, nullable=False)

    status = db.Column(
        db.String(20),
        nullable=False,
        default="UPLOADED",
    )

    extracted_text = db.Column(db.Text, nullable=True)
    is_shared = db.Column(db.Boolean, nullable=False, default=False, server_default="false")
    processing_error = db.Column(db.String(255), nullable=True)

    uploaded_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    uploader = db.relationship(
        "User",
        backref=db.backref("documents", lazy="select"),
    )

    def to_dict(self):
        """Return safe document metadata without stored paths or extracted text."""
        return {
            "id": self.id,
            "title": self.title,
            "original_filename": self.original_filename,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "status": self.status,
            "uploaded_by": self.uploaded_by,
            "is_shared": self.is_shared,
            "processing_error": self.processing_error,
            "created_at": (
                self.created_at.isoformat()
                if self.created_at
                else None
            ),
            "updated_at": (
                self.updated_at.isoformat()
                if self.updated_at
                else None
            ),
        }
