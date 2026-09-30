"""Authentication dependencies, roles and permission-based authorization."""
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import Permission, Role, User
from app.security.permissions import (
    ALL_PERMISSIONS,
    PERMISSION_DESCRIPTIONS,
    ROLE_PERMISSIONS,
    permissions_for_roles,
)
from app.security.tokens import decode_token
from app.services.audit_service import log_user_action

bearer_scheme = HTTPBearer(auto_error=False)

PUBLIC_ROLE = "public"


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to perform this action",
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise _unauthorized()
    try:
        payload = decode_token(credentials.credentials)
    except Exception:
        raise _unauthorized("Invalid or expired token")
    if payload.get("type") != "access":
        raise _unauthorized("Invalid token type")
    subject = payload.get("sub")
    if not subject:
        raise _unauthorized()
    user = db.get(User, subject)
    if user is None or not user.is_active:
        raise _unauthorized("Account inactive or missing")
    return user


def require_roles(*roles: str):
    """Dependency factory. `roles` are OR'ed: at least one required."""

    def checker(user: User = Depends(get_current_user)) -> User:
        user_roles = {r.name for r in user.roles}
        if not (user_roles & set(roles)):
            raise _forbidden()
        return user

    return checker


def get_effective_permissions(db: Session, user: User) -> set[str]:
    """Permissions granted to a user, read from the database.

    Falls back to the static matrix if the ``permissions`` tables are not yet
    seeded, so a fresh database never locks everyone out.
    """
    stored = _stored_permissions(db, user)
    if stored:
        return stored
    return permissions_for_roles(user.role_names)


def _stored_permissions(db: Session, user: User) -> set[str]:
    rows = (
        db.query(Permission.name)
        .join(Role.permissions)
        .filter(Role.users.any(User.id == user.id))
        .distinct()
        .all()
    )
    return {name for (name,) in rows if name}


def require_permission(*permissions: str, any_of: bool = False):
    """Dependency factory enforcing granular permissions.

    By default every named permission is required (``all_of``). Pass
    ``any_of=True`` to accept any one of them.
    """

    def checker(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        granted = get_effective_permissions(db, user)
        required = set(permissions)
        ok = bool(granted & required) if any_of else required.issubset(granted)
        if not ok:
            raise _forbidden()
        return user

    return checker


def get_roles(db: Session) -> dict[str, Role]:
    return {r.name: r for r in db.query(Role).all()}


def ensure_roles(db: Session, required_names: list[str]) -> None:
    """Seed roles if missing (idempotent)."""
    existing = {r.name for r in db.query(Role).all()}
    for name in required_names:
        if name not in existing:
            db.add(Role(name=name, description=ROLE_DESCRIPTIONS.get(name, "")))
    db.commit()


def ensure_permission_matrix(db: Session) -> None:
    """Seed permissions and the role-to-permission matrix (idempotent).

    Safe to call on every boot: it only inserts what is missing and repairs
    role/permission links, so a schema change does not require a data migration.
    """
    roles = {r.name: r for r in db.query(Role).all()}
    for name in ROLE_DESCRIPTIONS:
        if name not in roles:
            role = Role(name=name, description=ROLE_DESCRIPTIONS[name])
            db.add(role)
            roles[name] = role
    db.flush()

    perms = {p.name: p for p in db.query(Permission).all()}
    for name in ALL_PERMISSIONS:
        if name not in perms:
            perm = Permission(name=name, description=PERMISSION_DESCRIPTIONS[name])
            db.add(perm)
            perms[name] = perm
    db.flush()

    for role_name, granted in ROLE_PERMISSIONS.items():
        role = roles.get(role_name)
        if role is None:
            continue
        held = {p.name for p in role.permissions}
        for perm_name in granted:
            perm = perms.get(perm_name)
            if perm is not None and perm_name not in held:
                role.permissions.append(perm)
    db.commit()


ROLE_DESCRIPTIONS = {
    "public": "Bystander. Emergency-only access without an account.",
    "registered_user": "Registered person. Own profile, consent and medical data.",
    "medical_responder": "Paramedic / EMT. Emergency + authorized medical information.",
    "police_responder": "Police / first responder. Identity, contacts and incidents.",
    "hospital": "Hospital staff. Authorized clinical alerts for incoming patients.",
    "admin": "Administrator. System administration, audited on every action.",
    "auditor": "Auditor. Read-only access to the audit trail.",
}

ALL_ROLES = list(ROLE_DESCRIPTIONS.keys())


def log_login(db: Session, user: User) -> None:
    try:
        log_user_action(db, user.id, "user.login")
    except Exception:
        db.rollback()
