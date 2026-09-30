from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import User
from app.repositories.audit import AuditRepository
from app.repositories.notification import NotificationRepository
from app.repositories.profile import ProfileRepository
from app.schemas import (
    BiometricStatusOut,
    ConsentIn,
    ConsentOut,
    DeleteAccountRequest,
    EmergencyContactIn,
    EmergencyContactOut,
    MedicalProfileIn,
    MedicalProfileOut,
    TimelineEventOut,
    UpdateProfileRequest,
    UserSummary,
    VisibleFeatureIn,
    VisibleFeatureOut,
)
from app.security.auth import get_current_user, require_permission
from app.security.password import verify_password
from app.services.audit_service import log_user_action

router = APIRouter(prefix="/users", tags=["users"])

MAX_CONTACTS = 10


@router.get("/profile", response_model=dict)
def get_profile(user: User = Depends(require_permission("manage_own_profile"))):
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "date_of_birth": user.date_of_birth.isoformat() if user.date_of_birth else None,
        "roles": user.role_names,
        "created_at": user.created_at,
    }


@router.put("/profile", response_model=dict)
def update_profile(
    body: UpdateProfileRequest,
    request: Request,
    user: User = Depends(require_permission("manage_own_profile")),
    db: Session = Depends(get_db),
):
    if body.full_name is not None:
        user.full_name = body.full_name.strip()
    if body.phone is not None:
        user.phone = body.phone
    if body.date_of_birth is not None:
        user.date_of_birth = body.date_of_birth
    db.commit()
    log_user_action(db, user.id, "profile.updated", commit=False)
    db.commit()
    return get_profile(user)


# ------------------------------------------------------------------ medical
@router.get("/medical", response_model=MedicalProfileOut)
def get_medical(user: User = Depends(require_permission("manage_own_profile"))):
    profile = user.medical_profile
    if profile is None:
        return MedicalProfileOut()
    return MedicalProfileOut(
        blood_group=profile.blood_group,
        allergies=profile.allergies or [],
        conditions=profile.conditions or [],
        medications=profile.medications or [],
        emergency_notes=profile.emergency_notes,
        preferred_hospital=profile.preferred_hospital,
        updated_at=profile.updated_at,
    )


@router.put("/medical", response_model=MedicalProfileOut)
def update_medical(
    body: MedicalProfileIn,
    request: Request,
    user: User = Depends(require_permission("manage_own_profile")),
    db: Session = Depends(get_db),
):
    ProfileRepository(db).upsert_medical(
        user.id,
        blood_group=body.blood_group,
        allergies=body.allergies,
        conditions=body.conditions,
        medications=body.medications,
        emergency_notes=body.emergency_notes,
        preferred_hospital=body.preferred_hospital,
        home_lat=body.home_lat,
        home_lng=body.home_lng,
    )
    db.commit()
    log_user_action(db, user.id, "medical.updated", commit=False)
    db.commit()
    return get_medical(user)


# ------------------------------------------------------------------ contacts
@router.get("/contacts", response_model=list[EmergencyContactOut])
def list_contacts(user: User = Depends(require_permission("manage_own_profile"))):
    return user.contacts


@router.post("/contacts", response_model=EmergencyContactOut, status_code=status.HTTP_201_CREATED)
def add_contact(
    body: EmergencyContactIn,
    request: Request,
    user: User = Depends(require_permission("manage_own_profile")),
    db: Session = Depends(get_db),
):
    repo = ProfileRepository(db)
    if repo.count_contacts(user.id) >= MAX_CONTACTS:
        raise HTTPException(status_code=400, detail="Maximum of 10 emergency contacts")
    if body.is_primary:
        repo.clear_primary_contacts(user.id)
    contact = repo.add_contact(user.id, **body.model_dump())
    db.commit()
    db.refresh(contact)
    log_user_action(db, user.id, "contact.added", resource_id=contact.id, commit=False)
    db.commit()
    return contact


