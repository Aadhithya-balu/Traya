from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import (
    AuditLog,
    BiometricProfile,
    EmergencySession,
    Hospital,
    IdentificationAttempt,
    SystemSetting,
    User,
)
from app.schemas import (
    AnalyticsOut,
    AuditLogOut,
    HospitalAdminIn,
    HospitalAdminOut,
    RoleAssignmentIn,
    SettingIn,
    SettingOut,
    UserAdminOut,
)
from app.security.auth import get_current_user, require_roles

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN = require_roles("admin")


# ------------------------------------------------------------------ analytics
@router.get("/analytics", response_model=AnalyticsOut)
def analytics(db: Session = Depends(get_db), _: User = Depends(ADMIN)):
    total_users = db.query(User).count()
    total_enrolled = (
        db.query(BiometricProfile).filter(BiometricProfile.status == "enrolled").count()
    )
    total_sessions = db.query(EmergencySession).count()
    successful = (
        db.query(EmergencySession)
        .filter(EmergencySession.outcome == "identified")
        .count()
    )
    failed = (
        db.query(EmergencySession)
        .filter(EmergencySession.outcome == "not_identified")
        .count()
    )
    fallback = (
        db.query(IdentificationAttempt)
        .filter(IdentificationAttempt.fallback_used.is_(True))
        .count()
    )

    attempts = (
        db.query(IdentificationAttempt)
        .filter(IdentificationAttempt.result.isnot(None))
        .all()
    )
    avg_ms = None
    if attempts:
        times = [a.created_at.timestamp() for a in attempts]
        avg_ms = 0.0  # timing captured in audit details; fallback below

    # identification latency from audit details where available
    from app.models import AuditLog

    id_logs = (
        db.query(AuditLog)
        .filter(AuditLog.action == "identification.completed")
        .order_by(AuditLog.created_at.desc())
        .limit(500)
        .all()
    )
    latencies = []
    for row in id_logs:
        elapsed = (row.details or {}).get("elapsed_ms")
        if isinstance(elapsed, (int, float)):
            latencies.append(elapsed)
    avg_ms = round(sum(latencies) / len(latencies), 1) if latencies else None

    # daily breakdown (last 14 days)
    by_day: dict[str, dict] = {}
    since = datetime.now(UTC) - timedelta(days=13)
    for s in (
        db.query(EmergencySession)
        .filter(EmergencySession.created_at >= since)
        .order_by(EmergencySession.created_at.asc())
        .all()
    ):
        day = s.created_at.date().isoformat()
        entry = by_day.setdefault(day, {"date": day, "sessions": 0, "identified": 0})
        entry["sessions"] += 1
        if s.outcome == "identified":
            entry["identified"] += 1

    status_counts: dict[str, int] = {}
    for a in attempts:
        key = a.result or "unknown"
        status_counts[key] = status_counts.get(key, 0) + 1

    return AnalyticsOut(
        total_users=total_users,
        total_enrolled=total_enrolled,
        total_sessions=total_sessions,
        successful_identifications=successful,
        identification_rate=round(successful / total_sessions, 3) if total_sessions else 0.0,
        fallback_usage=fallback,
        failed_attempts=failed,
        average_identification_time_ms=avg_ms,
        identifications_by_day=sorted(by_day.values(), key=lambda d: d["date"]),
        status_breakdown=[{"status": k, "count": v} for k, v in status_counts.items()],
    )


# ------------------------------------------------------------------ audit log
@router.get("/audit", response_model=list[AuditLogOut])
def audit_logs(
    action: str | None = None,
    session_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin", "auditor")),
):
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if session_id:
        query = query.filter(AuditLog.session_id == session_id)
    rows = (
        query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
    )
    return rows


# ------------------------------------------------------------------ users
@router.get("/users", response_model=list[UserAdminOut])
def list_users(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(ADMIN),
):
    rows = db.query(User).order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    return [
        UserAdminOut(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            is_active=u.is_active,
            is_demo=u.is_demo,
            roles=u.role_names,
            created_at=u.created_at,
        )
        for u in rows
    ]


