from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("airflow")

from airflow.timetables.trigger import CronTriggerTimetable  # noqa: E402

from schedule_visualizer import service  # noqa: E402
from schedule_visualizer.airflow_io.adapter import ScheduledDag  # noqa: E402
from schedule_visualizer.config import Config  # noqa: E402

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _dag(dag_id: str, *, tasks: int, paused: bool) -> ScheduledDag:
    return ScheduledDag(dag_id, tasks, CronTriggerTimetable("0 * * * *", timezone="UTC"), None, paused)


def _total_tasks(agg) -> int:
    return sum(counts.tasks for _day, counts in agg.view().day_series())


def test_compute_window_starts_at_midnight() -> None:
    now = datetime(2026, 6, 15, 13, 47, 9, tzinfo=timezone.utc)
    start, end = service.compute_window(now, window_days=31)
    assert start == datetime(2026, 6, 15, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 16, tzinfo=timezone.utc)
    assert end - start == timedelta(days=31)


def test_aggregate_dags_partitions_paused() -> None:
    aggs = service.aggregate_dags(
        [_dag("active", tasks=2, paused=False), _dag("paused", tasks=5, paused=True)],
        now=NOW,
        window_days=2,
    )
    active = _total_tasks(aggs.active)
    everything = _total_tasks(aggs.all)
    assert active > 0
    assert everything > active  # the paused DAG's load shows only in `all`
    assert aggs.pick(include_paused=False) is aggs.active
    assert aggs.pick(include_paused=True) is aggs.all


def test_cache_is_lazy_and_single_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_aggregate_dags(dags, *, now, window_days):  # noqa: ARG001
        calls["n"] += 1
        return object()

    monkeypatch.setattr(service, "load_scheduled_dags", lambda **_: [])
    monkeypatch.setattr(service, "aggregate_dags", fake_aggregate_dags)
    clock = lambda: NOW  # noqa: E731
    cache = service.build_cache(Config.from_env({}), clock=clock)

    assert calls["n"] == 0  # building the cache must not touch the DB
    cache.get()
    cache.get()
    assert calls["n"] == 1  # served from memory within the TTL


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
