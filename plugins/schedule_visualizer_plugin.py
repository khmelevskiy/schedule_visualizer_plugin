import os
import pickle

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from airflow.models import DagModel
from airflow.plugins_manager import AirflowPlugin
from airflow.settings import Session
from airflow.www.app import csrf
from croniter import CroniterBadCronError, croniter
from flask import Blueprint, redirect, render_template, request, url_for


# - Get the path to the Airflow home directory
airflow_home = os.getenv("AIRFLOW_HOME", "/opt/airflow")
DAYS_TO_PROCESS = 35
MAX_CACHE_HOURS_AGE = 24
CACHE_FILE = os.path.join(airflow_home, "schedule_visualizer_plugin_cache.pkl")

# - Create a blueprint for the plugin
schedule_visualizer_plugin_blueprint = Blueprint(
    "schedule_visualizer_plugin",
    __name__,
    template_folder=os.path.join(
        airflow_home, "plugins/schedule_visualizer_plugin/templates/schedule_visualizer_plugin"
    ),
    static_folder=os.path.join(airflow_home, "plugins/schedule_visualizer_plugin/static/schedule_visualizer_plugin"),
    static_url_path="/static/schedule_visualizer_plugin",
)


# - Function for working with cache


def load_cache() -> tuple:
    """
    Load cache from file

    Returns
    -------
    tuple
        Tuple with cache data and file modified time
    """

    if os.path.exists(CACHE_FILE):
        file_modified_time = datetime.fromtimestamp(os.path.getmtime(CACHE_FILE))
        with open(CACHE_FILE, "rb") as f:
            return pickle.load(f), file_modified_time
    return None, None


def save_cache(data: tuple) -> None:
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(data, f)


def clear_cache() -> None:
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)


def get_dag_task_counts() -> dict:
    """
    Get the task counts for each DAG

    Returns
    -------
    dict
        Dictionary with DAG ID as key and task count as value
    """

    session = Session()

    # - SQL query to get the task counts for each DAG
    sql = """
        WITH dags AS (
    SELECT 
        dag_id
    FROM 
        dag
    WHERE 
        last_parsed_time >= now() - INTERVAL '12 hour'
),
max_task_dates AS (
    SELECT 
        dag_id, 
        MAX(updated_at) AS max_updated_at
    FROM 
        task_instance
    WHERE 
        updated_at >= now() - INTERVAL '1 month'
    GROUP BY 
        dag_id
),
tasks AS (
    SELECT 
        dags.dag_id, 
        task_instance.task_id, 
        task_instance.map_index + 1 AS map_index,
        task_instance.updated_at,
        ROW_NUMBER() OVER (PARTITION BY dags.dag_id ORDER BY task_instance.updated_at DESC) AS row_num
    FROM 
        dags
    LEFT JOIN
        task_instance ON dags.dag_id = task_instance.dag_id
    LEFT JOIN
        max_task_dates ON task_instance.dag_id = max_task_dates.dag_id
    WHERE 
        task_instance.updated_at >= now() - INTERVAL '1 month'
        AND task_instance.updated_at >= max_task_dates.max_updated_at - INTERVAL '24 hour'
),
distinct_tasks AS (
    SELECT DISTINCT 
        dag_id, 
        task_id, 
        map_index
    FROM 
        tasks
),
count_tasks AS (
    SELECT 
        dag_id, 
        COUNT(DISTINCT (task_id, map_index)) AS task_count 
    FROM 
        distinct_tasks 
    GROUP BY 
        dag_id
)
SELECT 
    count_tasks.dag_id, 
    count_tasks.task_count
FROM 
    count_tasks;
    """
    results = session.execute(sql).fetchall()

    dag_task_counts = {dag_id: cnt_tasks for dag_id, cnt_tasks in results}
    print(f"Found {len(dag_task_counts)} DAGs with task counts")

    session.close()

    return dag_task_counts


def get_next_runs(cron_expression: str, start_time: str, end_time: str) -> list:
    """
    Get the next runs for a cron expression between start and end time

    Parameters
    ----------
    cron_expression: str
        Cron expression
    start_time: str
        Start time
    end_time: str
        End time

    Returns
    -------
    list
        List of next runs, starting from start_time and ending at end_time
    """

    base_time = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    iter = croniter(cron_expression, base_time)
    next_runs = []
    while True:
        next_run = iter.get_next(datetime).replace(tzinfo=timezone.utc)
        if next_run > datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc):
            break
        next_runs.append(next_run.strftime("%Y-%m-%d %H:%M:%S"))

    return next_runs


