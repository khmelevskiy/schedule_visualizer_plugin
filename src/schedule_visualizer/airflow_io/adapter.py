"""Airflow data adapter: turn DAG timetables into planned :class:`RunEvent`s.

Kept separate from :mod:`schedule_visualizer.core` so the aggregation stays
Airflow-free. This module is the only place that touches Airflow's timetable
API, so a move to another scheduler means rewriting just this file.

Planned only: run times come from each DAG's timetable (``next_dagrun_info``),
which works for every timetable type (cron, data-interval, delta, custom) — not
just cron strings. Task weight is the DAG's task count, read from its structure,
so no run history is needed.
"""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any

import pendulum
from airflow.timetables.base import TimeRestriction, Timetable
from airflow.timetables.interval import CronDataIntervalTimetable
from airflow.timetables.trigger import CronTriggerTimetable
from croniter import croniter

from schedule_visualizer.core import RunEvent

# Safety bound on timetable expansion per DAG, so a sub-minute schedule over a
# month-wide window can't spin forever. A minutely DAG over ~35 days is ~50k.
DEFAULT_RUN_CAP = 200_000


@dataclass(frozen=True, slots=True)
class _CronFields:
    minutes: tuple[int, ...]
    hours: tuple[int, ...]
    days: tuple[int, ...] | None
    months: tuple[int, ...] | None
    weekdays: tuple[int, ...] | None
    day_or: bool
    skip_first: bool


def _values(field: list[Any]) -> tuple[int, ...] | None:
    """Return a simple numeric cron field, ``None`` for wildcard, or raise."""
    if field == ["*"]:
        return None
    if not all(type(value) is int for value in field):
        raise ValueError("advanced cron field")
    return tuple(field)


def _fast_cron_fields(timetable: Timetable, start: datetime) -> _CronFields | None:
    """Describe cron schedules safe for analytical UTC expansion.

    Airflow remains the correctness fallback for custom timetables, non-UTC
    schedules (where DST matters), trigger intervals/run-immediately behavior,
    and croniter's special ``L``/``#`` forms.
    """
    # Exact built-ins only: a subclass may override Airflow's scheduling
    # semantics even if its serialized cron fields look ordinary.
    if type(timetable) not in (CronTriggerTimetable, CronDataIntervalTimetable):
        return None
    try:
        payload = timetable.serialize()
        if str(payload.get("timezone")) != "UTC":
            return None
        if isinstance(timetable, CronTriggerTimetable) and (
            payload.get("interval", 0.0) != 0.0 or payload.get("run_immediately", False)
        ):
            return None
        parsed = croniter(str(payload["expression"]), start)
        expanded = parsed.expanded
        if len(expanded) != 5 or parsed.nth_weekday_of_month:
            return None
        minutes, hours, days, months, weekdays = (_values(field) for field in expanded)
        return _CronFields(
            minutes=tuple(range(60)) if minutes is None else minutes,
            hours=tuple(range(24)) if hours is None else hours,
            days=days,
            months=months,
            weekdays=weekdays,
            day_or=parsed._day_or,
            skip_first=isinstance(timetable, CronDataIntervalTimetable),
        )
    except KeyError, TypeError, ValueError:
        return None


def _day_matches(day: datetime, fields: _CronFields) -> bool:
    if fields.months is not None and day.month not in fields.months:
        return False
    day_of_month = fields.days is None or day.day in fields.days
    # cron: Sunday=0; datetime: Monday=0.
    day_of_week = fields.weekdays is None or (day.weekday() + 1) % 7 in fields.weekdays
    if fields.days is not None and fields.weekdays is not None:
        return day_of_month or day_of_week if fields.day_or else day_of_month and day_of_week
    return day_of_month and day_of_week


def _iter_standard_utc_cron(
    fields: _CronFields, *, window_start: datetime, window_end: datetime, cap: int
) -> Iterator[datetime]:
    start = window_start.astimezone(timezone.utc)
    end = window_end.astimezone(timezone.utc)
    day = datetime.combine(start.date(), time.min, tzinfo=timezone.utc)
    emitted = 0
    skipped_first = False
    while day < end and emitted < cap:
        if _day_matches(day, fields):
            for hour in fields.hours:
                for minute in fields.minutes:
                    when = day.replace(hour=hour, minute=minute)
                    if when < start or when >= end:
                        continue
                    # A data-interval run fires at the *end* of its interval.
                    # Airflow's earliest restriction applies to the interval
                    # start, so the first cron boundary in the window starts an
                    # interval but does not itself produce a run.
                    if fields.skip_first and not skipped_first:
                        skipped_first = True
                        continue
                    if when < end:
                        yield when
                        emitted += 1
                        if emitted >= cap:
                            return
        day += timedelta(days=1)


