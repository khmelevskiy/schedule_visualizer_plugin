"""Airflow 3 plugin: visualize DAG/task schedule load and find quiet slots.

Pure, Airflow-free logic lives in ``schedule_visualizer.core`` (aggregation) and
``schedule_visualizer.suggest`` (schedule placement) — import from there for
logic and tests. Airflow-coupled I/O is under ``airflow_io``; the HTTP surface is
under ``web``.
"""

__version__ = "0.1.0"
