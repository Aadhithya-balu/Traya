"""User, role and permission lookups."""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Permission, Role, User
from app.repositories.base import BaseRepository
from app.security.permissions import permissions_for_roles


class UserRepository(BaseRepository[User]):
    model = User

    def by_email(self, email: str) -> User | None:
        return (
            self.db.query(User)
            .filter(func.lower(User.email) == email.strip().lower())
            .first()
        )

    def by_id(self, user_id: str) -> User | None:
        return self.db.get(User, user_id)

    def list_paginated(self, limit: int, offset: int) -> list[User]:
        return (
            self.db.query(User)
            .order_by(User.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def roles_by_name(self, names: list[str]) -> list[Role]:
        return self.db.query(Role).filter(Role.name.in_(names)).all()

    def role(self, name: str) -> Role | None:
        return self.db.query(Role).filter(Role.name == name).first()

    def all_roles(self) -> list[Role]:
        return self.db.query(Role).order_by(Role.name).all()

    def set_roles(self, user: User, roles: list[Role]) -> None:
        user.roles = roles
        self.db.flush()

    def total(self) -> int:
        return self.db.query(User).count()

    def active_count(self) -> int:
        return self.db.query(User).filter(User.is_active.is_(True)).count()

    def stored_permissions(self, user: User) -> set[str]:
        """Permissions granted through the ``role_permissions`` table."""
        rows = (
            self.db.query(Permission.name)
            .join(Role.permissions)
            .filter(Role.users.any(User.id == user.id))
            .distinct()
            .all()
        )
        return {name for (name,) in rows}

    def effective_permissions(self, user: User) -> set[str]:
        """Database permissions, falling back to the static matrix.

        The fallback keeps a freshly created database usable before the
        permission tables have been seeded.
        """
        return self.stored_permissions(user) or permissions_for_roles(user.role_names)
