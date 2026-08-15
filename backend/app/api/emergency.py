from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.database.session import get_db
from app.models import (
    AuditLog,
    EmergencySession,
    IdentificationAttempt,
    Location,
    User,
)
from app.schemas import (
    CaptureRequest,
    CaptureOut,
    ConfirmRequest,
    ContactActionIn,
    ContactActionOut,
    EmergencyStartRequest,
    EmergencyStartOut,
    IdentifyOut,
    IdentifyRequest,
    LocationIn,
    LocationOut,
    SessionStatusOut,
    TimelineEventOut,
)
from app.security.auth import get_current_user, require_roles
from app.services.audit_service import log_session_action
from app.services.identification.pipeline import (
    STATUS_HIGH,
    STATUS_NO_FACE,
    STATUS_NO_MATCH,
    confirm_candidate,
    run_identification,
)
from app.services.medical.medical_service import get_public_summary, get_responder_profile
from app.utils.helpers import (
    hash_device_id,
    next_session_code,
    validate_and_decode_image,
)

router = APIRouter(prefix="/emergency", tags=["emergency"])


# ------------------------------------------------------------------ helpers
def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _get_active_session(db: Session, session_id: str) -> EmergencySession:
    session = db.get(EmergencySession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Emergency session not found")
    if session.status == "expired":
        raise HTTPException(status_code=410, detail="Emergency session has expired")
    if session.status == "aborted":
        raise HTTPException(status_code=410, detail="Emergency session was aborted")
    if session.expires_at and datetime.now(UTC) > _as_utc(session.expires_at):
        session.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="Emergency session has expired")
    return session


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ------------------------------------------------------------------ session
@router.post("/start", response_model=EmergencyStartOut)
def start_session(
    body: EmergencyStartRequest | None = None,
    request: Request = None,
    db: Session = Depends(get_db),
):
    body = body or EmergencyStartRequest()
    session = EmergencySession(
        session_code=next_session_code(db),
        access_type="public",
        initiator_id=None,
        device_id=hash_device_id(body.device_id),
        ip_hash=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.EMERGENCY_SESSION_MINUTES),
        status="active",
    )
    db.add(session)
    db.flush()

    if body.latitude is not None and body.longitude is not None:
        loc = Location(
            session_id=session.id,
            latitude=body.latitude,
            longitude=body.longitude,
            accuracy=None,
            source="manual",
        )
        db.add(loc)

    db.commit()
    log_session_action(
        db,
        session.id,
        "session.started",
        details={"access_type": "public", "code": session.session_code},
        ip=_client_ip(request),
        commit=False,
    )
    db.commit()

    return EmergencyStartOut(
        session_id=session.id,
        session_code=session.session_code,
        status=session.status,
        started_at=session.created_at,
        expires_at=session.expires_at,
    )


@router.get("/{session_id}", response_model=SessionStatusOut)
def session_status(session_id: str, db: Session = Depends(get_db)):
    session = _get_active_session(db, session_id)
    return SessionStatusOut(
        session_id=session.id,
        session_code=session.session_code,
        status=session.status,
        access_type=session.access_type,
        outcome=session.outcome,
        identification_method=session.identification_method or [],
        confidence_category=session.confidence_category,
        started_at=session.created_at,
        expires_at=session.expires_at,
        completed_at=session.completed_at,
        identified_user_id=session.identified_user_id,
    )