@dataclass(frozen=True, slots=True)
class ScheduledDag:
    """A DAG reduced to what the visualization needs.

    Attributes
    ----------
    dag_id : str
        DAG identifier (kept for future drill-down; not used by counts).
    task_count : int
        Number of tasks — the DAG's weight in the "tasks" metric.
    timetable : Timetable
        The DAG's Airflow timetable, expanded to planned run times.
    team : str | None
        Owning team; ``None`` for untagged / single-tenant.
    paused : bool
        Whether the DAG is paused (won't fire). Kept so the aggregate can be
        built with or without paused DAGs; excluded by default.
    """

    dag_id: str
    task_count: int
    timetable: Timetable
    team: str | None = None
    paused: bool = False


def iter_runs(
    timetable: Timetable,
    *,
    window_start: datetime,
    window_end: datetime,
    cap: int = DEFAULT_RUN_CAP,
) -> Iterator[datetime]:
    """Yield planned ``run_after`` times of ``timetable`` within the window.

    Parameters
    ----------
    timetable : Timetable
        An Airflow timetable.
    window_start, window_end : datetime
        Half-open window ``[window_start, window_end)`` (timezone-aware).
    cap : int
        Hard ceiling on iterations, so high-frequency schedules stay bounded.

    Yields
    ------
    datetime
        Each ``run_after`` in ``[window_start, window_end)``, ascending.

    Notes
    -----
    Windowing follows Airflow's own ``TimeRestriction``: a data-interval
    timetable only emits runs whose data interval *starts* within the window, so
    a run firing exactly at ``window_start`` (its interval began earlier) is not
    counted. Over a month-wide window this leading-edge effect is at most one run
    per DAG and immaterial to the picture.

    Examples
    --------
    >>> from datetime import datetime, timezone
    >>> from airflow.timetables.trigger import CronTriggerTimetable
    >>> tt = CronTriggerTimetable("0 0 * * *", timezone="UTC")  # daily at midnight
    >>> start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    >>> end = datetime(2026, 6, 3, tzinfo=timezone.utc)  # 2-day window
    >>> len(list(iter_runs(tt, window_start=start, window_end=end)))
    2
    """
    fast_fields = _fast_cron_fields(timetable, window_start)
    if fast_fields is not None:
        yield from _iter_standard_utc_cron(
            fast_fields,
            window_start=window_start,
            window_end=window_end,
            cap=cap,
        )
        return

    # Airflow timetables operate on pendulum datetimes (they call .in_timezone).
    earliest = pendulum.instance(window_start)
    latest = pendulum.instance(window_end)
    restriction = TimeRestriction(earliest=earliest, latest=latest, catchup=True)
    last_interval = None
    for _ in range(cap):
        info = timetable.next_dagrun_info(last_automated_data_interval=last_interval, restriction=restriction)
        if info is None:
            return
        run_after = info.run_after
        if run_after >= latest:
            return
        if run_after >= earliest:
            yield run_after
        last_interval = info.data_interval


def events_for(
    dag: ScheduledDag,
    *,
    window_start: datetime,
    window_end: datetime,
    cap: int = DEFAULT_RUN_CAP,
) -> Iterator[RunEvent]:
    """Expand one :class:`ScheduledDag` into :class:`RunEvent`s over the window.

    Parameters
    ----------
    dag : ScheduledDag
        The DAG whose timetable is expanded; its ``task_count`` and ``team``
        are stamped onto every emitted event.
    window_start, window_end : datetime
        Half-open window ``[window_start, window_end)`` (timezone-aware).
    cap : int
        Hard ceiling on run expansion (see :func:`iter_runs`).

    Yields
    ------
    RunEvent
        One event per planned run of ``dag`` within the window.
    """
    for when in iter_runs(dag.timetable, window_start=window_start, window_end=window_end, cap=cap):
        yield RunEvent(when=when, task_count=dag.task_count, team=dag.team)


