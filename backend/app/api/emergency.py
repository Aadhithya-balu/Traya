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
    AssistanceConfirmIn,
    AssistanceRequestIn,
    CaptureRequest,
    CaptureOut,
    ConfirmRequest,
    ContactActionIn,
    ContactActionOut,
    EmergencyIdentifierIn,
    EmergencyStartRequest,
    EmergencyStartOut,
    FallbackOut,
    IdentifyOut,
    IdentifyRequest,
    IncidentTimelineOut,
    LocationIn,
    LocationOut,
    ManualEntryIn,
    SessionStatusOut,
    TimelineEventOut,
    UnidentifiedIn,
)
from app.security.auth import get_current_user, get_effective_permissions, require_permission
from app.security.tokens import decode_token
from app.services.audit_service import log_session_action
from app.services.fallback_service import (
    FallbackError,
    complete_assistance,
    continue_unidentified,
    identify_by_emergency_identifier,
    identify_manually,
    request_assistance,
)
from app.services.incident_service import (
    CAPTURE_REJECTED,
    CONTACT_INITIATED,
    FACE_CAPTURE_STARTED,
    FACE_DETECTED,
    INCIDENT_CREATED,
    MATCH_FOUND,
    MATCH_REJECTED,
    PROFILE_ACCESSED,
    STATUS_ASSISTANCE_IN_PROGRESS,
    STATUS_CREATED,
    STATUS_IDENTIFIED,
    STATUS_IDENTIFYING,
    STATUS_NO_MATCH,
    STATUS_REVIEW_REQUIRED,
    record_event,
    set_status,
    timeline as incident_timeline,
)
from app.services.identification.pipeline import (
    STATUS_HIGH,
    STATUS_NO_FACE,
    STATUS_NO_MATCH as PIPELINE_NO_MATCH,
    confirm_candidate,
    run_identification,
)
from app.services.medical.medical_service import get_public_summary, get_responder_profile
from app.utils.helpers import (
    hash_device_id,
    issue_session_token,
    next_session_code,
    session_token_matches,
    validate_and_decode_image,
)

router = APIRouter(prefix="/emergency", tags=["emergency"])


# ------------------------------------------------------------------ helpers
def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _session_token(request: Request) -> str | None:
    return request.headers.get("X-TRAYA-Session-Token")


def _get_active_session(
    db: Session, session_id: str, request: Request | None = None
) -> EmergencySession:
    """Load an emergency session and prove the caller is allowed to.

    Possession of the session id is not authorization: the id travels in
    request bodies and logs, and a bystander flow has no login. Every
    read/write therefore requires either the session's own access token or a
    signed-in responder token. Without this, any caller who guessed or
    observed a session id could read a victim's medical summary and contact
    numbers.
    """
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
    if request is not None:
        _authorize_session(session, request, db)
    return session


def _authorize_session(session: EmergencySession, request: Request, db: Session) -> None:
    if session_token_matches(
        _session_token(request), session.access_token_hash
    ):
        return
    # A signed-in responder holding `identify_person` may join the session:
    # they are the one confirming the candidate and the one who needs the
    # clinical detail.
    if _responder_token_valid(request, db):
        return
    log_session_action(
        db,
        session.id,
        "session.access_denied",
        details={"path": request.url.path},
        ip=_client_ip(request),
        commit=False,
    )
    db.commit()
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This emergency session is not accessible from this device",
    )


def _responder_token_valid(request: Request, db: Session) -> bool:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return False
    try:
        payload = decode_token(header.split(" ", 1)[1].strip())
    except Exception:
        return False
    if payload.get("type") != "access":
        return False
    user = db.get(User, payload.get("sub") or "")
    if user is None or not user.is_active:
        return False
    return "identify_person" in get_effective_permissions(db, user)


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
    token, token_hash = issue_session_token()
    session = EmergencySession(
        session_code=next_session_code(db),
        access_type="public",
        initiator_id=None,
        access_token_hash=token_hash,
        device_id=hash_device_id(body.device_id),
        ip_hash=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.EMERGENCY_SESSION_MINUTES),
        status=STATUS_CREATED,
    )
    db.add(session)
    db.flush()
    record_event(
        db,
        session,
        INCIDENT_CREATED,
        details={"access_type": "public", "code": session.session_code},
    )

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
        session_token=token,
        status=session.status,
        started_at=session.created_at,
        expires_at=session.expires_at,
    )