@router.put("/contacts/{contact_id}", response_model=EmergencyContactOut)
def update_contact(
    contact_id: str,
    body: EmergencyContactIn,
    request: Request,
    user: User = Depends(require_permission("manage_own_profile")),
    db: Session = Depends(get_db),
):
    repo = ProfileRepository(db)
    contact = repo.contact(user.id, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    if body.is_primary:
        repo.clear_primary_contacts(user.id)
    for key, value in body.model_dump().items():
        setattr(contact, key, value)
    db.commit()
    log_user_action(db, user.id, "contact.updated", resource_id=contact.id, commit=False)
    db.commit()
    return contact


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(
    contact_id: str,
    request: Request,
    user: User = Depends(require_permission("manage_own_profile")),
    db: Session = Depends(get_db),
):
    repo = ProfileRepository(db)
    contact = repo.contact(user.id, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    repo.delete(contact)
    db.commit()
    log_user_action(db, user.id, "contact.deleted", resource_id=contact_id, commit=False)
    db.commit()


# ------------------------------------------------------------------ features
@router.get("/features", response_model=list[VisibleFeatureOut])
def list_features(user: User = Depends(require_permission("manage_own_profile"))):
    return user.visible_features


@router.post("/features", response_model=VisibleFeatureOut, status_code=status.HTTP_201_CREATED)
def add_feature(
    body: VisibleFeatureIn,
    request: Request,
    user: User = Depends(require_permission("manage_own_profile")),
    db: Session = Depends(get_db),
):
    feature = ProfileRepository(db).add_feature(user.id, **body.model_dump())
    db.commit()
    db.refresh(feature)
    return feature


@router.delete("/features/{feature_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_feature(
    feature_id: str,
    request: Request,
    user: User = Depends(require_permission("manage_own_profile")),
    db: Session = Depends(get_db),
):
    repo = ProfileRepository(db)
    feature = repo.feature(user.id, feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    repo.delete(feature)
    db.commit()


# ------------------------------------------------------------------ consents
@router.get("/consents", response_model=list[ConsentOut])
def list_consents(user: User = Depends(require_permission("manage_own_consent"))):
    return user.consents


@router.post("/consents", response_model=ConsentOut)
def set_consent(
    body: ConsentIn,
    request: Request,
    user: User = Depends(require_permission("manage_own_consent")),
    db: Session = Depends(get_db),
):
    repo = ProfileRepository(db)
    existing = repo.latest_consent(user.id, body.consent_type)
    if existing and existing.status == ("active" if body.granted else "withdrawn"):
        return existing
    consent = repo.add_consent(
        user.id,
        consent_type=body.consent_type,
        status="active" if body.granted else "withdrawn",
        version=body.version,
    )
    db.commit()
    db.refresh(consent)
    log_user_action(
        db,
        user.id,
        f"consent.{'granted' if body.granted else 'withdrawn'}",
        resource_id=consent.id,
        details={"consent_type": body.consent_type},
        commit=False,
    )
    db.commit()
    return consent


# ------------------------------------------------------------------ biometric
@router.get("/biometric-status", response_model=BiometricStatusOut)
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


@router.delete("/biometric", status_code=status.HTTP_204_NO_CONTENT)
def delete_biometric(
    request: Request,
    user: User = Depends(require_permission("enroll_biometric")),
    db: Session = Depends(get_db),
):
    profile = ProfileRepository(db).biometric(user.id)
    if profile:
        db.delete(profile)
        db.commit()
    log_user_action(db, user.id, "biometric.deleted", commit=False)
    db.commit()


# ------------------------------------------------------------------ account
@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    body: DeleteAccountRequest,
    request: Request,
    user: User = Depends(require_permission("manage_own_profile")),
    db: Session = Depends(get_db),
):
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    user.is_active = False
    user.email = f"{user.id}@deleted.traya"
    db.commit()
    log_user_action(db, user.id, "user.account_deleted", commit=False)
    db.commit()


# ------------------------------------------------------------------ access history
@router.get("/access-history", response_model=list[TimelineEventOut])
def access_history(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 200))
    rows = AuditRepository(db).actor_actions(user.id, limit=limit)
    return [
        TimelineEventOut(at=r.created_at, action=r.action, details=r.details) for r in rows
    ]


# ------------------------------------------------------------------ notifications
@router.get("/notifications", response_model=list[dict])
def list_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = NotificationRepository(db).recent(user.id, limit=30)
    return [
        {
            "id": n.id,
            "type": n.type,
            "payload": n.payload,
            "read": n.read,
            "created_at": n.created_at,
        }
        for n in rows
    ]
