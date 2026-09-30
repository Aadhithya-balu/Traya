"""Database seeder: roles, demo users (fictional), hospitals, settings.

Run:  python -m app.seed
All demo users, contacts and medical data below are FICTIONAL.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.config.settings import settings
from app.database.session import SessionLocal, init_db
from app.models import (
    BiometricEmbedding,
    BiometricProfile,
    Consent,
    EmergencyContact,
    Hospital,
    MedicalProfile,
    Role,
    SystemSetting,
    User,
    VisibleFeature,
)
from app.security.auth import ALL_ROLES, ROLE_DESCRIPTIONS, ensure_permission_matrix
from app.security.crypto import encrypt_bytes
from app.security.password import hash_password
from app.services.demo.demo_images import render_enrollment, to_bytes
from app.services.identification.engine import BiometricEngine, get_engine
from app.services.identification.registry import serialize_embedding

logger = logging.getLogger("traya.seed")

DEMO_PASSWORD = "TrayaDemo#2026"

# Fictional demo users -----------------------------------------------------
DEMO_USERS: list[dict] = [
    {
        "full_name": "Aarav Kumar",
        "email": "aarav.kumar@demo.traya",
        "phone": "+91 98100 12345",
        "date_of_birth": date(1992, 6, 15),
        "blood_group": "O+",
        "allergies": ["Penicillin"],
        "conditions": ["Epilepsy"],
        "medications": ["Anti-seizure medication"],
        "notes": "Wears a medical ID bracelet.",
        "preferred_hospital": "City Care Multispeciality Hospital",
        "home_lat": 19.0822,
        "home_lng": 72.8687,
        "contact": {"name": "Sneha Kumar", "relationship": "Spouse", "phone": "+91 98200 56789"},
        "features": [{"feature_type": "birthmark", "description": "Small birthmark on left cheek", "body_location": "Face"}],
        "seed": "aarav-kumar-demo",
    },
    {
        "full_name": "Priya Sharma",
        "email": "priya.sharma@demo.traya",
        "phone": "+91 98300 22334",
        "date_of_birth": date(1988, 11, 2),
        "blood_group": "B+",
        "allergies": ["Sulfa drugs", "Peanuts"],
        "conditions": ["Asthma", "Diabetes Type 1"],
        "medications": ["Insulin", "Inhaler"],
        "notes": "Carries an insulin pump.",
        "preferred_hospital": "Shanti Hospital",
        "home_lat": 19.1759,
        "home_lng": 72.9560,
        "contact": {"name": "Vikram Sharma", "relationship": "Spouse", "phone": "+91 98400 11223"},
        "features": [{"feature_type": "tattoo", "description": "Small lotus tattoo on right wrist", "body_location": "Right wrist"}],
        "seed": "priya-sharma-demo",
    },
    {
        "full_name": "Rohan Verma",
        "email": "rohan.verma@demo.traya",
        "phone": "+91 98500 99887",
        "date_of_birth": date(2000, 3, 21),
        "blood_group": "AB+",
        "allergies": ["Latex"],
        "conditions": ["None"],
        "medications": [],
        "notes": "Allergic to latex gloves.",
        "preferred_hospital": "Sunrise Emergency Hospital",
        "home_lat": 19.0450,
        "home_lng": 72.8420,
        "contact": {"name": "Kavita Verma", "relationship": "Mother", "phone": "+91 98600 77665"},
        "features": [{"feature_type": "scar", "description": "Thin scar above right eyebrow", "body_location": "Face"}],
        "seed": "rohan-verma-demo",
    },
    {
        "full_name": "Meera Iyer",
        "email": "meera.iyer@demo.traya",
        "phone": "+91 98700 44556",
        "date_of_birth": date(1995, 9, 8),
        "blood_group": "A+",
        "allergies": ["Aspirin"],
        "conditions": ["Hypothyroidism"],
        "medications": ["Levothyroxine"],
        "notes": "Avoid NSAIDs.",
        "preferred_hospital": "City Care Multispeciality Hospital",
        "home_lat": 19.1030,
        "home_lng": 72.8770,
        "contact": {"name": "Anand Iyer", "relationship": "Brother", "phone": "+91 98800 33445"},
        "features": [],
        "seed": "meera-iyer-demo",
    },
]

DEMO_RESPONDERS: list[dict] = [
    {"full_name": "Dr. Neha Rao", "email": "neha.rao@responder.traya", "phone": "+91 98900 12321", "role": "medical_responder"},
    {"full_name": "Inspector Suresh Patil", "email": "suresh.patil@responder.traya", "phone": "+91 98000 55443", "role": "police_responder"},
    {"full_name": "Dr. Karthik Raman", "email": "karthik.raman@responder.traya", "phone": "+91 98100 44556", "role": "hospital"},
    {"full_name": "TRAYA Admin", "email": "admin@traya.io", "phone": "+91 97900 00001", "role": "admin"},
    {"full_name": "TRAYA Auditor", "email": "auditor@traya.io", "phone": "+91 97900 00002", "role": "auditor"},
]

# Fictional hospital registry (Mumbai area) -------------------------------
HOSPITALS: list[dict] = [
    {"name": "City Care Multispeciality Hospital", "address": "12 Linking Road, Bandra West, Mumbai", "phone": "+91 22 2644 0000", "lat": 19.0596, "lng": 72.8295, "emergency": True, "verified": True},
    {"name": "Shanti Hospital", "address": "45 Grant Road, Mumbai", "phone": "+91 22 2382 0000", "lat": 18.9690, "lng": 72.8100, "emergency": True, "verified": True},
    {"name": "Sunrise Emergency Hospital", "address": "7 Andheri East, Mumbai", "phone": "+91 22 6680 0000", "lat": 19.1136, "lng": 72.8697, "emergency": True, "verified": True},
    {"name": "Wadia General Hospital", "address": "Lalbaug, Mumbai", "phone": "+91 22 2300 0000", "lat": 19.0060, "lng": 72.8370, "emergency": True, "verified": False},
    {"name": "Seabridge Trauma Center", "address": "Worli Sea Face, Mumbai", "phone": "+91 22 2433 0000", "lat": 19.0167, "lng": 72.8150, "emergency": True, "verified": True},
    {"name": "Northpoint City Hospital", "address": "Thane West", "phone": "+91 22 2534 0000", "lat": 19.2183, "lng": 72.9781, "emergency": True, "verified": False},
    {"name": "Delhi Trauma & Emergency Centre", "address": "AIIMS Campus, Ansari Nagar, New Delhi", "phone": "+91 11 2659 0000", "lat": 28.5672, "lng": 77.2100, "emergency": True, "verified": True},
    {"name": "Safdarjung Emergency Hospital", "address": "Safdarjung Enclave, New Delhi", "phone": "+91 11 2670 0000", "lat": 28.5670, "lng": 77.2040, "emergency": True, "verified": True},
    {"name": "City Heart Multi-Speciality", "address": "Karol Bagh, New Delhi", "phone": "+91 11 2875 0000", "lat": 28.6468, "lng": 77.1900, "emergency": True, "verified": False},
]

SETTINGS: list[tuple[str, str, str]] = [
    ("high", str(settings.HIGH_CONFIDENCE_THRESHOLD), "High confidence identification threshold (0-1)"),
    ("review", str(settings.REVIEW_THRESHOLD), "Review-required threshold (0-1)"),
    ("face_fallback", str(settings.FALLBACK_FACE_THRESHOLD), "Below this raw face score, fallback tiers are consulted"),
    ("context_boost", str(settings.CONTEXT_BOOST), "Boost applied when incident context matches (supporting evidence)"),
    ("secondary_boost", str(settings.SECONDARY_FEATURE_BOOST), "Boost applied for matching visible features (supporting evidence)"),
    ("session_retention_days", str(settings.SESSION_RETENTION_DAYS), "Emergency session retention period"),
]


def seed_roles(db: Session) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for name in ALL_ROLES:
        role = db.query(Role).filter(Role.name == name).first()
        if role is None:
            role = Role(name=name, description=ROLE_DESCRIPTIONS[name])
            db.add(role)
            db.flush()
        roles[name] = role
    db.commit()
    ensure_permission_matrix(db)
    return roles


def seed_settings(db: Session) -> None:
    for key, value, description in SETTINGS:
        if db.get(SystemSetting, key) is None:
            db.add(SystemSetting(key=key, value=value, description=description))
    db.commit()


def seed_hospitals(db: Session) -> None:
    for h in HOSPITALS:
        exists = db.query(Hospital).filter(Hospital.name == h["name"]).first()
        if exists:
            continue
        db.add(
            Hospital(
                name=h["name"],
                address=h["address"],
                phone=h["phone"],
                latitude=h["lat"],
                longitude=h["lng"],
                emergency_available=h["emergency"],
                availability_verified=h["verified"],
            )
        )
    db.commit()


def seed_user(
    db: Session,
    *,
    full_name: str,
    email: str,
    password: str,
    phone: str | None,
    date_of_birth: date | None,
    role_names: list[str],
    roles: dict[str, Role],
    is_demo: bool = False,
) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(
        full_name=full_name,
        email=email,
        phone=phone,
        date_of_birth=date_of_birth,
        hashed_password=hash_password(password),
        is_demo=is_demo,
    )
    user.roles = [roles[name] for name in role_names]
    db.add(user)
    db.flush()
    db.commit()
    return user


def seed_medical(db: Session, user: User, data: dict) -> None:
    existing = db.query(MedicalProfile).filter(MedicalProfile.user_id == user.id).first()
    if existing:
        return
    db.add(
        MedicalProfile(
            user_id=user.id,
            blood_group=data["blood_group"],
            allergies=data["allergies"],
            conditions=data["conditions"],
            medications=data["medications"],
            emergency_notes=data.get("notes"),
            preferred_hospital=data.get("preferred_hospital"),
            home_lat=data.get("home_lat"),
            home_lng=data.get("home_lng"),
        )
    )
    db.commit()


def seed_contact(db: Session, user: User, contact: dict) -> None:
    existing = (
        db.query(EmergencyContact)
        .filter(EmergencyContact.user_id == user.id, EmergencyContact.phone == contact["phone"])
        .first()
    )
    if existing:
        return
    db.add(
        EmergencyContact(
            user_id=user.id,
            name=contact["name"],
            relation=contact["relationship"],
            phone=contact["phone"],
            is_primary=True,
        )
    )
    db.commit()


def seed_features(db: Session, user: User, features: list[dict]) -> None:
    if not features:
        return
    existing = db.query(VisibleFeature).filter(VisibleFeature.user_id == user.id).first()
    if existing:
        return
    for f in features:
        db.add(
            VisibleFeature(
                user_id=user.id,
                feature_type=f["feature_type"],
                description=f["description"],
                body_location=f.get("body_location"),
            )
        )
    db.commit()


def seed_consent(db: Session, user: User, consent_type: str = "biometric") -> None:
    exists = (
        db.query(Consent)
        .filter(Consent.user_id == user.id, Consent.consent_type == consent_type, Consent.status == "active")
        .first()
    )
    if exists:
        return
    db.add(Consent(user_id=user.id, consent_type=consent_type, status="active", version="v1"))
    db.commit()


def seed_biometric(db: Session, user: User, seed: str, engine: BiometricEngine) -> None:
    existing = db.query(BiometricProfile).filter(BiometricProfile.user_id == user.id).first()
    if existing and existing.status == "enrolled":
        return

    images = render_enrollment(seed, samples=3)
    vectors = []
    quality_ok = 0
    for image in images:
        raw = to_bytes(image)
        det = engine.process(raw)
        if det.quality.usable_for_matching and det.faces:
            vectors.append(engine.embed(raw, det.faces[0]))
            quality_ok += 1
    if quality_ok < 2:
        logger.warning("Enrollment for %s produced only %d usable samples", user.email, quality_ok)
        return

    profile = existing or BiometricProfile(user_id=user.id)
    if existing is None:
        db.add(profile)
    else:
        db.query(BiometricEmbedding).filter(BiometricEmbedding.profile_id == profile.id).delete()
    profile.status = "enrolled"
    profile.algo_version = settings.BIOMETRIC_ALGO_VERSION
    profile.num_samples = len(vectors)
    profile.enrolled_at = datetime.now(UTC)
    db.flush()

    for vec in vectors:
        db.add(
            BiometricEmbedding(
                profile_id=profile.id,
                embedding_blob=encrypt_bytes(serialize_embedding(vec)),
                algo_version=settings.BIOMETRIC_ALGO_VERSION,
            )
        )
    db.commit()
    logger.info("Enrolled biometrics for %s (%d samples)", user.email, len(vectors))


def seed_all(skip_if_seeded: bool = False) -> None:
    """Seed roles, demo users, hospitals and settings.

    Idempotent. ``skip_if_seeded=True`` is used at app startup: it returns
    immediately when demo data already exists, keeping cold boots fast.
    """
    init_db()
    engine = get_engine()
    db: Session = SessionLocal()
    try:
        # The permission matrix is part of the schema contract, not demo
        # data, so it is always reconciled even on a fast-path boot.
        ensure_permission_matrix(db)
        if (
            skip_if_seeded
            and db.query(User).filter(User.email == "aarav.kumar@demo.traya").first() is not None
        ):
            return
        roles = seed_roles(db)
        seed_settings(db)
        seed_hospitals(db)

        for data in DEMO_USERS:
            user = seed_user(
                db,
                full_name=data["full_name"],
                email=data["email"],
                password=DEMO_PASSWORD,
                phone=data["phone"],
                date_of_birth=data["date_of_birth"],
                role_names=["registered_user"],
                roles=roles,
                is_demo=True,
            )
            seed_medical(db, user, data)
            seed_contact(db, user, data["contact"])
            seed_features(db, user, data["features"])
            seed_consent(db, user, "biometric")
            seed_consent(db, user, "medical")
            seed_biometric(db, user, data["seed"], engine)

        for r in DEMO_RESPONDERS:
            seed_user(
                db,
                full_name=r["full_name"],
                email=r["email"],
                password=DEMO_PASSWORD,
                phone=r["phone"],
                date_of_birth=None,
                role_names=[r["role"]],
                roles=roles,
                is_demo=True,
            )

        # A real account that users can register with is created by /api/auth/register.
        count = db.query(User).count()
        hospitals = db.query(Hospital).count()
        enrolled = db.query(BiometricProfile).filter(BiometricProfile.status == "enrolled").count()
        print(f"TRAYA seed complete: {count} users, {enrolled} enrolled, {hospitals} hospitals.")
        print(f"Demo password for all demo accounts: {DEMO_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_all()
