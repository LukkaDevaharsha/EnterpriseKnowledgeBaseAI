from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import JSONB

from app import db


class AuditEvent(db.Model):
    __tablename__ = "audit_events"

    id = db.Column(db.BigInteger, primary_key=True)
    actor_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action = db.Column(db.String(80), nullable=False, index=True)
    subject_type = db.Column(db.String(40), nullable=False)
    subject_id = db.Column(db.String(80), nullable=True)
    details = db.Column(JSONB, nullable=False, default=dict)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    actor = db.relationship("User", foreign_keys=[actor_user_id])
