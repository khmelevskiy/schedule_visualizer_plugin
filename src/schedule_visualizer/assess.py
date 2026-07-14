"""Score an arbitrary cron expression against the existing planned load.

The aggregate already holds a minute-of-week histogram, so no extra I/O is
needed: expand the cron's firing minutes, read the per-occurrence average load
at each, and grade the worst one. A cron is weekly-periodic when its
day-of-month and month fields are ``*`` — one week of firings then covers the
whole pattern; day-of-month schedules are expanded over the full window.

Score: 100 — every firing lands on empty minutes; 0 — the worst firing hits the
busiest minute of the week. Linear in between, relative to that busiest minute;
anything that hits a non-empty minute caps at 99.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from croniter import croniter

from schedule_visualizer.core import MINUTES_PER_DAY, Metric, ScheduleView
from schedule_visualizer.suggest import WEEKDAY_NAMES, _hhmm, _weekday_occurrences

# Backstop for pathological day-of-month crons expanded over the whole window
# (a minutely cron is weekly-periodic and never gets here).
_MAX_FIRINGS = 20_000

# @-aliases croniter accepts, and whether one week of firings covers the pattern.
_ALIAS_WEEKLY_PERIODIC = {
    "@hourly": True,
    "@midnight": True,
    "@daily": True,
    "@weekly": True,
    "@monthly": False,
    "@annually": False,
    "@yearly": False,
}


@dataclass(frozen=True, slots=True)
class Assessment:
    """How an existing/candidate cron fits the current load.

    Attributes
    ----------
    score : int
        0 (worst firing hits the busiest minute of the week) .. 100 (all
        firings land on empty minutes).
    peak : float
        Per-firing average load at the busiest firing minute.
    peak_label : str
        That minute, e.g. ``"Tue 02:00"``.
    average : float
        Mean per-firing load across all firing minutes.
    firings_per_week : float
        Firing count normalized to one week.
    """

    score: int
    peak: float
    peak_label: str
    average: float
    firings_per_week: float


def _weekly_periodic(cron: str) -> bool | None:
    """Whether one week of firings covers ``cron``'s pattern; ``None`` if invalid."""
    if cron.startswith("@"):
        return _ALIAS_WEEKLY_PERIODIC.get(cron)
    fields = cron.split()
    if len(fields) != 5 or not croniter.is_valid(cron):
        return None
    return fields[2] == "*" and fields[3] == "*"


def upcoming(cron: str, *, start: datetime, count: int = 5) -> list[datetime] | None:
    """List the next ``count`` firings of ``cron`` strictly after ``start``.

    Parameters
    ----------
    cron : str
        Five-field cron expression or an ``@``-alias, same dialect as
        :func:`assess`.
    start : datetime
        Instant to iterate from (timezone-aware).
    count : int
        How many firings to list.

    Returns
    -------
    list[datetime] | None
        Firing instants in ``start``'s timezone; ``None`` when ``cron`` is
        invalid.
    """
    cron = cron.strip()
    if _weekly_periodic(cron) is None:
        return None
    it = croniter(cron, start)
    return [it.get_next(datetime) for _ in range(count)]


def _firing_week_minutes(view: ScheduleView, cron: str) -> tuple[set[int], bool] | None:
    """Expand ``cron`` to ``(minutes-of-week, weekly_periodic)``; ``None`` if invalid."""
    weekly_periodic = _weekly_periodic(cron)
    if weekly_periodic is None:
        return None
    horizon = view.window_start + timedelta(days=7) if weekly_periodic else view.window_end
    minutes: set[int] = set()
    it = croniter(cron, view.window_start - timedelta(minutes=1))
    for _ in range(_MAX_FIRINGS):
        when = it.get_next(datetime)
        if when >= horizon:
            break
        minutes.add(when.weekday() * MINUTES_PER_DAY + when.hour * 60 + when.minute)
    return minutes, weekly_periodic


def assess(view: ScheduleView, cron: str, *, metric: Metric) -> Assessment | None:
    """Grade ``cron`` against the view's minute-of-week load.

    Parameters
    ----------
    view : ScheduleView
        The (team-filtered) load projection to grade against.
    cron : str
        Five-field cron expression or an ``@``-alias (``@daily`` …), UTC.
    metric : {"dags", "tasks"}
        Metric to grade on.

    Returns
    -------
    Assessment | None
        ``None`` when ``cron`` is invalid or never fires inside the window.
    """
    expanded = _firing_week_minutes(view, cron.strip())
    if expanded is None or not expanded[0]:
        return None
    minutes, weekly_periodic = expanded
    weekday_occ = _weekday_occurrences(view)

    def avg_at(wm: int) -> float:
        counts = view.by_week_minute.get(wm)
        occ = weekday_occ[wm // MINUTES_PER_DAY]
        return counts.metric(metric) / occ if counts is not None and occ else 0.0

    loads = {wm: avg_at(wm) for wm in minutes}
    # earliest minute wins ties so the label is deterministic
    peak_wm = min(loads, key=lambda wm: (-loads[wm], wm))
    peak = loads[peak_wm]
    busiest = max((avg_at(wm) for wm in view.by_week_minute), default=0.0)
    if peak == 0 or busiest == 0:
        score = 100
    else:
        score = max(0, min(99, round(100 * (1 - peak / busiest))))
    weekday, minute = divmod(peak_wm, MINUTES_PER_DAY)
    window_days = sum(weekday_occ)
    per_week = len(minutes) if weekly_periodic else round(len(minutes) * 7 / max(1, window_days), 1)
    return Assessment(
        score=score,
        peak=peak,
        peak_label=f"{WEEKDAY_NAMES[weekday]} {_hhmm(minute)}",
        average=sum(loads.values()) / len(loads),
        firings_per_week=per_week,
    )
