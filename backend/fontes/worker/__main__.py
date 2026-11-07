import asyncio
import contextlib
import logging
import signal

from fontes.config import get_settings
from fontes.container import build_worker


async def _run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Windows has no loop signal handlers; there Ctrl+C simply interrupts asyncio.run.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await build_worker(get_settings()).run(stop)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
