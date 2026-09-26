"""Bounded execution for calls that can block on the network, subprocesses or
the ONNX embedder.

The evaluation pipeline must never let a single stuck call block a worker
forever: a hung `git clone`, a stalled model download or a slow embedding pass
would otherwise keep every worker thread busy, leave projects stuck in
`running` and stop the queue from draining.
"""

import logging
import threading
from collections.abc import Callable
from typing import Any, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


def run_with_timeout(fn: Callable[[], T], timeout: float, *, label: str = "task") -> T:
    """Run `fn` in a daemon thread; raise TimeoutError if it outlives `timeout`.

    The abandoned thread is daemonic, so it cannot keep the process alive, and a
    later call still makes progress even if a previous one is stuck in native
    code that cannot be cancelled.
    """
    result: dict[str, Any] = {}

    def target() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller's thread
            result["error"] = exc

    worker = threading.Thread(target=target, name=f"evalio-watchdog-{label}", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        log.warning("%s exceeded its %ss budget and was abandoned", label, int(timeout))
        raise TimeoutError(f"{label} exceeded {int(timeout)}s")
    if "error" in result:
        raise result["error"]
    return result["value"]
