"""The ingest queues and the message format that travels through them."""

import json
from uuid import UUID

import aio_pika
from aio_pika.abc import AbstractChannel, HeadersType

ERROR_HEADER = "x-fontes-error"
CRASHES_HEADER = "x-fontes-crashes"


class Topology:
    """main → (consumer) → retry --TTL--> main, or → dlq. All queues use the default exchange."""

    def __init__(self, prefix: str, retry_delay_ms: int) -> None:
        self.main = f"{prefix}.ingest"
        self.retry = f"{prefix}.ingest.retry"
        self.dlq = f"{prefix}.ingest.dlq"
        self._retry_delay_ms = retry_delay_ms

    async def declare(self, channel: AbstractChannel) -> None:
        await channel.declare_queue(self.main, durable=True)
        await channel.declare_queue(
            self.retry,
            durable=True,
            arguments={
                "x-message-ttl": self._retry_delay_ms,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": self.main,
            },
        )
        await channel.declare_queue(self.dlq, durable=True)


def ingest_message(body: bytes, headers: HeadersType | None = None) -> aio_pika.Message:
    return aio_pika.Message(
        body,
        headers=headers,
        content_type="application/json",
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )


def encode_document_id(document_id: UUID) -> bytes:
    return json.dumps({"document_id": str(document_id)}).encode()


def decode_document_id(body: bytes) -> UUID:
    """Raises ValueError for anything that is not `{"document_id": "<uuid>"}`."""
    try:
        payload = json.loads(body)
        return UUID(payload["document_id"])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError(f"not an ingest message: {exc}") from None
