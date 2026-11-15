import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProcessedEvent(Base):
    """Durable idempotency record: one row per broker event already delivered.

    The consumer inserts the event_id after a successful delivery, so a
    redelivered event (after a crash, nack or Redis flush) is acknowledged
    without causing a second business effect.
    """

    __tablename__ = "processed_events"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
