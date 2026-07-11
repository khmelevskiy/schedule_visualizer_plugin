import type { Metric } from "../api";
import { teamLabel } from "../format";

export type Aggregation = "avg" | "sum";

interface Props {
  metric: Metric;
  onMetric: (m: Metric) => void;
  aggregation: Aggregation;
  onAggregation: (a: Aggregation) => void;
  windowDays: number;
  teams: (string | null)[];
  selected: string[];
  onToggleTeam: (team: string) => void;
  onClearTeams: () => void;
  includePaused: boolean;
  onIncludePaused: (v: boolean) => void;
}

export function Controls({
  metric,
  onMetric,
  aggregation,
  onAggregation,
  windowDays,
  teams,
  selected,
  onToggleTeam,
  onClearTeams,
  includePaused,
  onIncludePaused,
}: Props) {
  const realTeams = teams.filter((t): t is string => t !== null);
  return (
    <div className="controls">
      <div className="control-group">
        <span className="control-label">Metric</span>
        <div className="toggle">
          <button className={metric === "tasks" ? "active" : ""} onClick={() => onMetric("tasks")}>
            Tasks
          </button>
          <button className={metric === "dags" ? "active" : ""} onClick={() => onMetric("dags")}>
            DAGs
          </button>
        </div>
      </div>

      <div className="control-group">
        <span className="control-label">Values</span>
        <div className="toggle">
          <button className={aggregation === "avg" ? "active" : ""} onClick={() => onAggregation("avg")}>
            Avg / day
          </button>
          <button className={aggregation === "sum" ? "active" : ""} onClick={() => onAggregation("sum")}>
            Sum / {windowDays}d
          </button>
        </div>
      </div>

      <label className="switch">
        <input type="checkbox" checked={includePaused} onChange={(e) => onIncludePaused(e.target.checked)} />
        <span className="switch-track" aria-hidden="true" />
        Include paused
      </label>

      {realTeams.length > 0 && (
        <div className="control-group">
          <span className="control-label">Team</span>
          <button className={`chip ${selected.length === 0 ? "active" : ""}`} onClick={onClearTeams}>
            All
          </button>
          {realTeams.map((team) => (
            <button
              key={team}
              className={`chip ${selected.includes(team) ? "active" : ""}`}
              onClick={() => onToggleTeam(team)}
            >
              {teamLabel(team)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
