from datetime import datetime, timezone

from app import db


class Conversation(db.Model):
    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False, default="New chat")
    is_pinned = db.Column(db.Boolean, nullable=False, default=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    is_locked = db.Column(db.Boolean, nullable=False, default=False)
    share_token = db.Column(db.String(64), unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), index=True)
    messages = db.relationship("ConversationMessage", backref="conversation", cascade="all, delete-orphan", order_by="ConversationMessage.created_at")

    def to_dict(self, include_messages=False):
        result = {"id": self.id, "document_id": self.document_id, "title": self.title, "is_pinned": self.is_pinned,
                  "is_archived": self.is_archived, "is_locked": self.is_locked,
                  "updated_at": self.updated_at.isoformat() if self.updated_at else None,
                  "created_at": self.created_at.isoformat() if self.created_at else None,
                  "message_count": len(self.messages)}
        if include_messages:
            result["messages"] = [message.to_dict() for message in self.messages]
        return result


class ConversationMessage(db.Model):
    __tablename__ = "conversation_messages"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    citations = db.Column(db.JSON, nullable=False, default=list)
    extra_data = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    def to_dict(self):
        return {"id": self.id, "role": self.role, "content": self.content,
                "citations": self.citations or [], "metadata": self.extra_data or {},
                "created_at": self.created_at.isoformat() if self.created_at else None}
