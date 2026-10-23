"""Jobs for the worker process tests: a worker imports this module to run them, so it stays small."""

import os
import signal
import time


def sleeps(seconds: float, progress) -> None:
    progress(0.5)
    time.sleep(seconds)


def grabs(mb: int, progress) -> int:
    """Asks for memory without touching it: refused past the limit, and harmless without one."""
    import numpy as np

    return np.empty(mb * 2**20, dtype=np.uint8).nbytes


def dies(progress) -> None:
    os.kill(os.getpid(), signal.SIGKILL)


def fails(progress) -> None:
    raise ValueError("not a chess book")
