"""Multi-tier identification pipeline.

Tiers (see spec §14):

  LEVEL 1 - Facial matching (primary)
  LEVEL 2 - Secondary visible features (supporting evidence only)
  LEVEL 3 - Contextual filtering (supporting evidence only, never identity proof)
  LEVEL 4 - Human confirmation (required when confidence is insufficient)

Trauma-aware behaviour: when the raw face similarity is weak the pipeline
does not force an identity — it activates fallback signals (secondary
features + context) and returns a REVIEW_REQUIRED / LOW_CONFIDENCE status
so a human decides.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models import EmergencySession, IdentificationAttempt, IdentificationCandidate
from app.services.identification.confidence import Thresholds, thresholds_from_settings
from app.services.identification.engine import BiometricEngine, FaceBox, get_engine
from app.services.identification.registry import EnrolledProfile, load_enrolled

logger = logging.getLogger("traya.identification")

STATUS_NO_FACE = "NO_FACE"
STATUS_MULTIPLE_FACES = "MULTIPLE_FACES"
STATUS_POOR_QUALITY = "POOR_QUALITY"
STATUS_HIGH = "HIGH_CONFIDENCE"
STATUS_REVIEW = "REVIEW_REQUIRED"
STATUS_LOW = "LOW_CONFIDENCE"
STATUS_NO_MATCH = "NO_MATCH"

HUMAN_READABLE = {
    STATUS_HIGH: "Identity match found.",
    STATUS_REVIEW: "Possible match found. Please verify carefully.",
    STATUS_LOW: "We could not reliably identify this person.",
    STATUS_NO_MATCH: "No reliable match found.",
    STATUS_NO_FACE: "No face detected in the image.",
    STATUS_MULTIPLE_FACES: "Multiple faces detected. Please capture one victim at a time.",
    STATUS_POOR_QUALITY: "Face quality is insufficient for reliable identification.",
}

MAX_CANDIDATES = 3


class PipelineResult:
    def __init__(self, *, status: str, method: list[str], fallback_used: bool, requires_human_confirmation: bool):
        self.status = status
        self.method = method
        self.fallback_used = fallback_used
        self.requires_human_confirmation = requires_human_confirmation
        self.candidates: list[dict] = []
        self.confidence: float | None = None
        self.quality: dict | None = None
        self.face_count = 0

    def to_dict(self, session_id: str) -> dict:
        return {
            "session_id": session_id,
            "status": self.status,
            "human_readable": HUMAN_READABLE.get(self.status, self.status),
            "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "candidates": self.candidates,
            "method": self.method,
            "fallback_used": self.fallback_used,
            "requires_human_confirmation": self.requires_human_confirmation,
            "medical_alerts_available": self.status == STATUS_HIGH and bool(self.candidates),
            "quality": self.quality,
            "face_count": self.face_count,
        }


def _match_features(user: object, secondary_features: list[str]) -> float:
    """Very small matching of text descriptions to visible features (tier 2)."""
    try:
        features = user.visible_features
    except Exception:
        return 0.0
    if not features or not secondary_features:
        return 0.0
    corpus = " ".join(
        f"{f.feature_type} {f.description} {f.body_location or ''}".lower()
        for f in features
    )
    matched = sum(
        1
        for term in secondary_features
        if any(word in corpus for word in term.lower().split() if len(word) > 3)
    )
    return matched / max(1, len(secondary_features))


def _context_match(profile, lat: float | None, lng: float | None) -> float:
    """Incident location vs registered context. Supporting evidence only."""
    if lat is None or lng is None:
        return 0.0
    try:
        home_lat = profile.home_lat
        home_lng = profile.home_lng
        if home_lat is None or home_lng is None:
            return 0.0
        import math

        def hav(a: float, b: float, c: float, d: float) -> float:
            R = 6371.0
            p1, p2 = math.radians(a), math.radians(c)
            dp, dl = math.radians(c - a), math.radians(d - b)
            h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
            return 2 * R * math.asin(math.sqrt(h))

        distance_km = hav(float(lat), float(lng), float(home_lat), float(home_lng))
        if distance_km <= 10:
            return 1.0
        if distance_km <= 40:
            return 0.4
        return 0.0
    except Exception:
        return 0.0


def _max_similarity(profile: EnrolledProfile, embedding, engine: BiometricEngine) -> float:
    return max(engine.similarity(embedding, ref) for ref in profile.embeddings)


def run_identification(
    db: Session,
    *,
    image_bytes: bytes | str,
    session: EmergencySession,
    secondary_features: list[str] | None = None,
    lat: float | None = None,
    lng: float | None = None,
    engine: BiometricEngine | None = None,
) -> PipelineResult:
    engine = engine or get_engine()
    thresholds: Thresholds = thresholds_from_settings(db)

    detection = engine.process(image_bytes)
    face_boxes: list[FaceBox] = detection.faces
    quality = detection.quality

    result = PipelineResult(
        status=STATUS_NO_MATCH,
        method=[],
        fallback_used=False,
        requires_human_confirmation=False,
    )
    result.quality = quality.to_dict()
    result.face_count = len(face_boxes)

    # ---- Multi-face guard -------------------------------------------------
    if len(face_boxes) > 1:
        result.status = STATUS_MULTIPLE_FACES
        _persist_attempt(db, session, result, face_count=len(face_boxes), usable=False)
        return result

    # ---- No face / poor quality ------------------------------------------
    if not face_boxes:
        result.status = STATUS_NO_FACE
        _persist_attempt(db, session, result, face_count=0, usable=False)
        return result

    if not quality.usable_for_matching:
        result.status = STATUS_POOR_QUALITY
        _persist_attempt(
            db, session, result, face_count=1, usable=False, quality=quality.to_dict()
        )
        return result

    # ---- Tier 1: facial matching ------------------------------------------
    embedding = engine.embed(image_bytes, face_boxes[0])
    enrolled = load_enrolled(db)
    if not enrolled:
        result.status = STATUS_NO_MATCH
        _persist_attempt(db, session, result, face_count=1, usable=True)
        return result

    scores: list[tuple[float, EnrolledProfile, list[str]]] = []
    from app.models import User as UserModel

    for profile in enrolled:
        user_obj = db.get(UserModel, profile.user_id)
        base = _max_similarity(profile, embedding, engine)
        if base < thresholds.face_fallback:
            continue
        boost = 0.0
        methods = ["face"]
        if user_obj is not None and secondary_features:
            feat_score = _match_features(user_obj, secondary_features)
            if feat_score > 0.4:
                boost += thresholds.secondary_boost * feat_score
                methods.append("secondary_features")
        if user_obj is not None:
            medical = user_obj.medical_profile if hasattr(user_obj, "medical_profile") else None
            if _context_match(medical, lat, lng) > 0:
                boost += thresholds.context_boost
                methods.append("context")
        scores.append((min(1.0, base + boost), profile, methods))

    scores.sort(key=lambda t: t[0], reverse=True)
    top = scores[:MAX_CANDIDATES]

    fallback_used = False
    requires_human_confirmation = False

    if not top:
        result.status = STATUS_NO_MATCH
    else:
        best_score, best_profile, best_methods = top[0]
        result.confidence = best_score
        result.method = list(dict.fromkeys(best_methods))

        # Populate candidate list
        for rank, (score, profile, methods) in enumerate(top, start=1):
            result.candidates.append(
                {
                    "user_id": profile.user_id,
                    "confidence": round(score, 3),
                    "rank": rank,
                    "method": list(dict.fromkeys(methods)),
                }
            )

        if best_score >= thresholds.high:
            result.status = STATUS_HIGH
            result.candidates[0]["status"] = "accepted"
        elif best_score >= thresholds.review:
            result.status = STATUS_REVIEW
            requires_human_confirmation = True
        else:
            result.status = STATUS_LOW

        # Trauma-aware: weak face score but fallback signals present
        if best_score < thresholds.face_fallback + 0.08 and any(
            m != "face" for m in best_methods
        ):
            fallback_used = True
            requires_human_confirmation = True
            if best_score >= thresholds.review:
                result.status = STATUS_REVIEW

    result.fallback_used = fallback_used
    result.requires_human_confirmation = requires_human_confirmation

    _persist_attempt(db, session, result, face_count=1, usable=True)
    return result


def _persist_attempt(
    db: Session,
    session: EmergencySession,
    result: PipelineResult,
    *,
    face_count: int,
    usable: bool,
    quality: dict | None = None,
) -> IdentificationAttempt:
    attempt = IdentificationAttempt(
        session_id=session.id,
        image_quality_score=result.quality.get("image_quality_score") if result.quality else None,
        face_visibility_score=result.quality.get("face_visibility_score") if result.quality else None,
        occlusion_score=result.quality.get("occlusion_score") if result.quality else None,
        blur_score=result.quality.get("blur_score") if result.quality else None,
        lighting_score=result.quality.get("lighting_score") if result.quality else None,
        face_count=face_count,
        usable=usable,
        method=result.method,
        result=result.status,
        confidence=result.confidence,
        fallback_used=result.fallback_used,
    )
    db.add(attempt)
    db.flush()

    for cand in result.candidates:
        db.add(
            IdentificationCandidate(
                attempt_id=attempt.id,
                user_id=cand["user_id"],
                confidence=cand["confidence"],
                rank=cand["rank"],
                method=cand["method"],
                status="accepted" if cand.get("status") == "accepted" else "pending",
            )
        )

    session.identification_method = result.method
    session.confidence_category = result.status
    session.status = "completed" if result.status == STATUS_HIGH else "active"
    session.completed_at = datetime.now(UTC) if result.status == STATUS_HIGH else None
    if result.status == STATUS_HIGH and result.candidates:
        session.identified_user_id = result.candidates[0]["user_id"]
        session.outcome = "identified"
    elif result.status in (STATUS_NO_MATCH, STATUS_LOW):
        session.outcome = "not_identified"
    elif result.status == STATUS_REVIEW:
        session.outcome = "review_required"

    db.commit()
    return attempt


def confirm_candidate(db: Session, session: EmergencySession, candidate_user_id: str, confirmed_by: str, accept: bool) -> None:
    """Level 4 human confirmation for an identification candidate."""
    attempt = (
        db.query(IdentificationAttempt)
        .filter(IdentificationAttempt.session_id == session.id)
        .order_by(IdentificationAttempt.created_at.desc())
        .first()
    )
    if attempt is None:
        raise ValueError("No identification attempt exists for this session")

    candidate = (
        db.query(IdentificationCandidate)
        .filter(
            IdentificationCandidate.attempt_id == attempt.id,
            IdentificationCandidate.user_id == candidate_user_id,
        )
        .first()
    )
    if candidate is None:
        raise ValueError("Candidate not found for this attempt")

    candidate.status = "confirmed" if accept else "rejected"
    candidate.confirmed_by = confirmed_by

    if accept:
        session.identified_user_id = candidate_user_id
        session.status = "completed"
        session.outcome = "identified"
        session.confidence_category = "HUMAN_CONFIRMED"
        session.completed_at = datetime.now(UTC)
    db.commit()
