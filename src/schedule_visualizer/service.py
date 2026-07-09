"""Wire the loader, adapter, core and cache into ready-to-serve aggregates.

This is the composition root the FastAPI app depends on: it owns the window
computation (``now`` -> ``[start-of-day, +window_days)``) and hands back a
:class:`TtlCache` whose recompute walks the metadata DB once per TTL and builds
both the active-only and all-DAGs aggregates. The clock is injectable so the
window and cache expiry are testable without wall time.
"""

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from schedule_visualizer.airflow_io.adapter import ScheduledDag, group_runs
from schedule_visualizer.airflow_io.loader import TeamResolver, load_scheduled_dags
from schedule_visualizer.cache import Clock, TtlCache
from schedule_visualizer.config import Config
from schedule_visualizer.core import ScheduleAggregate

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Aggregates:
    """The two aggregates a single recompute produces.

    Attributes
    ----------
    active : ScheduleAggregate
        Only active (non-paused) DAGs — the default view.
    all : ScheduleAggregate
        Every DAG, including paused ones (handy in local dev, where DAGs are
        usually paused).
    """

    active: ScheduleAggregate
    all: ScheduleAggregate

    def pick(self, *, include_paused: bool) -> ScheduleAggregate:
        """Return the ``all`` aggregate when ``include_paused``, else ``active``."""
        return self.all if include_paused else self.active


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def compute_window(now: datetime, window_days: int) -> tuple[datetime, datetime]:
    """Half-open window from the start of ``now``'s day, spanning ``window_days``.

    Parameters
    ----------
    now : datetime
        Reference instant (timezone-aware).
    window_days : int
        Number of days the window spans.

    Returns
    -------
    tuple[datetime, datetime]
        ``(start, end)`` where ``start`` is midnight of ``now``'s day.
    """
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=window_days)


def aggregate_dags(dags: Iterable[ScheduledDag], *, now: datetime, window_days: int) -> Aggregates:
    """Expand DAG schedules over the window into active-only and all aggregates.

    Parameters
    ----------
    dags : Iterable[ScheduledDag]
        Every DAG (including paused); partitioned here by ``ScheduledDag.paused``.
    now : datetime
        Reference instant for the window.
    window_days : int
        Window span in days.

    Returns
    -------
    Aggregates
        The ``active`` and ``all`` aggregates.
    """
    started = time.perf_counter()
    start, end = compute_window(now, window_days)
    all_dags = list(dags)
    active_dags = [dag for dag in all_dags if not dag.paused]

    # Expand each distinct schedule at most once, shared across both aggregates.
    run_times: dict[str, list[datetime]] = {}

    def _agg(subset: list[ScheduledDag]) -> ScheduleAggregate:
        agg = ScheduleAggregate(window_start=start, window_end=end)
        for times, team, dag_count, task_sum in group_runs(
            subset, window_start=start, window_end=end, run_times=run_times
        ):
            agg.add_runs(times, team=team, dags=dag_count, tasks=task_sum)
        return agg

    aggregates = Aggregates(active=_agg(active_dags), all=_agg(all_dags))
    # One line per recompute (once per TTL) — not per request, to avoid log spam.
    log.info(
        "schedule aggregate recomputed: %d dags (%d active), %d-day window, %d teams, %.2fs",
        len(all_dags),
        len(active_dags),
        window_days,
        len(aggregates.all.teams),
        time.perf_counter() - started,
    )
    return aggregates


def build_cache(
    config: Config,
    *,
    team_of: TeamResolver | None = None,
    clock: Clock = utc_now,
) -> TtlCache[Aggregates]:
    """Build the TTL cache whose value is the current :class:`Aggregates`.

    Parameters
    ----------
    config : Config
        TTL and window settings.
    team_of : TeamResolver | None
        Team attribution strategy passed to the loader.
    clock : Clock
        Time source for both the window and the cache expiry.

    Returns
    -------
    TtlCache[Aggregates]
        A cache recomputing the aggregates at most once per ``config.ttl``. The
        metadata-DB scan (the expensive part) runs once; both aggregates are
        derived from that single load.
    """

    def compute() -> Aggregates:
        dags = load_scheduled_dags(team_of=team_of, include_paused=True)
        return aggregate_dags(dags, now=clock(), window_days=config.window_days)

    return TtlCache(compute=compute, ttl=config.ttl, clock=clock)
