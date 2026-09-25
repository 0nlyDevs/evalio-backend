"""Standalone evaluation worker.

Run the API with RUN_WORKER=false and start as many of these as you need
(`python worker.py`) to scale evaluations horizontally; they share the
PostgreSQL job queue safely.
"""

import logging
import signal
import threading

from config import settings
from db import close_pool, init_db
from pipeline.queue import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "ddgs", "primp", "chromadb"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    init_db()
    worker = Worker(settings.worker_concurrency)
    worker.start()
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()
    worker.stop()
    close_pool()


if __name__ == "__main__":
    main()
