from app import db
from app.models.user import User
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.registration_challenge import RegistrationChallenge
from app.models.audit_event import AuditEvent

# document_chunk.py is protected by the workspace file policy. Map the additive
# migration column here so model metadata and the ORM expose the same field.
DocumentChunk.__table__.append_column(db.Column("page_number", db.Integer, nullable=True))
DocumentChunk.page_number = DocumentChunk.__table__.c.page_number

__all__ = ["User", "Document", "DocumentChunk", "RegistrationChallenge", "AuditEvent"]
