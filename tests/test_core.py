from datetime import date, datetime, timezone

import pytest

from schedule_visualizer.core import Counts, RunEvent, aggregate

WINDOW_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 6, 8, tzinfo=timezone.utc)  # 7-day window


def _at(day: int, hour: int = 0, minute: int = 0, *, team: str | None = None, tasks: int = 1) -> RunEvent:
    return RunEvent(datetime(2026, 6, day, hour, minute, tzinfo=timezone.utc), task_count=tasks, team=team)


def _agg(events):
    return aggregate(events, window_start=WINDOW_START, window_end=WINDOW_END)


# region aggregation


def test_counts_add_and_metric() -> None:
    c = Counts(1, 4) + Counts(2, 6)
    assert (c.dags, c.tasks) == (3, 10)
    assert c.metric("dags") == 3
    assert c.metric("tasks") == 10


def test_events_outside_window_are_ignored() -> None:
    view = _agg([_at(1), _at(30)]).view()  # 2026-06-30 is past window_end
    assert sum(c.dags for _, c in view.day_series()) == 1


def test_day_series_zero_filled_and_ordered() -> None:
    view = _agg([_at(3, tasks=5)]).view()
    series = view.day_series()
    assert [d for d, _ in series] == [date(2026, 6, d) for d in range(1, 8)]
    assert dict(series)[date(2026, 6, 3)] == Counts(1, 5)
    assert dict(series)[date(2026, 6, 1)] == Counts()  # empty day


def test_task_count_accumulates_per_bucket() -> None:
    view = _agg([_at(2, 9, 0, tasks=3), _at(2, 9, 0, tasks=4)]).view()
    # same day AND same minute -> both buckets see 2 dags / 7 tasks
    assert dict(view.day_series())[date(2026, 6, 2)] == Counts(2, 7)
    assert dict(view.minute_series())[9 * 60] == Counts(2, 7)


def test_hour_series_sums_across_days_zero_filled() -> None:
    # two runs at 09:00 on different days collapse onto the same hour-of-day slot
    view = _agg([_at(1, 9, tasks=2), _at(3, 9, tasks=4), _at(2, 14, tasks=1)]).view()
    hours = dict(view.hour_series())
    assert [h for h, _ in view.hour_series()] == list(range(24))
    assert hours[9] == Counts(2, 6)
    assert hours[14] == Counts(1, 1)
    assert hours[0] == Counts()


def test_by_week_minute_indexes_weekday_and_minute() -> None:
    view = _agg([_at(1, 9, 0, tasks=5)]).view()
    weekday = date(2026, 6, 1).weekday()  # Monday=0..Sunday=6
    assert view.by_week_minute[weekday * 1440 + 9 * 60] == Counts(1, 5)


def test_heatmap_is_day_by_24_hour_grid() -> None:
    view = _agg([_at(2, 9, tasks=3), _at(2, 9, tasks=1), _at(4, 23, tasks=5)]).view()
    grid = dict(view.heatmap())
    assert len(grid) == 7  # one row per window day
    assert all(len(row) == 24 for row in grid.values())
    assert grid[date(2026, 6, 2)][9] == Counts(2, 4)
    assert grid[date(2026, 6, 4)][23] == Counts(1, 5)
    assert grid[date(2026, 6, 1)][9] == Counts()  # empty cell


# endregion

# region minute series


def test_minute_series_places_run_at_its_minute_of_day() -> None:
    view = _agg([_at(1, 9, 30, tasks=5)]).view()
    minutes = dict(view.minute_series())
    assert len(minutes) == 1440
    assert minutes[9 * 60 + 30] == Counts(1, 5)
    assert minutes[0] == Counts()  # empty minute


# endregion

# region team filter


def test_view_filters_by_team() -> None:
    agg = _agg([_at(1, team="a", tasks=2), _at(1, team="b", tasks=3)])
    assert dict(agg.view().day_series())[date(2026, 6, 1)] == Counts(2, 5)  # all
    assert dict(agg.view(["a"]).day_series())[date(2026, 6, 1)] == Counts(1, 2)
    assert dict(agg.view(["b"]).day_series())[date(2026, 6, 1)] == Counts(1, 3)


def test_teams_listing_sorted_none_last() -> None:
    agg = _agg([_at(1, team="z"), _at(1, team="a"), _at(1)])
    assert agg.teams == ["a", "z", None]


# endregion


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
