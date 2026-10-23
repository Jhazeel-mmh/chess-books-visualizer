"""Long work (analysing a book) in processes of their own, a few at a time.

A book file comes from outside, and the libraries that read it are large and written in C: a
malformed or hostile file could make them crash, hang or eat all the memory. Each analysis runs in a
worker process, at a lower priority than the server, with a limit on its memory and its time, so
such a book fails alone and the server goes on.

At most config.WORKERS jobs run at once, and never two of the same book. A hosted site also runs
one job of each reader at a time, and takes turns between readers: someone who imports fifty books
doesn't hold up everyone else.

Like any multiprocessing child, a worker imports the program that started the server again (as
__mp_main__): that program keeps its own work under ``if __name__ == "__main__"``.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import threading
import time
from collections.abc import Callable, Hashable

from . import config

try:
    import resource
except ImportError:  # Windows: no limits
    resource = None

log = logging.getLogger(__name__)


class Limit(Exception):
    """A worker went past its limit: "time" or "memory"."""

    def __init__(self, what: str):
        super().__init__(what)
        self.what = what


class Crashed(Exception):
    """A worker died without finishing (killed by a signal, or a crash in a library)."""


# --- Worker processes ---

# A fork server: each worker is a copy of a clean process that already loaded the readers, so it
# starts fast and shares nothing with the server's threads.
if "forkserver" in multiprocessing.get_all_start_methods():
    _context = multiprocessing.get_context("forkserver")
    _context.set_forkserver_preload(["cbv.library", "cbv.ingest.epub", "cbv.ingest.pdf"])
else:
    _context = multiprocessing.get_context("spawn")


def run(fn: Callable, *args, progress: Callable[[float], None] | None = None,
        minutes: float = 0, memory_mb: int = 0):
    """``fn(*args, progress=…)`` in a worker process, and what it returns or raises.

    ``fn`` and its arguments go to the worker by name: a function of a module, and plain values.
    ``progress`` gets what the worker reports as it goes. Raises Limit past ``minutes`` of time
    or ``memory_mb`` of memory (0: no limit), and Crashed if the worker dies.
    """
    receiver, sender = _context.Pipe(duplex=False)
    worker = _context.Process(target=_work, args=(sender, fn, args, memory_mb), daemon=True)
    worker.start()
    sender.close()
    deadline = time.monotonic() + minutes * 60 if minutes else None
    try:
        while True:
            if not receiver.poll(None if deadline is None else max(0.0, deadline - time.monotonic())):
                raise Limit("time")
            try:
                kind, value = receiver.recv()
            except EOFError:
                worker.join()
                raise Crashed(f"exit code {worker.exitcode}") from None
            if kind == "progress":
                if progress:
                    progress(value)
            elif kind == "done":
                return value
            elif kind == "memory":
                raise Limit("memory")
            else:
                raise value
    finally:
        if worker.is_alive():
            worker.kill()
        worker.join()
        receiver.close()


def _work(sender, fn: Callable, args: tuple, memory_mb: int) -> None:
    """In the worker: runs the job and sends back its progress and what came of it."""
    if hasattr(os, "nice"):
        os.nice(10)
    if memory_mb and resource:
        resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 2**20, memory_mb * 2**20))
    try:
        sender.send(("done", fn(*args, progress=lambda f: sender.send(("progress", f)))))
    except MemoryError:
        sender.send(("memory", None))
    except Exception as e:
        log.exception("a job failed")
        try:
            sender.send(("error", e))
        except Exception:  # the exception can't be sent as it is
            sender.send(("error", RuntimeError(repr(e))))


# --- Turns ---

class Queue:
    """Jobs waiting for their turn, and the server threads that run them."""

    def __init__(self) -> None:
        self.waiting: list[tuple[str, Hashable, Callable[[], None]]] = []
        self.running: list[tuple[str, Hashable]] = []
        # When each reader's last job started: the one served longest ago goes next.
        self.served: dict[str, float] = {}
        self.threads: list[threading.Thread] = []
        self.changed = threading.Condition()

    def submit(self, owner: str, key: Hashable, job: Callable[[], None]) -> None:
        """Runs ``job`` (in a server thread, which starts the worker) when its turn comes.

        ``owner`` is whose job it is, and ``key`` what it works on: a job already waiting with the
        same key isn't added twice; one already running with it runs again after.
        """
        with self.changed:
            if not any(k == key for _, k, _ in self.waiting):
                self.waiting.append((owner, key, job))
            while len(self.threads) < max(1, config.WORKERS):
                thread = threading.Thread(target=self._serve, daemon=True, name=f"jobs-{len(self.threads)}")
                self.threads.append(thread)
                thread.start()
            self.changed.notify_all()

    def _next(self) -> tuple[str, Hashable, Callable[[], None]] | None:
        """The job whose turn it is, or None while every waiting one must wait."""
        busy_keys = {k for _, k in self.running}
        busy_owners = {o for o, _ in self.running} if config.HOSTED else set()
        ready = [j for j in self.waiting if j[1] not in busy_keys and j[0] not in busy_owners]
        return min(ready, key=lambda j: self.served.get(j[0], 0.0), default=None)

    def _serve(self) -> None:
        while True:
            with self.changed:
                while (job := self._next()) is None:
                    self.changed.wait()
                owner, key, work = job
                self.waiting.remove(job)
                self.running.append((owner, key))
                self.served[owner] = time.monotonic()
            try:
                work()
            except Exception:
                log.exception("job %s failed", key)
            finally:
                with self.changed:
                    self.running.remove((owner, key))
                    self.changed.notify_all()


_queue = Queue()


def submit(owner: str, key: Hashable, job: Callable[[], None]) -> None:
    _queue.submit(owner, key, job)
