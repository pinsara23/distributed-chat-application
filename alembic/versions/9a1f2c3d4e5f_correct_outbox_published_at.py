"""Correct the historical outbox publication timestamp column spelling."""

from typing import Sequence, Union

from alembic import op


revision: str = "9a1f2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "c2070f9c6437"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'outbox_events' AND column_name = 'publised_at'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'outbox_events' AND column_name = 'published_at'
            ) THEN
                ALTER TABLE outbox_events RENAME COLUMN publised_at TO published_at;
            ELSIF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'outbox_events' AND column_name = 'publised_at'
            ) AND EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'outbox_events' AND column_name = 'published_at'
            ) THEN
                UPDATE outbox_events
                SET published_at = COALESCE(published_at, publised_at);
                ALTER TABLE outbox_events DROP COLUMN publised_at;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'outbox_events' AND column_name = 'published_at'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'outbox_events' AND column_name = 'publised_at'
            ) THEN
                ALTER TABLE outbox_events RENAME COLUMN published_at TO publised_at;
            END IF;
        END $$;
        """
    )