@router.get("/thresholds", response_model=dict)
def read_thresholds(db: Session = Depends(get_db)):
    """Published thresholds and the identity of the engine that applies them.

    Public and unauthenticated because it contains no user data: a responder
    deciding whether to trust a score needs to know where the cut-offs are, and a
    person deciding whether to enrol needs to know they are provisional.

    **Declared above `/{session_id}` deliberately.** FastAPI matches routes in
    declaration order, so a `/{session_id}` route defined first would swallow
    `/thresholds` and return 404 - or, worse, look for a session with that id.
    Any literal path on this router has to come first.

    ``simulated`` and ``calibrated`` are separate because the project is in a
    state one boolean cannot express: a real recogniser running on thresholds that
    have never been measured against it. A client that renders "82% confidence"
    without both implies a validation this project has not performed.
    """
    from app.services.identification.confidence import thresholds_from_settings
    from app.services.identification.engine import get_engine

    engine = get_engine()
    t = thresholds_from_settings()
    return {
        "high_confidence": t.high,
        "review": t.review,
        "face_fallback": t.face_fallback,
        "dimension": engine.dimension,
        "engine_mode": engine.mode,
        "engine_version": engine.algo_version,
        "simulated": engine.is_simulation,
        "calibrated": False,
        "note": (
            "Thresholds are provisional and uncalibrated. They must not be "
            "presented as validated accuracy."
        ),
    }


@router.get("/{session_id}", response_model=SessionStatusOut)
def session_status(session_id: str, request: Request, db: Session = Depends(get_db)):
    session = _get_active_session(db, session_id, request)
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
    session = _get_active_session(db, session_id, request)
    raw = validate_and_decode_image(body.image)

    from app.services.identification.engine import get_engine

    det = get_engine().process(raw)
    quality = det.quality
    # The capture is the event that explains entering `identifying`, so it is
    # written once whether or not the status moved. A re-capture inside an
    # already-identifying incident is still a capture worth recording, and it
    # must not be logged as a second match attempt.
    capture_details = {"usable": quality.usable_for_matching}
    if session.status in (STATUS_CREATED, STATUS_NO_MATCH, STATUS_REVIEW_REQUIRED):
        set_status(
            db,
            session,
            STATUS_IDENTIFYING,
            event_type=FACE_CAPTURE_STARTED,
            details=capture_details,
        )
    else:
        record_event(db, session, FACE_CAPTURE_STARTED, details=capture_details)
    if len(det.faces) == 1:
        record_event(
            db,
            session,
            FACE_DETECTED,
            details={"face_count": 1},
        )
    elif len(det.faces) > 1:
        record_event(
            db,
            session,
            CAPTURE_REJECTED,
            details={"face_count": len(det.faces), "reason": "multiple_faces"},
        )
    else:
        record_event(
            db,
            session,
            CAPTURE_REJECTED,
            details={"face_count": 0, "reason": "no_face"},
        )
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
    session = _get_active_session(db, session_id, request)
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
    # MATCH_ATTEMPTED is written by the pipeline, not here. The pipeline is the
    # only place that knows the outcome, so it writes both the attempt and the
    # result, in that order. Recording it here afterwards put MATCH_FOUND ahead
    # of its own attempt in the sequence log.
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
    user: User = Depends(require_permission("confirm_identity")),
    db: Session = Depends(get_db),
):
    session = _get_active_session(db, session_id, request)
    try:
        confirm_candidate(db, session, body.candidate_user_id, user.id, body.accept)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    # One `set_status` per branch, so exactly one event. An earlier version
    # called `record_event` and then `set_status` with the same type, writing
    # MATCH_FOUND twice and MATCH_REJECTED twice for a single human decision.
    if body.accept:
        set_status(
            db,
            session,
            STATUS_IDENTIFIED,
            event_type=MATCH_FOUND,
            actor_id=user.id,
            subject_id=body.candidate_user_id,
            details={"human_confirmed": True},
        )
    else:
        set_status(
            db,
            session,
            STATUS_REVIEW_REQUIRED,
            event_type=MATCH_REJECTED,
            actor_id=user.id,
            subject_id=body.candidate_user_id,
            details={"human_confirmed": False},
        )
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
    user: User = Depends(require_permission("view_medical_alerts")),
    db: Session = Depends(get_db),
):
    """Clinical summary for the identified person.

    Requires ``view_medical_alerts`` **and** the session. The permission
    dependency is the point: this endpoint previously ran on
    ``_get_active_session`` alone, which accepts the public session token. Anyone
    who could start an emergency and photograph a matching face could therefore
    read another person's allergies, blood group and medications.

    An identification is necessary but not sufficient. A police responder who
    has legitimately identified someone has still not earned access to that
    person's clinical history, so the role matrix - not the face match - is what
    opens this endpoint. Only ``medical_responder`` and ``hospital`` roles hold
    the permission.
    """
    session = _get_active_session(db, session_id, request)
    if session.status != "identified" or session.identified_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Medical summary is available only after a reliable identification.",
        )
    identified = db.get(User, session.identified_user_id)
    if identified is None:
        raise HTTPException(status_code=404, detail="Identified user no longer available")
    summary = get_public_summary(db, identified)
    record_event(
        db,
        session,
        PROFILE_ACCESSED,
        actor_id=user.id,
        subject_id=identified.id,
        details={"scope": "public_medical_summary"},
    )
    log_session_action(
        db,
        session.id,
        "medical.accessed",
        details={
            "user_id": identified.id,
            "summary_version": "public",
            "responder_id": user.id,
            "responder_roles": sorted(r.name for r in user.roles),
        },
        ip=_client_ip(request),
        commit=False,
    )
    db.commit()
    return summary.to_dict()


