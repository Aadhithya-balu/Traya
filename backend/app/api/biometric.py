from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.database.session import get_db
from app.models import BiometricProfile, User
from app.repositories.profile import ProfileRepository
from app.schemas import BiometricEnrollRequest, BiometricStatusOut
from app.security.auth import require_permission
from app.security.crypto import encrypt_bytes
from app.services.audit_service import log_user_action
from app.services.biometric.enrollment import (
    abort_enrollment,
    add_sample,
    complete_enrollment,
    enrollment_state,
    start_enrollment,
)
from app.services.identification.engine import get_engine
from app.services.identification.registry import serialize_embedding
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
    user: User = Depends(require_permission("enroll_biometric")),
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

    repo = ProfileRepository(db)
    profile = repo.biometric(user.id)
    if profile is None:
        profile = BiometricProfile(user_id=user.id)
        db.add(profile)
    profile.status = "enrolled"
    profile.enrolled_at = datetime.now(UTC)
    db.flush()

    repo.replace_embeddings(
        profile,
        [encrypt_bytes(serialize_embedding(vec)) for vec in vectors],
        settings.BIOMETRIC_ALGO_VERSION,
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
def biometric_status(user: User = Depends(require_permission("enroll_biometric"))):
    profile = user.biometric_profile
    if profile is None:
        return BiometricStatusOut(status="not_enrolled")
    return BiometricStatusOut(
        status=profile.status,
        enrolled_at=profile.enrolled_at,
        num_samples=profile.num_samples,
        algo_version=profile.algo_version,
    )


# ------------------------------------------------------------------ guided
# The guided flow is the primary enrollment path. The legacy multi-upload
# endpoint above is retained for the demo and API clients, but the app UI
# drives start -> sample -> complete.
@router.post("/enrollment/start", response_model=dict)
def start_guided_enrollment(
    user: User = Depends(require_permission("enroll_biometric")),
    db: Session = Depends(get_db),
):
    """Begin a coached enrollment and return the pose sequence to walk through."""
    enrollment = start_enrollment(db, user)
    return enrollment_state(enrollment)


@router.post("/enrollment/{enrollment_id}/sample", response_model=dict)
def submit_enrollment_sample(
    enrollment_id: str,
    body: BiometricEnrollRequest,
    user: User = Depends(require_permission("enroll_biometric")),
    db: Session = Depends(get_db),
):
    """Grade one capture against the current step.

    Returns the verdict with guidance codes the UI turns into plain-language
    prompts, plus the updated progress state.
    """
    image = body.images[0] if body.images else None
    if not image:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A single image is required per sample",
        )
    enrollment, verdict = add_sample(db, user, enrollment_id, image)
    return {"verdict": verdict.to_dict(), "state": enrollment_state(enrollment)}


@router.post("/enrollment/{enrollment_id}/complete", response_model=dict)
def finish_enrollment(
    enrollment_id: str,
    user: User = Depends(require_permission("enroll_biometric")),
    db: Session = Depends(get_db),
):
    """Promote the collected samples to the live biometric profile."""
    return complete_enrollment(db, user, enrollment_id)


@router.delete("/enrollment/{enrollment_id}", response_model=dict)
def cancel_enrollment(
    enrollment_id: str,
    user: User = Depends(require_permission("enroll_biometric")),
    db: Session = Depends(get_db),
):
    abort_enrollment(db, user, enrollment_id)
    return {"status": "abandoned", "enrollment_id": enrollment_id}
