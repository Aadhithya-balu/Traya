"""Confidence evaluation for the identification pipeline.

Levels (public-facing, human readable):
  HIGH_CONFIDENCE  -> "Identity match found."
  REVIEW_REQUIRED  -> "Possible match found. Please verify carefully."
  LOW_CONFIDENCE   -> "We could not reliably identify this person."
  NO_MATCH         -> "No reliable match found."

Special pipeline outcomes:
  NO_FACE          -> "No face detected in the image."
  MULTIPLE_FACES   -> "Multiple faces detected. Please capture one victim at a time."
  POOR_QUALITY     -> "Face quality is insufficient for reliable identification."
"""
from dataclasses import dataclass

from app.config.settings import settings


@dataclass(frozen=True)
class Thresholds:
    high: float = settings.HIGH_CONFIDENCE_THRESHOLD
    review: float = settings.REVIEW_THRESHOLD
    face_fallback: float = settings.FALLBACK_FACE_THRESHOLD
    context_boost: float = settings.CONTEXT_BOOST
    secondary_boost: float = settings.SECONDARY_FEATURE_BOOST

    def as_dict(self) -> dict:
        return {
            "high_confidence": self.high,
            "review": self.review,
            "face_fallback": self.face_fallback,
            "context_boost": self.context_boost,
            "secondary_feature_boost": self.secondary_boost,
        }


def thresholds_from_settings(db=None, fallback: Thresholds | None = None) -> Thresholds:
    base = fallback or Thresholds()
    if db is None:
        return base
    try:
        from app.models import SystemSetting

        values: dict[str, str] = {
            r.key: r.value for r in db.query(SystemSetting).all() if r.key in _SETTING_KEYS
        }

        def f(key: str) -> float:
            try:
                return float(values[key])
            except (KeyError, ValueError):
                return float(getattr(base, key))

        return Thresholds(
            high=f("high"),
            review=f("review"),
            face_fallback=f("face_fallback"),
            context_boost=f("context_boost"),
            secondary_boost=f("secondary_boost"),
        )
    except Exception:
        return base


_SETTING_KEYS = {
    "high",
    "review",
    "face_fallback",
    "context_boost",
    "secondary_boost",
}
