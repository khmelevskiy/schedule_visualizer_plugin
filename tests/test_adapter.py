from datetime import datetime, timezone

import pytest

pytest.importorskip("airflow")  # adapter tests need Airflow installed

from airflow.timetables.interval import CronDataIntervalTimetable  # noqa: E402
from airflow.timetables.trigger import CronTriggerTimetable  # noqa: E402

from schedule_visualizer.airflow_io.adapter import ScheduledDag, collect_events, events_for, iter_runs  # noqa: E402
from schedule_visualizer.core import aggregate  # noqa: E402

WINDOW_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 6, 3, tzinfo=timezone.utc)  # 2 days


def _hourly() -> CronDataIntervalTimetable:
    return CronDataIntervalTimetable("0 * * * *", timezone="UTC")


# region iter_runs


def test_iter_runs_hourly_count_and_bounds() -> None:
    runs = list(iter_runs(_hourly(), window_start=WINDOW_START, window_end=WINDOW_END))
    # 47, not 48: a data-interval timetable drops the run whose interval starts
    # before window_start (Airflow TimeRestriction semantics — see iter_runs docs).
    assert len(runs) == 47
    assert all(WINDOW_START <= r < WINDOW_END for r in runs)
    assert runs == sorted(runs)


def test_iter_runs_end_is_exclusive() -> None:
    runs = list(iter_runs(_hourly(), window_start=WINDOW_START, window_end=WINDOW_END))
    assert WINDOW_END not in runs


def test_iter_runs_cap_bounds_output() -> None:
    runs = list(iter_runs(_hourly(), window_start=WINDOW_START, window_end=WINDOW_END, cap=5))
    assert len(runs) <= 5


def test_iter_runs_trigger_timetable_supported() -> None:
    # CronTriggerTimetable is the Airflow-3 default for string cron — must work.
    tt = CronTriggerTimetable("0 0 * * *", timezone="UTC")
    runs = list(iter_runs(tt, window_start=WINDOW_START, window_end=WINDOW_END))
    assert len(runs) == 2  # daily over 2 days


# endregion

# region events / aggregation wiring


def test_events_for_propagates_team_and_task_count() -> None:
    dag = ScheduledDag(dag_id="d", task_count=3, timetable=_hourly(), team="alpha")
    events = list(events_for(dag, window_start=WINDOW_START, window_end=WINDOW_END))
    assert len(events) == 47
    assert all(e.team == "alpha" and e.task_count == 3 for e in events)


def test_collect_events_feeds_aggregate() -> None:
    dags = [
        ScheduledDag("a", task_count=2, timetable=_hourly(), team="alpha"),
        ScheduledDag("b", task_count=5, timetable=CronDataIntervalTimetable("0 0 * * *", timezone="UTC"), team="beta"),
    ]
    events = collect_events(dags, window_start=WINDOW_START, window_end=WINDOW_END)
    view = aggregate(events, window_start=WINDOW_START, window_end=WINDOW_END).view()
    # alpha: 47 hourly runs x 2 tasks; beta: 1 daily run x 5 tasks
    total = sum(c.tasks for _, c in view.day_series())
    assert total == 47 * 2 + 1 * 5
    assert sum(c.dags for _, c in view.day_series()) == 47 + 1


def test_collect_events_dedupes_identical_schedules(monkeypatch: pytest.MonkeyPatch) -> None:
    import schedule_visualizer.airflow_io.adapter as ad

    expanded: list[object] = []
    real_iter = ad.iter_runs

    def spy(timetable, **kwargs):
        expanded.append(timetable)
        return real_iter(timetable, **kwargs)

    monkeypatch.setattr(ad, "iter_runs", spy)

    dags = [
        ScheduledDag("a", 1, _hourly(), "t1"),  # same schedule as b
        ScheduledDag("b", 1, _hourly(), "t2"),
        ScheduledDag("c", 1, CronDataIntervalTimetable("0 0 * * *", timezone="UTC"), "t3"),
    ]
    events = list(ad.collect_events(dags, window_start=WINDOW_START, window_end=WINDOW_END))

    # 3 DAGs, but only 2 distinct schedules -> expanded twice, not thrice.
    assert len(expanded) == 2
    assert len(events) == 47 + 47 + 1  # a + b reuse the same 47 times; c has 1


# endregion


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
