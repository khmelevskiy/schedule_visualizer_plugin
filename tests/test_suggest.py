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
    assert [cs.cadence for cs in result] == [
        "every_5",
        "every_10",
        "every_15",
        "every_30",
        "hourly",
        "every_2h",
        "every_4h",
        "every_6h",
        "every_12h",
        "daily",
        "weekly",
        "monthly",
    ]
    assert all(len(cs.options) == 3 for cs in result)


def test_monthly_fixes_the_first_and_picks_the_quiet_minute() -> None:
    monthly = _cadence([_at(1, 9, 0, tasks=10), _at(2, 9, 0, tasks=10)], "monthly")
    best = monthly.options[0]
    assert best.peak.tasks == 0
    assert best.cron.split()[2] == "1"  # day-of-month pinned to the 1st
    assert best.label.startswith("1st, ")
    assert best.label != "1st, 09:00"


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


def test_multi_hour_cron_shape_and_offset() -> None:
    # load at 00:00 every day -> every-6h placements avoid minute-of-day 0
    six = _cadence([_at(d, 0, 0, tasks=9) for d in range(1, 8)], "every_6h")
    best = six.options[0]
    assert best.peak.tasks == 0
    minute_field, hour_field = best.cron.split()[:2]
    # hour field is either */6 (offset in hour 0) or H-23/6
    assert hour_field == "*/6" or hour_field.endswith("-23/6")
    assert not (hour_field == "*/6" and minute_field == "0")  # busy 00:00 avoided
    assert best.label.startswith("every 6 h at ")


def test_every_12h_avoids_the_loaded_phase() -> None:
    # load at 09:30 only -> the 09:30/21:30 phase is penalized; empty phases tie
    # at peak 0 and the earliest offset (00:00/12:00) wins
    twelve = _cadence([_at(d, 9, 30, tasks=5) for d in range(1, 8)], "every_12h")
    best = twelve.options[0]
    assert best.peak.tasks == 0
    assert best.cron == "0 */12 * * *"
    assert best.label == "every 12 h at 00:00"


def test_weekly_encodes_weekday_and_time() -> None:
    # runs Monday (2026-06-01) 09:00 -> weekly best avoids that week-minute
    weekly = _cadence([_at(1, 9, 0, tasks=7)], "weekly")
    best = weekly.options[0]
    assert best.peak.tasks == 0
    # cron day-of-week field present (5 fields, last is the DOW)
    assert len(best.cron.split()) == 5
    assert best.label.split()[0] in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


def test_occurrences_reflect_window_days() -> None:
    # 7-day window: minute-of-day slots recur 7 times, each weekday once
    for cadence in ("every_5", "hourly", "every_6h", "daily"):
        assert all(o.occurrences == 7 for o in _cadence([_at(1, 9, 0)], cadence).options)
    assert all(o.occurrences == 1 for o in _cadence([_at(1, 9, 0)], "weekly").options)


def test_weekly_ranking_normalizes_by_weekday_occurrences() -> None:
    # 8-day window Mon..Mon: Monday falls twice, the rest once. A daily DAG at
    # 09:00 loads every day equally per firing — raw sums would make Monday
    # 09:00 look twice as busy as the other weekdays at equal real load.
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)  # Monday
    end = datetime(2026, 6, 9, tzinfo=timezone.utc)
    events = [_at(d, 9, 0, tasks=5) for d in range(1, 9)]
    view = aggregate(events, window_start=start, window_end=end).view()
    weekly = next(cs for cs in suggest(view, metric="tasks") if cs.cadence == "weekly")
    # Every weekday 09:00 carries the same per-firing load (5 tasks); with
    # normalization no 09:00 slot is suggested at all — quieter minutes win.
    assert all(not o.label.endswith("09:00") for o in weekly.options)
    # Monday must not be systematically excluded either: all empty minutes tie
    # at avg 0 and the earliest week-minute wins, which is Monday 00:00.
    best = weekly.options[0]
    assert best.label == "Mon 00:00"
    assert best.occurrences == 2


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
