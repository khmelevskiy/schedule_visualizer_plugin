"""Suggest the least-contended placement for a new schedule of a given cadence.

Pure and Airflow-free. For a fixed cadence only the *phase* (offset) is free:
"every 15 min" can fire at ``:00/:15/…`` or ``:07/:22/…``; "daily" can fire at
any minute of the day. For each candidate offset we look up the existing load at
the minutes that offset would fire on, and rank offsets by their busiest firing
moment (peak), breaking ties by total then by earliest offset. The result is the
quietest few placements per cadence, each with a ready-to-paste cron expression.

Sub-daily, daily and monthly cadences read the minute-of-day histogram; weekly
reads the minute-of-week one. Empty minutes (load 0) are valid candidates and
usually win.

Histogram cells are sums over the whole window, and slots recur a different
number of times: a minute of the day recurs once per window day, a minute of the
week only on its weekday (4 or 5 times in a ~31-day window). Each suggestion
therefore carries ``occurrences`` so the load can be read per firing, and weekly
ranking compares per-occurrence averages — otherwise a weekday falling 5 times
in the window would look 25% busier than one falling 4 times at equal real load.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from schedule_visualizer.core import MINUTES_PER_DAY, Counts, Metric, ScheduleView

MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Interval cadences keyed by period in minutes (hourly == every 60 min).
# Multi-hour periods must divide 24 so the pattern repeats identically each day.
_INTERVAL_CADENCES = (
    ("every_5", "Every 5 minutes", 5),
    ("every_10", "Every 10 minutes", 10),
    ("every_15", "Every 15 minutes", 15),
    ("every_30", "Every 30 minutes", 30),
    ("hourly", "Hourly", 60),
    ("every_2h", "Every 2 hours", 120),
    ("every_4h", "Every 4 hours", 240),
    ("every_6h", "Every 6 hours", 360),
    ("every_12h", "Every 12 hours", 720),
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
        Existing load at the placement's busiest firing moment, summed over the
        window. Divide by ``occurrences`` for the per-firing average.
    occurrences : int
        How many times that moment recurs in the window (window days for
        minute-of-day slots; the weekday's count in the window for weekly).
    """

    label: str
    cron: str
    peak: Counts
    occurrences: int


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


def _rank[K](scored: Sequence[tuple[float, float, int, K]], top: int) -> list[tuple[int, K]]:
    """Sort by (peak, total, offset) and return ``top`` ``(offset, payload)`` pairs."""
    ordered = sorted(scored)
    return [(offset, payload) for _peak, _total, offset, payload in ordered[:top]]


def _weekday_occurrences(view: ScheduleView) -> list[int]:
    """How many times each weekday (Mon=0..Sun=6) falls inside the window."""
    counts = [0] * 7
    last = (view.window_end - timedelta(microseconds=1)).date()
    day = view.window_start.date()
    while day <= last:
        counts[day.weekday()] += 1
        day += timedelta(days=1)
    return counts


def _interval_options(
    minute_load: list[Counts], period: int, metric: Metric, top: int, occurrences: int
) -> list[Suggestion]:
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
        elif period == 60:
            cron = f"{offset} * * * *"
            label = f"every hour at :{offset:02d}"
        else:
            hours = period // 60
            first_hour, minute = divmod(offset, 60)
            hour_field = f"*/{hours}" if first_hour == 0 else f"{first_hour}-23/{hours}"
            cron = f"{minute} {hour_field} * * *"
            label = f"every {hours} h at {_hhmm(offset)}"
        options.append(Suggestion(label=label, cron=cron, peak=peak, occurrences=occurrences))
    return options


def _daily_options(minute_load: list[Counts], metric: Metric, top: int, occurrences: int) -> list[Suggestion]:
    scored = [(c.metric(metric), c.metric(metric), minute, c) for minute, c in enumerate(minute_load)]
    options: list[Suggestion] = []
    for minute, peak in _rank(scored, top):
        options.append(
            Suggestion(
                label=_hhmm(minute), cron=f"{minute % 60} {minute // 60} * * *", peak=peak, occurrences=occurrences
            )
        )
    return options


def _monthly_options(minute_load: list[Counts], metric: Metric, top: int, occurrences: int) -> list[Suggestion]:
    # The histograms have no day-of-month axis, so the day is fixed to the 1st
    # (the usual monthly-report convention) and only the time is optimized —
    # same quietest-minute search as daily.
    scored = [(c.metric(metric), c.metric(metric), minute, c) for minute, c in enumerate(minute_load)]
    options: list[Suggestion] = []
    for minute, peak in _rank(scored, top):
        options.append(
            Suggestion(
                label=f"1st, {_hhmm(minute)}",
                cron=f"{minute % 60} {minute // 60} 1 * *",
                peak=peak,
                occurrences=occurrences,
            )
        )
    return options


def _weekly_options(week_load: list[Counts], metric: Metric, top: int, weekday_occ: list[int]) -> list[Suggestion]:
    # Rank by per-occurrence average: raw sums would penalize weekdays that fall
    # 5 times in the window vs 4 at equal per-firing load. Weekdays outside the
    # window (occurrence 0) can't be assessed, so they are not offered.
    scored: list[tuple[float, float, int, Counts]] = []
    for wm, c in enumerate(week_load):
        occ = weekday_occ[wm // MINUTES_PER_DAY]
        if occ == 0:
            continue
        avg = c.metric(metric) / occ
        scored.append((avg, avg, wm, c))
    options: list[Suggestion] = []
    for week_minute, peak in _rank(scored, top):
        weekday, minute = divmod(week_minute, MINUTES_PER_DAY)
        cron_dow = (weekday + 1) % 7  # Python Mon=0..Sun=6 -> cron Sun=0, Mon=1..Sat=6
        cron = f"{minute % 60} {minute // 60} * * {cron_dow}"
        options.append(
            Suggestion(
                label=f"{WEEKDAY_NAMES[weekday]} {_hhmm(minute)}",
                cron=cron,
                peak=peak,
                occurrences=weekday_occ[weekday],
            )
        )
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
        One entry per cadence (5/10/15/30 min, 1/2/4/6/12 h, daily, weekly,
        monthly on the 1st).
    """
    minute_load = [counts for _minute, counts in view.minute_series()]
    week_load = [view.by_week_minute.get(i, Counts()) for i in range(MINUTES_PER_WEEK)]
    weekday_occ = _weekday_occurrences(view)
    window_days = sum(weekday_occ)
    result = [
        CadenceSuggestions(
            cadence=key, label=label, options=_interval_options(minute_load, period, metric, top, window_days)
        )
        for key, label, period in _INTERVAL_CADENCES
    ]
    result.append(CadenceSuggestions("daily", "Daily", _daily_options(minute_load, metric, top, window_days)))
    result.append(CadenceSuggestions("weekly", "Weekly", _weekly_options(week_load, metric, top, weekday_occ)))
    result.append(
        CadenceSuggestions("monthly", "Monthly (1st)", _monthly_options(minute_load, metric, top, window_days))
    )
    return result
