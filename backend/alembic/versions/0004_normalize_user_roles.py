"""Normalize account roles to user, admin, and super_admin."""
from alembic import op

revision = "0004_normalize_user_roles"
down_revision = "0003_user_avatar_upload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_role")
    op.execute("UPDATE users SET role = 'user' WHERE role IN ('student', 'teacher', 'moderator')")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'user'")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_role "
        "CHECK (role IN ('user', 'admin', 'super_admin'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_role")
    op.execute("UPDATE users SET role = 'student' WHERE role = 'user'")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'super_admin'")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'student'")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_role "
        "CHECK (role IN ('student', 'teacher', 'moderator', 'admin'))"
    )