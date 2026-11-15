"""Background RabbitMQ workers (topology, consumer, outbox publisher)."""

import asyncio

from app.core.config import settings
from app.messaging.rabbitmq.connection import rabbitmq_manager
from app.messaging.rabbitmq.consumer import start_consumer
from app.messaging.rabbitmq.publisher import process_outbox

RETRY_MIN_DELAY = 1.0
RETRY_MAX_DELAY = 30.0


async def run_rabbitmq_workers():
    """Connect to RabbitMQ (retrying with backoff), then relay the outbox.

    Running this as a background task means the HTTP/WebSocket API starts even
    when the broker is down. Nothing is lost meanwhile: messages are already
    committed to PostgreSQL together with their outbox events, and the
    publisher drains them once the broker is reachable.
    """
    delay = RETRY_MIN_DELAY

    while True:
        try:
            await rabbitmq_manager.connect()
            await rabbitmq_manager.setup_topology()
            await start_consumer()
            break
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"[{settings.SERVER_ID}] RabbitMQ unavailable ({error}); retrying in {delay:.0f}s.")
            await rabbitmq_manager.disconnect()
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX_DELAY)

    await process_outbox()
