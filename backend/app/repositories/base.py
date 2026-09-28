"""Shared repository plumbing."""
from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy.orm import Session

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Common accessors. Subclasses declare ``model``."""

    model: type[T]

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, entity_id: str) -> T | None:
        return self.db.get(self.model, entity_id)

    def add(self, entity: T) -> T:
        self.db.add(entity)
        self.db.flush()
        return entity

    def delete(self, entity: T) -> None:
        self.db.delete(entity)
        self.db.flush()

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()

    def count(self, *filters) -> int:
        query = self.db.query(self.model)
        if filters:
            query = query.filter(*filters)
        return query.count()
