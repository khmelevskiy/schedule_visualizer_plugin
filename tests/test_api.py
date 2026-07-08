from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from schedule_visualizer.cache import TtlCache  # noqa: E402
from schedule_visualizer.config import Config  # noqa: E402
from schedule_visualizer.core import RunEvent, aggregate  # noqa: E402
from schedule_visualizer.service import Aggregates  # noqa: E402
from schedule_visualizer.web.api import create_app  # noqa: E402

WINDOW_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 6, 8, tzinfo=timezone.utc)


def _at(day: int, hour: int = 0, *, team: str | None = None, tasks: int = 1) -> RunEvent:
    return RunEvent(datetime(2026, 6, day, hour, tzinfo=timezone.utc), task_count=tasks, team=team)


def _agg(events):
    return aggregate(events, window_start=WINDOW_START, window_end=WINDOW_END)


def _client(auth_dependency=None, paused_extra=None) -> TestClient:
    active_events = [_at(1, 9, team="alpha", tasks=2), _at(2, 10, team="beta", tasks=5)]
    aggregates = Aggregates(active=_agg(active_events), all=_agg(active_events + (paused_extra or [])))
    clock = lambda: datetime(2026, 6, 1, tzinfo=timezone.utc)  # noqa: E731
    cache = TtlCache(compute=lambda: aggregates, ttl=timedelta(hours=1), clock=clock)
    app = create_app(Config.from_env({}), cache=cache, auth_dependency=auth_dependency)
    return TestClient(app)


def test_healthz() -> None:
    assert _client().get("/api/healthz").json() == {"status": "ok"}


def test_schedule_default_is_global() -> None:
    body = _client().get("/api/schedule").json()
    assert body["selected_teams"] is None
    assert body["metric"] == "tasks"
    assert body["meta"]["teams"] == ["alpha", "beta"]
    assert sum(d["tasks"] for d in body["days"]) == 7  # 2 + 5


def test_schedule_team_filter() -> None:
    body = _client().get("/api/schedule", params={"team": "alpha"}).json()
    assert body["selected_teams"] == ["alpha"]
    assert sum(d["tasks"] for d in body["days"]) == 2


def test_schedule_multi_team_filter() -> None:
    body = _client().get("/api/schedule", params=[("team", "alpha"), ("team", "beta")]).json()
    assert body["selected_teams"] == ["alpha", "beta"]
    assert sum(d["tasks"] for d in body["days"]) == 7


def test_schedule_metric_param() -> None:
    body = _client().get("/api/schedule", params={"metric": "dags"}).json()
    assert body["metric"] == "dags"


def test_invalid_metric_rejected() -> None:
    assert _client().get("/api/schedule", params={"metric": "bogus"}).status_code == 422


def test_include_paused_toggles_paused_dag_load() -> None:
    client = _client(paused_extra=[_at(3, tasks=100)])  # a paused DAG worth 100 tasks
    default = sum(d["tasks"] for d in client.get("/api/schedule").json()["days"])
    with_paused = sum(d["tasks"] for d in client.get("/api/schedule", params={"include_paused": "true"}).json()["days"])
    assert default == 7  # active only: 2 + 5
    assert with_paused == 107  # active + the paused DAG


def test_auth_dependency_guards_data_but_not_health() -> None:
    def deny() -> None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    client = _client(auth_dependency=deny)
    assert client.get("/api/schedule").status_code == 401  # data is gated
    assert client.get("/api/healthz").status_code == 200  # liveness stays open


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
