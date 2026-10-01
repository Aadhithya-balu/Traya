"""The enrolled-biometric registry used by the matcher.

Biometric embeddings are stored encrypted at rest and decrypted only inside the
backend during a match. They are never returned to clients.

Data access lives in :class:`app.repositories.RecognitionRepository`; this
module is the thin domain-shaped wrapper the pipeline depends on.
"""
from sqlalchemy.orm import Session

from app.repositories.recognition import EnrolledProfile, RecognitionRepository
from app.services.identification.engine import get_engine

__all__ = ["EnrolledProfile", "load_enrolled", "serialize_embedding"]

import numpy as np


def load_enrolled(db: Session) -> list[EnrolledProfile]:
    """Templates the *current* engine can actually compare.

    The filter on algo version is the important part of this function. Templates
    enrolled by a different engine build live in a different vector space - the
    simulation writes 320 numbers, the real provider writes 128 - so including
    them would either raise on a shape mismatch or, worse, quietly score them
    against the wrong geometry. Re-enrollment is how a template changes engine.
    """
    return RecognitionRepository(db).enrolled_profiles(algo_version=get_engine().algo_version)


def serialize_embedding(vector: np.ndarray) -> bytes:
    return vector.astype(np.float64).tobytes()
