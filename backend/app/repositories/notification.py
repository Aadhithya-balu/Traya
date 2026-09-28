"""In-app notifications queued for a registered person."""
from __future__ import annotations

from typing import Any

from app.models import Notification
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    model = Notification

    def recent(self, user_id: str, limit: int = 30) -> list[Notification]:
        return (
            self.db.query(Notification)
            .filter(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .all()
        )

    def unread_count(self, user_id: str) -> int:
        return (
            self.db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.read.is_(False))
            .count()
        )

    def enqueue(self, user_id: str, *, type: str, payload: dict[str, Any]) -> Notification:
        """Queue a notification.

        The payload is deliberately minimal: an emergency contact is told that
        their relative was identified and where, never the full clinical record.
        """
        note = Notification(user_id=user_id, type=type, payload=payload)
        self.db.add(note)
        self.db.flush()
        return note

    def mark_read(self, user_id: str, notification_id: str) -> bool:
        note = (
            self.db.query(Notification)
            .filter(Notification.id == notification_id, Notification.user_id == user_id)
            .first()
        )
        if note is None:
            return False
        note.read = True
        self.db.flush()
        return True
