from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.database.session import get_db
from app.models import Role, User
from app.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserSummary,
)
from app.security.auth import ensure_roles, get_current_user, log_login
from app.security.password import hash_password, verify_password
from app.security.tokens import create_access_token, create_refresh_token, decode_token
from app.services.audit_service import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])


def _summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        is_active=user.is_active,
        roles=user.role_names,
        created_at=user.created_at,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    ensure_roles(db, ["registered_user"])
    role = db.query(Role).filter(Role.name == "registered_user").first()
    user = User(
        email=email,
        full_name=body.full_name.strip(),
        phone=body.phone,
        date_of_birth=body.date_of_birth,
        hashed_password=hash_password(body.password),
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    db.refresh(user)

    write_audit(
        db,
        actor_type="user",
        actor_id=user.id,
        action="user.registered",
        details={"email": user.email},
        ip=request.client.host if request.client else None,
    )

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=_summary(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None or not verify_password(body.password, user.hashed_password):
        write_audit(
            db,
            actor_type="system",
            action="auth.failed",
            details={"email": email},
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    log_login(db, user)
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=_summary(user),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Account unavailable")
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=_summary(user),
    )


@router.get("/me", response_model=UserSummary)
def me(user: User = Depends(get_current_user)):
    return _summary(user)
