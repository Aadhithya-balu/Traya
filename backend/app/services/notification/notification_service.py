"""Notification service. Pluggable providers behind a simple interface."""
from sqlalchemy.orm import Session

from app.models import Notification


def create_notification(
    db: Session,
    user_id: str,
    notification_type: str,
    payload: dict | None = None,
) -> Notification:
    note = Notification(
        user_id=user_id,
        type=notification_type,
        payload=payload or {},
    )
    db.add(note)
    db.commit()
    return note


def get_unread(db: Session, user_id: str, limit: int = 20) -> list[Notification]:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )


def mark_read(db: Session, notification_id: str, user_id: str) -> None:
    note = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if note:
        note.read = True
        db.commit()
