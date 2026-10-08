"""
We write our encrypted message into postgresql and notify RabbitmQ new event has arrived
but itf threre is any network issue or RabbitMQ is down, we will lose the event and the message will not be sent to the recipient.
To solve this problem, we will use the outbox pattern. We will write the message into
 
Insted of tring to talk RabbitMq duting users HTTP request,
we writes encrypted message and a JSON Representation of RabbitMQ event into PostgreSQL at the ewxact same time

THen either both success or both fail

Then we have a background process that reads the outbox table and sends the event to RabbitMQ. 
If it fails, it will retry until it succeeds. Once it succeeds, it will delete the event from the outbox table.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # matched to event_id in pydentic envelope
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        unique=True,
        index=True,
        nullable=False
    )

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # full JSON envelope string that will be sent to RabbitMQ
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

# when it was successfully published to RabbitMQ (None - not yet published)
    publised_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