def get_dag_schedule() -> tuple:
    """
    Get the DAG schedule. Cache the data for 'MAX_CACHE_HOURS_AGE' hours or if cache will be cleared by pressing the
    button on the page

    Returns
    -------
    tuple
        Tuple with DAG schedule data(day and time), task schedule data(day and time), least occupied task days and times
    """

    cached_data, file_modified_time = load_cache()
    # - Max lifetime of cache is 5 hours
    if (
        cached_data
        and file_modified_time
        and file_modified_time > datetime.now() - timedelta(hours=MAX_CACHE_HOURS_AGE)
    ):
        print("Plugin 'schedule_visualizer_plugin'. Loaded data from cache")
        return cached_data

    print("Plugin 'schedule_visualizer_plugin'. Generating data")
    session = Session()
    dag_task_counts = get_dag_task_counts()
    dags = session.query(DagModel).all()
    dag_schedules_day = defaultdict(int)
    dag_schedules_time = defaultdict(int)
    task_schedules_day = defaultdict(int)
    task_schedules_time = defaultdict(int)
    task_count_by_schedule_interval = defaultdict(int)
    dag_schedules_count = defaultdict(int)
    dag_schedules_map = {
        "@hourly": "0 * * * *",
        "@daily": "0 0 * * *",
        "@weekly": "0 0 * * 1",
        "@monthly": "0 0 1 * *",
        "@yearly": "0 0 1 1 *",
    }
    for dag in dags:
        # - Map schedule_interval to standard cron expression and calculate count
        schedule_interval = dag.schedule_interval
        if schedule_interval in dag_schedules_map:
            schedule_interval = dag_schedules_map[schedule_interval]
        dag_schedules_count.update({schedule_interval: dag_schedules_count.get(schedule_interval, 0) + 1})

        # - Calculate task count for each DAG
        task_count = dag_task_counts.get(dag.dag_id, 1)
        task_count_by_schedule_interval[schedule_interval] += task_count

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    start_time = (today - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    end_time_day = (today.replace(hour=23, minute=59, second=59) + timedelta(days=DAYS_TO_PROCESS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    end_time_time = (today.replace(hour=23, minute=59, second=59)).strftime("%Y-%m-%d %H:%M:%S")

    # - Process each schedule interval
    for schedule_interval, count in dag_schedules_count.items():
        if not schedule_interval or schedule_interval == "@once":
            continue
        try:
            # - Check if the schedule interval is valid
            croniter(schedule_interval)

            next_runs_day = get_next_runs(schedule_interval, start_time, end_time_day)
            for run in next_runs_day:
                run_datetime = datetime.strptime(run, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                dag_schedules_day[run_datetime.strftime("%Y-%m-%d")] += dag_schedules_count[schedule_interval]
                task_schedules_day[run_datetime.strftime("%Y-%m-%d")] += task_count_by_schedule_interval.get(
                    schedule_interval, 1
                )

            next_runs_time = get_next_runs(schedule_interval, start_time, end_time_time)
            for run in next_runs_time:
                run_datetime = datetime.strptime(run, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                run_time = run_datetime.strftime("%H:%M")
                dag_schedules_time[run_time] += dag_schedules_count[schedule_interval]
                task_schedules_time[run_time] += task_count_by_schedule_interval.get(schedule_interval, 1)

        except CroniterBadCronError:
            print(f"Plugin 'schedule_visualizer_plugin'. Invalid cron expression {schedule_interval}")
        except Exception as e:
            print(f"Plugin 'schedule_visualizer_plugin'. Error parsing schedule {schedule_interval}: {e}")

    # - Generate least occupied task days and times
    all_days = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(DAYS_TO_PROCESS + 1)]
    all_times = [f"{str(i).zfill(2)}:{str(j).zfill(2)}" for i in range(24) for j in range(0, 60, 1)]

    # - Fill in missing days and times
    for day in all_days:
        if day not in dag_schedules_day:
            dag_schedules_day[day] = 0
        if day not in task_schedules_day:
            task_schedules_day[day] = 0

    for time in all_times:
        if time not in dag_schedules_time:
            dag_schedules_time[time] = 0
        if time not in task_schedules_time:
            task_schedules_time[time] = 0

    # - Sort the least occupied task days and times
    least_occupied_task_days = sorted(
        task_schedules_day.items(), key=lambda x: (x[1], datetime.strptime(x[0], "%Y-%m-%d"))
    )
    least_occupied_task_times = sorted(
        task_schedules_time.items(), key=lambda x: (x[1], datetime.strptime(x[0], "%H:%M"))
    )

    data = (
        dag_schedules_day,
        dag_schedules_time,
        task_schedules_day,
        task_schedules_time,
        least_occupied_task_days,
        least_occupied_task_times,
        datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),  # - Cache time
    )

    save_cache(data)

    return data


@schedule_visualizer_plugin_blueprint.route("/schedule_visualizer_plugin", methods=["GET", "POST"])
@csrf.exempt
def schedule():
    if request.method == "POST":
        # - Clear the cache if the button is pressed and redirect to the schedule page
        clear_cache()
        print("Plugin 'schedule_visualizer_plugin'. Cache cleared")

        return redirect(url_for("schedule_visualizer_plugin.schedule"))

    (
        dag_schedules_day,
        dag_schedules_time,
        task_schedules_day,
        task_schedules_time,
        least_occupied_task_days,
        least_occupied_task_times,
        cache_time,
    ) = get_dag_schedule()

    return render_template(
        "schedule_visualizer_plugin.html",
        dag_schedules_day=dag_schedules_day,
        dag_schedules_time=dag_schedules_time,
        task_schedules_day=task_schedules_day,
        task_schedules_time=task_schedules_time,
        least_occupied_task_days=least_occupied_task_days,
        least_occupied_task_times=least_occupied_task_times,
        cache_time=cache_time,
        current_time=datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
    )


class MySchedulePlugin(AirflowPlugin):
    name = "schedule_visualizer_plugin"
    flask_blueprints = [schedule_visualizer_plugin_blueprint]

    appbuilder_menu_items = [
        {
            "name": "📊ScheduleVisualizerPlugin",
            "href": "/schedule_visualizer_plugin",
        }
    ]
