from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.database.session import get_db
from app.models import BiometricEmbedding, BiometricProfile, Consent, User
from app.schemas import BiometricEnrollRequest, BiometricStatusOut
from app.security.auth import get_current_user
from app.services.audit_service import log_user_action
from app.services.identification.engine import get_engine
from app.services.identification.registry import serialize_embedding
from app.security.crypto import encrypt_bytes
from app.utils.helpers import validate_and_decode_image

router = APIRouter(prefix="/biometric", tags=["biometric"])


def _has_active_consent(user: User) -> bool:
    return any(
        c.consent_type == "biometric" and c.status == "active" for c in user.consents
    )


@router.post("/enroll", response_model=dict)
def enroll(
    body: BiometricEnrollRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Enroll facial embeddings from several images. Requires explicit consent.

    Raw images are validated, processed into embeddings and then discarded --
    only the encrypted embeddings are persisted.
    """
    if not _has_active_consent(user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Biometric consent required before enrollment. Please review and grant consent first.",
        )

    engine = get_engine()
    vectors = []
    usable = 0
    reports = []

    for raw_b64 in body.images:
        raw = validate_and_decode_image(raw_b64, "images")
        det = engine.process(raw)
        reports.append(
            {
                "usable": det.quality.usable_for_matching,
                "quality_score": det.quality.image_quality_score,
                "face_count": len(det.faces),
            }
        )
        if det.quality.usable_for_matching and det.faces:
            vectors.append(engine.embed(raw, det.faces[0]))
            usable += 1

    if usable < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Enrollment failed: at least 2 usable face images are required "
                "(clear lighting, face fully visible, one face per image)."
            ),
        )

    profile = user.biometric_profile
    if profile is None:
        profile = BiometricProfile(user_id=user.id)
        db.add(profile)
    profile.status = "enrolled"
    profile.algo_version = settings.BIOMETRIC_ALGO_VERSION
    profile.num_samples = len(vectors)
    profile.enrolled_at = datetime.now(UTC)
    db.flush()

    for row in db.query(BiometricEmbedding).filter(BiometricEmbedding.profile_id == profile.id):
        db.delete(row)
    for vec in vectors:
        db.add(
            BiometricEmbedding(
                profile_id=profile.id,
                embedding_blob=encrypt_bytes(serialize_embedding(vec)),
                algo_version=settings.BIOMETRIC_ALGO_VERSION,
            )
        )
    db.commit()

    log_user_action(
        db,
        user.id,
        "biometric.enrolled",
        details={"samples": len(vectors), "algo": settings.BIOMETRIC_ALGO_VERSION},
        commit=False,
    )
    db.commit()

    return {
        "status": "enrolled",
        "num_samples": len(vectors),
        "image_reports": reports,
        "algo_version": settings.BIOMETRIC_ALGO_VERSION,
    }


@router.get("/status", response_model=BiometricStatusOut)
def biometric_status(user: User = Depends(get_current_user)):
    profile = user.biometric_profile
    if profile is None:
        return BiometricStatusOut(status="not_enrolled")
    return BiometricStatusOut(
        status=profile.status,
        enrolled_at=profile.enrolled_at,
        num_samples=profile.num_samples,
        algo_version=profile.algo_version,
    )