@router.get("/{session_id}/responder-profile", response_model=dict)
def responder_profile(
    session_id: str,
    request: Request,
    user: User = Depends(require_permission("view_emergency_profile")),
    db: Session = Depends(get_db),
):
    session = _get_active_session(db, session_id, request)
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
    session = _get_active_session(db, session_id, request)
    if session.identified_user_id is None:
        raise HTTPException(status_code=403, detail="No identified user in this session")
    user = db.get(User, session.identified_user_id)
    summary = get_public_summary(db, user)
    record_event(
        db,
        session,
        CONTACT_INITIATED,
        actor_id=None,
        subject_id=user.id,
        details={"action": body.action, "channel": "responder_reported"},
    )
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
    session = _get_active_session(db, session_id, request)
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
def timeline(session_id: str, request: Request, db: Session = Depends(get_db)):
    """The audit trail for this session.

    Distinct from ``GET /{id}/events``. This reads ``audit_log`` and is the
    system administrator's record; the incident event log is the operational
    record and exists even for an incident nobody has audited.
    """
    session = _get_active_session(db, session_id, request)
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


# ------------------------------------------------------------------ events
@router.get("/{session_id}/events", response_model=IncidentTimelineOut)
def incident_events(session_id: str, request: Request, db: Session = Depends(get_db)):
    """The incident event log, in sequence order.

    Answers "what happened, in what order, and how was this person actually
    identified?" without reading the audit trail. Ordered by ``sequence`` rather
    than ``at`` so two events written in the same millisecond cannot reorder
    themselves into a misleading story.
    """
    session = _get_active_session(db, session_id, request)
    return IncidentTimelineOut(
        session_id=session.id,
        status=session.status,
        events=incident_timeline(db, session.id),
    )


