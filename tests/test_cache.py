import threading
import time
from datetime import datetime, timedelta, timezone

from schedule_visualizer.cache import TtlCache


class FakeClock:
    """Manually advanced clock for deterministic TTL tests."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def _counter():
    calls = {"n": 0}

    def compute() -> int:
        calls["n"] += 1
        return calls["n"]

    return compute, calls


def test_computes_once_within_ttl() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    compute, calls = _counter()
    cache = TtlCache(compute=compute, ttl=timedelta(hours=1), clock=clock)

    assert cache.get().value == 1
    clock.advance(timedelta(minutes=59))
    assert cache.get().value == 1  # still fresh
    assert calls["n"] == 1


def test_recomputes_after_ttl() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    compute, calls = _counter()
    cache = TtlCache(compute=compute, ttl=timedelta(hours=1), clock=clock)

    cache.get()
    clock.advance(timedelta(hours=1, seconds=1))
    assert cache.get().value == 2
    assert calls["n"] == 2


def test_invalidate_forces_recompute() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    compute, _ = _counter()
    cache = TtlCache(compute=compute, ttl=timedelta(hours=1), clock=clock)

    cache.get()
    cache.invalidate()
    assert cache.get().value == 2


def test_exposes_computed_and_expiry() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = FakeClock(start)
    compute, _ = _counter()
    cache = TtlCache(compute=compute, ttl=timedelta(hours=1), clock=clock)

    entry = cache.get()
    assert entry.computed_at == start
    assert entry.expires_at == start + timedelta(hours=1)


def test_single_flight_under_concurrency() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    calls = {"n": 0}

    def compute() -> int:
        calls["n"] += 1
        time.sleep(0.05)  # hold the lock long enough for every thread to queue on it
        return calls["n"]

    cache = TtlCache(compute=compute, ttl=timedelta(hours=1), clock=clock)
    threads = [threading.Thread(target=cache.get) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Only the lock holder computes; the rest see the fresh entry on re-check.
    assert calls["n"] == 1


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
