import datetime as dt

import pytest

pytest.importorskip("airflow")  # loader tests need Airflow installed

from airflow.providers.standard.operators.empty import EmptyOperator  # noqa: E402
from airflow.sdk import DAG  # noqa: E402
from airflow.serialization.serialized_objects import DagSerialization  # noqa: E402

from schedule_visualizer.airflow_io.loader import (  # noqa: E402
    DagMeta,
    _to_scheduled_dag,
    resolver_for,
    team_from_bundle,
    team_from_tag,
)
from schedule_visualizer.config import Config  # noqa: E402


def _serialized(dag_id: str, *, schedule: str, tasks: int, tags: list[str]):
    with DAG(dag_id=dag_id, schedule=schedule, start_date=dt.datetime(2026, 1, 1), catchup=False, tags=tags) as dag:
        for i in range(tasks):
            EmptyOperator(task_id=f"t{i}")
    return DagSerialization.from_dict(DagSerialization.to_dict(dag))


# region team_from_tag


def test_team_from_tag_reads_prefix() -> None:
    resolve = team_from_tag()
    assert resolve(DagMeta("d", frozenset({"team:alpha", "etl"}), (), None)) == "alpha"


def test_team_from_tag_none_when_absent() -> None:
    resolve = team_from_tag()
    assert resolve(DagMeta("d", frozenset({"etl"}), (), "some-bundle")) is None


def test_team_from_tag_custom_prefix() -> None:
    resolve = team_from_tag(prefix="squad-")
    assert resolve(DagMeta("d", frozenset({"squad-payments"}), (), None)) == "payments"


def test_team_from_bundle_returns_bundle_name() -> None:
    resolve = team_from_bundle()
    assert resolve(DagMeta("d", frozenset({"team:alpha"}), (), "data-cube-de")) == "data-cube-de"
    assert resolve(DagMeta("d", frozenset(), (), None)) is None


def test_resolver_for_picks_by_config() -> None:
    bundle = resolver_for(Config.from_env({"SCHEDULE_VIZ_TEAM_SOURCE": "bundle"}))
    tag = resolver_for(Config.from_env({"SCHEDULE_VIZ_TEAM_SOURCE": "tag", "SCHEDULE_VIZ_TEAM_TAG_PREFIX": "squad-"}))
    meta = DagMeta("d", frozenset({"squad-pay"}), (), "bundle-x")
    assert bundle(meta) == "bundle-x"
    assert tag(meta) == "pay"


# endregion

# region conversion


def test_to_scheduled_dag_maps_fields() -> None:
    sd = _serialized("demo", schedule="0 * * * *", tasks=3, tags=["team:beta"])
    meta = DagMeta("demo", frozenset(sd.tags), ("airflow",), "beta-bundle")
    scheduled = _to_scheduled_dag(sd, meta, team_from_tag(), paused=True)

    assert scheduled.dag_id == "demo"
    assert scheduled.task_count == 3
    assert scheduled.team == "beta"
    assert scheduled.paused is True
    assert type(scheduled.timetable).__name__ == "CronTriggerTimetable"


def test_to_scheduled_dag_untagged_has_no_team() -> None:
    sd = _serialized("plain", schedule="@daily", tasks=1, tags=["etl"])
    meta = DagMeta("plain", frozenset(sd.tags), (), None)
    scheduled = _to_scheduled_dag(sd, meta, team_from_tag(), paused=False)
    assert scheduled.team is None
    assert scheduled.paused is False


# endregion


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
