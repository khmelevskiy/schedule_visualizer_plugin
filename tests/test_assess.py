from datetime import datetime, timezone

from schedule_visualizer.assess import assess, upcoming
from schedule_visualizer.core import RunEvent, aggregate

# A full week window so weekly minutes map 1:1 to weekdays.
WINDOW_START = datetime(2026, 6, 1, tzinfo=timezone.utc)  # Monday
WINDOW_END = datetime(2026, 6, 8, tzinfo=timezone.utc)


def _at(day: int, hour: int = 0, minute: int = 0, *, tasks: int = 1) -> RunEvent:
    return RunEvent(datetime(2026, 6, day, hour, minute, tzinfo=timezone.utc), task_count=tasks, team=None)


def _view(events):
    return aggregate(events, window_start=WINDOW_START, window_end=WINDOW_END).view()


def test_invalid_cron_returns_none() -> None:
    view = _view([_at(1, 9, 0)])
    assert assess(view, "not a cron", metric="tasks") is None
    assert assess(view, "* * * *", metric="tasks") is None


def test_empty_cluster_scores_100() -> None:
    a = assess(_view([]), "0 3 * * *", metric="tasks")
    assert a is not None
    assert a.score == 100
    assert a.peak == 0


def test_hitting_the_busiest_minute_scores_0() -> None:
    # all load on Tuesday 09:00; a cron firing exactly there is the worst case
    a = assess(_view([_at(2, 9, 0, tasks=10)]), "0 9 * * 2", metric="tasks")
    assert a is not None
    assert a.score == 0
    assert a.peak == 10
    assert a.peak_label == "Tue 09:00"


def test_quiet_slot_scores_100_even_with_load_elsewhere() -> None:
    a = assess(_view([_at(2, 9, 0, tasks=10)]), "30 4 * * *", metric="tasks")
    assert a is not None
    assert a.score == 100
    assert a.peak == 0


def test_score_is_linear_between_extremes() -> None:
    # busiest minute holds 10 tasks, the assessed cron hits a 5-task minute
    events = [_at(2, 9, 0, tasks=10), _at(3, 12, 0, tasks=5)]
    a = assess(_view(events), "0 12 * * 3", metric="tasks")
    assert a is not None
    assert a.score == 50


def test_touching_any_load_never_scores_100() -> None:
    # tiny load vs a huge busiest minute: capped at 99, not rounded to 100
    events = [_at(2, 9, 0, tasks=1000), _at(3, 12, 0, tasks=1)]
    a = assess(_view(events), "0 12 * * 3", metric="tasks")
    assert a is not None
    assert a.score == 99


def test_daily_cron_grades_its_worst_weekday() -> None:
    # daily at 09:00, but only Tuesday 09:00 is loaded -> peak is that firing
    a = assess(_view([_at(2, 9, 0, tasks=10)]), "0 9 * * *", metric="tasks")
    assert a is not None
    assert a.score == 0
    assert a.peak_label == "Tue 09:00"
    assert a.firings_per_week == 7


def test_day_of_month_cron_expands_the_window() -> None:
    # 2026-06-03 is the only June day in the window matching day-of-month 3
    a = assess(_view([_at(3, 0, 0, tasks=4)]), "0 0 3 * *", metric="tasks")
    assert a is not None
    assert a.peak == 4
    assert a.peak_label == "Wed 00:00"


def test_never_firing_in_window_returns_none() -> None:
    # day-of-month 20 does not occur in the 7-day window
    assert assess(_view([_at(1)]), "0 0 20 * *", metric="tasks") is None


def test_daily_alias_is_graded_like_midnight_cron() -> None:
    # all load at Monday 00:00 -> @daily hits it head-on
    a = assess(_view([_at(1, 0, 0, tasks=10)]), "@daily", metric="tasks")
    assert a is not None
    assert a.score == 0
    assert a.peak_label == "Mon 00:00"
    assert a.firings_per_week == 7


def test_monthly_alias_expands_the_window() -> None:
    # @monthly fires on the 1st at 00:00 — inside the 7-day window exactly once
    a = assess(_view([_at(1, 0, 0, tasks=4)]), "@monthly", metric="tasks")
    assert a is not None
    assert a.peak == 4
    assert a.peak_label == "Mon 00:00"


def test_yearly_alias_outside_window_returns_none() -> None:
    # Jan 1st never falls inside a June window
    assert assess(_view([_at(1)]), "@yearly", metric="tasks") is None


def test_unknown_alias_returns_none() -> None:
    assert assess(_view([_at(1)]), "@reboot", metric="tasks") is None


def test_upcoming_lists_the_next_firings() -> None:
    start = datetime(2026, 6, 1, 2, 59, tzinfo=timezone.utc)
    runs = upcoming("0 3 * * *", start=start)
    assert runs == [datetime(2026, 6, day, 3, 0, tzinfo=timezone.utc) for day in range(1, 6)]


def test_upcoming_honors_count_and_aliases() -> None:
    start = datetime(2026, 6, 1, 5, 0, tzinfo=timezone.utc)
    runs = upcoming("@daily", start=start, count=2)
    assert runs == [datetime(2026, 6, 2, tzinfo=timezone.utc), datetime(2026, 6, 3, tzinfo=timezone.utc)]


def test_upcoming_invalid_cron_returns_none() -> None:
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert upcoming("nope", start=start) is None
    assert upcoming("* * * *", start=start) is None
    assert upcoming("@reboot", start=start) is None


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
