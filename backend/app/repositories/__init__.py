"""Repository layer.

Routers and services talk to these repositories instead of issuing queries
directly. That keeps SQL in one place and means a backend swap (Supabase
PostgreSQL vs SQLite fallback) is a repository concern rather than an
application-wide rewrite.

Every repository takes a ``Session`` and returns ORM instances or plain
dataclasses. None of them commits implicitly unless the method name says so,
so callers stay in control of transaction boundaries.
"""
from app.repositories.audit import AuditRepository
from app.repositories.base import BaseRepository
from app.repositories.incident import IncidentRepository
from app.repositories.profile import ProfileRepository
from app.repositories.recognition import RecognitionRepository
from app.repositories.user import UserRepository

__all__ = [
    "AuditRepository",
    "BaseRepository",
    "IncidentRepository",
    "ProfileRepository",
    "RecognitionRepository",
    "UserRepository",
]
