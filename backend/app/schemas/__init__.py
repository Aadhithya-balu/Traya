"""Pydantic request/response schemas for the TRAYA API."""
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

PHONE_RE = r"^\+?[0-9][0-9\s\-]{6,20}$"
NAME_MAX = 120


# ------------------------------------------------------------------ auth
class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=NAME_MAX)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    date_of_birth: date | None = None

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one uppercase letter and one digit")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str | None = None
    user: "UserSummary"


class RefreshRequest(BaseModel):
    refresh_token: str


# ------------------------------------------------------------------ users
class RoleOut(BaseModel):
    name: str
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PermissionOut(BaseModel):
    name: str
    description: str | None = None
    roles: list[str] = []


class UserSummary(BaseModel):
    id: str
    email: str
    full_name: str
    phone: str | None = None
    is_active: bool = True
    roles: list[str] = []
    permissions: list[str] = []
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class UpdateProfileRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=NAME_MAX)
    phone: str | None = Field(default=None, max_length=32)
    date_of_birth: date | None = None


class MedicalProfileIn(BaseModel):
    blood_group: str | None = Field(default=None, max_length=8)
    allergies: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    emergency_notes: str | None = Field(default=None, max_length=2000)
    preferred_hospital: str | None = Field(default=None, max_length=255)
    home_lat: float | None = Field(default=None, ge=-90, le=90)
    home_lng: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("blood_group")
    @classmethod
    def _blood_group(cls, v):
        allowed = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", ""}
        if v is not None and v.strip() not in allowed:
            raise ValueError("Invalid blood group")
        return (v or "").strip() or None


class MedicalProfileOut(BaseModel):
    blood_group: str | None = None
    allergies: list[str] = []
    conditions: list[str] = []
    medications: list[str] = []
    emergency_notes: str | None = None
    preferred_hospital: str | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class EmergencyContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    relation: str | None = Field(default=None, max_length=64)
    phone: str = Field(min_length=7, max_length=32)
    email: EmailStr | None = None
    is_primary: bool = True


class EmergencyContactOut(EmergencyContactIn):
    id: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class VisibleFeatureIn(BaseModel):
    feature_type: str = Field(pattern="^(scar|tattoo|birthmark|mark)$")
    description: str = Field(min_length=2, max_length=500)
    body_location: str | None = Field(default=None, max_length=120)


class VisibleFeatureOut(VisibleFeatureIn):
    id: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ConsentIn(BaseModel):
    consent_type: str = Field(pattern="^(biometric|medical|data)$")
    granted: bool = True
    version: str = "v1"


class ConsentOut(BaseModel):
    consent_type: str
    status: str
    version: str
    granted_at: datetime | None = None
    withdrawn_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class BiometricEnrollRequest(BaseModel):
    images: list[str] = Field(min_length=1, max_length=8, description="Base64 JPEG/PNG images")


class BiometricStatusOut(BaseModel):
    status: str
    enrolled_at: datetime | None = None
    num_samples: int = 0
    algo_version: str | None = None


class DeleteAccountRequest(BaseModel):
    password: str


# ------------------------------------------------------------------ emergency
class EmergencyStartRequest(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    device_id: str | None = Field(default=None, max_length=128)


class EmergencyStartOut(BaseModel):
    session_id: str
    session_code: str
    session_token: str
    status: str
    started_at: datetime
    expires_at: datetime


class CaptureRequest(BaseModel):
    image: str = Field(min_length=16)


class CaptureOut(BaseModel):
    session_id: str
    image_quality_score: float | None = None
    face_visibility_score: float | None = None
    occlusion_score: float | None = None
    blur_score: float | None = None
    lighting_score: float | None = None
    face_count: int = 0
    usable_for_matching: bool = False
    reasons: list[str] = []


class IdentifyRequest(BaseModel):
    image: str = Field(min_length=16)
    secondary_features: list[str] = Field(default_factory=list, max_length=10)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class CandidateOut(BaseModel):
    user_id: str
    confidence: float
    rank: int
    method: list[str] = []
    status: str = "pending"


class IdentifyOut(BaseModel):
    session_id: str
    status: str
    human_readable: str
    confidence: float | None = None
    candidates: list[CandidateOut] = []
    method: list[str] = []
    fallback_used: bool = False
    requires_human_confirmation: bool = False
    medical_alerts_available: bool = False
    quality: dict[str, Any] | None = None
    face_count: int = 0
    # Which matcher produced this. "simulation" means the demo engine, which is
    # not a production biometric and must not be used to identify a real person.
    engine_mode: str = "simulation"
    demo_mode: bool = False
    # Which build of the engine scored this. Without it a stored score cannot be
    # traced to the implementation that produced it, and the Phase 5 swap from
    # the simulation to a real model becomes indistinguishable from a regression.
    algo_version: str | None = None


class ConfirmRequest(BaseModel):
    candidate_user_id: str
    accept: bool = True


class LocationIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)
    source: str = Field(default="gps", pattern="^(gps|manual)$")


