"""Standalone demo server: seeded schedule, no Airflow metadata DB needed.

Run via ``make demo`` (or ``uv run --no-sync python scripts/demo.py``). Seeds a
realistic mix of team schedules, serves the data API and — if the frontend has
been built into ``static/`` — the UI, at http://127.0.0.1:8888/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import uvicorn
from airflow.timetables.interval import CronDataIntervalTimetable
from airflow.timetables.trigger import CronTriggerTimetable

from schedule_visualizer.airflow_io.adapter import ScheduledDag
from schedule_visualizer.cache import TtlCache
from schedule_visualizer.config import Config
from schedule_visualizer.service import Aggregates, aggregate_dags, utc_now
from schedule_visualizer.web.api import create_app

HOST = "127.0.0.1"
PORT = 8888

# (cron, team, task_count, count) — expanded into `count` DAGs sharing the schedule.
# Spread across hours and weekdays so the heatmap shows structure: an hourly
# baseline, a night-batch band, a business-hours block, and quieter weekends.
SEED = [
    ("0 * * * *", "ingest", 3, 5),  # hourly baseline
    ("*/15 * * * *", "ingest", 2, 2),  # quarter-hourly pollers
    ("0 6 * * *", "ingest", 8, 4),  # morning load
    ("0 2 * * *", "analytics", 12, 6),  # night batch
    ("0 3 * * *", "analytics", 8, 4),
    ("0 9-17 * * 1-5", "analytics", 3, 5),  # business-hours refreshes (weekdays)
    ("0 5 * * *", "reporting", 15, 4),  # pre-dawn reports
    ("30 7 * * 1-5", "reporting", 6, 3),  # weekday morning
    ("0 3 * * 1", "reporting", 20, 3),  # weekly Monday roll-up
    ("0 22 * * *", "ml", 25, 3),  # nightly training
    ("0 */6 * * *", "ml", 4, 3),  # every 6h
    ("0 1 * * *", None, 2, 4),  # untagged / single-tenant style
]

# Paused DAGs — hidden by default, revealed by the "Include paused" toggle
# (locally most DAGs are paused, so this makes the toggle worth trying).
PAUSED_SEED = [
    ("0 * * * *", "ingest", 6, 3),  # paused hourly
    ("0 0 * * *", "analytics", 40, 2),  # paused heavy nightly
]


def _timetable(cron: str):
    # Mix both timetable kinds the way real DAGs do (string cron -> trigger).
    if cron.startswith("@") or ("," in cron) or ("-" in cron) or ("/" in cron.split()[0]):
        return CronTriggerTimetable(cron, timezone="UTC")
    return CronDataIntervalTimetable(cron, timezone="UTC")


def seed_dags() -> list[ScheduledDag]:
    dags: list[ScheduledDag] = []
    for cron, team, tasks, count in SEED:
        for i in range(count):
            name = f"{team or 'misc'}_{cron.replace(' ', '_').replace('*', 'x')}_{i}"
            dags.append(ScheduledDag(dag_id=name, task_count=tasks, timetable=_timetable(cron), team=team))
    for cron, team, tasks, count in PAUSED_SEED:
        for i in range(count):
            name = f"paused_{team}_{cron.replace(' ', '_').replace('*', 'x')}_{i}"
            dags.append(ScheduledDag(dag_id=name, task_count=tasks, timetable=_timetable(cron), team=team, paused=True))
    return dags


def build_cache(config: Config) -> TtlCache[Aggregates]:
    def compute() -> Aggregates:
        return aggregate_dags(seed_dags(), now=utc_now(), window_days=config.window_days)

    return TtlCache(compute=compute, ttl=config.ttl, clock=utc_now)


def main() -> None:
    config = Config.from_env()
    app = create_app(config, cache=build_cache(config))
    print(f"Schedule Visualizer demo → http://{HOST}:{PORT}/  ({len(seed_dags())} seeded DAGs)")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
