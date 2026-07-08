"""Integration smoke test for the metadata-DB loader path.

Runs in its own process against a throwaway AIRFLOW_HOME + SQLite DB (set before
Airflow imports), so it never touches a real Airflow database. It writes a couple
of DAGs the way Airflow does (serialized DAG + version + code + ``dag`` row), then
asserts :func:`load_scheduled_dags` reads them back correctly — the one code path
that unit tests can't cover because it needs a live schema.

Run via ``make smoke``.
"""

import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="sv-smoke-"))
os.environ["AIRFLOW_HOME"] = str(_TMP)
os.environ["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"] = f"sqlite:///{_TMP / 'airflow.db'}"
os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from airflow.models.dag import DagModel, DagTag  # noqa: E402
from airflow.models.dagbundle import DagBundleModel  # noqa: E402
from airflow.models.serialized_dag import SerializedDagModel  # noqa: E402
from airflow.providers.standard.operators.empty import EmptyOperator  # noqa: E402
from airflow.sdk import DAG  # noqa: E402
from airflow.serialization.serialized_objects import DagSerialization, LazyDeserializedDAG  # noqa: E402
from airflow.utils.db import initdb  # noqa: E402
from airflow.utils.session import create_session  # noqa: E402

from schedule_visualizer.airflow_io.loader import load_scheduled_dags  # noqa: E402

BUNDLE = "smoke-bundle"


def _write_dag(session, dag_id: str, *, tags: list[str], tasks: int, paused: bool) -> None:
    dagfile = _TMP / f"{dag_id}.py"
    dagfile.write_text(f"# {dag_id} source\n")
    with DAG(dag_id=dag_id, schedule="0 * * * *", start_date=dt.datetime(2026, 1, 1), catchup=False, tags=tags) as dag:
        for i in range(tasks):
            EmptyOperator(task_id=f"t{i}")
    dag.fileloc = str(dagfile)
    row = DagModel(
        dag_id=dag_id,
        bundle_name=BUNDLE,
        is_paused=paused,
        is_stale=False,
        timetable_partitioned=False,
        timetable_periodic=True,
        max_active_tasks=16,
        max_consecutive_failed_dag_runs=0,
        has_task_concurrency_limits=False,
    )
    row.tags = [DagTag(name=t, dag_id=dag_id) for t in tags]
    session.add(row)
    session.flush()  # the dag row must exist before write_dag's DagVersion FK
    SerializedDagModel.write_dag(
        LazyDeserializedDAG(data=DagSerialization.to_dict(dag)), bundle_name=BUNDLE, session=session
    )


def main() -> int:
    initdb()
    with create_session() as session:
        session.add(DagBundleModel(name=BUNDLE))
        session.flush()  # bundle must exist before the DAG rows' FK to it
        _write_dag(session, "smoke_active", tags=["team:alpha", "etl"], tasks=3, paused=False)
        _write_dag(session, "smoke_paused", tags=["team:beta"], tasks=5, paused=True)
        session.commit()

    active = {d.dag_id: d for d in load_scheduled_dags()}
    assert "smoke_active" in active, "active DAG missing from loader output"
    assert "smoke_paused" not in active, "paused DAG must be excluded by default"
    dag = active["smoke_active"]
    assert dag.task_count == 3, f"expected 3 tasks, got {dag.task_count}"
    assert dag.team == "alpha", f"expected team 'alpha' from tag, got {dag.team!r}"
    assert type(dag.timetable).__name__ == "CronTriggerTimetable"

    with_paused = {d.dag_id for d in load_scheduled_dags(include_paused=True)}
    assert {"smoke_active", "smoke_paused"} <= with_paused, "include_paused should return paused DAGs too"

    print("smoke OK: loader read", len(active), "active DAG(s); paused excluded; team + task_count correct")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil

        shutil.rmtree(_TMP, ignore_errors=True)