@router.patch("/users/{user_id}/roles", response_model=UserAdminOut)
def set_roles(
    user_id: str,
    body: RoleAssignmentIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(ADMIN),
):
    from app.models import Role
    from app.services.audit_service import log_user_action

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    roles = db.query(Role).filter(Role.name.in_(body.roles)).all()
    if len(roles) != len(set(body.roles)):
        raise HTTPException(status_code=400, detail="Unknown role name in request")
    if target.id == admin.id and "admin" not in body.roles:
        raise HTTPException(status_code=400, detail="You cannot remove your own admin role")
    target.roles = roles
    db.commit()
    log_user_action(
        db,
        admin.id,
        "admin.roles_updated",
        resource_id=target.id,
        details={"roles": body.roles},
        commit=False,
    )
    db.commit()
    return UserAdminOut(
        id=target.id,
        email=target.email,
        full_name=target.full_name,
        is_active=target.is_active,
        is_demo=target.is_demo,
        roles=target.role_names,
        created_at=target.created_at,
    )


@router.patch("/users/{user_id}/active", response_model=UserAdminOut)
def set_active(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(ADMIN),
    active: bool = Query(default=True),
):
    from app.services.audit_service import log_user_action

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")
    target.is_active = active
    db.commit()
    log_user_action(
        db,
        admin.id,
        "admin.user_active_changed",
        resource_id=target.id,
        details={"active": active},
        commit=False,
    )
    db.commit()
    return UserAdminOut(
        id=target.id,
        email=target.email,
        full_name=target.full_name,
        is_active=target.is_active,
        is_demo=target.is_demo,
        roles=target.role_names,
        created_at=target.created_at,
    )


@router.get("/sessions", response_model=list[dict])
def list_sessions(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(ADMIN),
):
    rows = db.query(EmergencySession).order_by(EmergencySession.created_at.desc()).limit(limit).all()
    return [
        {
            "id": s.id,
            "session_code": s.session_code,
            "status": s.status,
            "access_type": s.access_type,
            "outcome": s.outcome,
            "confidence_category": s.confidence_category,
            "created_at": s.created_at,
            "identified_user_id": s.identified_user_id,
        }
        for s in rows
    ]


# ------------------------------------------------------------------ settings
@router.get("/settings", response_model=list[SettingOut])
def get_settings(db: Session = Depends(get_db), _: User = Depends(ADMIN)):
    return db.query(SystemSetting).order_by(SystemSetting.key).all()


@router.put("/settings/{key}", response_model=SettingOut)
def update_setting(
    key: str,
    body: SettingIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(ADMIN),
):
    from app.services.audit_service import log_user_action

    setting = db.get(SystemSetting, key)
    if setting is None:
        raise HTTPException(status_code=404, detail="Setting not found")
    setting.value = body.value
    if body.description is not None:
        setting.description = body.description
    db.commit()
    log_user_action(
        db,
        admin.id,
        "admin.setting_updated",
        resource_id=key,
        details={"key": key, "value": body.value},
        commit=False,
    )
    db.commit()
    return setting


# ------------------------------------------------------------------ hospitals
@router.get("/hospitals", response_model=list[HospitalAdminOut])
def list_hospitals(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(ADMIN),
):
    return db.query(Hospital).order_by(Hospital.name).all()


@router.post("/hospitals", response_model=HospitalAdminOut, status_code=status.HTTP_201_CREATED)
def add_hospital(
    body: HospitalAdminIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(ADMIN),
):
    from app.services.audit_service import log_user_action

    hospital = Hospital(**body.model_dump())
    db.add(hospital)
    db.commit()
    db.refresh(hospital)
    log_user_action(
        db,
        admin.id,
        "admin.hospital_added",
        resource_id=hospital.id,
        commit=False,
    )
    db.commit()
    return hospital


@router.put("/hospitals/{hospital_id}", response_model=HospitalAdminOut)
def update_hospital(
    hospital_id: str,
    body: HospitalAdminIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(ADMIN),
):
    from app.services.audit_service import log_user_action

    hospital = db.get(Hospital, hospital_id)
    if hospital is None:
        raise HTTPException(status_code=404, detail="Hospital not found")
    for key, value in body.model_dump().items():
        setattr(hospital, key, value)
    db.commit()
    log_user_action(db, admin.id, "admin.hospital_updated", resource_id=hospital_id, commit=False)
    db.commit()
    return hospital


@router.delete("/hospitals/{hospital_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hospital(
    hospital_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(ADMIN),
):
    from app.services.audit_service import log_user_action

    hospital = db.get(Hospital, hospital_id)
    if hospital is None:
        raise HTTPException(status_code=404, detail="Hospital not found")
    db.delete(hospital)
    db.commit()
    log_user_action(db, admin.id, "admin.hospital_deleted", resource_id=hospital_id, commit=False)
    db.commit()
