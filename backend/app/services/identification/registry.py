"""The enrolled-biometric registry used by the matcher.

Biometric embeddings are stored encrypted at rest and decrypted only inside
the backend during a match. They are never returned to clients.

Data access lives in :class:`app.repositories.RecognitionRepository`; this
module is the thin domain-shaped wrapper the pipeline depends on.
"""
from sqlalchemy.orm import Session

from app.repositories.recognition import EnrolledProfile, RecognitionRepository

__all__ = ["EnrolledProfile", "load_enrolled", "serialize_embedding"]

import numpy as np


def load_enrolled(db: Session) -> list[EnrolledProfile]:
    return RecognitionRepository(db).enrolled_profiles()


def serialize_embedding(vector: np.ndarray) -> bytes:
    return vector.astype(np.float64).tobytes()
