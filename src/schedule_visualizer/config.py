"""Runtime configuration, read from the environment.

Kept Airflow-free and side-effect-light: :meth:`Config.from_env` reads a mapping
(``os.environ`` by default) so it can be exercised in tests without touching the
process environment.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

type TeamSource = Literal["tag", "bundle"]

DEFAULT_TTL_SECONDS = 3600
DEFAULT_WINDOW_DAYS = 31
DEFAULT_TEAM_SOURCE = "tag"
DEFAULT_TEAM_TAG_PREFIX = "team:"

ENV_TTL_SECONDS = "SCHEDULE_VIZ_TTL_SECONDS"
ENV_WINDOW_DAYS = "SCHEDULE_VIZ_WINDOW_DAYS"
ENV_TEAM_SOURCE = "SCHEDULE_VIZ_TEAM_SOURCE"
ENV_TEAM_TAG_PREFIX = "SCHEDULE_VIZ_TEAM_TAG_PREFIX"


@dataclass(frozen=True, slots=True)
class Config:
    """Effective plugin settings.

    Attributes
    ----------
    ttl : timedelta
        How long a computed aggregate is served before recompute.
    window_days : int
        How many days ahead the schedule window spans.
    team_source : {"tag", "bundle"}
        Where a DAG's team comes from: a ``team:<name>`` tag (single-tenant /
        OSS) or the source bundle name (the multi-team platform).
    team_tag_prefix : str
        Tag prefix used when ``team_source == "tag"``.
    """

    ttl: timedelta
    window_days: int
    team_source: TeamSource
    team_tag_prefix: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        """Build a config from environment variables, falling back to defaults.

        Parameters
        ----------
        env : Mapping[str, str] | None
            Source mapping; defaults to ``os.environ``.

        Returns
        -------
        Config
            The resolved settings.
        """
        source = os.environ if env is None else env
        team_source: TeamSource = "bundle" if source.get(ENV_TEAM_SOURCE) == "bundle" else "tag"
        return cls(
            ttl=timedelta(seconds=int(source.get(ENV_TTL_SECONDS, DEFAULT_TTL_SECONDS))),
            window_days=int(source.get(ENV_WINDOW_DAYS, DEFAULT_WINDOW_DAYS)),
            team_source=team_source,
            team_tag_prefix=source.get(ENV_TEAM_TAG_PREFIX, DEFAULT_TEAM_TAG_PREFIX),
        )
