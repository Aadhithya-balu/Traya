"""Audit logging service. All sensitive actions funnel through here.

Audit records are append-only by design. :class:`AuditRepository` exposes no
update or delete method, the admin UI renders the trail read-only, and the
PostgreSQL policies in ``database/rls.sql`` deny writes to every role except
the service account.
"""
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.repositories.audit import AuditRepository, hash_ip

# Documented set of actions that touch identity, biometrics, clinical data or
# emergency contacts. The repository does not reject unknown actions, so
# adding a call site cannot silently fail, but this list is what the privacy
# page and the compliance review are written against.
SENSITIVE_ACTIONS = {
    "session.started",
    "session.access_denied",
    "image.captured",
    "identification.completed",
    "candidate.confirmed",
    "candidate.rejected",
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
    "profile.updated",
    "medical.updated",
    "contact.added",
    "contact.updated",
    "contact.deleted",
    "incident.created",
    "incident.updated",
    "admin.roles_updated",
    "admin.user_active_changed",
    "admin.setting_updated",
    "admin.hospital_added",
    "admin.hospital_updated",
    "admin.hospital_deleted",
    "model.activated",
}

__all__ = [
    "SENSITIVE_ACTIONS",
    "hash_ip",
    "log_session_action",
    "log_user_action",
    "write_audit",
]


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
    entry = AuditRepository(db).write(
        actor_type=actor_type,
        action=action,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        session_id=session_id,
        details=details,
        ip=ip,
    )
    if commit:
        db.commit()
    return entry


def log_user_action(db: Session, user_id: str, action: str, **kwargs) -> AuditLog:
    return write_audit(db, actor_type="user", actor_id=user_id, action=action, **kwargs)


def log_session_action(db: Session, session_id: str, action: str, **kwargs) -> AuditLog:
    return write_audit(
        db,
        actor_type="public_session",
        actor_id=session_id,
        session_id=session_id,
        action=action,
        **kwargs,
    )
