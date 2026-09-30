"""Permission catalogue and role-to-permission matrix.

Roles answer *who someone is*. Permissions answer *what they may do*. Every
protected endpoint declares a permission via ``require_permission`` so that
authorization is a data question answered against the database, not a string
comparison against hard-coded role literals.

The matrix below is the single source of truth. It is seeded into the
``permissions`` and ``role_permissions`` tables on startup, so administrators
can inspect and audit it, and the Supabase RLS policies in
``database/rls.sql`` are generated from the same shape.
"""

PERMISSION_DESCRIPTIONS: dict[str, str] = {
    # --- identification -------------------------------------------------
    "identify_person": "Run face capture and request an identification.",
    "confirm_identity": "Accept or reject a candidate after human review.",
    "view_identity": "See the matched person's name and basic details.",
    "view_emergency_profile": "See the responder-facing emergency profile.",
    "view_medical_alerts": "See blood group, allergies and critical alerts.",
    "view_emergency_contact": "See and reach the emergency contacts.",
    "notify_contact": "Trigger an emergency-contact notification.",
    # --- incidents ------------------------------------------------------
    "create_incident": "Open a new incident record.",
    "update_incident": "Update incident status, notes and location.",
    "view_hospitals": "Query nearby hospitals and emergency departments.",
    # --- self service ---------------------------------------------------
    "manage_own_profile": "Edit own profile, medical data and contacts.",
    "enroll_biometric": "Submit and re-enroll own face samples.",
    "manage_own_consent": "Grant or withdraw own consent.",
    # --- administration -------------------------------------------------
    "manage_users": "Activate, deactivate and list user accounts.",
    "manage_roles": "Assign or revoke roles.",
    "manage_settings": "Change system settings and thresholds.",
    "view_audit_logs": "Read the audit trail.",
    "view_analytics": "Read system-wide statistics.",
}

ALL_PERMISSIONS = list(PERMISSION_DESCRIPTIONS.keys())

RESPONDER_CORE = [
    "identify_person",
    "view_identity",
    "view_emergency_profile",
    "view_emergency_contact",
    "notify_contact",
    "view_hospitals",
]

ROLE_PERMISSIONS: dict[str, list[str]] = {
    # A bystander may start an identification and nothing else. They receive
    # the minimum needed to help, never the victim record.
    "public": ["identify_person"],
    # A registered person controls their own data and may be identified.
    "registered_user": [
        "identify_person",
        "manage_own_profile",
        "enroll_biometric",
        "manage_own_consent",
    ],
    # Paramedic / EMT: full clinical picture for a patient in their care.
    "medical_responder": RESPONDER_CORE
    + [
        "confirm_identity",
        "view_medical_alerts",
        "create_incident",
        "update_incident",
    ],
    # Police: identity, contacts and incidents. No clinical detail.
    "police_responder": RESPONDER_CORE
    + ["confirm_identity", "create_incident", "update_incident"],
    # Hospital staff: clinical alerts, but identity is not theirs to police.
    "hospital": RESPONDER_CORE + ["view_medical_alerts", "update_incident"],
    # Auditor: read-only on the trail itself.
    "auditor": ["view_audit_logs"],
    "admin": ALL_PERMISSIONS,
}


def permissions_for_roles(role_names: set[str] | list[str]) -> set[str]:
    """Union of permissions granted by the given roles."""
    granted: set[str] = set()
    for name in role_names:
        granted.update(ROLE_PERMISSIONS.get(name, []))
    return granted
