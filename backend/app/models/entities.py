from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


def uuid_str() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- roles

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", String(36), ForeignKey("users.id"), primary_key=True),
    Column("role_id", String(36), ForeignKey("roles.id"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", String(36), ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", String(36), ForeignKey("permissions.id"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    users: Mapped[list["User"]] = relationship(
        secondary=user_roles, back_populates="roles"
    )
    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permissions, back_populates="roles"
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions, back_populates="permissions"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    date_of_birth: Mapped[Date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, back_populates="users", lazy="selectin"
    )
    medical_profile: Mapped["MedicalProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    contacts: Mapped[list["EmergencyContact"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    biometric_profile: Mapped["BiometricProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    visible_features: Mapped[list["VisibleFeature"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    consents: Mapped[list["Consent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def role_names(self) -> list[str]:
        return [r.name for r in self.roles]


class MedicalProfile(Base):
    __tablename__ = "medical_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    blood_group: Mapped[str | None] = mapped_column(String(8), nullable=True)
    allergies: Mapped[list] = mapped_column(JSON, default=list)
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    medications: Mapped[list] = mapped_column(JSON, default=list)
    emergency_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_hospital: Mapped[str | None] = mapped_column(String(255), nullable=True)
    home_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="medical_profile")


class EmergencyContact(Base):
    __tablename__ = "emergency_contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    relation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phone: Mapped[str] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="contacts")


class BiometricProfile(Base):
    __tablename__ = "biometric_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(String(32), default="not_enrolled")
    algo_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    num_samples: Mapped[int] = mapped_column(Integer, default=0)
    enrolled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="biometric_profile")
    embeddings: Mapped[list["BiometricEmbedding"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class BiometricEmbedding(Base):
    __tablename__ = "biometric_embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("biometric_profiles.id", ondelete="CASCADE"), index=True
    )
    embedding_blob: Mapped[bytes] = mapped_column("embedding_blob")  # encrypted bytes
    algo_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    profile: Mapped[BiometricProfile] = relationship(back_populates="embeddings")


class BiometricEnrollment(Base):
    """One in-progress guided enrollment.

    The camera is walked through a fixed pose sequence. Each accepted sample
    is stored as a pending, encrypted embedding alongside the step it was
    captured for, so a half-finished enrollment can be reviewed and resumed
    and the final template is only committed on ``complete``.
    """

    __tablename__ = "biometric_enrollments"
    __table_args__ = (
        # Resume-lookup: "is this user already mid-enrollment?"
        Index("ix_biometric_enrollments_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="in_progress"
    )  # in_progress | completed | abandoned | expired
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    accepted_samples: Mapped[int] = mapped_column(Integer, default=0)
    rejected_samples: Mapped[int] = mapped_column(Integer, default=0)
    algo_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sample_reports: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # The front-facing capture doubles as this person's vertical bias
    # reference; hair, beard and lighting all shift it, so up/down steps are
    # judged against it rather than against an absolute zero.
    baseline_offset_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_offset_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship()
    samples: Mapped[list["BiometricEnrollmentSample"]] = relationship(
        back_populates="enrollment", cascade="all, delete-orphan"
    )


class BiometricEnrollmentSample(Base):
    __tablename__ = "biometric_enrollment_samples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    enrollment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("biometric_enrollments.id", ondelete="CASCADE"), index=True
    )
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    step_key: Mapped[str] = mapped_column(String(32), default="front")
    embedding_blob: Mapped[bytes] = mapped_column("embedding_blob")
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    pose_offset_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    pose_offset_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    enrollment: Mapped[BiometricEnrollment] = relationship(back_populates="samples")


class VisibleFeature(Base):
    __tablename__ = "visible_features"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    feature_type: Mapped[str] = mapped_column(String(32))  # scar | tattoo | birthmark | mark
    description: Mapped[str] = mapped_column(Text)
    body_location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="visible_features")


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    consent_type: Mapped[str] = mapped_column(String(32))  # biometric | medical | data
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | withdrawn
    version: Mapped[str] = mapped_column(String(16), default="v1")
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="consents")


# ---------------------------------------------------------------- emergency

class EmergencySession(Base):
    __tablename__ = "emergency_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    session_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    access_type: Mapped[str] = mapped_column(String(32), default="public")
    initiator_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    access_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="active"
    )  # active | completed | expired | aborted
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    identification_method: Mapped[list] = mapped_column(JSON, default=list)
    confidence_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    identified_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    identified_user: Mapped["User | None"] = relationship(lazy="selectin")
    location: Mapped["Location | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    attempts: Mapped[list["IdentificationAttempt"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class IdentificationAttempt(Base):
    __tablename__ = "identification_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("emergency_sessions.id", ondelete="CASCADE"), index=True
    )
    image_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    face_visibility_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    occlusion_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    blur_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    lighting_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    face_count: Mapped[int] = mapped_column(Integer, default=0)
    usable: Mapped[bool] = mapped_column(Boolean, default=False)
    method: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[EmergencySession] = relationship(back_populates="attempts")
    candidates: Mapped[list["IdentificationCandidate"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )


class IdentificationCandidate(Base):
    __tablename__ = "identification_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    attempt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("identification_attempts.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    confidence: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    method: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|confirmed|rejected
    confirmed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    attempt: Mapped[IdentificationAttempt] = relationship(back_populates="candidates")
    user: Mapped[User] = relationship(lazy="selectin")


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("emergency_sessions.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="gps")  # gps | manual
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped["EmergencySession | None"] = relationship(back_populates="location")


class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    emergency_available: Mapped[bool] = mapped_column(Boolean, default=True)
    availability_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    actor_type: Mapped[str] = mapped_column(String(32))  # user | public_session | system
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("emergency_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


all_models = [
    Role,
    Permission,
    User,
    MedicalProfile,
    EmergencyContact,
    BiometricProfile,
    BiometricEmbedding,
    BiometricEnrollment,
    BiometricEnrollmentSample,
    VisibleFeature,
    Consent,
    EmergencySession,
    IdentificationAttempt,
    IdentificationCandidate,
    Location,
    Hospital,
    AuditLog,
    Notification,
    SystemSetting,
]
