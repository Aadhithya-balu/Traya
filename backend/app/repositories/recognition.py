"""Recognition data access: the enrolled-biometric registry and audit reads."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    BiometricEmbedding,
    BiometricProfile,
    User,
)
from app.repositories.base import BaseRepository
from app.security.crypto import decrypt_bytes


@dataclass
class EnrolledProfile:
    """One identity available to the matcher, with its decrypted templates."""

    user_id: str
    full_name: str
    embeddings: list[np.ndarray] = field(default_factory=list)
    algo_version: str | None = None
    is_demo: bool = False


class RecognitionRepository(BaseRepository[BiometricProfile]):
    model = BiometricProfile

    def enrolled_profiles(self) -> list[EnrolledProfile]:
        """Every enrolled identity, with templates decrypted for matching.

        Profiles whose embeddings cannot be decrypted under the current
        encryption key are skipped rather than failing the whole scan, so one
        stale record cannot take down identification.
        """
        rows = (
            self.db.query(BiometricProfile, User)
            .join(User, User.id == BiometricProfile.user_id)
            .filter(BiometricProfile.status == "enrolled", User.is_active.is_(True))
            .all()
        )
        profiles: list[EnrolledProfile] = []
        for bio, user in rows:
            vectors = self.decrypt_templates(bio.id)
            if not vectors:
                continue
            profiles.append(
                EnrolledProfile(
                    user_id=user.id,
                    full_name=user.full_name,
                    embeddings=vectors,
                    algo_version=bio.algo_version,
                    is_demo=user.is_demo,
                )
            )
        return profiles

    def decrypt_templates(self, profile_id: str) -> list[np.ndarray]:
        rows = (
            self.db.query(BiometricEmbedding.embedding_blob)
            .filter(BiometricEmbedding.profile_id == profile_id)
            .all()
        )
        vectors: list[np.ndarray] = []
        for (blob,) in rows:
            try:
                vectors.append(np.frombuffer(decrypt_bytes(blob), dtype=np.float64))
            except Exception:
                continue
        return vectors

    def enrolled_count(self) -> int:
        return (
            self.db.query(BiometricProfile)
            .filter(BiometricProfile.status == "enrolled")
            .count()
        )

    # ---------------------------------------------------------------- audit
    def audit_entries(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        action: str | None = None,
        actor_id: str | None = None,
    ) -> list[AuditLog]:
        query = self.db.query(AuditLog)
        if action:
            query = query.filter(AuditLog.action == action)
        if actor_id:
            query = query.filter(AuditLog.actor_id == actor_id)
        return query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()

    def audit_count(self) -> int:
        return self.db.query(AuditLog).count()

    def access_history(self, user_id: str, limit: int = 50) -> list[AuditLog]:
        """Everything done on a registered person's record, for their own view.

        Matched on the resource id or the session that identified them, so a
        person can see every time their emergency data was opened.
        """
        from app.models import IdentificationCandidate, IdentificationAttempt

        session_ids = [
            row[0]
            for row in self.db.query(IdentificationAttempt.session_id)
            .join(IdentificationCandidate, IdentificationCandidate.attempt_id == IdentificationAttempt.id)
            .filter(IdentificationCandidate.user_id == user_id)
            .distinct()
            .all()
        ]
        query = self.db.query(AuditLog).filter(AuditLog.resource_id == user_id)
        if session_ids:
            query = query.filter(
                (AuditLog.session_id.in_(session_ids))
                | (AuditLog.resource_id == user_id)
            )
        return query.order_by(AuditLog.created_at.desc()).limit(limit).all()

    def attempts_since(self, since: datetime | None = None) -> list:
        query = self.db.query(BiometricProfile)
        if since:
            query = query.filter(BiometricProfile.updated_at >= since)
        return query.all()
