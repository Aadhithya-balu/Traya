"""incident events

Revision ID: eabc34d087df
Revises: c74d0b1e8fa2
Create Date: 2026-10-01 18:50:32.829976

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eabc34d087df'
down_revision: Union[str, None] = 'c74d0b1e8fa2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incident_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("subject_id", sa.String(length=36), nullable=True),
        sa.Column("fallback_used", sa.String(length=48), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["emergency_sessions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "session_id", "sequence", name="uq_incident_events_session_sequence"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_incident_events_event_type"),
        "incident_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_incident_events_session_id"),
        "incident_events",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_incident_events_session_id"), table_name="incident_events")
    op.drop_index(op.f("ix_incident_events_event_type"), table_name="incident_events")
    op.drop_table("incident_events")
