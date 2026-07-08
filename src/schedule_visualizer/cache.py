"""A tiny single-flight TTL cache, Airflow-free and clock-injected.

Recomputing the schedule aggregate walks every DAG's timetable, so it must run
rarely and never concurrently: the value is served from memory until its TTL
lapses, and exactly one caller recomputes on expiry while the rest wait for that
result (single-flight). The clock is injected so expiry is testable without
sleeping.

Storage is a single in-memory slot — correct for the per-replica cache each
api-server keeps. Swapping in a shared backend (Redis) for the multi-replica
platform means reimplementing this one class behind the same interface.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

type Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class Cached[T]:
    """A cached value with its freshness bounds.

    Attributes
    ----------
    value : T
        The cached payload.
    computed_at : datetime
        When it was computed.
    expires_at : datetime
        When it goes stale and the next :meth:`TtlCache.get` recomputes.
    """

    value: T
    computed_at: datetime
    expires_at: datetime


class TtlCache[T]:
    """Serve a computed value from memory, recomputing once per TTL.

    Parameters
    ----------
    compute : Callable[[], T]
        Produces a fresh value; called at most once per TTL, never concurrently.
    ttl : timedelta
        How long a computed value stays fresh.
    clock : Clock
        Returns "now" (timezone-aware); injected for testability.

    Notes
    -----
    Thread-safe and single-flight: the FastAPI layer serves each request from a
    worker thread, so many requests can hit an expired cache at once. Only the
    lock holder recomputes; the rest block briefly, then the re-check returns the
    value the holder just stored — so a burst of N concurrent readers triggers
    one recompute, not N. The trade-off is that on a *cold* cache those readers
    wait for that single compute (there is no prior value to serve meanwhile).

    The lock is process-local. Under multiple worker processes or replicas each
    computes once; a shared backend (Redis) reimplemented behind this interface
    collapses that to one compute per cluster.

    Examples
    --------
    >>> from datetime import datetime, timedelta, timezone
    >>> clock = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    >>> cache = TtlCache(compute=lambda: 42, ttl=timedelta(hours=1), clock=clock)
    >>> cache.get().value
    42
    """

    def __init__(self, *, compute: Callable[[], T], ttl: timedelta, clock: Clock) -> None:
        self._compute = compute
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._entry: Cached[T] | None = None

    def get(self) -> Cached[T]:
        """Return the fresh value, recomputing under a single-flight lock if stale.

        Returns
        -------
        Cached[T]
            The current value with its computation and expiry timestamps.
        """
        entry = self._entry
        if entry is not None and self._clock() < entry.expires_at:
            return entry
        with self._lock:
            # Re-check: another caller may have refreshed while we waited.
            entry = self._entry
            if entry is not None and self._clock() < entry.expires_at:
                return entry
            value = self._compute()
            now = self._clock()
            entry = Cached(value=value, computed_at=now, expires_at=now + self._ttl)
            self._entry = entry
            return entry

    def invalidate(self) -> None:
        """Drop the cached value so the next :meth:`get` recomputes."""
        with self._lock:
            self._entry = None
