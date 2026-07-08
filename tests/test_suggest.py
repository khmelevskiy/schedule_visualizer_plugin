from datetime import datetime, timezone

from schedule_visualizer.core import RunEvent, aggregate
from schedule_visualizer.suggest import suggest

# A full week window so weekly suggestions have every weekday available.
WINDOW_START = datetime(2026, 6, 1, tzinfo=timezone.utc)  # Monday
WINDOW_END = datetime(2026, 6, 8, tzinfo=timezone.utc)


def _at(day: int, hour: int = 0, minute: int = 0, *, tasks: int = 1) -> RunEvent:
    return RunEvent(datetime(2026, 6, day, hour, minute, tzinfo=timezone.utc), task_count=tasks, team=None)


def _view(events):
    return aggregate(events, window_start=WINDOW_START, window_end=WINDOW_END).view()


def _cadence(events, key):
    return next(cs for cs in suggest(_view(events), metric="tasks") if cs.cadence == key)


def test_all_cadences_present_and_ranked() -> None:
    result = suggest(_view([_at(2, 9, 0, tasks=5)]), metric="tasks")
    assert [cs.cadence for cs in result] == ["every_5", "every_10", "every_15", "every_30", "hourly", "daily", "weekly"]
    assert all(len(cs.options) == 3 for cs in result)


def test_daily_picks_the_emptiest_minute() -> None:
    # load only at 09:00 -> the quietest daily placement avoids minute 540
    daily = _cadence([_at(1, 9, 0, tasks=10), _at(2, 9, 0, tasks=10)], "daily")
    best = daily.options[0]
    assert best.peak.tasks == 0
    assert best.cron.endswith("* * *")
    assert best.label != "09:00"


def test_hourly_offset_avoids_the_busy_minute() -> None:
    # every day something runs at minute :00 -> hourly should avoid offset 0
    hourly = _cadence([_at(d, 0, 0, tasks=4) for d in range(1, 8)], "hourly")
    best = hourly.options[0]
    assert best.cron != "0 * * * *"
    assert best.peak.tasks == 0


def test_interval_cron_shape() -> None:
    fifteen = _cadence([_at(1, 0, 0, tasks=1)], "every_15")
    crons = {o.cron for o in fifteen.options}
    # offset 0 -> */15; other offsets -> N-59/15
    assert any(c == "*/15 * * * *" or c.endswith("-59/15 * * * *") for c in crons)


def test_weekly_encodes_weekday_and_time() -> None:
    # runs Monday (2026-06-01) 09:00 -> weekly best avoids that week-minute
    weekly = _cadence([_at(1, 9, 0, tasks=7)], "weekly")
    best = weekly.options[0]
    assert best.peak.tasks == 0
    # cron day-of-week field present (5 fields, last is the DOW)
    assert len(best.cron.split()) == 5
    assert best.label.split()[0] in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
