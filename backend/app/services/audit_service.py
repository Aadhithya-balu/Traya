"""Audit logging service. All sensitive actions funnel through here.

Audit records are append-only by design. A record, once written, is only
created through this module; there is no update/delete API exposed to
application code, and the admin UI exposes the audit trail as read-only.
"""
import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog

SENSITIVE_ACTIONS = {
    "session.started",
    "image.captured",
    "identification.completed",
    "candidate.confirmed",
    "medical.accessed",
    "contact.initiated",
    "location.captured",
    "biometric.enrolled",
    "biometric.deleted",
    "consent.granted",
    "consent.withdrawn",
    "user.registered",
    "user.login",
    "user.account_deleted",
    "responder.profile_accessed",
    "auth.failed",
    "rate_limited",
}


def hash_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:32]


def write_audit(
    db: Session,
    *,
    actor_type: str,
    action: str,
    actor_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    session_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
    commit: bool = True,
) -> AuditLog:
    entry = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        session_id=session_id,
        details=details or {},
        ip_hash=hash_ip(ip),
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry


def log_user_action(db: Session, user_id: str, action: str, **kwargs) -> AuditLog:
    return write_audit(db, actor_type="user", actor_id=user_id, action=action, **kwargs)


def log_session_action(db: Session, session_id: str, action: str, **kwargs) -> AuditLog:
    return write_audit(
        db, actor_type="public_session", actor_id=session_id, session_id=session_id, action=action, **kwargs
    )