# ------------------------------------------------------------------ capture
@router.post("/{session_id}/capture", response_model=CaptureOut)
def capture_image(
    session_id: str,
    body: CaptureRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Run image quality analysis for a captured image (no identification)."""
    session = _get_active_session(db, session_id)
    raw = validate_and_decode_image(body.image)

    from app.services.identification.engine import get_engine

    det = get_engine().process(raw)
    quality = det.quality
    log_session_action(
        db,
        session.id,
        "image.captured",
        details={
            "quality_score": quality.image_quality_score,
            "face_count": len(det.faces),
            "usable": quality.usable_for_matching,
        },
        ip=_client_ip(request),
        commit=False,
    )
    db.commit()
    return CaptureOut(
        session_id=session.id,
        image_quality_score=quality.image_quality_score,
        face_visibility_score=quality.face_visibility_score,
        occlusion_score=quality.occlusion_score,
        blur_score=quality.blur_score,
        lighting_score=quality.lighting_score,
        face_count=len(det.faces),
        usable_for_matching=quality.usable_for_matching,
        reasons=quality.reasons,
    )


# ------------------------------------------------------------------ identify
@router.post("/{session_id}/identify", response_model=IdentifyOut)
def identify(
    session_id: str,
    body: IdentifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    session = _get_active_session(db, session_id)
    raw = validate_and_decode_image(body.image)
    started = datetime.now(UTC)

    result = run_identification(
        db,
        image_bytes=raw,
        session=session,
        secondary_features=body.secondary_features,
        lat=body.latitude,
        lng=body.longitude,
    )

    elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    log_session_action(
        db,
        session.id,
        "identification.completed",
        details={
            "status": result.status,
            "confidence": result.confidence,
            "method": result.method,
            "fallback_used": result.fallback_used,
            "elapsed_ms": elapsed_ms,
        },
        ip=_client_ip(request),
        commit=False,
    )
    db.commit()

    return IdentifyOut(**result.to_dict(session.id))


# ------------------------------------------------------------------ confirm
@router.post("/{session_id}/confirm", response_model=dict)
def confirm(
    session_id: str,
    body: ConfirmRequest,
    request: Request,
    user: User = Depends(require_roles("medical_responder", "police_responder", "admin")),
    db: Session = Depends(get_db),
):
    session = _get_active_session(db, session_id)
    try:
        confirm_candidate(db, session, body.candidate_user_id, user.id, body.accept)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    log_session_action(
        db,
        session.id,
        "candidate.confirmed" if body.accept else "candidate.rejected",
        details={"user_id": body.candidate_user_id, "confirmed_by": user.id},
        ip=_client_ip(request),
        commit=False,
    )
    db.commit()
    return {"status": "confirmed" if body.accept else "rejected"}


# ------------------------------------------------------------------ medical
@router.get("/{session_id}/medical-summary", response_model=dict)
def medical_summary(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    session = _get_active_session(db, session_id)
    if session.status != "completed" or session.identified_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Medical summary is available only after a reliable identification.",
        )
    user = db.get(User, session.identified_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Identified user no longer available")
    summary = get_public_summary(db, user)
    log_session_action(
        db,
        session.id,
        "medical.accessed",
        details={"user_id": user.id, "summary_version": "public"},
        ip=_client_ip(request),
        commit=False,
    )
    db.commit()
    return summary.to_dict()


@router.get("/{session_id}/responder-profile", response_model=dict)
def responder_profile(
    session_id: str,
    request: Request,
    user: User = Depends(require_roles("medical_responder", "police_responder", "admin")),
    db: Session = Depends(get_db),
):
    session = _get_active_session(db, session_id)
    if session.identified_user_id is None:
        raise HTTPException(status_code=404, detail="No identified user in this session")
    target = db.get(User, session.identified_user_id)
    profile = get_responder_profile(db, target)
    log_session_action(
        db,
        session.id,
        "responder.profile_accessed",
        details={"user_id": target.id, "accessor": user.id, "role": user.role_names},
        ip=_client_ip(request),
        commit=False,
    )
    db.commit()
    return profile


# ------------------------------------------------------------------ contact
@router.post("/{session_id}/contact", response_model=ContactActionOut)
def contact_action(
    session_id: str,
    body: ContactActionIn,
    request: Request,
    db: Session = Depends(get_db),
):
    session = _get_active_session(db, session_id)
    if session.identified_user_id is None:
        raise HTTPException(status_code=403, detail="No identified user in this session")
    user = db.get(User, session.identified_user_id)
    summary = get_public_summary(db, user)
    log_session_action(
        db,
        session.id,
        "contact.initiated",
        details={"action": body.action, "user_id": user.id},
        ip=_client_ip(request),
        commit=False,
    )
    db.commit()
    return ContactActionOut(
        session_id=session.id,
        action=body.action,
        contact_name=summary.emergency_contact_name,
        contact_phone=summary.emergency_contact_phone,
        logged_at=datetime.now(UTC),
    )


# ------------------------------------------------------------------ location
@router.post("/{session_id}/location", response_model=LocationOut)
def capture_location(
    session_id: str,
    body: LocationIn,
    request: Request,
    db: Session = Depends(get_db),
):
    session = _get_active_session(db, session_id)
    loc = session.location
    if loc is None:
        loc = Location(session_id=session.id)
        db.add(loc)
    loc.latitude = body.latitude
    loc.longitude = body.longitude
    loc.accuracy = body.accuracy
    loc.source = body.source
    db.commit()
    log_session_action(
        db,
        session.id,
        "location.captured",
        details={"source": body.source, "accuracy": body.accuracy},
        ip=_client_ip(request),
        commit=False,
    )
    db.commit()
    return LocationOut(
        id=loc.id,
        latitude=loc.latitude,
        longitude=loc.longitude,
        accuracy=loc.accuracy,
        source=loc.source,
        captured_at=loc.captured_at,
    )


@router.get("/{session_id}/timeline", response_model=list[TimelineEventOut])
def timeline(session_id: str, db: Session = Depends(get_db)):
    session = _get_active_session(db, session_id)
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.session_id == session.id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )
    return [
        TimelineEventOut(at=r.created_at, action=r.action, details=r.details)
        for r in rows
    ]
