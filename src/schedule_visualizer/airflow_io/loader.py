"""Read serialized DAGs from the Airflow metadata DB into :class:`ScheduledDag`.

The scheduler keeps a serialized snapshot of every DAG (``serialized_dag``),
paired with scheduling metadata (``dag`` table: paused/stale flags, owning
bundle). This module joins the two and projects each active DAG down to the
handful of fields the visualization needs — nothing here touches the DAG files
on disk or a live scheduler.

Team attribution is deliberately pluggable: :data:`TeamResolver` maps a DAG's
metadata to a team label. The default reads a ``team:<name>`` tag (single-tenant
DAGs simply carry none); the multi-team platform injects a resolver keyed on the
GitDagBundle name instead.
"""

from collections.abc import Callable
from dataclasses import dataclass

from airflow.models.dag import DagModel
from airflow.models.serialized_dag import SerializedDagModel
from airflow.serialization.serialized_objects import decode_timetable
from airflow.utils.session import create_session
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from schedule_visualizer.airflow_io.adapter import ScheduledDag
from schedule_visualizer.config import DEFAULT_TEAM_TAG_PREFIX, Config


@dataclass(frozen=True, slots=True)
class DagMeta:
    """Scheduling metadata a :data:`TeamResolver` gets to decide the team.

    Attributes
    ----------
    dag_id : str
        DAG identifier.
    tags : frozenset[str]
        The DAG's tags (e.g. ``{"team:alpha", "etl"}``).
    owners : tuple[str, ...]
        Owner handles, split from the DAG's ``owner`` string.
    bundle_name : str | None
        Name of the source bundle; the per-team signal on the platform.
    """

    dag_id: str
    tags: frozenset[str]
    owners: tuple[str, ...]
    bundle_name: str | None


type TeamResolver = Callable[[DagMeta], str | None]


def team_from_tag(prefix: str = DEFAULT_TEAM_TAG_PREFIX) -> TeamResolver:
    """Build a resolver that reads the team from a ``prefix``-prefixed tag.

    Parameters
    ----------
    prefix : str
        Tag prefix marking the team, e.g. ``"team:"`` for ``team:alpha``.

    Returns
    -------
    TeamResolver
        Resolver returning the first matching tag's suffix, or ``None`` when no
        tag carries the prefix (ties broken by sorted tag order for stability).

    Examples
    --------
    >>> resolve = team_from_tag()
    >>> resolve(DagMeta("d", frozenset({"team:alpha", "etl"}), (), None))
    'alpha'
    >>> resolve(DagMeta("d", frozenset({"etl"}), (), None)) is None
    True
    """

    def resolve(meta: DagMeta) -> str | None:
        for tag in sorted(meta.tags):
            if tag.startswith(prefix):
                return tag.removeprefix(prefix) or None
        return None

    return resolve


def team_from_bundle() -> TeamResolver:
    """Build a resolver that reads the team from the DAG's source bundle.

    On the multi-team platform each team's DAGs are synced by their own
    GitDagBundle, so the bundle name is the team.

    Returns
    -------
    TeamResolver
        Resolver returning ``meta.bundle_name``.
    """
    return lambda meta: meta.bundle_name


def resolver_for(config: Config) -> TeamResolver:
    """Pick the team resolver named by ``config.team_source``.

    Parameters
    ----------
    config : Config
        Settings carrying ``team_source`` and ``team_tag_prefix``.

    Returns
    -------
    TeamResolver
        :func:`team_from_bundle` for ``"bundle"``, else :func:`team_from_tag`.
    """
    if config.team_source == "bundle":
        return team_from_bundle()
    return team_from_tag(config.team_tag_prefix)


def _to_scheduled_dag(dag_data: dict, meta: DagMeta, team_of: TeamResolver, *, paused: bool) -> ScheduledDag:
    """Project one serialized-DAG payload + its metadata into a :class:`ScheduledDag`.

    Reads the timetable and task count straight from the serialized JSON
    (``dag_data`` is ``SerializedDagModel.data["dag"]``), so the DAG's operators
    are never instantiated — much faster than a full deserialization, and free of
    the provider imports one would demand. The caller guarantees a ``timetable``
    key is present.
    """
    return ScheduledDag(
        dag_id=meta.dag_id,
        task_count=len(dag_data.get("tasks", [])),
        timetable=decode_timetable(dag_data["timetable"]),
        team=team_of(meta),
        paused=paused,
    )


def _meta_of(row: DagModel) -> DagMeta:
    # DagModel uses legacy SQLAlchemy Column declarations, so ty types instance
    # attribute access as the column descriptor rather than the runtime value.
    owners = tuple(o.strip() for o in (row.owners or "").split(",") if o.strip())
    return DagMeta(
        dag_id=row.dag_id,  # ty: ignore[invalid-argument-type]
        tags=frozenset(tag.name for tag in row.tags),
        owners=owners,
        bundle_name=row.bundle_name,  # ty: ignore[invalid-argument-type]
    )


def load_scheduled_dags(*, team_of: TeamResolver | None = None, include_paused: bool = False) -> list[ScheduledDag]:
    """Load active, scheduled DAGs from the metadata DB.

    Parameters
    ----------
    team_of : TeamResolver | None
        Team attribution strategy; defaults to :func:`team_from_tag`.
    include_paused : bool
        Whether to include paused DAGs. Off by default — paused DAGs won't fire,
        so they don't contribute to planned load.

    Returns
    -------
    list[ScheduledDag]
        One entry per active DAG that has a serialized snapshot *and* a
        time-based schedule. DAGs with no timetable (e.g. asset-triggered) are
        skipped — they carry no planned load.
    """
    resolve = team_of if team_of is not None else team_from_tag()
    with create_session() as session:
        # Eager-load tags: the resolver reads them per DAG, and a lazy load would
        # fire one query per DAG (N+1) on a metadata DB that may be remote.
        stmt = select(DagModel).where(DagModel.is_stale.is_(False)).options(selectinload(DagModel.tags))
        if not include_paused:
            stmt = stmt.where(DagModel.is_paused.is_(False))
        rows = session.scalars(stmt).all()
        # Raw serialized payloads: `.data` is the stored JSON, NOT a deserialized
        # DAG (that is `.dag` / read_all_dags) — so no operators are built.
        payloads = {row.dag_id: row.data for row in session.scalars(select(SerializedDagModel)).all()}
        result: list[ScheduledDag] = []
        for row in rows:
            payload = payloads.get(row.dag_id)
            if payload is None:
                continue
            dag_data = payload["dag"]
            if not dag_data.get("timetable"):
                continue
            result.append(_to_scheduled_dag(dag_data, _meta_of(row), resolve, paused=bool(row.is_paused)))
    return result