# ------------------------------------------------------------------ fallback
@router.post("/{session_id}/fallback/emergency-identifier", response_model=FallbackOut)
def fallback_emergency_identifier(
    session_id: str,
    body: EmergencyIdentifierIn,
    request: Request,
    user: User = Depends(require_permission("identify_person")),
    db: Session = Depends(get_db),
):
    """Identify by a wristband, card or contact number the person carries."""
    session = _get_active_session(db, session_id, request)
    try:
        outcome = identify_by_emergency_identifier(
            db, session, body.identifier, actor_id=user.id
        )
    except FallbackError as exc:
        db.commit()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return FallbackOut(
        status=session.status,
        method=outcome.method,
        identified=True,
        subject_id=outcome.subject_id,
        subject_name=outcome.subject_name,
        resolved=outcome.resolved,
        reason=outcome.reason,
    )


@router.post("/{session_id}/fallback/manual-entry", response_model=FallbackOut)
def fallback_manual_entry(
    session_id: str,
    body: ManualEntryIn,
    request: Request,
    user: User = Depends(require_permission("identify_person")),
    db: Session = Depends(get_db),
):
    """Identify from responder knowledge: a name plus one corroborating detail."""
    session = _get_active_session(db, session_id, request)
    try:
        outcome = identify_manually(
            db,
            session,
            full_name=body.full_name,
            corroborating_detail=body.corroborating_detail,
            subject_id=body.subject_id,
            actor_id=user.id,
        )
    except FallbackError as exc:
        db.commit()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return FallbackOut(
        status=session.status,
        method=outcome.method,
        identified=True,
        subject_id=outcome.subject_id,
        subject_name=outcome.subject_name,
        resolved=outcome.resolved,
    )


@router.post("/{session_id}/fallback/assistance", response_model=FallbackOut)
def fallback_assistance(
    session_id: str,
    body: AssistanceRequestIn,
    request: Request,
    user: User = Depends(require_permission("identify_person")),
    db: Session = Depends(get_db),
):
    """Ask a second party at the scene to confirm a proposed identity."""
    session = _get_active_session(db, session_id, request)
    try:
        result = request_assistance(
            db,
            session,
            proposed_subject_id=body.proposed_subject_id,
            requested_by=user.id,
        )
    except FallbackError as exc:
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return FallbackOut(
        status=result["status"],
        method=result["method"],
        identified=False,
        subject_id=result["subject_id"],
        resolved=False,
        awaiting_second_party=result["awaiting_second_party"],
    )


@router.post("/{session_id}/fallback/assistance/confirm", response_model=FallbackOut)
def fallback_assistance_confirm(
    session_id: str,
    body: AssistanceConfirmIn,
    request: Request,
    user: User = Depends(require_permission("identify_person")),
    db: Session = Depends(get_db),
):
    """Record a second party's confirmation. Must not be the requesting user."""
    session = _get_active_session(db, session_id, request)
    try:
        outcome = complete_assistance(
            db,
            session,
            confirmed_subject_id=body.confirmed_subject_id,
            confirmed_by=user.id,
            requested_by=body.requested_by,
        )
    except FallbackError as exc:
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return FallbackOut(
        status=session.status,
        method=outcome.method,
        identified=True,
        subject_id=outcome.subject_id,
        subject_name=outcome.subject_name,
        resolved=outcome.resolved,
    )


@router.post("/{session_id}/fallback/unidentified", response_model=FallbackOut)
def fallback_unidentified(
    session_id: str,
    body: UnidentifiedIn,
    request: Request,
    user: User = Depends(require_permission("identify_person")),
    db: Session = Depends(get_db),
):
    """Continue the incident with the person unidentified.

    The path that must exist. "We do not know who this is" is a legitimate
    outcome, and a system that cannot record it will either refuse to help or
    silently invent an identity.
    """
    session = _get_active_session(db, session_id, request)
    result = continue_unidentified(db, session, actor_id=user.id, reason=body.reason)
    db.commit()
    return FallbackOut(
        status=result["status"],
        method=result["method"],
        identified=False,
        resolved=True,
        reason=result["reason"],
    )
