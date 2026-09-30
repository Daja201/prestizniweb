"""Persist request throttling across workers and restarts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_rate_limit_buckets"
down_revision = "0005_avatar_character"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_buckets",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("subject_hash", postgresql.CHAR(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("hit_count > 0", name="ck_rate_limit_buckets_hit_count"),
        sa.PrimaryKeyConstraint("name", "subject_hash"),
    )
    op.create_index("ix_rate_limit_buckets_updated_at", "rate_limit_buckets", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_rate_limit_buckets_updated_at", table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")