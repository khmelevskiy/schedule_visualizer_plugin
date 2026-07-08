"""Suggest the least-contended placement for a new schedule of a given cadence.

Pure and Airflow-free. For a fixed cadence only the *phase* (offset) is free:
"every 15 min" can fire at ``:00/:15/…`` or ``:07/:22/…``; "daily" can fire at
any minute of the day. For each candidate offset we look up the existing load at
the minutes that offset would fire on, and rank offsets by their busiest firing
moment (peak), breaking ties by total then by earliest offset. The result is the
quietest few placements per cadence, each with a ready-to-paste cron expression.

Sub-daily and daily cadences read the minute-of-day histogram; weekly reads the
minute-of-week one. Empty minutes (load 0) are valid candidates and usually win.
"""

from dataclasses import dataclass

from schedule_visualizer.core import MINUTES_PER_DAY, Counts, Metric, ScheduleView

MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Interval cadences keyed by period in minutes (hourly == every 60 min).
_INTERVAL_CADENCES = (
    ("every_5", "Every 5 minutes", 5),
    ("every_10", "Every 10 minutes", 10),
    ("every_15", "Every 15 minutes", 15),
    ("every_30", "Every 30 minutes", 30),
    ("hourly", "Hourly", 60),
)


@dataclass(frozen=True, slots=True)
class Suggestion:
    """One candidate placement.

    Attributes
    ----------
    label : str
        Human placement, e.g. ``":07, :22, :37, :52"`` or ``"03:23"`` or
        ``"Mon 03:23"``.
    cron : str
        Ready-to-paste cron expression for the placement.
    peak : Counts
        Existing load at the placement's busiest firing moment.
    """

    label: str
    cron: str
    peak: Counts


@dataclass(frozen=True, slots=True)
class CadenceSuggestions:
    """Ranked placements for one cadence.

    Attributes
    ----------
    cadence : str
        Stable cadence key (e.g. ``"every_15"``).
    label : str
        Human cadence name (e.g. ``"Every 15 minutes"``).
    options : list[Suggestion]
        Quietest placements first.
    """

    cadence: str
    label: str
    options: list[Suggestion]


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _rank[K](scored: list[tuple[int, int, int, K]], top: int) -> list[tuple[int, K]]:
    """Sort by (peak, total, offset) and return ``top`` ``(offset, payload)`` pairs."""
    scored.sort()
    return [(offset, payload) for _peak, _total, offset, payload in scored[:top]]


def _interval_options(minute_load: list[Counts], period: int, metric: Metric, top: int) -> list[Suggestion]:
    scored: list[tuple[int, int, int, Counts]] = []
    for offset in range(period):
        fired = [minute_load[m] for m in range(offset, MINUTES_PER_DAY, period)]
        peak = max(fired, key=lambda c: c.metric(metric))
        total = sum((c.metric(metric) for c in fired), 0)
        scored.append((peak.metric(metric), total, offset, peak))
    options: list[Suggestion] = []
    for offset, peak in _rank(scored, top):
        if period < 60:
            cron = f"*/{period} * * * *" if offset == 0 else f"{offset}-59/{period} * * * *"
            label = ", ".join(f":{m:02d}" for m in range(offset, 60, period))
        else:
            cron = f"{offset} * * * *"
            label = f"every hour at :{offset:02d}"
        options.append(Suggestion(label=label, cron=cron, peak=peak))
    return options


def _daily_options(minute_load: list[Counts], metric: Metric, top: int) -> list[Suggestion]:
    scored = [(c.metric(metric), c.metric(metric), minute, c) for minute, c in enumerate(minute_load)]
    options: list[Suggestion] = []
    for minute, peak in _rank(scored, top):
        options.append(Suggestion(label=_hhmm(minute), cron=f"{minute % 60} {minute // 60} * * *", peak=peak))
    return options


def _weekly_options(week_load: list[Counts], metric: Metric, top: int) -> list[Suggestion]:
    scored = [(c.metric(metric), c.metric(metric), wm, c) for wm, c in enumerate(week_load)]
    options: list[Suggestion] = []
    for week_minute, peak in _rank(scored, top):
        weekday, minute = divmod(week_minute, MINUTES_PER_DAY)
        cron_dow = (weekday + 1) % 7  # Python Mon=0..Sun=6 -> cron Sun=0, Mon=1..Sat=6
        cron = f"{minute % 60} {minute // 60} * * {cron_dow}"
        options.append(Suggestion(label=f"{WEEKDAY_NAMES[weekday]} {_hhmm(minute)}", cron=cron, peak=peak))
    return options


def suggest(view: ScheduleView, *, metric: Metric, top: int = 3) -> list[CadenceSuggestions]:
    """Rank the quietest placements for every supported cadence.

    Parameters
    ----------
    view : ScheduleView
        The (already team-filtered) load projection to place against.
    metric : {"dags", "tasks"}
        Metric to minimize contention on.
    top : int
        How many placements to return per cadence.

    Returns
    -------
    list[CadenceSuggestions]
        One entry per cadence (5/10/15/30 min, hourly, daily, weekly).
    """
    minute_load = [counts for _minute, counts in view.minute_series()]
    week_load = [view.by_week_minute.get(i, Counts()) for i in range(MINUTES_PER_WEEK)]
    result = [
        CadenceSuggestions(cadence=key, label=label, options=_interval_options(minute_load, period, metric, top))
        for key, label, period in _INTERVAL_CADENCES
    ]
    result.append(CadenceSuggestions("daily", "Daily", _daily_options(minute_load, metric, top)))
    result.append(CadenceSuggestions("weekly", "Weekly", _weekly_options(week_load, metric, top)))
    return result
