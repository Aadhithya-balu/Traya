"""Audit trail writes and reads.

Audit records are append-only. Nothing in the application updates or deletes
an ``AuditLog``; the repository deliberately exposes no such method.
"""
from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    model = AuditLog

    def write(
        self,
        *,
        actor_type: str,
        action: str,
        actor_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        session_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip: str | None = None,
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
        self.db.add(entry)
        self.db.flush()
        return entry

    def write_user(
        self, user_id: str, action: str, *, ip: str | None = None, **kwargs
    ) -> AuditLog:
        return self.write(actor_type="user", actor_id=user_id, action=action, ip=ip, **kwargs)

    def write_session(self, session_id: str, action: str, *, ip: str | None = None, **kwargs) -> AuditLog:
        return self.write(
            actor_type="public_session",
            actor_id=session_id,
            session_id=session_id,
            action=action,
            ip=ip,
            **kwargs,
        )

    def list(self, *, limit: int = 100, offset: int = 0, action: str | None = None) -> list[AuditLog]:
        query = self.db.query(AuditLog)
        if action:
            query = query.filter(AuditLog.action == action)
        return query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()

    def for_resource(self, resource_id: str, limit: int = 50) -> list[AuditLog]:
        return (
            self.db.query(AuditLog)
            .filter(AuditLog.resource_id == resource_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .all()
        )

    def actor_actions(self, actor_id: str, limit: int = 50) -> list[AuditLog]:
        """What one signed-in account did, for their own history view."""
        return (
            self.db.query(AuditLog)
            .filter(AuditLog.actor_type == "user", AuditLog.actor_id == actor_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .all()
        )


def hash_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:32]
