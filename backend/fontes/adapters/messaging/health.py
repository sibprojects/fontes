import aio_pika
from yarl import URL

from fontes.adapters.errors import scrub


class RabbitMQHealthCheck:
    name = "rabbitmq"

    def __init__(self, url: str, connect_timeout: float = 3.0) -> None:
        self._url = url
        self._connect_timeout = connect_timeout

    async def check(self) -> None:
        try:
            connection = await aio_pika.connect(self._url, timeout=self._connect_timeout)
            await connection.close()
        except Exception as exc:
            detail = scrub(str(exc), URL(self._url).password)
            raise RuntimeError(f"rabbitmq unavailable: {type(exc).__name__}: {detail}") from None
