import { useEffect, useState } from "react";
import type { CadenceSuggestions, Metric, SuggestionOption } from "../api";

interface Props {
  suggestions: CadenceSuggestions[];
  metric: Metric;
  timezone: string;
  windowDays: number;
}

export function Suggest({ suggestions, metric, timezone, windowDays }: Props) {
  const [cadence, setCadence] = useState("daily");
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(null), 1500);
    return () => clearTimeout(t);
  }, [copied]);

  const current = suggestions.find((s) => s.cadence === cadence) ?? suggestions[0];
  if (!current) return null;

  const copy = (cron: string) => {
    navigator.clipboard?.writeText(cron);
    setCopied(cron);
  };
  const load = (o: SuggestionOption) => (metric === "tasks" ? o.tasks : o.dags);

  return (
    <div className="card wide">
      <h2>Recommended schedule</h2>
      <p className="hint">
        Pick a cadence — placed where the cluster is least busy (by {metric}). Times and cron in {timezone}.
      </p>
      <div className="suggest-controls">
        <span className="control-label">Run</span>
        <select value={current.cadence} onChange={(e) => setCadence(e.target.value)}>
          {suggestions.map((s) => (
            <option key={s.cadence} value={s.cadence}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      <ul className="suggest-list">
        {current.options.map((o, i) => (
          <li key={o.cron} className={i === 0 ? "best" : ""}>
            <div className="slot">
              <span className="when">{o.label}</span>
              {i === 0 && <span className="badge">best</span>}
              <span className="cost">
                busiest minute: {load(o)} {metric} over {windowDays} days
              </span>
            </div>
            <div className="cron">
              <code>{o.cron}</code>
              <button onClick={() => copy(o.cron)}>{copied === o.cron ? "copied ✓" : "copy"}</button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
