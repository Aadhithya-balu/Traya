"""Database engine, session factory and base declarative class.

The engine itself is owned by :mod:`app.database.service`, which decides
between the Supabase/PostgreSQL primary and the SQLite demo fallback. This
module only re-exports the resolved objects so the rest of the application
keeps a single, obvious import.
"""
from collections.abc import Generator

from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.database.service import db_service

db_service.initialize()

engine = db_service.engine
SessionLocal: sessionmaker = db_service.sessionmaker()


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create tables. Migrations (Alembic) are the production path."""
    db_service.create_all()
