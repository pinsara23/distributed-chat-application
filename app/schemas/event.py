from pydantic import BaseModel, Field
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Union

def get_utc_now():
    return datetime.now(timezone.utc)

# 1. the payload
class MessageCreatePayload(BaseModel):
    """actual data"""
    message_id: Union[str, UUID]
    conversation_id: int
    sender_id: int
    target_user_id: int

    # intentionally exclude message data from here  we use claim check pattern
    # then fetch securely encrypted content from postgresql

class ChatEventEnvelope(BaseModel):
    """Standard wrapper for all events entering RabbitMQ"""

    # unique id for every event
    event_id: UUID = Field(default_factory=uuid4)

    event_type: str = Field(...)

    # schema version
    version: int = Field(default=1)

    # when did happen
    occured_at: datetime = Field(default_factory=get_utc_now)

    # which server instence generated this
    producer: str = Field(...)

    # actual business data
    payload: MessageCreatePayload


"""
Here we perform envelope method we wrap the actual content using enevlope and writes sender did and receiver id and event id 
on enevelope and then we send the actual content to postgresql and then we send the 
envelope to rabbitmq so that other servers can listen to it and fetch the actual content from 
postgresql using the claim check pattern


Why We Designed It This Way
event_id: This is automatically generated as a UUID every time you create an envelope. 
In Step 12, the consumer will check this exact UUID to ensure it never processes the same event twice (Idempotency).

version: If we ever completely change how chat works in Stage 4, we can set version=2.
Our consumers can check the version and know exactly how to parse the data safely.

No Plaintext Content: By only passing IDs in the payload (the "Claim Check" pattern), 
we ensure that if a rogue developer somehow got access to our RabbitMQ server, they could not read the users' 
private messages.
"""