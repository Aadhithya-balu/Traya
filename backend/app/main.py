import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.config.settings import settings
from app.database.session import SessionLocal, init_db
from app.security.rate_limit import RateLimitMiddleware

logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("traya")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.db_factory = SessionLocal
    if settings.DEMO_MODE:
        from app.services.demo.seed import seed_all

        try:
            seed_all()
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "app": settings.APP_NAME, "mode": "demo" if settings.DEMO_MODE else "production"}
