"""Add a small selectable profile icon to users."""
from alembic import op

revision = "0002_user_avatar"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN avatar VARCHAR(12) NOT NULL DEFAULT 'circle'")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN avatar")
