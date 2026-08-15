from fastapi import APIRouter

from app.api import admin, auth, biometric, demo, emergency, hospitals, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(biometric.router)
api_router.include_router(emergency.router)
api_router.include_router(hospitals.router)
api_router.include_router(admin.router)
api_router.include_router(demo.router)
