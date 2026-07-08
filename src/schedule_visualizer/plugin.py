"""Airflow 3 plugin registration.

Mounts the FastAPI sub-app (data API + static UI) under ``/schedule-visualizer``
and adds a nav entry that opens it. An external view (a link to our own
self-contained page) is used rather than a ``react_apps`` federated bundle: it
needs no build-time module contract and is stable across Airflow 3.x minors.

Building the app here is cheap and DB-free: the cache is lazy, so the first
schedule request — not plugin import — triggers the metadata-DB scan.

The data endpoint is guarded by Airflow's current-user dependency, so it is only
reachable by a logged-in session — same auth boundary as the rest of the UI. The
team source (``team:`` tag vs bundle name) comes from the environment, so the
same build serves single-tenant and the multi-team platform.
"""

from airflow.api_fastapi.core_api.security import get_user
from airflow.plugins_manager import AirflowPlugin

from schedule_visualizer.airflow_io.loader import resolver_for
from schedule_visualizer.config import Config
from schedule_visualizer.web.api import create_app

URL_PREFIX = "/schedule-visualizer"

_config = Config.from_env()
_app = create_app(config=_config, team_of=resolver_for(_config), auth_dependency=get_user)


class ScheduleVisualizerPlugin(AirflowPlugin):
    """Registers the Schedule Visualizer FastAPI app and its nav entry."""

    name = "schedule_visualizer"
    fastapi_apps = [
        {
            "name": "Schedule Visualizer",
            "app": _app,
            "url_prefix": URL_PREFIX,
        }
    ]
    external_views = [
        {
            "name": "Schedule Visualizer",
            "href": f"{URL_PREFIX}/",
            "url_route": "schedule-visualizer",
            "destination": "nav",
            # The UI renders this as <img src=...>, so it must be a URL, not an
            # icon name. Served from our own static bundle.
            "icon": f"{URL_PREFIX}/icon.svg",
        }
    ]
