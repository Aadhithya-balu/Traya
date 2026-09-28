import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.config.settings import settings
from app.database.service import db_service
from app.database.session import SessionLocal, init_db
from app.security.rate_limit import RateLimitMiddleware
from app.services.identification.engine import get_engine

logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("traya")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.db_factory = SessionLocal
    if settings.DEMO_MODE:
        from app.services.demo.seed import seed_all

        try:
            seed_all(skip_if_seeded=True)
            logger.info("Demo data ensured.")
        except Exception as exc:  # pragma: no cover
            logger.error("Seeding failed: %s", exc)
    yield
    app.state.db_factory = None


app = FastAPI(
    title="TRAYA API",
    description="AI-powered emergency victim identification & rapid-response platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_PREFIX)

if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/api/health", tags=["system"])
def health():
    """Liveness plus a plain-language view of which database is in use.

    The frontend renders ``status.state`` directly, so a Supabase outage
    surfaces as "Demo Offline Mode" rather than a driver error.
    """
    db = db_service.health()
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "mode": "demo" if settings.DEMO_MODE else "production",
        "database": db.as_dict(),
        "state": _connection_state(db),
        "recognition": {
            "engine": settings.BIOMETRIC_ENGINE,
            "model": settings.BIOMETRIC_ALGO_VERSION,
            "simulation": get_engine().is_simulation,
        },
    }


def _connection_state(db) -> str:
    if db.degraded:
        return "demo_offline"
    if not db.checks.get("connect", True):
        return "disconnected"
    return "connected"


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(
            status_code=404,
            detail="Frontend not built. Run `npm run build` in frontend/ or open http://localhost:5173",
        )
    if full_path.startswith(settings.API_PREFIX.strip("/")):
        raise HTTPException(status_code=404, detail="Not found")
    candidate = (FRONTEND_DIST / full_path).resolve()
    try:
        candidate.relative_to(FRONTEND_DIST.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")
    if full_path and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(index)
