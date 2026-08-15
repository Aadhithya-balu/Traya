"""Loads protected enrollment embeddings from the database for matching.

Biometric embeddings are stored encrypted at rest and are decrypted only
inside the backend during a match. They are never returned to clients.
"""
from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from app.models import BiometricEmbedding, BiometricProfile, User
from app.security.crypto import decrypt_bytes


@dataclass
class EnrolledProfile:
    user_id: str
    full_name: str
    embeddings: list[np.ndarray]
    algo_version: str
    is_demo: bool


def _to_vector(payload: bytes) -> np.ndarray:
    raw = decrypt_bytes(payload)
    arr = np.frombuffer(raw, dtype=np.float64)
    return arr


def load_enrolled(db: Session) -> list[EnrolledProfile]:
    profiles = (
        db.query(BiometricProfile)
        .filter(BiometricProfile.status == "enrolled")
        .all()
    )
    result: list[EnrolledProfile] = []
    for profile in profiles:
        user = db.get(User, profile.user_id)
        if user is None or not user.is_active:
            continue
        embs = [
            _to_vector(row.embedding_blob)
            for row in db.query(BiometricEmbedding)
            .filter(BiometricEmbedding.profile_id == profile.id)
            .all()
        ]
        if not embs:
            continue
        result.append(
            EnrolledProfile(
                user_id=user.id,
                full_name=user.full_name,
                embeddings=embs,
                algo_version=profile.algo_version or "",
                is_demo=user.is_demo,
            )
        )
    return result


def serialize_embedding(vector: np.ndarray) -> bytes:
    return vector.astype(np.float64).tobytes()
