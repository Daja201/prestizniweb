"""Allow printable ASCII avatar characters and admin-only square avatars."""
from alembic import op
import sqlalchemy as sa

revision = "0005_avatar_character"
down_revision = "0004_normalize_user_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_character", sa.String(length=1), nullable=True))
    op.execute("UPDATE users SET avatar = 'circle' WHERE avatar NOT IN ('circle', 'square')")
    op.execute(
        "UPDATE users SET avatar = 'circle' "
        "WHERE avatar = 'square' AND role NOT IN ('admin', 'super_admin')"
    )
    op.create_check_constraint("ck_users_avatar_shape", "users", "avatar in ('circle','square')")
    op.create_check_constraint(
        "ck_users_square_avatar_admin_only",
        "users",
        "avatar <> 'square' or role in ('admin','super_admin')",
    )
    op.create_check_constraint(
        "ck_users_avatar_character_ascii",
        "users",
        "avatar_character is null or (octet_length(avatar_character) = 1 "
        "and ascii(avatar_character) between 32 and 126)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_avatar_character_ascii", "users", type_="check")
    op.drop_constraint("ck_users_square_avatar_admin_only", "users", type_="check")
    op.drop_constraint("ck_users_avatar_shape", "users", type_="check")
    op.drop_column("users", "avatar_character")