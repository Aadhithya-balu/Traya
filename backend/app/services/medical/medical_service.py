"""Medical information disclosure service.

Enforces minimum-necessary disclosure:

* PUBLIC_SUMMARY  - visible to any public emergency user after a reliable match.
* RESPONDER_PROFILE - additional information, only for authorized responders,
                      and still restricted to what the role permits.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import EmergencyContact, MedicalProfile, User


@dataclass
class PublicSummary:
    user_id: str
    full_name: str
    age: int | None
    blood_group: str | None
    critical_allergies: list[str]
    critical_conditions: list[str]
    critical_medications: list[str]
    emergency_warnings: list[str]
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    emergency_contact_relation: str | None
    photo_available: bool

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "full_name": self.full_name,
            "age": self.age,
            "blood_group": self.blood_group,
            "critical_allergies": self.critical_allergies,
            "critical_conditions": self.critical_conditions,
            "critical_medications": self.critical_medications,
            "emergency_warnings": self.emergency_warnings,
            "emergency_contact": {
                "name": self.emergency_contact_name,
                "phone": self.emergency_contact_phone,
                "relationship": self.emergency_contact_relation,
            },
            "photo_available": self.photo_available,
        }


def _age(dob) -> int | None:
    if dob is None:
        return None
    from datetime import UTC, datetime

    today = datetime.now(UTC).date()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def get_public_summary(db: Session, user: User) -> PublicSummary:
    medical: MedicalProfile | None = user.medical_profile
    primary = (
        db.query(EmergencyContact)
        .filter(EmergencyContact.user_id == user.id, EmergencyContact.is_primary.is_(True))
        .first()
    )
    if primary is None:
        primary = (
            db.query(EmergencyContact)
            .filter(EmergencyContact.user_id == user.id)
            .first()
        )

    warnings: list[str] = []
    if medical:
        warnings.extend(f"Severe allergy: {a}" for a in (medical.allergies or []))
        warnings.extend(f"Condition: {c}" for c in (medical.conditions or []))

    return PublicSummary(
        user_id=user.id,
        full_name=user.full_name,
        age=_age(user.date_of_birth),
        blood_group=medical.blood_group if medical else None,
        critical_allergies=list(medical.allergies or []) if medical else [],
        critical_conditions=list(medical.conditions or []) if medical else [],
        critical_medications=list(medical.medications or []) if medical else [],
        emergency_warnings=warnings,
        emergency_contact_name=primary.name if primary else None,
        emergency_contact_phone=primary.phone if primary else None,
        emergency_contact_relation=primary.relation if primary else None,
        photo_available=False,
    )


RESPONDER_VISIBLE_KEYS = {
    "emergency_notes",
    "preferred_hospital",
    "home_lat",
    "home_lng",
}


def get_responder_profile(db: Session, user: User) -> dict:
    """Extended profile for authorized responders only. No full medical history
    is ever exposed; responders get treatment-relevant notes."""
    medical: MedicalProfile | None = user.medical_profile
    summary = get_public_summary(db, user)
    result = summary.to_dict()
    result["additional"] = {}
    if medical:
        for key in ("emergency_notes", "preferred_hospital"):
            value = getattr(medical, key, None)
            if value:
                result["additional"][key] = value
    result["visible_features"] = [
        {
            "feature_type": f.feature_type,
            "description": f.description,
            "body_location": f.body_location,
        }
        for f in user.visible_features
    ]
    result["all_contacts"] = [
        {
            "name": c.name,
            "relationship": c.relation,
            "phone": c.phone,
        }
        for c in user.contacts
    ]
    return result
