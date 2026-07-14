import { useEffect, useState } from "react";
import { type Assessment, fetchAssess, type Metric } from "../api";
import { fmtNum } from "../format";

interface Props {
  metric: Metric;
  teams: string[];
  includePaused: boolean;
  timezone: string;
  cron: string;
  onCron: (cron: string) => void;
}

// 0 = red (busiest), 100 = green (empty).
const scoreColor = (score: number) => `hsl(${Math.round(score * 1.2)}, 65%, 42%)`;

// meta.timezone is always a valid zone name (currently "UTC").
const runLabel = (iso: string, timezone: string): string =>
  new Intl.DateTimeFormat("en-GB", {
    timeZone: timezone,
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));

export function CronCheck({ metric, teams, includePaused, timezone, cron, onCron }: Props) {
  const [result, setResult] = useState<Assessment | null>(null);
  const isAlias = cron.trim().startsWith("@");

  // Debounced fetch: grade while typing without a request per keystroke.
  useEffect(() => {
    const trimmed = cron.trim();
    if (!trimmed) {
      setResult(null);
      return;
    }
    let live = true;
    const t = setTimeout(() => {
      fetchAssess(trimmed, { teams, metric, includePaused })
        .then((a) => live && setResult(a))
        .catch(() => live && setResult(null));
    }, 350);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [cron, teams, metric, includePaused]);

  return (
    <div className="cron-check">
      <span className="control-label">Check a cron</span>
      <input
        type="text"
        value={cron}
        onChange={(e) => onCron(e.target.value)}
        placeholder={`e.g. 0 3 * * * (${timezone})`}
        spellCheck={false}
      />
      {isAlias && (
        <span className="cron-alias-hint">
          @-aliases fire at midnight / on the hour, right where load piles up — prefer an explicit cron with an offset
        </span>
      )}
      {cron.trim() && result && !result.valid && <span className="cron-invalid">not a valid cron (or never fires in the window)</span>}
      {cron.trim() && result?.valid && (
        <span className="cron-result">
          <span className="score" style={{ background: scoreColor(result.score) }}>
            {result.score}
          </span>
          {result.peak > 0
            ? `worst firing overlaps ~${fmtNum(result.peak)} ${metric} (${result.peak_label})`
            : "every firing lands on a free minute"}
          {" · fires "}
          {fmtNum(result.firings_per_week)}×/week
          {result.next_runs.length > 0 && (
            <span className="cron-next" tabIndex={0}>
              next runs
              <span className="cron-next-list" role="tooltip">
                {result.next_runs.map((iso) => (
                  <span key={iso}>{runLabel(iso, timezone)}</span>
                ))}
              </span>
            </span>
          )}
        </span>
      )}
    </div>
  );
}