class LocationOut(BaseModel):
    id: str
    latitude: float
    longitude: float
    accuracy: float | None = None
    source: str
    captured_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContactActionIn(BaseModel):
    action: str = Field(pattern="^(call|sms|share_location)$")


class ContactActionOut(BaseModel):
    session_id: str
    action: str
    contact_name: str | None = None
    contact_phone: str | None = None
    logged_at: datetime


class TimelineEventOut(BaseModel):
    at: datetime
    action: str
    details: dict[str, Any] | None = None


class EmergencyIdentifierIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=64)


class ManualEntryIn(BaseModel):
    full_name: str = Field(default="", max_length=120)
    corroborating_detail: str | None = Field(default=None, max_length=200)
    subject_id: str | None = None


class AssistanceRequestIn(BaseModel):
    proposed_subject_id: str | None = None


class AssistanceConfirmIn(BaseModel):
    confirmed_subject_id: str
    requested_by: str


class UnidentifiedIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class FallbackOut(BaseModel):
    """What a fallback resolved to. Never carries clinical detail.

    ``method`` is the fallback path name, which is also the incident log's
    ``fallback_used`` value, so a responder and a later review agree on the
    vocabulary.
    """

    status: str
    method: str
    identified: bool = True
    subject_id: str | None = None
    subject_name: str | None = None
    resolved: bool = True
    reason: str | None = None
    awaiting_second_party: bool | None = None
    options: list[str] = []


class IncidentEventOut(BaseModel):
    sequence: int
    event_type: str
    actor_id: str | None = None
    subject_id: str | None = None
    fallback_used: str | None = None
    details: dict[str, Any] = {}
    at: datetime


class IncidentTimelineOut(BaseModel):
    session_id: str
    status: str
    events: list[IncidentEventOut] = []


class SessionStatusOut(BaseModel):
    session_id: str
    session_code: str
    status: str
    access_type: str
    outcome: str | None = None
    identification_method: list[str] = []
    confidence_category: str | None = None
    started_at: datetime
    expires_at: datetime
    completed_at: datetime | None = None
    identified_user_id: str | None = None


# ------------------------------------------------------------------ hospitals
class HospitalNearbyOut(BaseModel):
    id: str
    name: str
    address: str | None = None
    phone: str | None = None
    distance_km: float
    travel_minutes: int | None = None
    emergency_available: bool = True
    availability_verified: bool = False


# ------------------------------------------------------------------ admin
class HospitalAdminIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    address: str | None = None
    phone: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    emergency_available: bool = True
    availability_verified: bool = False


class HospitalAdminOut(HospitalAdminIn):
    id: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SettingIn(BaseModel):
    value: str
    description: str | None = None


class SettingOut(BaseModel):
    key: str
    value: str
    description: str | None = None


class AuditLogOut(BaseModel):
    id: str
    actor_type: str
    actor_id: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    session_id: str | None = None
    details: dict[str, Any] | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserAdminOut(BaseModel):
    id: str
    email: str
    full_name: str
    is_active: bool
    is_demo: bool
    roles: list[str] = []
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class RoleAssignmentIn(BaseModel):
    roles: list[str] = Field(min_length=1)


class AnalyticsOut(BaseModel):
    total_users: int
    total_enrolled: int
    total_sessions: int
    successful_identifications: int
    identification_rate: float
    fallback_usage: int
    failed_attempts: int
    average_identification_time_ms: float | None = None
    identifications_by_day: list[dict[str, Any]] = []
    status_breakdown: list[dict[str, Any]] = []


# ------------------------------------------------------------------ demo
class DemoScenarioOut(BaseModel):
    id: str
    title: str
    description: str


class DemoRunOut(BaseModel):
    session_id: str
    session_code: str
    preview_image: str | None = None
    identification: IdentifyOut
