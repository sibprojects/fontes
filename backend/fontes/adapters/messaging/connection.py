import asyncio

import aio_pika
from aio_pika.abc import AbstractRobustConnection


class AmqpConnection:
    """One long-lived, self-healing broker connection, opened on first use."""

    def __init__(self, url: str, connect_timeout: float) -> None:
        self.url = url
        self._connect_timeout = connect_timeout
        self._connection: AbstractRobustConnection | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> AbstractRobustConnection:
        # A failed first connect raises and leaves nothing cached, so the next call tries again.
        # After that, aio-pika reconnects (and restores channels and consumers) by itself.
        async with self._lock:
            if self._connection is None:
                self._connection = await aio_pika.connect_robust(
                    self.url, timeout=self._connect_timeout
                )
            return self._connection

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                await self._connection.close()
                self._connection = None
