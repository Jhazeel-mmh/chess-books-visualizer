"""How often a hosted site lets each client do what is worth abusing: guessing passwords, signing
up, making the site send mail, uploading books, sending copyright notices.

Tries are counted in the server's memory over a sliding window, so the site runs one server
process (they would be counted apart in each). They are never written down, and are forgotten
within a minute of being older than the longest window (an hour): the privacy notice says so.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from collections import deque
from typing import NamedTuple

from . import config


class Limit(NamedTuple):
    times: int
    seconds: int


class TooMany(Exception):
    """Past the limit: ``retry_after`` is how many seconds until the next try counts."""

    def __init__(self, retry_after: int):
        super().__init__(retry_after)
        self.retry_after = retry_after


_tries: dict[tuple[str, str], deque[float]] = {}
_lock = threading.Lock()
_LONGEST = 3600  # no limit counts over more than an hour
_KEYS = 100_000  # tries kept before the old ones are swept at once
_SWEEP = 60  # otherwise they are swept this often (seconds)
_sweeper: threading.Thread | None = None


def check(action: str, key: str, limit: Limit, now: float | None = None) -> None:
    """Raises TooMany if ``key`` (a client, an account, an email) already tried ``action`` as often
    as ``limit`` allows. Only on a hosted site: the local app limits nothing."""
    if not config.HOSTED:
        return
    now = time.monotonic() if now is None else now
    with _lock:
        tries = _recent(action, key, limit.seconds, now)
        if len(tries) >= limit.times:
            raise TooMany(int(tries[0] + limit.seconds - now) + 1)


def count(action: str, key: str, now: float | None = None) -> None:
    """Counts one try of ``action`` by ``key``."""
    if not config.HOSTED:
        return
    global _sweeper
    now = time.monotonic() if now is None else now
    with _lock:
        _tries.setdefault((action, key), deque()).append(now)
        if len(_tries) > _KEYS:
            _sweep(now)
        if _sweeper is None:
            _sweeper = threading.Thread(target=_sweep_forever, name="ratelimit-sweep", daemon=True)
            _sweeper.start()


def take(action: str, key: str, limit: Limit, now: float | None = None) -> None:
    """Checks, then counts, one try."""
    check(action, key, limit, now)
    count(action, key, now)


def sweep(now: float | None = None) -> None:
    """Forgets the clients, accounts and emails whose last try is older than any limit counts."""
    now = time.monotonic() if now is None else now
    with _lock:
        _sweep(now)


def _sweep(now: float) -> None:
    for k in [k for k, tries in _tries.items() if not tries or tries[-1] <= now - _LONGEST]:
        del _tries[k]


def _sweep_forever() -> None:
    while True:
        time.sleep(_SWEEP)
        sweep()


def _recent(action: str, key: str, seconds: int, now: float) -> deque[float]:
    tries = _tries.get((action, key), deque())
    while tries and tries[0] <= now - seconds:
        tries.popleft()
    return tries


def client(host: str | None) -> str:
    """Who a request comes from: its address, or for IPv6 its network (anyone gets a whole /64)."""
    try:
        address = ipaddress.ip_address(host or "")
    except ValueError:
        return host or "?"
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def reset() -> None:
    """Forgets every try (for tests)."""
    with _lock:
        _tries.clear()