def _timetable_key(timetable: Timetable) -> str:
    """Stable identity for a timetable, so identical schedules dedupe.

    Uses the timetable's own ``serialize()`` (what Airflow persists), keyed by
    concrete type. Falls back to instance identity if a timetable can't
    serialize — correctness holds, that one just isn't shared.
    """
    cls = f"{type(timetable).__module__}.{type(timetable).__qualname__}"
    try:
        payload = json.dumps(timetable.serialize(), sort_keys=True, default=str)
    except Exception:
        return f"{cls}:{id(timetable)}"
    return f"{cls}:{payload}"


def collect_events(
    dags: Iterable[ScheduledDag],
    *,
    window_start: datetime,
    window_end: datetime,
    cap_per_dag: int = DEFAULT_RUN_CAP,
) -> Iterator[RunEvent]:
    """Stream events for every DAG, expanding each *distinct* schedule only once.

    DAGs that share a timetable (e.g. many ``*/5 * * * *`` DAGs) reuse one cached
    list of run times — the expensive expansion runs once per unique schedule,
    not once per DAG. Times are shared; ``team`` / ``task_count`` stay per-DAG.

    Parameters
    ----------
    dags : Iterable[ScheduledDag]
        DAGs to expand.
    window_start, window_end : datetime
        Half-open window ``[window_start, window_end)``.
    cap_per_dag : int
        Per-schedule expansion ceiling (see :func:`iter_runs`).

    Yields
    ------
    RunEvent
        Planned events across all DAGs, ready for ``core.aggregate``.
    """
    run_times: dict[str, list[datetime]] = {}
    for dag in dags:
        key = _timetable_key(dag.timetable)
        times = run_times.get(key)
        if times is None:
            times = list(iter_runs(dag.timetable, window_start=window_start, window_end=window_end, cap=cap_per_dag))
            run_times[key] = times
        for when in times:
            yield RunEvent(when=when, task_count=dag.task_count, team=dag.team)


def group_runs(
    dags: Iterable[ScheduledDag],
    *,
    window_start: datetime,
    window_end: datetime,
    cap_per_dag: int = DEFAULT_RUN_CAP,
    run_times: dict[str, list[datetime]] | None = None,
) -> Iterator[tuple[list[datetime], str | None, int, int]]:
    """Group DAGs by ``(schedule, team)`` and yield each group's shared run times.

    The weighted counterpart to :func:`collect_events`: instead of one event per
    DAG per run, it folds DAGs that share a schedule *and* team into a single
    group and emits that schedule's run times once, tagged with the group's DAG
    count and summed task count. Aggregating those costs ``O(runs)`` per group,
    not ``O(runs * DAGs)`` — the difference between fast and unusable when many
    DAGs share a high-frequency schedule.

    Parameters
    ----------
    dags : Iterable[ScheduledDag]
        DAGs to group.
    window_start, window_end : datetime
        Half-open window ``[window_start, window_end)``.
    cap_per_dag : int
        Per-schedule expansion ceiling (see :func:`iter_runs`).
    run_times : dict[str, list[datetime]] | None
        Expansion cache keyed by schedule. Pass a shared dict to reuse
        expansions across several calls (e.g. the active-only and all-DAGs
        aggregates), so each distinct schedule is expanded at most once.

    Yields
    ------
    tuple[list[datetime], str | None, int, int]
        ``(run_times, team, dag_count, task_sum)`` per ``(schedule, team)`` group.
    """
    cache = {} if run_times is None else run_times
    groups: dict[tuple[str, str | None], list] = {}  # (schedule, team) -> [dag_count, task_sum, timetable]
    for dag in dags:
        gkey = (_timetable_key(dag.timetable), dag.team)
        group = groups.get(gkey)
        if group is None:
            groups[gkey] = [1, dag.task_count, dag.timetable]
        else:
            group[0] += 1
            group[1] += dag.task_count
    for (schedule_key, team), (dag_count, task_sum, timetable) in groups.items():
        times = cache.get(schedule_key)
        if times is None:
            times = list(iter_runs(timetable, window_start=window_start, window_end=window_end, cap=cap_per_dag))
            cache[schedule_key] = times
        yield times, team, dag_count, task_sum
