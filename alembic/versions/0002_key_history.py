"""Public key history and recipient key version on messages.

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "public_key_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "key_version", name="uq_public_key_history_user_version"),
    )
    op.create_index("ix_public_key_history_user_id", "public_key_history", ["user_id"])
    # Older versions were overwritten in place and are gone; keep the current ones.
    op.execute(
        "INSERT INTO public_key_history (user_id, key_version, public_key_pem, created_at) "
        "SELECT user_id, key_version, public_key_pem, created_at FROM public_keys"
    )
    op.add_column("messages", sa.Column("recipient_key_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "recipient_key_version")
    op.drop_index("ix_public_key_history_user_id", table_name="public_key_history")
    op.drop_table("public_key_history")
