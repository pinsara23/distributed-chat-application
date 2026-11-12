"""Consume RabbitMQ event envelopes and deliver claim-check messages to Redis."""

import asyncio
import json
import uuid

import aio_pika
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.messaging.rabbitmq.connection import rabbitmq_manager
from app.messaging.redis_client import redis_manager
from app.models.message import Message
from app.schemas.message import serialize_message

PROCESSING_CLAIM_TTL = 300
PROCESSED_EVENT_TTL = 86400
RETRY_COUNTER_TTL = 86400
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 3


async def _release_claim(redis, claim_key: str, token: str) -> None:
    await redis.eval(
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end",
        1,
        claim_key,
        token,
    )


async def _dead_letter(message: aio_pika.abc.AbstractIncomingMessage) -> None:
    await message.nack(requeue=False)


async def _retry_or_dead_letter(message, event_id):
    redis = getattr(redis_manager, "redis", None)

    if redis is None:
        await asyncio.sleep(RETRY_DELAY_SECONDS)
        await message.nack(requeue=True)
        return

    try:
        retry_key = f"retry_count:{event_id}"
        attempts = await redis.incr(retry_key)

        if attempts == 1:
            await redis.expire(retry_key, RETRY_COUNTER_TTL)

    except Exception as retry_error:
        print(f"Retry counter unavailable: {retry_error}")
        await asyncio.sleep(RETRY_DELAY_SECONDS)
        await message.nack(requeue=True)
        return

    if attempts <= MAX_RETRIES:
        await asyncio.sleep(RETRY_DELAY_SECONDS)
        await message.nack(requeue=True)
    else:
        await message.nack(requeue=False)

async def on_message(message: aio_pika.abc.AbstractIncomingMessage):
    event_id = None
    claim_key = None
    claim_token = None

    try:
        try:
            envelope = json.loads(message.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            print(f"[{settings.SERVER_ID}] Malformed event envelope. Routing to DLQ.")
            await _dead_letter(message)
            return

        if not isinstance(envelope, dict):
            await _dead_letter(message)
            return

        raw_event_id = envelope.get("event_id")
        try:
            event_id = str(uuid.UUID(str(raw_event_id)))
        except (ValueError, TypeError, AttributeError):
            print(f"[{settings.SERVER_ID}] Invalid event ID. Routing to DLQ.")
            await _dead_letter(message)
            return

        event_type = envelope.get("event_type")
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            await _dead_letter(message)
            return
        if event_type != "message.created":
            print(f"[{settings.SERVER_ID}] Unsupported event type {event_type!r}. Routing to DLQ.")
            await _dead_letter(message)
            return

        message_uuid = payload.get("message_id")
        target_user_id = payload.get("target_user_id")
        try:
            message_uuid = uuid.UUID(str(message_uuid))
            target_user_id = int(target_user_id)
        except (ValueError, TypeError, AttributeError):
            await _dead_letter(message)
            return

        redis = getattr(redis_manager, "redis", None)
        if redis is None:
            raise RuntimeError("Redis client is not connected.")

        processed_key = f"processed_event:{event_id}"
        if await redis.exists(processed_key):
            await message.ack()
            return

        claim_key = f"processing_event:{event_id}"
        claim_token = str(uuid.uuid4())
        claimed = await redis.set(
            claim_key,
            claim_token,
            ex=PROCESSING_CLAIM_TTL,
            nx=True,
        )
        if not claimed:
            # Another consumer owns the live claim. Requeue rather than lose
            # the delivery; an expired claim can be recovered after a crash.
            await message.nack(requeue=True)
            return

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Message).where(Message.message_uuid == message_uuid)
            )
            db_message = result.scalar_one_or_none()
            if db_message is None:
                raise LookupError(f"Message {message_uuid} was not found.")

            await redis_manager.publish_message(
                target_user_id,
                serialize_message(db_message),
            )

        await redis.set(processed_key, "1", ex=PROCESSED_EVENT_TTL)
        await _release_claim(redis, claim_key, claim_token)
        await message.ack()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        print(f"[{settings.SERVER_ID}] Consumer error: {error}")
        if claim_key and claim_token:
            redis = getattr(redis_manager, "redis", None)
            if redis is not None:
                try:
                    await _release_claim(redis, claim_key, claim_token)
                except Exception as release_error:
                    print(f"[{settings.SERVER_ID}] Claim release failed: {release_error}")

        if event_id is None:
            await _dead_letter(message)
        else:
            await _retry_or_dead_letter(message, event_id)


async def start_consumer():
    print(f"[{settings.SERVER_ID}] Starting RabbitMQ Consumer...")

    if not rabbitmq_manager.channel:
        raise Exception("RabbitMQ channel not initialized.")

    await rabbitmq_manager.channel.set_qos(prefetch_count=10)

    queue = await rabbitmq_manager.channel.get_queue("chat.message.queue")
    await queue.consume(on_message)
