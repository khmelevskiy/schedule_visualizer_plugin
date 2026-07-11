"""FastAPI sub-app mounted by the plugin under ``/schedule-visualizer``.

Thin HTTP layer over the cached aggregate: it reads the team selection and
metric off the query string, serves the serialized payload, and — where a built
frontend bundle is present — the static UI. All heavy lifting lives in
:mod:`schedule_visualizer.service` and :mod:`schedule_visualizer.web.serialize`.

There is deliberately no public refresh endpoint: the cache auto-refreshes on
TTL, and a manual recompute is left to be an admin-gated action on the platform.

Handlers are intentionally synchronous (``def``, not ``async def``): the reads
they do are a synchronous SQLAlchemy session plus CPU-bound aggregation. Starlette
runs sync handlers in a worker threadpool, so they never block the api-server's
event loop; an ``async def`` handler would run that blocking work directly on the
loop and stall every other route.

The data endpoint is guarded by ``auth_dependency`` when one is supplied — the
plugin passes Airflow's "current user" dependency so the API is only reachable by
a logged-in session. Nothing binds a new port; the app is mounted on the existing
api-server.
"""

from collections.abc import Callable
from pathlib import Path

from fastapi import Depends, FastAPI, Query
from fastapi.staticfiles import StaticFiles

from schedule_visualizer.airflow_io.loader import TeamResolver
from schedule_visualizer.cache import Cached, TtlCache
from schedule_visualizer.config import Config
from schedule_visualizer.core import Metric
from schedule_visualizer.service import Aggregates, build_cache
from schedule_visualizer.web.serialize import assess_payload, schedule_payload

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(
    config: Config | None = None,
    *,
    team_of: TeamResolver | None = None,
    cache: TtlCache[Aggregates] | None = None,
    auth_dependency: Callable[..., object] | None = None,
) -> FastAPI:
    """Build the plugin's FastAPI application.

    Parameters
    ----------
    config : Config | None
        Settings; defaults to :meth:`Config.from_env`.
    team_of : TeamResolver | None
        Team attribution strategy passed through to the cache builder.
    cache : TtlCache[Aggregates] | None
        Pre-built cache; mainly for tests. Built from ``config`` when omitted.
    auth_dependency : Callable[..., object] | None
        FastAPI dependency gating the data endpoint (e.g. Airflow's current-user
        check). ``None`` leaves it open — used by the standalone demo.

    Returns
    -------
    FastAPI
        The sub-app, ready to mount.
    """
    settings = config if config is not None else Config.from_env()
    schedule_cache = cache if cache is not None else build_cache(settings, team_of=team_of)
    guarded = [Depends(auth_dependency)] if auth_dependency is not None else []
    app = FastAPI(title="Schedule Visualizer")

    @app.get("/api/schedule", dependencies=guarded)
    def get_schedule(
        team: list[str] | None = Query(default=None),
        metric: Metric = "tasks",
        include_paused: bool = False,
    ) -> dict[str, object]:
        cached = schedule_cache.get()
        agg = cached.value.pick(include_paused=include_paused)
        picked = Cached(value=agg, computed_at=cached.computed_at, expires_at=cached.expires_at)
        return schedule_payload(picked, teams=team, metric=metric)

    @app.get("/api/assess", dependencies=guarded)
    def get_assess(
        cron: str,
        team: list[str] | None = Query(default=None),
        metric: Metric = "tasks",
        include_paused: bool = False,
    ) -> dict[str, object]:
        cached = schedule_cache.get()
        agg = cached.value.pick(include_paused=include_paused)
        view = agg.view(list(team) if team is not None else None)
        return assess_payload(view, cron, metric=metric)

    @app.get("/api/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")

    return app
