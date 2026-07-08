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
from datetime import datetime

import pendulum
from airflow.timetables.base import TimeRestriction, Timetable

from schedule_visualizer.core import RunEvent

# Safety bound on timetable expansion per DAG, so a sub-minute schedule over a
# month-wide window can't spin forever. A minutely DAG over ~35 days is ~50k.
DEFAULT_RUN_CAP = 200_000


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
