import { type ReactNode, useEffect, useState } from "react";
import type { CadenceSuggestions, Metric, SuggestionOption } from "../api";
import { fmtNum } from "../format";

interface Props {
  suggestions: CadenceSuggestions[];
  metric: Metric;
  timezone: string;
  cadence: string;
  onCadence: (cadence: string) => void;
  children?: ReactNode; // extra footer content (the cron checker)
}

export function Suggest({ suggestions, metric, timezone, cadence, onCadence, children }: Props) {
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
  // Per-firing average: the histogram sums the whole window, so divide by how
  // many times the slot fires in it — "what's already running when I fire".
  const load = (o: SuggestionOption) => (metric === "tasks" ? o.tasks : o.dags) / Math.max(1, o.occurrences);

  return (
    <div className="card wide">
      <h2>Recommended schedule</h2>
      <p className="hint">
        Pick a cadence — placed where the cluster is least busy (by {metric}). Times and cron in {timezone}.
      </p>
      <div className="suggest-controls">
        <span className="control-label">Run</span>
        <select value={current.cadence} onChange={(e) => onCadence(e.target.value)}>
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
                {load(o) > 0 ? `worst firing overlaps ~${fmtNum(load(o))} ${metric}` : "nothing scheduled here"}
              </span>
            </div>
            <div className="cron">
              <code>{o.cron}</code>
              <button onClick={() => copy(o.cron)}>{copied === o.cron ? "copied ✓" : "copy"}</button>
            </div>
          </li>
        ))}
      </ul>
      {children}
    </div>
  );
}
