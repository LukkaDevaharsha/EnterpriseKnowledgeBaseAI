from app import db
from app.models import AuditEvent


def record_admin_action(actor_id, action, subject_type, subject_id, details=None):
    db.session.add(AuditEvent(
        actor_user_id=actor_id,
        action=action,
        subject_type=subject_type,
        subject_id=str(subject_id) if subject_id is not None else None,
        details=details or {},
    ))
