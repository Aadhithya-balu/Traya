"""Location capture and nearby-hospital discovery.

Hospitals come from the platform's verified hospital registry (seeded DB).
An external directory (e.g. Google Places / Overpass API) can be plugged in
behind the same interface. Availability is only reported when explicitly
verified -- never invented.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Hospital

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def travel_minutes(distance_km: float, assumed_speed_kmh: float = 40.0) -> int | None:
    if distance_km <= 0:
        return None
    return int(round(distance_km / assumed_speed_kmh * 60))


@dataclass
class NearbyHospital:
    id: str
    name: str
    address: str | None
    phone: str | None
    distance_km: float
    travel_minutes: int | None
    emergency_available: bool
    availability_verified: bool


def find_nearby_hospitals(
    db: Session, lat: float, lng: float, radius_km: float = 50.0, limit: int = 10
) -> list[dict]:
    hospitals = db.query(Hospital).all()
    results: list[NearbyHospital] = []
    for h in hospitals:
        if h.latitude is None or h.longitude is None:
            continue
        distance = haversine_km(lat, lng, h.latitude, h.longitude)
        if distance <= radius_km:
            results.append(
                NearbyHospital(
                    id=h.id,
                    name=h.name,
                    address=h.address,
                    phone=h.phone,
                    distance_km=distance,
                    travel_minutes=travel_minutes(distance),
                    emergency_available=h.emergency_available,
                    availability_verified=h.availability_verified,
                )
            )
    results.sort(key=lambda r: r.distance_km)
    return [
        {
            "id": r.id,
            "name": r.name,
            "address": r.address,
            "phone": r.phone,
            "distance_km": round(r.distance_km, 2),
            "travel_minutes": r.travel_minutes,
            "emergency_available": r.emergency_available,
            "availability_verified": r.availability_verified,
        }
        for r in results[:limit]
    ]
