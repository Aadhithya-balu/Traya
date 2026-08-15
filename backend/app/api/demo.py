"""DEMO / SIMULATION MODE endpoints.

Everything here produces or consumes SYNTHETIC data only. No real person's
biometrics are involved. The synthetic images flow through the exact same
real pipeline (quality analysis -> detection -> embedding -> matching) so the
demo is a faithful walkthrough of the production workflow.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.database.session import get_db
from app.models import BiometricEmbedding, BiometricProfile, EmergencySession, Location, User
from app.schemas import DemoRunOut, DemoScenarioOut, IdentifyOut
from app.security.auth import get_current_user
from app.security.crypto import encrypt_bytes
from app.services.audit_service import log_session_action
from app.services.demo.demo_images import render_face, to_base64, to_bytes, render_enrollment
from app.services.identification.engine import get_engine
from app.services.identification.pipeline import run_identification
from app.services.identification.registry import serialize_embedding
from app.utils.helpers import next_session_code

logger = logging.getLogger("traya.demo")

router = APIRouter(prefix="/demo", tags=["demo"])

SCENARIOS = [
    {
        "id": "high_confidence",
        "title": "Scenario 1 - High-confidence match",
        "description": "A clean capture of a registered user produces a high-confidence identity match with medical alerts.",
    },
    {
        "id": "low_confidence",
        "title": "Scenario 2 - Low confidence / trauma",
        "description": "A degraded capture triggers a low-confidence result and activates fallback identification.",
    },
    {
        "id": "no_match",
        "title": "Scenario 3 - No match",
        "description": "An unknown person produces no reliable match. The system never fabricates an identity.",
    },
    {
        "id": "multiple_faces",
        "title": "Scenario 4 - Multiple faces",
        "description": "Two faces in the frame triggers a warning instead of an automatic identification.",
    },
    {
        "id": "poor_quality",
        "title": "Scenario 5 - Poor image quality",
        "description": "A dark, obstructed image is rejected by the quality engine before matching.",
    },
    {
        "id": "gps_unavailable",
        "title": "Scenario 6 - GPS unavailable",
        "description": "Geolocation is denied. Identification still works and manual location can be entered.",
    },
]

SCENARIO_SEEDS = {
    "high_confidence": "aarav-kumar-demo",
    "low_confidence": "aarav-kumar-demo",
    "no_match": "enroll-demo-charlie-99",
    "multiple_faces": "aarav-kumar-demo",
    "poor_quality": "aarav-kumar-demo",
    "gps_unavailable": "aarav-kumar-demo",
}

SCENARIO_KWARGS = {
    "low_confidence": {"noise": 0.30, "occluded": 0.30},
    "poor_quality": {"dark": True, "blur": True, "occluded": 0.5},
    "multiple_faces": {"faces": 2},
}


class DemoRunRequest(BaseModel):
    scenario_id: str
    session_id: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


@router.get("/scenarios", response_model=list[DemoScenarioOut])
def list_scenarios():
    return SCENARIOS


@router.post("/run", response_model=DemoRunOut)
def run_scenario(
    body: DemoRunRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo mode is disabled")
    if body.scenario_id not in SCENARIO_SEEDS:
        raise HTTPException(status_code=404, detail="Unknown demo scenario")

    session = None
    if body.session_id:
        session = db.get(EmergencySession, body.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

    identity = SCENARIO_SEEDS[body.scenario_id]
    image = render_face(
        f"{identity}-capture",
        identity=identity,
        **SCENARIO_KWARGS.get(body.scenario_id, {}),
    )
    preview = to_base64(image)

    if session is None:
        session = EmergencySession(
            session_code=next_session_code(db),
            access_type="demo",
            status="active",
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.EMERGENCY_SESSION_MINUTES),
        )
        db.add(session)
        db.flush()

    if body.latitude is not None and body.longitude is not None:
        loc = session.location or Location(session_id=session.id)
        loc.latitude = body.latitude
        loc.longitude = body.longitude
        loc.source = "manual"
        db.add(loc)

    db.commit()
    log_session_action(
        db,
        session.id,
        "session.started",
        details={"access_type": "demo", "scenario": body.scenario_id},
        commit=False,
    )
    db.commit()

    result = run_identification(
        db,
        image_bytes=to_bytes(image),
        session=session,
        secondary_features=None,
        lat=body.latitude,
        lng=body.longitude,
    )
    log_session_action(
        db,
        session.id,
        "identification.completed",
        details={
            "status": result.status,
            "scenario": body.scenario_id,
            "method": result.method,
            "fallback_used": result.fallback_used,
        },
        commit=False,
    )
    db.commit()

    return DemoRunOut(
        session_id=session.id,
        session_code=session.session_code,
        preview_image=f"data:image/jpeg;base64,{preview}",
        identification=IdentifyOut(**result.to_dict(session.id)),
    )


class DemoEnrollRequest(BaseModel):
    samples: int = Field(default=3, ge=2, le=6)


@router.post("/enroll", response_model=dict)
def demo_enroll(
    body: DemoEnrollRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Enroll the current user with SYNTHETIC demo images (for demonstration)."""
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo mode is disabled")
    consent_ok = any(
        c.consent_type == "biometric" and c.status == "active" for c in user.consents
    )
    if not consent_ok:
        raise HTTPException(
            status_code=409,
            detail="Biometric consent required before enrollment. Please grant consent first.",
        )

    engine = get_engine()
    images = render_enrollment(f"{user.id}-demo-enroll", samples=body.samples)
    vectors = []
    usable = 0
    for image in images:
        raw = to_bytes(image)
        det = engine.process(raw)
        if det.quality.usable_for_matching and det.faces:
            vectors.append(engine.embed(raw, det.faces[0]))
            usable += 1

    if usable < 2:
        raise HTTPException(status_code=422, detail="Demo enrollment failed: insufficient usable samples")

    profile = user.biometric_profile or BiometricProfile(user_id=user.id)
    profile.status = "enrolled"
    profile.algo_version = settings.BIOMETRIC_ALGO_VERSION
    profile.num_samples = len(vectors)
    profile.enrolled_at = datetime.now(UTC)
    if user.biometric_profile is None:
        db.add(profile)
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
    return {"status": "enrolled", "num_samples": len(vectors), "mode": "demo"}
