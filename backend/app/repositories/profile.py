"""A registered person's own emergency profile: medical data, contacts,
visible features and consent records."""
from __future__ import annotations

from app.models import (
    BiometricEmbedding,
    BiometricProfile,
    Consent,
    EmergencyContact,
    MedicalProfile,
    User,
    VisibleFeature,
)
from app.repositories.base import BaseRepository


class ProfileRepository(BaseRepository[User]):
    model = User

    def medical(self, user_id: str) -> MedicalProfile | None:
        return (
            self.db.query(MedicalProfile)
            .filter(MedicalProfile.user_id == user_id)
            .first()
        )

    def upsert_medical(self, user_id: str, **fields) -> MedicalProfile:
        profile = self.medical(user_id)
        if profile is None:
            profile = MedicalProfile(user_id=user_id, **fields)
            self.db.add(profile)
        else:
            for key, value in fields.items():
                setattr(profile, key, value)
        self.db.flush()
        return profile

    def contacts(self, user_id: str) -> list[EmergencyContact]:
        return (
            self.db.query(EmergencyContact)
            .filter(EmergencyContact.user_id == user_id)
            .order_by(EmergencyContact.is_primary.desc(), EmergencyContact.name)
            .all()
        )

    def count_contacts(self, user_id: str) -> int:
        return (
            self.db.query(EmergencyContact)
            .filter(EmergencyContact.user_id == user_id)
            .count()
        )

    def clear_primary_contacts(self, user_id: str) -> None:
        """Demote the current primary so exactly one contact can hold the flag."""
        self.db.query(EmergencyContact).filter(
            EmergencyContact.user_id == user_id,
            EmergencyContact.is_primary.is_(True),
        ).update({EmergencyContact.is_primary: False}, synchronize_session=False)
        self.db.flush()

    def contact(self, user_id: str, contact_id: str) -> EmergencyContact | None:
        return (
            self.db.query(EmergencyContact)
            .filter(EmergencyContact.user_id == user_id, EmergencyContact.id == contact_id)
            .first()
        )

    def primary_contact(self, user_id: str) -> EmergencyContact | None:
        """Primary contact, falling back to any contact when none is flagged."""
        query = self.db.query(EmergencyContact).filter(
            EmergencyContact.user_id == user_id
        )
        return (
            query.filter(EmergencyContact.is_primary.is_(True)).first()
            or query.first()
        )

    def add_contact(self, user_id: str, **fields) -> EmergencyContact:
        contact = EmergencyContact(user_id=user_id, **fields)
        self.db.add(contact)
        self.db.flush()
        return contact

    def features(self, user_id: str) -> list[VisibleFeature]:
        return (
            self.db.query(VisibleFeature)
            .filter(VisibleFeature.user_id == user_id)
            .order_by(VisibleFeature.created_at.desc())
            .all()
        )

    def feature(self, user_id: str, feature_id: str) -> VisibleFeature | None:
        return (
            self.db.query(VisibleFeature)
            .filter(VisibleFeature.user_id == user_id, VisibleFeature.id == feature_id)
            .first()
        )

    def add_feature(self, user_id: str, **fields) -> VisibleFeature:
        feature = VisibleFeature(user_id=user_id, **fields)
        self.db.add(feature)
        self.db.flush()
        return feature

    def consents(self, user_id: str) -> list[Consent]:
        return (
            self.db.query(Consent)
            .filter(Consent.user_id == user_id)
            .order_by(Consent.created_at.desc())
            .all()
        )

    def latest_consent(self, user_id: str, consent_type: str) -> Consent | None:
        return (
            self.db.query(Consent)
            .filter(Consent.user_id == user_id, Consent.consent_type == consent_type)
            .order_by(Consent.granted_at.desc())
            .first()
        )

    def add_consent(self, user_id: str, **fields) -> Consent:
        consent = Consent(user_id=user_id, **fields)
        self.db.add(consent)
        self.db.flush()
        return consent

    def active_consent(self, user_id: str, consent_type: str) -> Consent | None:
        return (
            self.db.query(Consent)
            .filter(
                Consent.user_id == user_id,
                Consent.consent_type == consent_type,
                Consent.status == "active",
            )
            .first()
        )

    def set_consent(self, user_id: str, consent_type: str, granted: bool) -> Consent:
        from datetime import UTC, datetime

        record = self.active_consent(user_id, consent_type)
        if granted:
            if record is None:
                record = Consent(user_id=user_id, consent_type=consent_type)
                self.db.add(record)
            record.status = "active"
            record.withdrawn_at = None
        elif record is not None:
            record.status = "withdrawn"
            record.withdrawn_at = datetime.now(UTC)
        self.db.flush()
        return record

    # ------------------------------------------------------------ biometrics
    def biometric(self, user_id: str) -> BiometricProfile | None:
        return (
            self.db.query(BiometricProfile)
            .filter(BiometricProfile.user_id == user_id)
            .first()
        )

    def replace_embeddings(self, profile: BiometricProfile, blobs: list[bytes], algo: str) -> None:
        """Swap in a new set of encrypted embeddings, discarding the old ones.

        Re-enrollment always invalidates previous templates rather than adding
        to them, so a withdrawn-and-regranted consent cannot leave stale
        biometric data behind.
        """
        self.db.query(BiometricEmbedding).filter(
            BiometricEmbedding.profile_id == profile.id
        ).delete(synchronize_session=False)
        for blob in blobs:
            self.db.add(
                BiometricEmbedding(
                    profile_id=profile.id, embedding_blob=blob, algo_version=algo
                )
            )
        profile.algo_version = algo
        profile.num_samples = len(blobs)
        self.db.flush()
