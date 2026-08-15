from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas import HospitalNearbyOut
from app.services.location.location_service import find_nearby_hospitals

router = APIRouter(prefix="/hospitals", tags=["hospitals"])


@router.get("/nearby", response_model=list[HospitalNearbyOut])
def nearby(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Find nearby emergency-capable hospitals from the verified registry.

    Availability is reported only when explicitly verified; otherwise a clear
    fallback state is shown in the client. This is a real search over the
    platform's hospital registry (an external directory can be plugged in).
    """
    results = find_nearby_hospitals(db, lat, lng, radius_km)
    if not results:
        return []
    return [HospitalNearbyOut(**r) for r in results]
