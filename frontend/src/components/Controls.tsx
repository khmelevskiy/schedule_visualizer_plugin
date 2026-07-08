import type { Metric } from "../api";
import { teamLabel } from "../format";

interface Props {
  metric: Metric;
  onMetric: (m: Metric) => void;
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

      <label className="check">
        <input type="checkbox" checked={includePaused} onChange={(e) => onIncludePaused(e.target.checked)} />
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
