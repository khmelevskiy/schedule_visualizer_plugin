"""Pure, Airflow-free schedule aggregation.

The data adapter feeds a stream of :class:`RunEvent` (one DAG firing at a
timestamp, tagged with its team and task count). This module aggregates them
into the projections the UI needs — per-day load, time-of-day load, a day x hour
heatmap, and per-minute slots. No Airflow, no I/O, no clock — everything is
passed in, so it runs and tests standalone.

Three accumulators, each a minimal basis: a joint ``(day, hour)`` histogram is
the single source for the day, hour and heatmap series (each a marginal of it); a
minute-of-day histogram keeps minute resolution for the slot table; a
minute-of-week histogram feeds weekly schedule suggestions. Tenancy is a plain
filter: :meth:`ScheduleAggregate.view` sums the requested teams (or all), so one
cached aggregate serves both the global picture and any per-team lens.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

type Metric = Literal["dags", "tasks"]
type DayHour = tuple[date, int]
MINUTES_PER_DAY = 24 * 60
HOURS_PER_DAY = 24


@dataclass(frozen=True, slots=True)
class Counts:
    """A (DAGs, tasks) tally for one bucket.

    Attributes
    ----------
    dags : int
        Number of DAG runs that fell into the bucket.
    tasks : int
        Sum of task counts across those runs.
    """

    dags: int = 0
    tasks: int = 0

    def __add__(self, other: Counts) -> Counts:
        return Counts(self.dags + other.dags, self.tasks + other.tasks)

    def metric(self, metric: Metric) -> int:
        """Return the ``"dags"`` or ``"tasks"`` component.

        Parameters
        ----------
        metric : {"dags", "tasks"}
            Which component to read.

        Returns
        -------
        int
            ``self.tasks`` for ``"tasks"``, otherwise ``self.dags``.
        """
        return self.tasks if metric == "tasks" else self.dags


@dataclass(frozen=True, slots=True)
class RunEvent:
    """One planned DAG run.

    Attributes
    ----------
    when : datetime
        When the DAG fires (timezone-aware, normalized to UTC by the adapter).
    task_count : int
        Number of tasks in the DAG — its weight in the "tasks" metric.
    team : str | None
        Owning team; ``None`` for untagged / single-tenant deployments.
    """

    when: datetime
    task_count: int
    team: str | None = None


def _minute_of_day(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def _bump[K](store: dict[tuple[K, str | None], list[int]], key: tuple[K, str | None], task_count: int) -> None:
    """Add one run (``+1`` dag, ``+task_count`` tasks) to ``store[key]``."""
    bucket = store.get(key)
    if bucket is None:
        store[key] = [1, task_count]
    else:
        bucket[0] += 1
        bucket[1] += task_count


def _sum_teams[K](
    store: dict[tuple[K, str | None], list[int]],
    selected: set[str | None] | None,
) -> dict[K, Counts]:
    """Collapse a ``(bucket, team) -> [dags, tasks]`` store to ``bucket -> Counts``.

    Parameters
    ----------
    store : dict[tuple[K, str | None], list[int]]
        Team-keyed accumulator.
    selected : set[str | None] | None
        Teams to include; ``None`` includes all.

    Returns
    -------
    dict[K, Counts]
        Per-bucket totals over the selected teams.
    """
    out: dict[K, Counts] = {}
    for (bucket, team), (dags, tasks) in store.items():
        if selected is not None and team not in selected:
            continue
        out[bucket] = out.get(bucket, Counts()) + Counts(dags, tasks)
    return out


@dataclass(frozen=True, slots=True)
class ScheduleView:
    """A team-filtered projection over the window.

    Attributes
    ----------
    window_start, window_end : datetime
        Half-open window ``[window_start, window_end)``.
    by_day_hour : Mapping[DayHour, Counts]
        Totals per ``(calendar day, hour-of-day)`` (sparse; empties omitted).
    by_minute : Mapping[int, Counts]
        Totals per minute-of-day ``0..1439`` (sparse; empties omitted).
    by_week_minute : Mapping[int, Counts]
        Totals per minute-of-week ``weekday * 1440 + minute-of-day`` (``0..10079``,
        Monday first; sparse). Feeds weekly schedule suggestions.
    """

    window_start: datetime
    window_end: datetime
    by_day_hour: Mapping[DayHour, Counts]
    by_minute: Mapping[int, Counts]
    by_week_minute: Mapping[int, Counts]

    def _days(self) -> list[date]:
        last = (self.window_end - timedelta(microseconds=1)).date()
        days: list[date] = []
        day = self.window_start.date()
        while day <= last:
            days.append(day)
            day += timedelta(days=1)
        return days

    def day_series(self) -> list[tuple[date, Counts]]:
        """Per-day totals for every day the window touches, ordered, zero-filled.

        Returns
        -------
        list[tuple[date, Counts]]
            ``(day, counts)`` for each day in the window, ascending.
        """
        totals: dict[date, Counts] = {}
        for (day, _hour), counts in self.by_day_hour.items():
            totals[day] = totals.get(day, Counts()) + counts
        return [(day, totals.get(day, Counts())) for day in self._days()]

    def hour_series(self) -> list[tuple[int, Counts]]:
        """Time-of-day totals ``0..23`` summed across all days, zero-filled.

        Returns
        -------
        list[tuple[int, Counts]]
            ``(hour, counts)`` for ``0..23``.
        """
        totals: dict[int, Counts] = {}
        for (_day, hour), counts in self.by_day_hour.items():
            totals[hour] = totals.get(hour, Counts()) + counts
        return [(hour, totals.get(hour, Counts())) for hour in range(HOURS_PER_DAY)]

    def heatmap(self) -> list[tuple[date, list[Counts]]]:
        """Day x hour grid, one zero-filled 24-slot row per day in the window.

        Returns
        -------
        list[tuple[date, list[Counts]]]
            ``(day, [counts_hour_0 .. counts_hour_23])`` per day, ascending.
        """
        return [
            (day, [self.by_day_hour.get((day, hour), Counts()) for hour in range(HOURS_PER_DAY)])
            for day in self._days()
        ]

    def minute_series(self) -> list[tuple[int, Counts]]:
        """All 1440 minutes of the day, in order, zero-filled.

        Returns
        -------
        list[tuple[int, Counts]]
            ``(minute_of_day, counts)`` for ``0..1439``.
        """
        return [(m, self.by_minute.get(m, Counts())) for m in range(MINUTES_PER_DAY)]


class ScheduleAggregate:
    """Team-keyed day-hour / minute / week-minute histograms over a fixed window.

    Built by :func:`aggregate`. Memory is bounded by the aggregate, not by the
    number of events: ``#days x 24 x #teams`` + ``1440 x #teams`` + ``10080 x
    #teams`` buckets.
    """

    __slots__ = ("_by_day_hour", "_by_minute", "_by_week_minute", "_teams", "window_end", "window_start")

    def __init__(self, window_start: datetime, window_end: datetime) -> None:
        self.window_start = window_start
        self.window_end = window_end
        self._by_day_hour: dict[tuple[DayHour, str | None], list[int]] = {}
        self._by_minute: dict[tuple[int, str | None], list[int]] = {}
        self._by_week_minute: dict[tuple[int, str | None], list[int]] = {}
        self._teams: set[str | None] = set()

    def add(self, event: RunEvent) -> None:
        """Fold one event in (ignored if outside the window)."""
        if not self.window_start <= event.when < self.window_end:
            return
        self._teams.add(event.team)
        minute = _minute_of_day(event.when)
        _bump(self._by_day_hour, ((event.when.date(), event.when.hour), event.team), event.task_count)
        _bump(self._by_minute, (minute, event.team), event.task_count)
        _bump(self._by_week_minute, (event.when.weekday() * MINUTES_PER_DAY + minute, event.team), event.task_count)

    @property
    def teams(self) -> list[str | None]:
        """Teams seen in the data, sorted (``None`` — untagged — last)."""
        return sorted(self._teams, key=lambda t: (t is None, t or ""))

    def view(self, teams: Iterable[str | None] | None = None) -> ScheduleView:
        """Collapse to a single projection, summing ``teams``.

        Parameters
        ----------
        teams : Iterable[str | None] | None
            Teams to include; ``None`` sums all (the global picture).

        Returns
        -------
        ScheduleView
            Day-hour and minute projections over the selected teams.
        """
        selected = None if teams is None else set(teams)
        return ScheduleView(
            window_start=self.window_start,
            window_end=self.window_end,
            by_day_hour=_sum_teams(self._by_day_hour, selected),
            by_minute=_sum_teams(self._by_minute, selected),
            by_week_minute=_sum_teams(self._by_week_minute, selected),
        )


def aggregate(
    events: Iterable[RunEvent],
    *,
    window_start: datetime,
    window_end: datetime,
) -> ScheduleAggregate:
    """Stream ``events`` into a :class:`ScheduleAggregate`.

    Parameters
    ----------
    events : Iterable[RunEvent]
        Planned run events; consumed lazily. Events outside the window are
        skipped.
    window_start, window_end : datetime
        Half-open window ``[window_start, window_end)`` (timezone-aware).

    Returns
    -------
    ScheduleAggregate
        The populated aggregate, ready to :meth:`~ScheduleAggregate.view`.

    Examples
    --------
    >>> from datetime import datetime, timezone
    >>> start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    >>> end = datetime(2026, 6, 8, tzinfo=timezone.utc)
    >>> events = [
    ...     RunEvent(datetime(2026, 6, 2, 9, 0, tzinfo=timezone.utc), task_count=3, team="alpha"),
    ...     RunEvent(datetime(2026, 6, 2, 9, 0, tzinfo=timezone.utc), task_count=1, team="beta"),
    ... ]
    >>> view = aggregate(events, window_start=start, window_end=end).view(["alpha"])
    >>> sum(c.tasks for _, c in view.day_series())  # only alpha's 3 tasks, beta filtered out
    3
    """
    agg = ScheduleAggregate(window_start=window_start, window_end=window_end)
    for event in events:
        agg.add(event)
    return agg
