from datetime import datetime, timezone

from schedule_visualizer.cache import Cached
from schedule_visualizer.core import RunEvent, aggregate
from schedule_visualizer.web.serialize import schedule_payload

WINDOW_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 6, 8, tzinfo=timezone.utc)  # 7 days
COMPUTED_AT = datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc)
EXPIRES_AT = datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc)


def _at(day: int, hour: int = 0, minute: int = 0, *, team: str | None = None, tasks: int = 1) -> RunEvent:
    return RunEvent(datetime(2026, 6, day, hour, minute, tzinfo=timezone.utc), task_count=tasks, team=team)


def _cached(events) -> Cached:
    agg = aggregate(events, window_start=WINDOW_START, window_end=WINDOW_END)
    return Cached(value=agg, computed_at=COMPUTED_AT, expires_at=EXPIRES_AT)


def _payload(events, *, teams=None, metric="tasks"):
    return schedule_payload(_cached(events), teams=teams, metric=metric)


def test_meta_and_window() -> None:
    p = _payload([_at(1, team="alpha"), _at(2, team="beta")])
    assert p["window"] == {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()}
    assert p["meta"]["updated_at"] == COMPUTED_AT.isoformat()
    assert p["meta"]["next_refresh"] == EXPIRES_AT.isoformat()
    assert p["meta"]["teams"] == ["alpha", "beta"]


def test_series_shapes() -> None:
    p = _payload([_at(2, 9, 30, tasks=3)])
    assert len(p["days"]) == 7  # one per window day
    assert len(p["hours"]) == 24
    assert len(p["heatmap"]["rows"]) == 7
    assert all(len(row["cells"]) == 24 for row in p["heatmap"]["rows"])
    assert p["heatmap"]["hours"] == list(range(24))


def test_slots_cover_every_minute_zero_filled() -> None:
    # runs at 09:30 and 14:05; the table still lists all 1440 minutes so free ones show
    p = _payload([_at(1, 9, 30, tasks=3), _at(2, 9, 30, tasks=2), _at(3, 14, 5, tasks=1)])
    assert len(p["slots"]) == 1440
    slots = {s["label"]: (s["dags"], s["tasks"]) for s in p["slots"]}
    assert slots["09:30"] == (2, 5)  # two runs collapse onto the same minute-of-day
    assert slots["14:05"] == (1, 1)
    assert slots["00:01"] == (0, 0)  # empty minutes are present (schedulable slots)


def test_team_filter_narrows_totals() -> None:
    events = [_at(1, team="alpha", tasks=2), _at(1, team="beta", tasks=3)]
    all_tasks = sum(d["tasks"] for d in _payload(events)["days"])
    alpha_tasks = sum(d["tasks"] for d in _payload(events, teams=["alpha"])["days"])
    assert all_tasks == 5
    assert alpha_tasks == 2


def test_suggestions_present_with_cron_and_load() -> None:
    p = _payload([_at(2, 9, 30, tasks=3)])
    cadences = [s["cadence"] for s in p["suggestions"]]
    assert cadences == [
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
    option = p["suggestions"][0]["options"][0]
    assert set(option) == {"label", "cron", "occurrences", "dags", "tasks"}
    assert option["occurrences"] == 7  # minute-of-day slots recur once per window day


def test_weekly_suggestion_occurrences_count_the_weekday() -> None:
    p = _payload([_at(2, 9, 30, tasks=3)])
    weekly = next(s for s in p["suggestions"] if s["cadence"] == "weekly")
    # 7-day window: every weekday falls exactly once
    assert all(o["occurrences"] == 1 for o in weekly["options"])


def test_days_and_slots_carry_both_metrics() -> None:
    # full rows for every day/slot, each with both metrics for client-side sorting
    events = [_at(2, 9, tasks=100), _at(4, 9, tasks=1), _at(4, 9, tasks=1)]
    p = _payload(events)
    day2 = next(d for d in p["days"] if d["date"] == "2026-06-02")
    day4 = next(d for d in p["days"] if d["date"] == "2026-06-04")
    assert (day2["dags"], day2["tasks"]) == (1, 100)
    assert (day4["dags"], day4["tasks"]) == (2, 2)
    assert p["metric"] == "tasks"  # echoed default sort key


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
