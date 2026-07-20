"""Turn a cached aggregate into the JSON payload the frontend consumes.

Pure and dependency-free (no Airflow, no FastAPI): it takes a
:class:`Cached[ScheduleAggregate]` and query choices, and returns plain dicts.
Every series carries both metrics and all rows, so the client sorts and switches
metric without a round-trip. ``metric`` is echoed as the client's default sort
key.
"""

from datetime import date, datetime

from schedule_visualizer.assess import assess, upcoming
from schedule_visualizer.cache import Cached
from schedule_visualizer.core import Counts, Metric, ScheduleAggregate, ScheduleView
from schedule_visualizer.suggest import suggest


def _counts(counts: Counts) -> dict[str, int]:
    return {"dags": counts.dags, "tasks": counts.tasks}


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _day(day: date, counts: Counts) -> dict[str, object]:
    return {"date": day.isoformat(), **_counts(counts)}


def _slots(view: ScheduleView) -> list[dict[str, object]]:
    # Every minute of the day (0..1439), zero-filled — free minutes are the whole
    # point (that's where you place new work), so they must be listed too. The
    # client sorts, surfacing the quietest minutes first.
    return [{"minute": minute, "label": _hhmm(minute), **_counts(counts)} for minute, counts in view.minute_series()]


def _heatmap(view: ScheduleView) -> dict[str, object]:
    rows = [{"date": day.isoformat(), "cells": [_counts(c) for c in cells]} for day, cells in view.heatmap()]
    return {"hours": list(range(24)), "rows": rows}


def _suggestions(view: ScheduleView, metric: Metric) -> list[dict[str, object]]:
    return [
        {
            "cadence": cs.cadence,
            "label": cs.label,
            "options": [
                {"label": o.label, "cron": o.cron, "occurrences": o.occurrences, **_counts(o.peak)} for o in cs.options
            ],
        }
        for cs in suggest(view, metric=metric)
    ]


def assess_payload(view: ScheduleView, cron: str, *, metric: Metric, now: datetime) -> dict[str, object]:
    """Grade ``cron`` against ``view``; ``{"valid": False}`` when unparseable.

    Parameters
    ----------
    view : ScheduleView
        Team-filtered projection to grade against.
    cron : str
        Five-field cron expression, UTC.
    metric : {"dags", "tasks"}
        Metric to grade on.
    now : datetime
        Instant the upcoming firings are listed from (timezone-aware, UTC).

    Returns
    -------
    dict[str, object]
        ``valid``, and for valid crons: ``score`` (0 busiest .. 100 empty),
        ``peak``, ``peak_label``, ``average``, ``firings_per_week``,
        ``next_runs`` (ISO instants of the next five firings).
    """
    a = assess(view, cron, metric=metric)
    if a is None:
        return {"valid": False}
    return {
        "valid": True,
        "score": a.score,
        "peak": round(a.peak, 1),
        "peak_label": a.peak_label,
        "average": round(a.average, 1),
        "firings_per_week": a.firings_per_week,
        "next_runs": [run.isoformat() for run in upcoming(cron, start=now) or []],
    }


def schedule_payload(
    cached: Cached[ScheduleAggregate],
    *,
    teams: list[str] | None,
    metric: Metric,
) -> dict[str, object]:
    """Serialize a cached aggregate for a team selection and metric.

    Parameters
    ----------
    cached : Cached[ScheduleAggregate]
        The cached aggregate with its freshness timestamps.
    teams : list[str] | None
        Teams to include; ``None`` sums all (the global picture).
    metric : {"dags", "tasks"}
        Echoed back as the client's default sort key.

    Returns
    -------
    dict[str, object]
        The full response payload.
    """
    agg = cached.value
    selection: list[str | None] | None = list(teams) if teams is not None else None
    view = agg.view(selection)
    suggestions_by_metric = {candidate: _suggestions(view, candidate) for candidate in ("dags", "tasks")}
    return {
        "window": {
            "start": view.window_start.isoformat(),
            "end": view.window_end.isoformat(),
        },
        "meta": {
            "updated_at": cached.computed_at.isoformat(),
            "next_refresh": cached.expires_at.isoformat(),
            "teams": agg.teams,
            # All time-of-day analysis is bucketed in UTC (what timetables emit).
            # Converting minute-of-day to a local zone is unstable across DST, so
            # the UI states the zone rather than silently shifting buckets.
            "timezone": "UTC",
            "window_days": len(view.day_series()),
        },
        "selected_teams": teams,
        "metric": metric,
        "days": [_day(day, counts) for day, counts in view.day_series()],
        "hours": [{"hour": hour, **_counts(counts)} for hour, counts in view.hour_series()],
        "slots": _slots(view),
        "heatmap": _heatmap(view),
        # Keep the legacy selected list for API compatibility. The complete
        # mapping lets the UI switch metrics without another HTTP request.
        "suggestions": suggestions_by_metric[metric],
        "suggestions_by_metric": suggestions_by_metric,
    }
