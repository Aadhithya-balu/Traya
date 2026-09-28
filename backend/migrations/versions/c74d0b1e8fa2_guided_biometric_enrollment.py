"""guided biometric enrollment

Adds the two tables backing the coached enrollment flow: an enrollment session
that tracks progress through the pose sequence, and the encrypted samples
collected for it. Pending samples are intentionally kept separate from
biometric_embeddings so a half-finished enrollment never becomes a live
identity, and are cascade-deleted with the session.

Revision ID: c74d0b1e8fa2
Revises: b32e84ef129d
Create Date: 2026-09-28 18:40:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c74d0b1e8fa2"
down_revision: Union[str, None] = "b32e84ef129d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "biometric_enrollments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("total_steps", sa.Integer(), nullable=False),
        sa.Column("accepted_samples", sa.Integer(), nullable=False),
        sa.Column("rejected_samples", sa.Integer(), nullable=False),
        sa.Column("algo_version", sa.String(length=64), nullable=True),
        sa.Column("sample_reports", sa.JSON(), nullable=False),
        sa.Column("baseline_offset_x", sa.Float(), nullable=True),
        sa.Column("baseline_offset_y", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_biometric_enrollments_user_id", "biometric_enrollments", ["user_id"]
    )
    # Resume-lookup: "is this user already mid-enrollment?"
    op.create_index(
        "ix_biometric_enrollments_user_status",
        "biometric_enrollments",
        ["user_id", "status"],
    )

    op.create_table(
        "biometric_enrollment_samples",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("enrollment_id", sa.String(length=36), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(length=32), nullable=False),
        sa.Column("embedding_blob", sa.LargeBinary(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        # Normalised darkness-centroid offsets, not degrees: the pose reader
        # has no landmark model behind it and reports no angle.
        sa.Column("pose_offset_x", sa.Float(), nullable=True),
        sa.Column("pose_offset_y", sa.Float(), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["enrollment_id"], ["biometric_enrollments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_biometric_enrollment_samples_enrollment_id",
        "biometric_enrollment_samples",
        ["enrollment_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_biometric_enrollment_samples_enrollment_id",
        table_name="biometric_enrollment_samples",
    )
    op.drop_table("biometric_enrollment_samples")
    op.drop_index("ix_biometric_enrollments_user_status", table_name="biometric_enrollments")
    op.drop_index("ix_biometric_enrollments_user_id", table_name="biometric_enrollments")
    op.drop_table("biometric_enrollments")
