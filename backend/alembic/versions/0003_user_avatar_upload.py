"""Add uploadable profile picture path to users."""
from alembic import op

revision = "0003_user_avatar_upload"
down_revision = "0002_user_avatar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN avatar_path VARCHAR(255) NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN avatar_path")
