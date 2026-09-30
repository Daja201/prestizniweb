"""Index the meme feed's recent and popular sort orders."""
from alembic import op

revision = "0007_meme_feed_sort_indexes"
down_revision = "0006_rate_limit_buckets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX ix_memes_status_created_at_id ON memes (status, created_at DESC, id DESC)")
    op.execute("CREATE INDEX ix_memes_status_likes_id ON memes (status, likes_count DESC, id DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memes_status_likes_id")
    op.execute("DROP INDEX IF EXISTS ix_memes_status_created_at_id")