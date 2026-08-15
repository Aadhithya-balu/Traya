"""Authentication dependencies and role-based access control (RBAC)."""
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import Role, User
from app.security.tokens import decode_token
from app.services.audit_service import log_user_action

bearer_scheme = HTTPBearer(auto_error=False)

PUBLIC_ROLE = "public"


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


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
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
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


ROLE_DESCRIPTIONS = {
    "public": "Emergency-only access without an account.",
    "registered_user": "Own profile, consent and medical data.",
    "medical_responder": "Emergency + authorized medical information.",
    "police_responder": "Emergency + authorized responder information.",
    "admin": "System administration.",
    "auditor": "Audit logs only.",
}

ALL_ROLES = list(ROLE_DESCRIPTIONS.keys())


def log_login(db: Session, user: User) -> None:
    try:
        log_user_action(db, user.id, "user.login")
    except Exception:
        db.rollback()
