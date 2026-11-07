from yarl import URL

from fontes.adapters.errors import scrub
from fontes.adapters.messaging.connection import AmqpConnection


class RabbitMQHealthCheck:
    """Checks the app's shared broker connection instead of opening a new one per request."""

    name = "rabbitmq"

    def __init__(self, connection: AmqpConnection) -> None:
        self._connection = connection

    async def check(self) -> None:
        try:
            connection = await self._connection.get()
            if not connection.connected.is_set():
                raise ConnectionError("connection lost, reconnecting")
        except TimeoutError:
            raise RuntimeError("rabbitmq unavailable: connect timed out") from None
        except Exception as exc:
            detail = scrub(str(exc), URL(self._connection.url).password)
            raise RuntimeError(f"rabbitmq unavailable: {type(exc).__name__}: {detail}") from None
